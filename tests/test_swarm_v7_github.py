import base64
import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / "skills" / "github-project-swarm" / "scripts"
sys.path.insert(0, str(SCRIPTS))
v7 = importlib.import_module("swarm_v7")
gh = importlib.import_module("swarm_v7_github")
H1 = "1" * 40; H2 = "2" * 40

def config(): return v7.ManifestV7(swarm_id="test",repo="owner/repo",default_branch="main",issues=(45,46),worker_model="worker",reviewer_models=("reviewer-a","reviewer-b"),adjudicator_model="adjudicator")
def review(slot, head, native=None, ident=None): return {"id":ident or slot,"body":gh.review_marker("test",46,slot,head),"commit_id":native if native is not None else head,"state":"COMMENTED","submitted_at":"2026-09-12T00:00:00Z"}
def decision(head, value="accept", ident=10):
    payload=base64.urlsafe_b64encode(json.dumps({"head_sha":head,"decision":value},separators=(",",":")).encode()).decode(); return {"id":ident,"body":gh.adjudication_marker("test",46,head)+f"\n<!-- hermes-swarm-decision-b64:{payload} -->"}
def pr(number, head, *, state="open", merged_at=None, mergeable=True, branch="swarm/test/46"): return {"number":number,"html_url":f"https://github.com/owner/repo/pull/{number}","state":state,"draft":False,"base":{"ref":"main"},"head":{"sha":head,"ref":branch},"mergeable":mergeable,"mergeable_state":"clean" if mergeable else "dirty","merged_at":merged_at,"labels":[]}
def cross_ref(number): return {"event":"cross-referenced","source":{"issue":{"number":number,"repository_url":"https://api.github.com/repos/owner/repo","pull_request":{"url":f"https://api.github.com/repos/owner/repo/pulls/{number}"}}}}
class FakeReader:
    def __init__(self,values=None,error=None,job_logs=None): self.values=values or {}; self.error=error; self.job_logs=job_logs or {}; self.calls=[]
    def get(self,endpoint):
        self.calls.append(("get",endpoint))
        if self.error: raise gh.GitHubReadError(self.error)
        return self.values.get(endpoint,{})
    def list(self,endpoint):
        self.calls.append(("list",endpoint))
        if self.error: raise gh.GitHubReadError(self.error)
        return self.values.get(endpoint,[])
    def job_log(self,repo,job):
        self.calls.append(("job_log",repo,job))
        if self.error: raise gh.GitHubReadError(self.error)
        return self.job_logs.get(job,"")
def action_check(head=H2): return {"id":700,"name":"tests","status":"completed","conclusion":"success","head_sha":head,"details_url":"https://github.com/owner/repo/actions/runs/800/job/700","app":{"slug":"github-actions"}}
def action_run(head=H2,branch="swarm/test/46",event="pull_request"): return {"head_sha":head,"head_branch":branch,"event":event}
def checkout_log(head): return f"2026-09-25T00:00:00Z ##[group]Run actions/checkout@deadbeef\n2026-09-25T00:00:00Z   repository: owner/repo\n2026-09-25T00:00:00Z [command]/usr/bin/git log -1 --format=%H\n2026-09-25T00:00:00Z {head}\n"
def ci_reader(checkout=H2,*,row_head=H2,run_head=H2,branch="swarm/test/46",event="pull_request"):
    values={f"repos/owner/repo/commits/{H2}/check-runs?filter=latest":{"check_runs":[action_check(row_head)]},f"repos/owner/repo/commits/{H2}/status":{"statuses":[]},"repos/owner/repo/actions/runs/800":action_run(run_head,branch,event)}
    return FakeReader(values,job_logs={700:checkout_log(checkout)})
class ExactHeadPublicationTests(unittest.TestCase):
    def test_old_head_review_is_ignored(self):
        pubs,state=gh.review_publications(config(),46,H2,[review(1,H1)]); self.assertEqual(pubs,()); self.assertEqual(state,v7.ReviewState.NONE)
    def test_native_commit_id_must_match_claimed_head(self):
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.review_publications(config(),46,H2,[review(1,H2,native=H1)])
    def test_review_publication_requires_submitted_comment_review(self):
        marker=gh.review_marker("test",46,1,H2); rows=({"body":marker,"commit_id":H2,"state":"PENDING","submitted_at":"2026-09-12T00:00:00Z"},{"body":marker,"commit_id":H2,"state":"COMMENTED"},{"body":marker,"state":"COMMENTED","submitted_at":"2026-09-12T00:00:00Z"})
        for row in rows:
            with self.assertRaises(gh.UnsafeGitHubObservation): gh.review_publications(config(),46,H2,[row])
    def test_all_slots_are_recovered_from_github_only(self):
        pubs,state=gh.review_publications(config(),46,H2,[review(2,H2),review(1,H2)]); self.assertEqual([x.slot for x in pubs],[1,2]); self.assertEqual(state,v7.ReviewState.DISPUTED)
    def test_old_head_adjudication_is_ignored(self):
        publication,state=gh.adjudication_publication(config(),46,H2,[decision(H1)]); self.assertIsNone(publication); self.assertEqual(state,v7.AdjudicationDecision.NONE)
    def test_duplicate_and_malformed_publications_fail_closed(self):
        duplicate=[review(1,H2,ident=1),review(1,H2,ident=2)]
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.review_publications(config(),46,H2,duplicate)
        malformed=[{"body":"<!-- hermes-swarm-review:test:46:v1:abc -->"}]
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.review_publications(config(),46,H2,malformed)
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.adjudication_publication(config(),46,H2,[decision(H2,ident=1),decision(H2,ident=2)])
    def test_unpadded_adjudication_payload_is_accepted(self):
        encoded=base64.urlsafe_b64encode(json.dumps({"head_sha":H2,"decision":"changes"},separators=(",",":")).encode()).decode().rstrip("=")
        body=gh.adjudication_marker("test",46,H2)+f"\n<!-- hermes-swarm-decision-b64:{encoded} -->"
        publication,state=gh.adjudication_publication(config(),46,H2,[{"body":body}])
        self.assertEqual(publication.head,H2); self.assertEqual(state,v7.AdjudicationDecision.REVISE)
    def test_malformed_adjudication_payload_is_recoverable(self):
        encoded=base64.urlsafe_b64encode(json.dumps({"head_sha":H2,"decision":"accept"}).encode()).decode(); marker=gh.adjudication_marker("test",46,H2)
        rows=({"body":marker+f"\n<!-- hermes-swarm-decision-b64 --> {encoded}"},{"body":marker+"\n<!-- hermes-swarm-decision-b64:YWJj -->"})
        for row in rows:
            with self.assertRaises(gh.AdjudicationExecutionError): gh.adjudication_publication(config(),46,H2,[row])
    def test_legacy_round_markers_fail_closed_instead_of_becoming_history(self):
        body=f"<!-- hermes-swarm-review:test:46:3:v1:{H2} -->"
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.review_publications(config(),46,H2,[{"body":body,"commit_id":H2}])
    def test_full_sha_required(self):
        with self.assertRaises(ValueError): gh.review_marker("test",46,1,H1[:12])
        with self.assertRaises(ValueError): gh.adjudication_marker("test",46,H1[:12])
        with self.assertRaises(ValueError): gh.exact_sha(H1[:12])
class DependencyTests(unittest.TestCase):
    def test_github_merged_at_releases_internal_dependency(self):
        values={"repos/owner/repo/issues/45/timeline":[cross_ref(101)],"repos/owner/repo/pulls/101":pr(101,H1,state="closed",merged_at="2026-09-04T11:00:00Z")}; facts,state=gh._dependency_observation(config(),[{"number":45,"state":"closed"}],FakeReader(values)); self.assertEqual(state,v7.DependencyState.READY); self.assertEqual(facts[0].merged_at,"2026-09-04T11:00:00Z")
    def test_cached_predecessor_state_cannot_release_dependency(self):
        values={"repos/owner/repo/issues/45/timeline":[cross_ref(101)],"repos/owner/repo/pulls/101":pr(101,H1,state="closed",merged_at=None)}; blocker={"number":45,"state":"closed","cached_merged":True}; facts,state=gh._dependency_observation(config(),[blocker],FakeReader(values)); self.assertEqual(state,v7.DependencyState.BLOCKED); self.assertIsNone(facts[0].merged_at)
    def test_external_open_blocker_remains_blocked(self):
        _,state=gh._dependency_observation(config(),[{"number":999,"state":"open"}],FakeReader()); self.assertEqual(state,v7.DependencyState.BLOCKED)
class ReadFailureAndSideEffectTests(unittest.TestCase):
    def test_github_read_failure_is_unsafe_and_planner_stalls(self):
        observed=gh.observe_issue(config(),46,FakeReader(error="network down")); self.assertEqual(observed.planner.dependency,v7.DependencyState.UNKNOWN); self.assertIn("network down",observed.unsafe_reason); plan=v7.plan_issue(observed.planner,config()); self.assertEqual(plan.phase,v7.Phase.EXECUTION_STALLED); self.assertIsNone(plan.action)
    def test_gh_reader_uses_only_get(self):
        completed=subprocess.CompletedProcess([],0,stdout="{}",stderr="")
        with patch.object(subprocess,"run",return_value=completed) as run: gh.GhReader().get("repos/owner/repo/issues/46")
        cmd=run.call_args.args[0]; self.assertEqual(cmd[:4],["gh","api","--method","GET"]); self.assertNotIn("mutation"," ".join(cmd).lower())
class ExactHeadCiTests(unittest.TestCase):
    def state(self,reader): return gh.ci_state(config(),gh.checks(reader,"owner/repo",H2,"swarm/test/46"))
    def test_actions_green_requires_actual_exact_head_checkout(self):
        self.assertEqual(self.state(ci_reader(H2)),v7.CiState.PASSED); self.assertEqual(self.state(ci_reader(H1)),v7.CiState.PENDING); self.assertEqual(gh.ci_state(config(),([],[{"state":"success"}])),v7.CiState.PENDING)
    def test_stale_base_sibling_and_missing_action_receipts_do_not_pass(self):
        readers=(ci_reader(H1,row_head=H1,run_head=H1),ci_reader(H2,event="push"),ci_reader(H2,branch="swarm/test/45"),ci_reader(""))
        for reader in readers:
            with self.subTest(calls=reader.calls): self.assertEqual(self.state(reader),v7.CiState.PENDING)
    def test_synthetic_checkout_keeps_planner_waiting_ci(self):
        reader=ci_reader(H1); reader.values.update({"repos/owner/repo/issues/46":{"number":46,"state":"open"},"repos/owner/repo/issues/46/dependencies/blocked_by":[],"repos/owner/repo/issues/46/timeline":[cross_ref(102)],"repos/owner/repo/pulls/102":pr(102,H2),"repos/owner/repo/pulls/102/reviews":[review(1,H2),review(2,H2)],"repos/owner/repo/issues/102/comments":[decision(H2)]})
        observed=gh.observe_issue(config(),46,reader); plan=v7.plan_issue(observed.planner,config()); self.assertEqual(observed.planner.ci,v7.CiState.PENDING); self.assertEqual(plan.phase,v7.Phase.WAITING_CI); self.assertIsNone(plan.action)
class EndToEndObservationTests(unittest.TestCase):
    def test_open_issue_ignores_merged_sibling_cross_reference(self):
        values={"repos/owner/repo/issues/46":{"number":46,"state":"open"},"repos/owner/repo/issues/46/dependencies/blocked_by":[],"repos/owner/repo/issues/46/timeline":[cross_ref(101)],"repos/owner/repo/pulls/101":pr(101,H1,state="closed",merged_at="2026-09-05T12:00:00Z",branch="swarm/test/45")}
        observed=gh.observe_issue(config(),46,FakeReader(values)); self.assertIsNone(observed.pull_request); self.assertFalse(observed.planner.merged); self.assertEqual(v7.plan_issue(observed.planner,config()).phase,v7.Phase.NEEDS_IMPLEMENTATION)
    def test_current_head_facts_feed_planner(self):
        values={"repos/owner/repo/issues/46":{"number":46,"state":"open"},"repos/owner/repo/issues/46/dependencies/blocked_by":[],"repos/owner/repo/issues/46/timeline":[cross_ref(102)],"repos/owner/repo/pulls/102":pr(102,H2),f"repos/owner/repo/commits/{H2}/check-runs?filter=latest":{"check_runs":[{"name":"tests","status":"completed","conclusion":"success"}]},f"repos/owner/repo/commits/{H2}/status":{"statuses":[]},"repos/owner/repo/pulls/102/reviews":[review(1,H2),review(2,H2)],"repos/owner/repo/issues/102/comments":[decision(H2)]}
        observed=gh.observe_issue(config(),46,FakeReader(values)); self.assertIsNone(observed.unsafe_reason); self.assertEqual(observed.pull_request.head,H2); self.assertEqual(observed.planner.ci,v7.CiState.PASSED); self.assertEqual(observed.planner.adjudication_decision,v7.AdjudicationDecision.ACCEPT); plan=v7.plan_issue(observed.planner,config()); self.assertEqual(plan.phase,v7.Phase.READY_TO_MERGE); self.assertEqual(plan.action,v7.Action.MERGE); self.assertTrue(plan.intent_key.endswith(H2))
    def test_malformed_adjudication_restarts_instead_of_stalling(self):
        bad={"body":gh.adjudication_marker("test",46,H2)+"\n<!-- hermes-swarm-decision-b64 --> eyJjb2...fV19"}; values={"repos/owner/repo/issues/46":{"number":46,"state":"open"},"repos/owner/repo/issues/46/dependencies/blocked_by":[],"repos/owner/repo/issues/46/timeline":[cross_ref(102)],"repos/owner/repo/pulls/102":pr(102,H2),f"repos/owner/repo/commits/{H2}/check-runs?filter=latest":{"check_runs":[{"name":"tests","status":"completed","conclusion":"success"}]},f"repos/owner/repo/commits/{H2}/status":{"statuses":[]},"repos/owner/repo/pulls/102/reviews":[review(1,H2),review(2,H2)],"repos/owner/repo/issues/102/comments":[bad]}
        observed=gh.observe_issue(config(),46,FakeReader(values)); plan=v7.plan_issue(observed.planner,config()); self.assertIsNone(observed.unsafe_reason); self.assertIsNone(observed.pull_request.adjudication); self.assertEqual(plan.phase,v7.Phase.NEEDS_ADJUDICATION); self.assertEqual(plan.action,v7.Action.START_ADJUDICATION)
if __name__=="__main__": unittest.main()

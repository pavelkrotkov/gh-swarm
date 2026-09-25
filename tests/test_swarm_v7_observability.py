import json, sys, tempfile, unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
ROOT=Path(__file__).parents[1]; SCRIPTS=ROOT/"skills"/"github-project-swarm"/"scripts"
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
import swarm_v7_cli as cli, swarm_v7_github as gh, swarm_v7_merge as merge
from swarm_v7 import AdjudicationDecision, CiState, DependencyState, ManifestV7, MergeGate, Observation, Phase, ReviewState, plan_issue
from swarm_v7_controller import IssueObservation, PlannedIssue, RuntimeManifest, observation_payload
H1="1"*40; H2="2"*40; M1="a"*40
def runtime(*,paused=False,policy="automatic"): return RuntimeManifest(ManifestV7("demo","owner/repo","main",(7,),"worker",("r1","r2"),"judge",paused=paused,merge_policy=policy),"/repo","demo","sat-swarm",2,"30m",{})
def planned(rt,*,dependency=DependencyState.READY,ci=CiState.PASSED,review=ReviewState.APPROVED,decision=AdjudicationDecision.NONE,merge_gate=MergeGate.READY,labels=(),unsafe_reason=None,github_unsafe=None,merged_at=None,merge_sha=None,head=H1):
    planner=Observation(7,dependency=dependency,pr_head=head,ci=ci,review=review,adjudication_decision=decision,merge_gate=merge_gate,merge_confirmed=bool(merged_at),unsafe_reason=unsafe_reason); pr=SimpleNamespace(number=61,url="https://github.com/owner/repo/pull/61",head=head,base="main",state="CLOSED" if merged_at else "OPEN",draft=False,merged_at=merged_at,merge_sha=merge_sha,labels=tuple(labels),mergeable=True,merge_state="CLEAN",reviewers=(),adjudication=None); github=SimpleNamespace(issue_number=7,issue_state="CLOSED" if merged_at else "OPEN",blockers=(),pull_request=pr,planner=planner,unsafe_reason=github_unsafe)
    observed=IssueObservation(github,planner,{}); return PlannedIssue(observed,plan_issue(planner,rt.config))
class SwarmV7ObservabilityTests(unittest.TestCase):
    def test_structured_gates_keep_intentional_holds_out_of_execution_stalled(self):
        rt=runtime(paused=True,policy="manual"); held=planned(rt,dependency=DependencyState.BLOCKED,ci=CiState.UNKNOWN,merge_gate=MergeGate.BLOCKED,labels=("hold-merge",)); gates={row["code"]:row["detail"] for row in observation_payload(held.observation,rt.config)["gates"]}
        self.assertEqual(gates["hold_label"],"hold-merge"); self.assertTrue({"paused","manual_merge_mode","dependency_wait","ci_missing_evidence"}<=set(gates))
        ready=planned(rt,merge_gate=MergeGate.BLOCKED,labels=("hold-merge",)); self.assertEqual((ready.plan.phase,ready.plan.action),(Phase.MERGE_BLOCKED,None))
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)): rendered=cli._render(cli._snapshot(rt,7,ready))
        self.assertIn("MERGE_BLOCKED",rendered); self.assertIn("hold_label:hold-merge",rendered); self.assertNotIn("EXECUTION_STALLED",rendered)
        behind=planned(runtime()); behind.observation.github.pull_request.merge_state="BEHIND"; self.assertEqual(gh._merge_gate(runtime().config,behind.observation.github.pull_request),MergeGate.BLOCKED)
        execution=planned(runtime(),unsafe_reason="execution attempts exhausted"); self.assertIn("execution_failure",{row["code"] for row in observation_payload(execution.observation,runtime().config)["gates"]})
        failed=planned(runtime(),unsafe_reason="GitHub observation failed: 502",github_unsafe="GitHub observation failed: 502"); codes={row["code"] for row in observation_payload(failed.observation,runtime().config)["gates"]}; self.assertIn("observation_failure",codes); self.assertNotIn("execution_failure",codes)
        args=cli._parser().parse_args(["status","--name","demo","--json"]); self.assertTrue(args.json)
    def test_merge_receipts_distinguish_rejected_unknown_controller_and_external_outcomes(self):
        rt=runtime(); candidate=planned(rt)
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)),patch.object(cli,"apply_plan",side_effect=RuntimeError("rejected by GitHub")):
            with self.assertRaisesRegex(RuntimeError,"rejected"): cli._apply_with_receipt(rt,candidate,"cid-1")
            path=Path(td)/"demo.journal.jsonl"; events=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row["event"] for row in events],["merge_intent","merge_outcome"]); self.assertEqual({row["correlation_id"] for row in events},{"cid-1"}); self.assertEqual((events[0]["pr"],events[0]["head"],events[0]["policy"]),(61,H1,"automatic")); self.assertEqual(events[1]["merge_outcome"],"rejected"); self.assertEqual(events[0]["gate_evidence"]["ci"],"PASSED")
            requested=dict(events[1]); requested.update(outcome="requested",error=None,merge_outcome="requested"); path.write_text("\n".join(map(json.dumps,(events[0],requested)))+"\n"); pr=candidate.observation.github.pull_request; pr.merged_at="2026-09-25T23:00:00Z"; pr.merge_sha=M1
            self.assertEqual(cli._merge_attribution(rt,7,candidate)["state"],"controller_request_confirmed")
            path.write_text(json.dumps(events[0])+"\n"); unknown=cli._merge_attribution(rt,7,candidate); self.assertEqual((unknown["state"],unknown["merge_sha"]),("confirmed_after_unknown_request_outcome",M1))
            pr.head=H2; self.assertEqual(cli._merge_attribution(rt,7,candidate)["state"],"observed_external")
    def test_successful_merge_request_re_reads_github_for_merge_sha(self):
        config=runtime().config; before=SimpleNamespace(number=61,head=H1,merged_at=None,merge_sha=None); after=SimpleNamespace(number=61,head=H1,merged_at="2026-09-25T23:00:00Z",merge_sha=M1); first=SimpleNamespace(pull_request=before,unsafe_reason=None); fresh=SimpleNamespace(pull_request=after,unsafe_reason=None); reader=Mock(); writer=Mock()
        with patch.object(merge,"observe_issue",side_effect=(first,fresh)),patch.object(merge,"adjudication_ledger_error",return_value=None),patch.object(merge,"_blockers",return_value=[]),patch.object(merge,"_close_source_issue") as close:
            result=merge.request_exact_head_merge(config,7,H1,reader,writer)
        self.assertEqual((result.state, result.merge_sha),(merge.MergeResultState.GITHUB_CONFIRMED,M1)); writer.merge.assert_called_once_with("owner/repo",61,H1); close.assert_called_once_with(config,fresh,reader,writer)
    def test_real_reconcile_json_reports_mixed_swarm_results_and_nonzero(self):
        rt=runtime(); calls=[]
        def run(_runtime,*,correlation_id=None,rows=None):
            failed=not calls; calls.append(correlation_id); rows.append({"issue":7,"outcome":"error" if failed else "noop","correlation_id":correlation_id}); return ["a #7: injected"] if failed else []
        args=SimpleNamespace(dry_run=False,json=True,all=True,name=None); out=StringIO()
        with patch.object(cli,"selected",return_value=[Path("a.json"),Path("b.json")]),patch.object(cli,"locked",return_value=MagicMock()),patch.object(cli,"load",return_value=rt),patch.object(cli,"reconcile_runtime",side_effect=run),redirect_stdout(out):
            with self.assertRaisesRegex(RuntimeError,"injected"): cli.reconcile(args)
        payload=json.loads(out.getvalue()); self.assertEqual(payload["status"],"partial_failure"); self.assertEqual([row["status"] for row in payload["swarms"]],["partial_failure","success"]); self.assertEqual([row["issues"][0]["issue"] for row in payload["swarms"]],[7,7]); self.assertEqual(set(calls),{payload["correlation_id"]})
if __name__=="__main__": unittest.main()

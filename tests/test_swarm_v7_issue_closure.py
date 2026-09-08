import importlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS=Path(__file__).parents[1]/"skills"/"github-project-swarm"/"scripts"; sys.path.insert(0,str(SCRIPTS))
v7=importlib.import_module("swarm_v7"); gh=importlib.import_module("swarm_v7_github"); merge=importlib.import_module("swarm_v7_merge")
H1="1"*40; H2="2"*40; MERGED_AT="2026-09-08T01:00:00Z"
def config(): return v7.ManifestV7("test","owner/repo","main",(50,),"worker",("reviewer",),"judge")
def pr(head=H1,merged_at=MERGED_AT): return {"number":61,"state":"closed" if merged_at else "open","draft":False,"base":{"ref":"main"},"head":{"sha":head,"ref":"swarm/test/50"},"mergeable":True,"mergeable_state":"clean","merged_at":merged_at,"labels":[]}
def cross_ref(): return {"event":"cross-referenced","source":{"issue":{"number":61,"repository_url":"https://api.github.com/repos/owner/repo","pull_request":{"url":"https://api.github.com/repos/owner/repo/pulls/61"}}}}
class Reader:
    def __init__(self,state="open",pr_row=None):
        row=pr_row or pr(); head=row["head"]["sha"]; self.values={"repos/owner/repo/issues/50":{"number":50,"state":state},"repos/owner/repo/issues/50/dependencies/blocked_by":[],"repos/owner/repo/issues/50/timeline":[cross_ref()],"repos/owner/repo/pulls/61":row,f"repos/owner/repo/commits/{head}/check-runs?filter=latest":{"check_runs":[]},f"repos/owner/repo/commits/{head}/status":{"statuses":[]},"repos/owner/repo/pulls/61/reviews":[],"repos/owner/repo/issues/61/comments":[]}
    def get(self,endpoint): return self.values.get(endpoint,{})
    def list(self,endpoint): return self.values.get(endpoint,[])
class Writer:
    def __init__(self,reader,*,mutate=True,crash=False): self.reader=reader; self.mutate=mutate; self.crash=crash; self.closes=[]; self.merges=[]
    def merge(self,repo,number,head): self.merges.append((repo,number,head)); return {"merged":True}
    def close_issue(self,repo,number):
        self.closes.append((repo,number))
        if self.mutate: self.reader.values[f"repos/{repo}/issues/{number}"]["state"]="closed"
        if self.crash: raise RuntimeError("crash after close")
        return {"state":"closed"}
class IssueClosureTests(unittest.TestCase):
    def test_merged_pr_without_closing_keyword_stays_actionable_then_closes(self):
        reader=Reader(); observed=gh.observe_issue(config(),50,reader); plan=v7.plan_issue(observed.planner,config()); self.assertTrue(observed.planner.merge_confirmed); self.assertFalse(observed.planner.merged); self.assertEqual(plan.action,v7.Action.MERGE)
        writer=Writer(reader); result=merge.request_exact_head_merge(config(),50,H1,reader,writer); self.assertEqual(result.state,merge.MergeResultState.GITHUB_CONFIRMED); self.assertEqual(writer.closes,[("owner/repo",50)]); self.assertEqual(reader.values["repos/owner/repo/issues/50"]["state"],"closed")
    def test_already_closed_issue_is_idempotent(self):
        reader=Reader(state="closed"); writer=Writer(reader); result=merge.request_exact_head_merge(config(),50,H1,reader,writer); self.assertEqual(result.state,merge.MergeResultState.GITHUB_CONFIRMED); self.assertEqual(writer.closes,[])
    def test_close_api_failure_fails_closed(self):
        reader=Reader()
        def runner(cmd,payload,timeout): raise RuntimeError("close failed")
        with self.assertRaisesRegex(merge.MergeRequestError,"close failed"): merge.request_exact_head_merge(config(),50,H1,reader,merge.GhMerger(runner=runner))
        self.assertEqual(reader.values["repos/owner/repo/issues/50"]["state"],"open")
    def test_close_requires_closed_readback(self):
        reader=Reader(); writer=Writer(reader,mutate=False)
        with self.assertRaisesRegex(merge.MergeAuthorityError,"not CLOSED"): merge.request_exact_head_merge(config(),50,H1,reader,writer)
        self.assertEqual(writer.closes,[("owner/repo",50)])
    def test_crash_after_close_converges_on_retry(self):
        reader=Reader(); first=Writer(reader,crash=True)
        with self.assertRaisesRegex(RuntimeError,"crash after close"): merge.request_exact_head_merge(config(),50,H1,reader,first)
        retry=Writer(reader); result=merge.request_exact_head_merge(config(),50,H1,reader,retry); self.assertEqual(result.state,merge.MergeResultState.GITHUB_CONFIRMED); self.assertEqual(retry.closes,[])
    def test_missing_confirmation_or_head_mismatch_never_closes(self):
        reader=Reader(pr_row=pr(merged_at=None)); writer=Writer(reader)
        with self.assertRaises(merge.MergeAuthorityError): merge.request_exact_head_merge(config(),50,H1,reader,writer)
        self.assertEqual(writer.closes,[])
        reader=Reader(pr_row=pr(head=H2)); writer=Writer(reader)
        with self.assertRaisesRegex(merge.MergeAuthorityError,"head differs"): merge.request_exact_head_merge(config(),50,H1,reader,writer)
        self.assertEqual(writer.closes,[])
    def test_concrete_close_uses_patch(self):
        calls=[]
        def runner(cmd,payload,timeout): calls.append((cmd,json.loads(payload))); return json.dumps({"state":"closed"})
        merge.GhMerger(runner=runner).close_issue("owner/repo",50); self.assertEqual(calls[0][0][2:4],["--method","PATCH"]); self.assertEqual(calls[0][1],{"state":"closed"})
if __name__=="__main__": unittest.main()

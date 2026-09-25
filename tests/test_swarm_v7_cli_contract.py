import json, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
ROOT=Path(__file__).parents[1]; SCRIPTS=ROOT/"skills"/"github-project-swarm"/"scripts"
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
import swarm_v7_cli as cli
from swarm_v7 import Action, ManifestV7, Observation, Phase, Plan
from swarm_v7_controller import ActionResult, IssueObservation, PlannedIssue, RuntimeManifest, plan_payload
from swarm_v7_github import GitHubIssueObservation
def runtime(): return RuntimeManifest(ManifestV7("demo","owner/repo","main",(7,),"worker",("r1","r2"),"judge"),"/repo","demo","sat-swarm",2,"30m",{})
def planned():
    observation=Observation(issue_number=7); github=GitHubIssueObservation(7,"OPEN",(),None,observation); wrapped=IssueObservation(github,observation,{}); return PlannedIssue(wrapped,Plan(Phase.NEEDS_IMPLEMENTATION,Action.START_IMPLEMENTATION,"reason",None,"issue:7:intent"))
class CliContractTests(unittest.TestCase):
    def test_dry_run_explain_and_live_share_plan_once(self):
        rt,item=runtime(),planned(); planner=Mock(return_value=item); adapter=Mock(); adapter.watchdog.return_value={}
        with patch.object(cli,"selected",return_value=[Path("demo.json")]),patch.object(cli,"load",return_value=rt),patch.object(cli,"KanbanAdapter",return_value=adapter),patch.object(cli,"plan_once",planner),patch.object(cli,"apply_plan",return_value=ActionResult("active")) as apply,patch.object(cli,"save"),patch.object(cli,"journal"),redirect_stdout(StringIO()):
            cli.dry_run(name="demo",json_output=True); cli.explain(name="demo",issue=7,json_output=True); self.assertEqual(adapter.watchdog.call_count,0); self.assertEqual(cli.reconcile_runtime(rt),[])
        self.assertEqual(adapter.watchdog.call_count,1); self.assertEqual(planner.call_count,3); self.assertIs(apply.call_args.args[1],item); self.assertEqual(plan_payload(item.plan)["action"],"START_IMPLEMENTATION")
    def test_retire_persists_reason_and_removes_issue_from_active_scope(self):
        rt=runtime(); adapter=Mock(); adapter.watchdog.return_value={}; adapter.block_issue.return_value=("task-7",)
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)),patch.object(cli,"KanbanAdapter",return_value=adapter),redirect_stdout(StringIO()):
            cli.save(rt); cli.retire(SimpleNamespace(name="demo",issue=7,reason="closed externally")); saved=cli.load(Path(td)/"demo.json"); event=json.loads((Path(td)/"demo.journal.jsonl").read_text())
            with self.assertRaisesRegex(RuntimeError,r"retired.*closed externally"): cli.explain(name="demo",issue=7)
            with patch.object(cli,"plan_once") as plan: self.assertEqual(cli.reconcile_runtime(saved),[]); plan.assert_not_called()
            status=StringIO()
            with patch.object(cli,"_timer_health"),redirect_stdout(status): cli.dry_run(name="demo")
        adapter.block_issue.assert_called_once_with("demo",7,"retired by operator: closed externally"); self.assertEqual(saved.config.issues,()); self.assertEqual(saved.retired_issues,{"7":"closed externally"}); self.assertEqual((event["outcome"],event["detail"],event["task_ids"]),("retired","closed externally",["task-7"])); self.assertIn("no active issues",status.getvalue()); self.assertNotIn("no swarms configured",status.getvalue())
    def test_all_reconcile_isolates_busy_swarm_and_surfaces_other_failure(self):
        rt=runtime(); busy=MagicMock(); busy.__enter__.side_effect=BlockingIOError; err=StringIO(); args=Mock(dry_run=False,json=False,all=True); args.name=None
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)),patch.object(cli,"locked",side_effect=[busy,MagicMock(),MagicMock()]),patch.object(cli,"load",return_value=rt),patch.object(cli,"reconcile_runtime",side_effect=[["b #7: injected"],[]]) as run,redirect_stderr(err):
            for name in ("a.json","b.json","c.json"): (Path(td)/name).touch()
            with self.assertRaisesRegex(RuntimeError,"injected"): cli.reconcile(args)
        self.assertIn("a: reconcile already running; skipped",err.getvalue()); self.assertEqual(run.call_count,2)
    def test_unsafe_planning_result_is_journaled_not_persisted(self):
        rt=runtime(); obs=Observation(issue_number=7,unsafe_reason="observation failed"); gh=GitHubIssueObservation(7,"CLOSED",(),None,obs,"observation failed"); item=PlannedIssue(IssueObservation(gh,obs,{}),Plan(Phase.EXECUTION_STALLED,None,"unsafe observation: observation failed",None,None))
        adapter=Mock(); adapter.watchdog.return_value={}
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)),patch.object(cli,"KanbanAdapter",return_value=adapter),patch.object(cli,"plan_once",return_value=item),patch.object(cli,"save") as save:
            errors=cli.reconcile_runtime(rt); event=json.loads((Path(td)/"demo.journal.jsonl").read_text())
        self.assertEqual(errors,["demo #7: observation failed"]); self.assertEqual(event["outcome"],"error"); self.assertIn("demo [owner/repo] #7: state=CLOSED",cli._render(cli._snapshot(rt,7,item))); save.assert_not_called()
if __name__=="__main__": unittest.main()

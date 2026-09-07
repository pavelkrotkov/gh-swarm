import json, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
ROOT=Path(__file__).parents[1]; SCRIPTS=ROOT/"skills"/"github-project-swarm"/"scripts"; BOOTSTRAP=SCRIPTS/"bootstrap.sh"; SERVICE=ROOT/"skills/github-project-swarm/templates/systemd/hermes-swarm-reconcile.service"; TIMER=ROOT/"skills/github-project-swarm/templates/systemd/hermes-swarm-reconcile.timer"
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
import swarm_v7_cli as cli
import swarm_v7_cli_process as process
from swarm_v7 import Action, AdjudicationDecision, CiState, ExecutionState, ManifestV7, Observation, Phase, Plan, ReviewState, plan_issue
from swarm_v7_controller import ActionResult, ExecutionContext, IssueObservation, PlannedIssue, RuntimeManifest, _overlay, _slot, _worker, dispatch_attempts
from swarm_v7_github import GitHubIssueObservation
from swarm_v7_kanban import Outcome, semantic_key
LEGACY=("lifecycle.py","observability.py","swarm.py","swarm_v6.py","swarm_legacy.py")
def runtime(paused=False,issues=(1,2)): return RuntimeManifest(ManifestV7("demo","owner/repo","main",issues,"worker",("r1","r2"),"judge",paused=paused),"/repo","demo","sat-swarm",2,"30m",{})
def planned(issue=1):
    obs=Observation(issue_number=issue); gh=GitHubIssueObservation(issue,"OPEN",(),None,obs); return PlannedIssue(IssueObservation(gh,obs,{}),Plan(Phase.NEEDS_IMPLEMENTATION,Action.START_IMPLEMENTATION,"reason",None,f"issue:{issue}:intent"))
class LifecycleTests(unittest.TestCase):
    def test_only_final_v7_runtime_entrypoints_remain(self):
        for name in LEGACY: self.assertFalse((SCRIPTS/name).exists(),name)
        self.assertNotIn("Facade",(SCRIPTS/"swarm_v7_cli.py").read_text())
    def test_cli_contains_exact_retained_command_surface(self): self.assertEqual(set(cli._parser()._subparsers._group_actions[0].choices),{"init","status","reconcile","pause","resume","doctor","validate","explain","prepare","activate","disable"})
    def test_schema_five_and_six_fail_closed(self):
        for schema in (5,6):
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/"old.json"; path.write_text(json.dumps({"schema":schema}))
                with self.assertRaisesRegex(RuntimeError,"fresh v7"): cli.load(path)
    def test_schema_seven_rejects_hidden_state(self):
        data=runtime(issues=(1,)).to_dict()
        for field in ("state","finished","acceptance","review","round"):
            with self.assertRaisesRegex(ValueError,"legacy/unknown fields"): RuntimeManifest.from_dict(data|{field:"stale"})
    def test_manifest_save_is_atomic_and_fsynced(self):
        rt=runtime(issues=(1,))
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)),patch.object(cli,"_fsync_directory") as fsync:
            cli.save(rt); self.assertEqual(cli.load(Path(td)/"demo.json").to_dict(),rt.to_dict()); fsync.assert_called_once_with(Path(td)); self.assertEqual(list(Path(td).glob("*.tmp")),[])
    def test_nonblocking_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"demo.lock"
            with cli.locked(path):
                with self.assertRaises(BlockingIOError):
                    with cli.locked(path,nonblocking=True): pass
    def test_subprocess_timeout_is_bounded(self):
        with patch.dict(process.os.environ,{"HERMES_SWARM_SUBPROCESS_TIMEOUT":"0.2"}),patch.object(process.subprocess,"run",side_effect=subprocess.TimeoutExpired(["gh"],0.2)):
            with self.assertRaisesRegex(RuntimeError,"timed out after 0.2s"): process.run_command(["gh","api","rate_limit"],timeout=30)
    def test_attempt_cursor_survives_observation_failure(self):
        rt=runtime(issues=(1,)); adapter=Mock(); adapter.create.return_value="task-1"; adapter.observe.side_effect=RuntimeError("lost observation"); key="issue:1:implementation"
        with self.assertRaisesRegex(RuntimeError,"lost observation"): dispatch_attempts(rt,adapter,key,Mock())
        self.assertEqual(rt.cursors[key],{"task_id":"task-1","attempt":1})
    def test_active_task_without_worker_run_fails_closed_next_reconcile(self):
        rt=runtime(issues=(1,)); key="swarm:demo:issue:1:implementation"; rt.cursors[key]={"task_id":"task-1","attempt":1}; adapter=Mock(); adapter.observe.return_value=SimpleNamespace(outcome=Outcome.ACTIVE,status="ready",has_run=False,task_id="task-1"); state,reason=_slot(rt,key,adapter,{})
        self.assertEqual(state,ExecutionState.FAILED); self.assertIn("no worker run",reason)
    def test_exhausted_implementation_attempt_fails_closed(self):
        rt=runtime(issues=(1,)); key="swarm:demo:issue:1:implementation"; rt.cursors[key]={"task_id":"task-2","attempt":2}; adapter=Mock(); adapter.observe.return_value=SimpleNamespace(outcome=Outcome.FAILURE,status="blocked",has_run=True,task_id="task-2"); state,reason=_slot(rt,key,adapter,{})
        self.assertEqual(state,ExecutionState.FAILED); self.assertIn("attempts exhausted",reason)
    def test_slot_maps_active_success_and_retryable_failure(self):
        rt=runtime(issues=(1,)); key="swarm:demo:issue:1:implementation"; rt.cursors[key]={"task_id":"task-1","attempt":1}; adapter=Mock()
        for outcome,status,expected in ((Outcome.ACTIVE,"running",ExecutionState.RUNNING),(Outcome.SUCCESS,"done",ExecutionState.IDLE),(Outcome.FAILURE,"blocked",ExecutionState.IDLE)):
            with self.subTest(outcome=outcome): adapter.observe.return_value=SimpleNamespace(outcome=outcome,status=status,has_run=True,task_id="task-1"); self.assertEqual(_slot(rt,key,adapter,{})[0],expected)
    def test_durable_adjudication_beats_completed_task_cursor(self): rt=runtime(issues=(1,)); head="1"*40; key=semantic_key(rt.config.swarm_id,1,"adjudication",head=head); rt.cursors[key]={"task_id":"task-3","attempt":1}; planner=Observation(1,pr_head=head,ci=CiState.PASSED,review=ReviewState.DISPUTED,adjudication_decision=AdjudicationDecision.REVISE); github=SimpleNamespace(issue_number=1,pull_request=SimpleNamespace(head=head,reviewers=(SimpleNamespace(slot=1),SimpleNamespace(slot=2))),planner=planner); adapter=Mock(); adapter.observe.return_value=SimpleNamespace(outcome=Outcome.SUCCESS,status="done",has_run=True,task_id="task-3"); self.assertEqual(plan_issue(_overlay(rt,github,adapter,{}),rt.config).action,Action.START_REVISION); adapter.observe.assert_not_called()
    def test_completed_revision_yields_to_durable_publication(self):
        rt=runtime(issues=(1,)); head="3"*40; rt.cursors[semantic_key(rt.config.swarm_id,1,"revision",head=head)]={"task_id":"task-5","attempt":1}; planner=Observation(1,pr_head=head,ci=CiState.PASSED,review=ReviewState.DISPUTED,adjudication_decision=AdjudicationDecision.ACCEPT); github=SimpleNamespace(issue_number=1,pull_request=SimpleNamespace(head=head,reviewers=(SimpleNamespace(slot=1),SimpleNamespace(slot=2))),planner=planner); adapter=Mock(); adapter.observe.return_value=SimpleNamespace(outcome=Outcome.SUCCESS,status="done",has_run=True,task_id="task-5")
        plan=plan_issue(_overlay(rt,github,adapter,{}),rt.config); self.assertEqual((plan.phase,plan.action),(Phase.READY_TO_MERGE,Action.MERGE))
    def test_remote_exact_head_ci_failure_beats_done_worker_task(self): rt=runtime(issues=(1,)); head="2"*40; rt.cursors[semantic_key(rt.config.swarm_id,1,"implementation")]={"task_id":"task-4","attempt":1}; github=SimpleNamespace(issue_number=1,pull_request=SimpleNamespace(head=head,reviewers=()),planner=Observation(1,pr_head=head,ci=CiState.FAILED)); adapter=Mock(); adapter.observe.return_value=SimpleNamespace(outcome=Outcome.SUCCESS,status="done",has_run=True,task_id="task-4"); self.assertEqual(plan_issue(_overlay(rt,github,adapter,{}),rt.config).action,Action.START_REVISION); adapter.observe.assert_not_called()
    def test_worker_task_uses_supported_first_failure_retry(self):
        rt=runtime(issues=(1,)); adapter=Mock(); adapter.create.return_value="task-1"; adapter.observe.return_value=SimpleNamespace(outcome=Outcome.ACTIVE,status="running"); workspace=Mock(); workspace.prepare.return_value="1"*40; reader=Mock(); reader.get.return_value={"body":"work"}; item=planned(); ctx=ExecutionContext(rt,item.observation,reader,adapter,workspace,Mock())
        _worker(ctx,item.plan,False); spec=adapter.create.call_args.args[0]; self.assertEqual(spec.max_retries,1); self.assertEqual(spec.assignee,"sat-swarm"); self.assertIn("all required checks for PUSHED_SHA have completed successfully",spec.body); self.assertIn("prior-head, base-branch, merge-candidate, sibling-PR, and local results do not count",spec.body); self.assertIn("104595",spec.body)
    def test_invalid_zero_attempt_bound_fails_before_dispatch(self):
        rt=runtime(issues=(1,)); rt.max_attempts=0; adapter=Mock()
        with self.assertRaisesRegex(ValueError,"max_execution_attempts must be positive"): dispatch_attempts(rt,adapter,"issue:1:implementation",Mock())
        adapter.create.assert_not_called()
    def test_reconcile_applies_once_and_failure_does_not_persist(self):
        rt,item=runtime(issues=(1,)),planned(); result=ActionResult("active",("task-1",))
        with patch.object(cli,"plan_once",return_value=item),patch.object(cli,"apply_plan",return_value=result) as apply,patch.object(cli,"save") as save,patch.object(cli,"journal"): self.assertEqual(cli.reconcile_runtime(rt),[])
        apply.assert_called_once_with(rt,item); save.assert_called_once_with(rt)
        with patch.object(cli,"plan_once",return_value=item),patch.object(cli,"apply_plan",side_effect=RuntimeError("execution failed")),patch.object(cli,"save") as save,patch.object(cli,"journal"): self.assertIn("execution failed",cli.reconcile_runtime(rt)[0]); save.assert_not_called()
    def test_paused_init_is_configuration_only(self):
        args=SimpleNamespace(repo="owner/repo",repo_path="/repo",issues="1",epic=None,name="demo",board=None,assignee="sat-swarm",worker="worker",reviewer=["r1","r2"],adjudicator=None,ci_mode="required",paused=True,max_execution_attempts=2,max_runtime="30m"); reader=Mock(); reader.get.side_effect=[{"number":1,"state":"open"},{"default_branch":"main"}]
        with tempfile.TemporaryDirectory() as td,patch.object(cli,"STATE",Path(td)),patch.object(cli,"GhReader",return_value=reader),patch.object(cli,"GitWorkspace") as workspace,patch.object(cli,"KanbanAdapter") as kanban,patch.object(cli,"save") as save:
            cli.init(args)
        workspace.return_value.validate_binding.assert_called_once_with("owner/repo"); kanban.return_value.create_board.assert_called_once(); save.assert_called_once_with(save.call_args.args[0]); self.assertEqual(save.call_args.args[0].assignee,"sat-swarm")
    def test_disable_targets_only_swarm_units(self):
        with patch.object(cli,"systemctl") as systemctl: cli.disable()
        self.assertEqual([call.args for call in systemctl.call_args_list],[("disable","--now","hermes-swarm-reconcile.timer"),("stop","hermes-swarm-reconcile.service")])
    def test_timer_rearms_after_restart_and_dead_schedule_fails_loudly(self):
        timer=TIMER.read_text(); self.assertIn("OnActiveSec=2min",timer); self.assertIn("OnUnitInactiveSec=2min",timer); self.assertNotIn("OnBootSec=",timer); self.assertNotIn("OnUnitActiveSec=",timer)
        dead="ActiveState=active\nNextElapseUSecMonotonic=0"
        with patch.object(cli,"systemctl",side_effect=(dead,"inactive")),self.assertRaisesRegex(RuntimeError,"no next elapse"): cli._timer_health()
        with patch.object(cli,"systemctl",side_effect=(dead,"activating")): cli._timer_health()
        with patch.object(cli,"systemctl",return_value="ActiveState=active\nNextElapseUSecMonotonic=123"): cli._timer_health()
        args=cli._parser().parse_args(["status","--all"])
        with patch.object(cli,"_timer_health") as health,patch.object(cli,"selected",return_value=[]): args.fn(args); health.assert_called_once()
        with patch.object(cli,"run_command",return_value=" ".join(cli._REQUIRED)),patch.object(cli,"KanbanAdapter"),patch.object(cli,"_timer_health") as health: cli.doctor(SimpleNamespace(repo=None)); health.assert_called_once()
    def test_bootstrap_and_service_stay_gateway_independent(self):
        bootstrap=BOOTSTRAP.read_text(); service=SERVICE.read_text(); self.assertIn("hermes swarm reconcile --all",service); self.assertIn("TimeoutStartSec=15min",service); self.assertNotIn("hermes-gateway.service",bootstrap+(SCRIPTS/"swarm_v7_cli.py").read_text())
if __name__=="__main__": unittest.main()

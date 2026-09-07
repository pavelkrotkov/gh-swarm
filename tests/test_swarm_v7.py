import ast, builtins, importlib.util, subprocess, sys, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
SCRIPTS = Path(__file__).parents[1] / "skills" / "github-project-swarm" / "scripts"; SCRIPT = SCRIPTS / "swarm_v7.py"
if str(SCRIPTS) not in sys.path: sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("swarm_v7", SCRIPT); v7 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(v7); H1 = "1" * 40
def config(*, paused=False, ci_required=True): return v7.ManifestV7(swarm_id="test", repo="owner/repo", default_branch="main", issues=(45,), worker_model="worker", reviewer_models=("reviewer-a","reviewer-b"), adjudicator_model="adjudicator", ci_required=ci_required, paused=paused)
def obs(**changes): return replace(v7.Observation(issue_number=45), **changes)
class PlannerTransitionTests(unittest.TestCase):
    def test_table_covers_every_phase_and_action(self):
        cases = [(obs(merged=True),v7.Phase.MERGED,None),(obs(dependency=v7.DependencyState.BLOCKED),v7.Phase.WAITING_DEPENDENCY,None),(obs(),v7.Phase.NEEDS_IMPLEMENTATION,v7.Action.START_IMPLEMENTATION),(obs(implementation=v7.ExecutionState.RUNNING),v7.Phase.IMPLEMENTATION_RUNNING,None),(obs(pr_head=H1,ci=v7.CiState.PENDING),v7.Phase.WAITING_CI,None),(obs(pr_head=H1,ci=v7.CiState.PASSED),v7.Phase.NEEDS_REVIEW,v7.Action.START_REVIEW),(obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.RUNNING),v7.Phase.REVIEW_RUNNING,None),(obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.DISPUTED),v7.Phase.NEEDS_ADJUDICATION,v7.Action.START_ADJUDICATION),(obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.DISPUTED,adjudication=v7.ExecutionState.RUNNING),v7.Phase.ADJUDICATION_RUNNING,None),(obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.CHANGES_REQUESTED),v7.Phase.NEEDS_REVISION,v7.Action.START_REVISION),(obs(pr_head=H1,revision=v7.ExecutionState.RUNNING),v7.Phase.REVISION_RUNNING,None),(obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.APPROVED),v7.Phase.READY_TO_MERGE,v7.Action.MERGE),(obs(pr_head=H1,ci=v7.CiState.UNKNOWN),v7.Phase.EXECUTION_STALLED,None)]
        phases, actions = set(), set()
        for observation, phase, action in cases:
            plan = v7.plan_issue(observation, config()); self.assertEqual((plan.phase, plan.action),(phase,action)); phases.add(plan.phase); actions |= {plan.action} if plan.action else set()
        self.assertEqual(phases,set(v7.Phase)); self.assertEqual(actions,set(v7.Action))
    def test_pause_and_exact_head_intent(self):
        live = v7.plan_issue(obs(pr_head=H1,ci=v7.CiState.PASSED),config()); paused = v7.plan_issue(obs(pr_head=H1,ci=v7.CiState.PASSED),config(paused=True)); self.assertIsNone(paused.action); self.assertEqual(paused.would_action,live.action); self.assertEqual(paused.intent_key,live.intent_key); self.assertTrue(live.intent_key.endswith(H1))
    def test_ci_none_and_adjudication(self):
        self.assertEqual(v7.plan_issue(obs(pr_head=H1),config(ci_required=False)).action,v7.Action.START_REVIEW); accepted=obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.DISPUTED,adjudication_decision=v7.AdjudicationDecision.ACCEPT); self.assertEqual(v7.plan_issue(accepted,config()).action,v7.Action.MERGE); self.assertEqual(v7.plan_issue(replace(accepted,adjudication_decision=v7.AdjudicationDecision.REVISE),config()).action,v7.Action.START_REVISION)
    def test_execution_precedence_and_unsafe_fail_closed(self):
        running=obs(pr_head=H1,implementation=v7.ExecutionState.RUNNING,revision=v7.ExecutionState.FAILED); self.assertEqual(v7.plan_issue(running,config()).phase,v7.Phase.IMPLEMENTATION_RUNNING)
        for observation in (obs(dependency=v7.DependencyState.UNKNOWN),obs(pr_head="short",ci=v7.CiState.PASSED),obs(pr_head=H1,ci=v7.CiState.PASSED,review=v7.ReviewState.UNKNOWN),obs(unsafe_reason="conflict"),obs(ci=v7.CiState.PENDING)):
            self.assertEqual(v7.plan_issue(observation,config()).phase,v7.Phase.EXECUTION_STALLED)
    def test_planner_is_deterministic_and_io_free(self):
        observation=obs(pr_head=H1,ci=v7.CiState.PASSED); self.assertEqual(v7.plan_issue(observation,config()),v7.plan_issue(observation,config()))
        with patch.object(builtins,"open") as opened, patch.object(subprocess,"run") as run, patch.object(Path,"write_text") as write: v7.plan_issue(observation,config())
        opened.assert_not_called(); run.assert_not_called(); write.assert_not_called()
class ManifestV7Tests(unittest.TestCase):
    def test_round_trip_and_forbidden_state(self):
        raw=config().to_dict(); self.assertEqual(v7.ManifestV7.from_dict(raw),config())
        for key in v7._FORBIDDEN:
            with self.assertRaises(ValueError): v7.ManifestV7.from_dict(raw|{key:{}})
    def test_validation_order(self):
        raw=config().to_dict(); models=dict(raw["models"]); models["reviewers"]=[" "]
        with self.assertRaisesRegex(ValueError,r"^models\.reviewers must be a non-empty string$"): v7.ManifestV7.from_dict(raw|{"models":models})
        with self.assertRaisesRegex(ValueError,r"^id must be a non-empty string$"): v7.ManifestV7.from_dict(raw|{"id":"","issues":[]})
    def test_final_core_has_no_legacy_controller_dependency(self):
        tree=ast.parse(SCRIPT.read_text(encoding="utf-8")); imported={alias.name for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)) for alias in node.names}; self.assertFalse(imported & {"swarm","swarm_v6","swarm_legacy","lifecycle","observability","importlib"}); self.assertNotIn("globals()",SCRIPT.read_text(encoding="utf-8"))
if __name__ == "__main__": unittest.main()

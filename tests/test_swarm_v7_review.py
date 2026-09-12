import importlib
import shlex
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).parents[1] / "skills" / "github-project-swarm" / "scripts"
sys.path.insert(0, str(SCRIPTS))
v7 = importlib.import_module("swarm_v7")
gh = importlib.import_module("swarm_v7_github")
kb = importlib.import_module("swarm_v7_kanban")
rx = importlib.import_module("swarm_v7_review")

H1 = "1" * 40
H2 = "2" * 40


def config():
    return v7.ManifestV7(swarm_id="s", repo="owner/repo", default_branch="main", issues=(49,), worker_model="worker", reviewer_models=("reviewer-a --provider alpha", "reviewer-b"), adjudicator_model="judge --provider beta", ci_required=False)


def target(head=H1): return rx.ExactHeadTarget("owner/repo", 49, 60, head, "dir:/tmp/swarm-review-launcher", "sat-swarm")
def review(slot, head=H1): return gh.ReviewerPublication(slot, head)
def adjudication(head=H1, decision="accept"): return gh.AdjudicationPublication(head, {"head_sha":head,"decision":decision,"comment_dispositions":[],"required_changes":[]})


class FakeAdapter:
    def __init__(self):
        self.by_key = {}; self.outcomes = {}; self.created_specs = {}; self.default_outcome = kb.Outcome.ACTIVE; self.next_id = 1
    def set_outcome(self, attempt_key, outcome): self.outcomes[attempt_key] = outcome
    def create(self, spec, key, attempt=1):
        attempt_key = kb.attempt_key(key, attempt)
        if attempt_key not in self.by_key:
            task_id = f"task-{self.next_id}"; self.next_id += 1; self.by_key[attempt_key] = task_id; self.created_specs[attempt_key] = spec
        return self.by_key[attempt_key]
    def observe(self, task_id):
        key = next(key for key, value in self.by_key.items() if value == task_id); return SimpleNamespace(outcome=self.outcomes.get(key, self.default_outcome))


class ReviewerSlotTests(unittest.TestCase):
    def test_reviewer_uses_stable_launcher_not_implementation_worktree(self):
        spec = rx.reviewer_task_spec(config(), target(), 1); self.assertEqual(spec.workspace, "dir:/tmp/swarm-review-launcher"); self.assertEqual(spec.model,"reviewer-a"); self.assertEqual(spec.provider,"alpha"); self.assertEqual(spec.assignee,"sat-swarm"); self.assertIsNone(spec.branch); self.assertIn(H1, spec.body); self.assertIn("disposable temporary checkout", spec.body); self.assertIn("Do not depend on or modify the implementation worktree", spec.body)
    def test_publication_satisfies_slot_even_if_attempt_failed(self):
        adapter = FakeAdapter(); key = kb.semantic_key("s", 49, "review", slot=1, head=H1); adapter.set_outcome(key, kb.Outcome.FAILURE); adapter.create(rx.reviewer_task_spec(config(), target(), 1), key); before = dict(adapter.by_key); result = rx.reconcile_reviewers(config(), target(), (review(1), review(2)), adapter)[0]
        self.assertEqual(result.state, rx.SlotState.SATISFIED); self.assertEqual(adapter.by_key, before)
    def test_failed_attempt_without_publication_gets_bounded_same_slot_replacement(self):
        adapter = FakeAdapter(); key = kb.semantic_key("s", 49, "review", slot=1, head=H1); adapter.set_outcome(key, kb.Outcome.FAILURE); adapter.set_outcome(f"{key}:a2", kb.Outcome.ACTIVE); results = rx.reconcile_reviewers(config(), target(), (review(2),), adapter)
        self.assertEqual(results[0].state, rx.SlotState.ACTIVE); self.assertEqual(results[0].attempt, 2); self.assertIn(key, adapter.by_key); self.assertIn(f"{key}:a2", adapter.by_key); self.assertEqual(adapter.created_specs[key].max_retries,1)
    def test_done_without_visible_publication_waits_and_never_replays(self):
        adapter = FakeAdapter(); key = kb.semantic_key("s", 49, "review", slot=1, head=H1); adapter.set_outcome(key, kb.Outcome.SUCCESS); first = rx.reconcile_reviewers(config(), target(), (review(2),), adapter)[0]; second = rx.reconcile_reviewers(config(), target(), (review(2),), adapter)[0]
        self.assertEqual(first.state, rx.SlotState.WAITING_PUBLICATION); self.assertEqual(second.state, rx.SlotState.WAITING_PUBLICATION); self.assertNotIn(f"{key}:a2", adapter.by_key)
    def test_head_drift_ignores_h1_execution_and_starts_fresh_h2_slot(self):
        adapter = FakeAdapter(); h1 = rx.reconcile_reviewers(config(), target(H1), (), adapter)[0]; h2 = rx.reconcile_reviewers(config(), target(H2), (), adapter)[0]
        self.assertEqual(h1.state, rx.SlotState.ACTIVE); self.assertEqual(h2.state, rx.SlotState.ACTIVE); self.assertNotEqual(h1.semantic_key, h2.semantic_key); self.assertIn(H1, h1.semantic_key); self.assertIn(H2, h2.semantic_key)
    def test_create_error_propagates_instead_of_falling_through_to_exhausted(self):
        class RaisingAdapter:
            def create(self, spec, key, attempt=1): raise kb.KanbanExecutionError("create failed")
        with self.assertRaisesRegex(kb.KanbanExecutionError, "create failed"): rx.reconcile_reviewers(config(), target(), (review(2),), RaisingAdapter())


class AdjudicationSlotTests(unittest.TestCase):
    def test_all_head_reviews_dispatch_exactly_one_adjudication_slot(self):
        adapter = FakeAdapter(); reviewers = (review(1), review(2)); first = rx.reconcile_adjudication(config(), target(), reviewers, (), adapter); second = rx.reconcile_adjudication(config(), target(), reviewers, (), adapter); key = kb.semantic_key("s", 49, "adjudication", head=H1)
        self.assertEqual(first.state, rx.SlotState.ACTIVE); self.assertEqual(second.state, rx.SlotState.ACTIVE); self.assertEqual(list(k for k in adapter.by_key if k.startswith(key)), [key]); self.assertEqual(adapter.created_specs[key].max_retries,1); self.assertEqual(adapter.created_specs[key].model,"judge"); self.assertEqual(adapter.created_specs[key].provider,"beta"); self.assertEqual(adapter.created_specs[key].assignee,"sat-swarm")
    def test_adjudication_not_dispatched_until_every_head_review_exists(self):
        adapter = FakeAdapter(); result = rx.reconcile_adjudication(config(), target(), (review(1),), (), adapter); self.assertEqual(result.state, rx.SlotState.NOT_READY); self.assertEqual(adapter.by_key, {})
    def test_valid_adjudication_satisfies_slot_even_if_task_failed(self):
        adapter = FakeAdapter(); key = kb.semantic_key("s", 49, "adjudication", head=H1); adapter.set_outcome(key, kb.Outcome.FAILURE); adapter.create(rx.adjudicator_task_spec(config(), target()), key); before = dict(adapter.by_key); result = rx.reconcile_adjudication(config(), target(), (review(1), review(2)), (adjudication(),), adapter)
        self.assertEqual(result.state, rx.SlotState.SATISFIED); self.assertEqual(adapter.by_key, before)
    def test_success_without_valid_adjudication_uses_next_bounded_attempt(self):
        adapter = FakeAdapter(); key = kb.semantic_key("s", 49, "adjudication", head=H1); adapter.set_outcome(key, kb.Outcome.SUCCESS); adapter.set_outcome(f"{key}:a2", kb.Outcome.ACTIVE); result = rx.reconcile_adjudication(config(), target(), (review(1), review(2)), (), adapter)
        self.assertEqual(result.state,rx.SlotState.ACTIVE); self.assertEqual(result.attempt,2); self.assertIn(f"{key}:a2",adapter.by_key)
    def test_duplicate_current_head_adjudication_fails_closed(self):
        with self.assertRaisesRegex(rx.ReviewExecutionError, "duplicate adjudication"): rx.reconcile_adjudication(config(), target(), (review(1), review(2)), (adjudication(), adjudication()), FakeAdapter())


class ContractTests(unittest.TestCase):
    def test_reviewer_prompt_pins_native_review_write_and_readback(self):
        for head, slot in ((H1, 1), (H2, 2)):
            with self.subTest(head=head, slot=slot):
                body = rx.reviewer_task_spec(config(), target(head), slot).body
                commands = [shlex.split(line.strip()) for line in body.splitlines() if line.strip().startswith("gh api ")]
                endpoint = "repos/owner/repo/pulls/60/reviews"
                self.assertEqual(commands, [
                    ["gh", "api", "--method", "GET", "--paginate", endpoint],
                    ["gh", "api", "--method", "POST", endpoint, "-f", "event=COMMENT", "-f", f"commit_id={head}", "-f", "body=$summary"],
                    ["gh", "api", "--method", "GET", "--paginate", endpoint],
                ])
                self.assertIn(gh.review_marker("s", 49, slot, head), body)
                self.assertIn(f"commit_id equals {head}", body)
                self.assertIn("/issues/60/comments", body)
                self.assertIn("/pulls/60/comments", body)

    def test_reviewer_skill_and_task_share_fail_closed_publication_rules(self):
        skill = (SCRIPTS.parents[1] / "github-project-reviewer" / "SKILL.md").read_text()
        task = rx.reviewer_task_spec(config(), target(), 1).body
        for name, text in (("skill", skill), ("task", task)):
            with self.subTest(source=name):
                for rule in (
                    "submitted native GitHub pull-request review", "Publish the summary last",
                    "Never use", "gh pr comment", "for the summary", "state equals COMMENTED",
                    "submitted_at is present", "Missing fields are failures", "POST times out",
                    "do not substitute an issue comment", "summary_review_id", "summary_review_url",
                    "reviewed_head", "finding_comment_ids", "finish without new writes",
                ):
                    self.assertIn(rule, text)
                self.assertLess(text.index("Before any publication"), text.index("Publish and verify"))
                self.assertNotIn("when GitHub exposes", text)
                self.assertNotIn("when exposed", text)
                self.assertNotIn("summary_comment_id", text)

    def test_worker_contracts_require_publication_before_success(self):
        review_body = rx.reviewer_task_spec(config(), target(), 1).body; judge_body = rx.adjudicator_task_spec(config(), target()).body
        self.assertIn("Only then may the Kanban task report success", review_body); self.assertIn("Only then may the Kanban task report success", judge_body); self.assertIn("exactly one", review_body); self.assertIn("exactly one", judge_body); self.assertNotIn("review_publication_waits", review_body + judge_body); self.assertNotIn("round counter", review_body + judge_body)


if __name__ == "__main__": unittest.main()

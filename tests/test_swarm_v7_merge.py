import base64
import importlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "skills" / "github-project-swarm" / "scripts"
sys.path.insert(0, str(SCRIPTS))
v7 = importlib.import_module("swarm_v7")
gh = importlib.import_module("swarm_v7_github")
merge = importlib.import_module("swarm_v7_merge")

H1 = "1" * 40
H2 = "2" * 40


def config(*, ci_required=True, paused=False):
    return v7.ManifestV7(
        swarm_id="test",
        repo="owner/repo",
        default_branch="main",
        issues=(50, 51),
        worker_model="worker",
        reviewer_models=("reviewer-a", "reviewer-b"),
        adjudicator_model="judge",
        ci_required=ci_required,
        paused=paused,
    )


def review(slot, head=H1, *, native=None):
    return {
        "id": 100 + slot,
        "body": gh.review_marker("test", 50, slot, head),
        "commit_id": native if native is not None else head,
    }


def finding(slot, ident, head=H1, *, native=None):
    row = {"id": ident, "body": gh.review_marker("test", 50, slot, head) + "\nFinding"}
    if native is not None:
        row["commit_id"] = native
    return row


def decision(head=H1, *, finding_ids=(301, 302), ident=400, value="accept"):
    payload = {
        "head_sha": head,
        "decision": value,
        "comment_dispositions": [
            {"github_comment_id": finding_id, "disposition": "accepted-risk", "reason": "adjudicated"}
            for finding_id in finding_ids
        ],
        "required_changes": [],
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return {
        "id": ident,
        "body": gh.adjudication_marker("test", 50, head)
        + f"\n<!-- hermes-swarm-decision-b64:{encoded} -->",
    }


def malformed_decision(head=H1):
    return {
        "id": 499,
        "body": gh.adjudication_marker("test", 50, head)
        + "\n<!-- hermes-swarm-decision-b64:not-valid-base64 -->",
    }


def pr(head=H1, *, state="open", draft=False, labels=(), mergeable=True,
       merge_state="clean", merged_at=None):
    return {
        "number": 61,
        "html_url": "https://github.com/owner/repo/pull/61",
        "state": state,
        "draft": draft,
        "base": {"ref": "main"},
        "head": {"sha": head, "ref": "swarm/test/50"},
        "mergeable": mergeable,
        "mergeable_state": merge_state,
        "merged_at": merged_at,
        "labels": [{"name": label} for label in labels],
    }


def cross_ref(number=61):
    return {
        "event": "cross-referenced",
        "source": {
            "issue": {
                "number": number,
                "repository_url": "https://api.github.com/repos/owner/repo",
                "pull_request": {"url": f"https://api.github.com/repos/owner/repo/pulls/{number}"},
            }
        },
    }


class FakeReader:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def get(self, endpoint):
        self.calls.append(("get", endpoint))
        return self.values.get(endpoint, {})

    def list(self, endpoint):
        self.calls.append(("list", endpoint))
        return self.values.get(endpoint, [])

    def graphql(self, query):
        self.calls.append(("graphql", query))
        return {"repository": {"issue": {"closedByPullRequestsReferences": {"nodes": []}}}}


def reader_for(
    *,
    head=H1,
    pr_row=None,
    reviews=None,
    adjudications=None,
    inline_findings=None,
    top_findings=None,
    checks=None,
    issue_extra=None,
):
    pr_row = pr_row or pr(head)
    reviews = [review(1, head), review(2, head)] if reviews is None else reviews
    inline_findings = [finding(1, 301, head, native=head)] if inline_findings is None else inline_findings
    top_findings = [finding(2, 302, head)] if top_findings is None else top_findings
    adjudications = [decision(head)] if adjudications is None else adjudications
    checks = [{"name": "tests", "status": "completed", "conclusion": "success"}] if checks is None else checks
    issue = {"number": 50, "state": "open"}
    issue.update(issue_extra or {})
    values = {
        "repos/owner/repo/issues/50": issue,
        "repos/owner/repo/issues/50/dependencies/blocked_by": [],
        "repos/owner/repo/issues/50/timeline": [cross_ref()],
        "repos/owner/repo/pulls/61": pr_row,
        "repos/owner/repo/pulls/61/reviews": reviews,
        "repos/owner/repo/issues/61/comments": [*top_findings, *adjudications],
        "repos/owner/repo/pulls/61/comments": inline_findings,
        f"repos/owner/repo/commits/{head}/check-runs?filter=latest": {"check_runs": checks},
        f"repos/owner/repo/commits/{head}/status": {"statuses": []},
    }
    return FakeReader(values)


class FakeMerger:
    def __init__(self):
        self.calls = []

    def merge(self, repo, pr_number, head):
        self.calls.append((repo, pr_number, head))
        return {"merged": True, "sha": "f" * 40}


class MergePredicateTests(unittest.TestCase):
    def test_fully_eligible_exact_head_requests_automatic_merge(self):
        merger = FakeMerger()
        result = merge.request_exact_head_merge(config(), 50, H1, reader_for(), merger)
        self.assertEqual(result.state, merge.MergeResultState.REQUESTED)
        self.assertIsNone(result.merged_at)
        self.assertEqual(merger.calls, [("owner/repo", 61, H1)])

    def test_local_or_cached_accept_without_github_accept_never_merges(self):
        merger = FakeMerger()
        reader = reader_for(adjudications=[], issue_extra={"accepted": True, "completed": True})
        with self.assertRaises(merge.MergeAuthorityError):
            merge.request_exact_head_merge(config(), 50, H1, reader, merger)
        self.assertEqual(merger.calls, [])

    def test_accept_for_h1_cannot_authorize_current_h2(self):
        merger = FakeMerger()
        reader = reader_for(head=H2, adjudications=[decision(H1)])
        with self.assertRaises(merge.MergeAuthorityError):
            merge.request_exact_head_merge(config(), 50, H2, reader, merger)
        self.assertEqual(merger.calls, [])

    def test_missing_reviewer_slot_blocks_merge(self):
        merger = FakeMerger()
        reader = reader_for(reviews=[review(1)])
        with self.assertRaises(merge.MergeAuthorityError):
            merge.request_exact_head_merge(config(), 50, H1, reader, merger)
        self.assertEqual(merger.calls, [])

    def test_native_review_commit_mismatch_fails_closed(self):
        merger = FakeMerger()
        reader = reader_for(reviews=[review(1, native=H2), review(2)])
        with self.assertRaises(merge.MergeAuthorityError):
            merge.request_exact_head_merge(config(), 50, H1, reader, merger)
        self.assertEqual(merger.calls, [])

    def test_malformed_and_duplicate_adjudications_fail_closed(self):
        cases = [
            [malformed_decision()],
            [decision(ident=400), decision(ident=401)],
        ]
        for adjudications in cases:
            with self.subTest(adjudications=len(adjudications)):
                merger = FakeMerger()
                with self.assertRaises(merge.MergeAuthorityError):
                    merge.request_exact_head_merge(
                        config(), 50, H1, reader_for(adjudications=adjudications), merger
                    )
                self.assertEqual(merger.calls, [])

    def test_accept_must_disposition_the_exact_head_finding_ledger(self):
        merger = FakeMerger()
        reader = reader_for(adjudications=[decision(finding_ids=())])
        with self.assertRaisesRegex(merge.MergeAuthorityError, "dispositions mismatch"):
            merge.request_exact_head_merge(config(), 50, H1, reader, merger)
        self.assertEqual(merger.calls, [])

    def test_native_finding_commit_mismatch_fails_closed(self):
        merger = FakeMerger()
        reader = reader_for(inline_findings=[finding(1, 301, native=H2)])
        with self.assertRaisesRegex(merge.MergeAuthorityError, "finding commit_id"):
            merge.request_exact_head_merge(config(), 50, H1, reader, merger)
        self.assertEqual(merger.calls, [])

    def test_required_ci_zero_pending_and_failing_checks_never_merge(self):
        cases = [
            [],
            [{"name": "tests", "status": "in_progress", "conclusion": None}],
            [{"name": "tests", "status": "completed", "conclusion": "failure"}],
        ]
        for checks in cases:
            with self.subTest(checks=checks):
                merger = FakeMerger()
                with self.assertRaises(merge.MergeAuthorityError):
                    merge.request_exact_head_merge(config(), 50, H1, reader_for(checks=checks), merger)
                self.assertEqual(merger.calls, [])

    def test_ci_none_intentionally_allows_zero_checks(self):
        merger = FakeMerger()
        result = merge.request_exact_head_merge(
            config(ci_required=False), 50, H1, reader_for(checks=[]), merger
        )
        self.assertEqual(result.state, merge.MergeResultState.REQUESTED)
        self.assertEqual(merger.calls, [("owner/repo", 61, H1)])

    def test_no_merge_label_and_paused_swarm_block(self):
        cases = [
            (config(), reader_for(pr_row=pr(labels=("hold-merge",)))),
            (config(paused=True), reader_for()),
        ]
        for cfg, reader in cases:
            with self.subTest(paused=cfg.paused):
                merger = FakeMerger()
                with self.assertRaises(merge.MergeAuthorityError):
                    merge.request_exact_head_merge(cfg, 50, H1, reader, merger)
                self.assertEqual(merger.calls, [])

    def test_conflict_and_incompatible_github_merge_state_block(self):
        cases = [
            pr(mergeable=False, merge_state="dirty"),
            pr(mergeable=True, merge_state="blocked"),
            pr(mergeable=True, merge_state="behind"),
        ]
        for pr_row in cases:
            with self.subTest(state=pr_row["mergeable_state"]):
                merger = FakeMerger()
                with self.assertRaises(merge.MergeAuthorityError):
                    merge.request_exact_head_merge(config(), 50, H1, reader_for(pr_row=pr_row), merger)
                self.assertEqual(merger.calls, [])


class RaceAndCompletionTests(unittest.TestCase):
    def test_head_move_between_observation_and_merge_is_exact_sha_rejected(self):
        class RaceMerger:
            def __init__(self): self.calls = []
            def merge(self, repo, pr_number, head):
                self.calls.append((repo, pr_number, head))
                current_head = H2
                if head != current_head:
                    raise merge.MergeRequestError("head SHA does not match")
                return {"merged": True}

        merger = RaceMerger()
        with self.assertRaisesRegex(merge.MergeRequestError, "head SHA"):
            merge.request_exact_head_merge(config(), 50, H1, reader_for(), merger)
        self.assertEqual(merger.calls, [("owner/repo", 61, H1)])

    def test_concrete_merge_client_sends_exact_sha_guard(self):
        calls = []
        def runner(cmd, payload, timeout):
            calls.append((list(cmd), json.loads(payload), timeout))
            return json.dumps({"merged": True, "sha": "f" * 40})

        result = merge.GhMerger(timeout_s=7, runner=runner).merge("owner/repo", 61, H1)
        self.assertTrue(result["merged"])
        cmd, payload, timeout = calls[0]
        self.assertEqual(cmd[2:4], ["--method", "PUT"])
        self.assertIn("repos/owner/repo/pulls/61/merge", cmd)
        self.assertEqual(payload, {"sha": H1})
        self.assertEqual(timeout, 7)

    def test_merge_api_success_without_merged_at_does_not_release_dependency(self):
        result = merge.request_exact_head_merge(config(), 50, H1, reader_for(), FakeMerger())
        self.assertEqual(result.state, merge.MergeResultState.REQUESTED)
        reader = reader_for()
        facts, state = gh._dependency_observation(
            config(), [{"number": 50, "state": "open"}], reader
        )
        self.assertEqual(state, v7.DependencyState.BLOCKED)
        self.assertIsNone(facts[0].merged_at)

    def test_crash_immediately_before_merge_is_safe_to_retry(self):
        class BeforeCrash:
            def merge(self, repo, pr_number, head):
                raise RuntimeError("crash before request")

        reader = reader_for()
        with self.assertRaisesRegex(RuntimeError, "before request"):
            merge.request_exact_head_merge(config(), 50, H1, reader, BeforeCrash())
        retry = FakeMerger()
        result = merge.request_exact_head_merge(config(), 50, H1, reader, retry)
        self.assertEqual(result.state, merge.MergeResultState.REQUESTED)
        self.assertEqual(retry.calls, [("owner/repo", 61, H1)])

    def test_crash_after_success_converges_from_fresh_merged_at_without_second_merge(self):
        reader = reader_for()
        class AfterCrash:
            def __init__(self): self.calls = 0
            def merge(self, repo, pr_number, head):
                self.calls += 1
                row = reader.values["repos/owner/repo/pulls/61"]
                row["state"] = "closed"
                row["merged_at"] = "2026-09-04T13:30:00Z"
                raise RuntimeError("crash after successful request")

        first = AfterCrash()
        with self.assertRaisesRegex(RuntimeError, "after successful"):
            merge.request_exact_head_merge(config(), 50, H1, reader, first)
        reader.values["repos/owner/repo/issues/50"]["state"] = "closed"
        second = FakeMerger()
        result = merge.request_exact_head_merge(config(), 50, H1, reader, second)
        self.assertEqual(first.calls, 1)
        self.assertEqual(second.calls, [])
        self.assertEqual(result.state, merge.MergeResultState.GITHUB_CONFIRMED)
        self.assertEqual(result.merged_at, "2026-09-04T13:30:00Z")

    def test_fresh_merged_at_is_the_only_dependency_release_fact(self):
        merged_at = "2026-09-04T13:31:00Z"
        reader = reader_for(pr_row=pr(state="closed", merged_at=merged_at), issue_extra={"state": "closed"})
        result = merge.request_exact_head_merge(config(), 50, H1, reader, FakeMerger())
        self.assertEqual(result.state, merge.MergeResultState.GITHUB_CONFIRMED)
        facts, state = gh._dependency_observation(
            config(), [{"number": 50, "state": "closed"}], reader
        )
        self.assertEqual(state, v7.DependencyState.READY)
        self.assertEqual(facts[0].merged_at, merged_at)


class QualityGuardTests(unittest.TestCase):
    def test_merge_module_keeps_gate_functions_small_and_has_no_settle_timer(self):
        import ast
        path = SCRIPTS / "swarm_v7_merge.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        spans = {
            node.name: node.end_lineno - node.lineno + 1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno
        }
        self.assertLessEqual(max(spans.values()), 50, spans)
        self.assertNotIn("settle", source.lower())
        self.assertNotIn("sleep(", source)


if __name__ == "__main__":
    unittest.main()

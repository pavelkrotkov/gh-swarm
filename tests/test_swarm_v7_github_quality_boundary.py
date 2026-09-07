import base64, importlib, json, sys, unittest
from pathlib import Path
ROOT = Path(__file__).parents[1]; SCRIPTS = ROOT / "skills" / "github-project-swarm" / "scripts"; TOOLS = ROOT / "tools"
for path in (SCRIPTS, TOOLS):
    if str(path) not in sys.path: sys.path.insert(0, str(path))
import swarm_v7_quality as quality
v7 = importlib.import_module("swarm_v7"); gh = importlib.import_module("swarm_v7_github"); H2 = "2" * 40
OWNED_MODULE_NAMES = ("swarm_v7_github.py",)
RETIRED_EVIDENCE_MODULES = ("swarm_v7_github_transport.py", "swarm_v7_github_types.py", "swarm_v7_github_decision.py", "swarm_v7_github_markers.py", "swarm_v7_github_publication_types.py", "swarm_v7_github_evidence.py", "swarm_v7_github_ci.py", "swarm_v7_github_support.py")
def config(): return v7.ManifestV7(swarm_id="test", repo="owner/repo", default_branch="main", issues=(45, 46), worker_model="worker", reviewer_models=("reviewer-a", "reviewer-b"), adjudicator_model="adjudicator")
class SwarmV7GitHubQualityTests(unittest.TestCase):
    def test_owned_boundary_is_active_and_within_staged_size_guardrail(self):
        self.assertTrue(set(OWNED_MODULE_NAMES) <= set(quality.ACTIVE_MODULE_NAMES)); text=(quality.SCRIPTS/"swarm_v7_github.py").read_text(encoding="utf-8"); self.assertLessEqual(quality.code_loc(text),200)
    def test_retired_evidence_fragments_stay_deleted(self):
        for name in RETIRED_EVIDENCE_MODULES: self.assertFalse((quality.SCRIPTS / name).exists(), name)
    def test_incomplete_check_run_keeps_legacy_pending_precedence(self): self.assertEqual(gh.ci_state(config(), ([{"status":"in_progress","conclusion":None}], [{"state":"failure"}])), v7.CiState.PENDING)
    def test_multiple_open_linked_prs_fail_closed(self):
        with self.assertRaises(gh.UnsafeGitHubObservation): gh._select_pr([{"state":"open","number":1},{"state":"OPEN","number":2}])
    def test_falsy_label_representations_are_normalized_not_dropped(self): self.assertEqual(gh._labels([{"name":""}, 0, False]), {"", "0", "false"})
    def test_duplicate_current_head_adjudication_markers_in_one_comment_fail_closed(self):
        payload = base64.urlsafe_b64encode(json.dumps({"head_sha":H2,"decision":"accept"}, separators=(",", ":")).encode()).decode(); marker = gh.adjudication_marker("test", 46, H2); row = {"id":10,"body":f"{marker}\n{marker}\n<!-- hermes-swarm-decision-b64:{payload} -->"}
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.adjudication_publication(config(), 46, H2, [row])
if __name__ == "__main__": unittest.main()

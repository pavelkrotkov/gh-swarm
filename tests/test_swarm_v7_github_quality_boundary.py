import base64,importlib,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; SCRIPTS=ROOT/"skills/github-project-swarm/scripts"; TOOLS=ROOT/"tools"
for path in (SCRIPTS,TOOLS):
    if str(path) not in sys.path: sys.path.insert(0,str(path))
import swarm_v7_quality as quality
v7=importlib.import_module("swarm_v7"); gh=importlib.import_module("swarm_v7_github"); H2="2"*40
OWNED=("swarm_v7_github.py","swarm_v7_github_pr.py","swarm_v7_github_links.py","swarm_v7_github_pr_links.py","swarm_v7_github_scalars.py","swarm_v7_github_transport.py","swarm_v7_github_publication.py","swarm_v7_github_review.py","swarm_v7_github_adjudication.py","swarm_v7_github_ci.py")
def config(): return v7.ManifestV7("test","owner/repo","main",(45,46),"worker",("reviewer-a","reviewer-b"),"adjudicator")
class SwarmV7GitHubQualityTests(unittest.TestCase):
    def test_github_boundaries_are_active_and_small(self):
        self.assertTrue(set(OWNED)<=set(quality.ACTIVE_MODULE_NAMES))
        for name in OWNED: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text()),70)
    def test_incomplete_check_run_keeps_pending_precedence(self): self.assertEqual(gh.ci_state(config(),([{"status":"in_progress","conclusion":None}],[{"state":"failure"}])),v7.CiState.PENDING)
    def test_multiple_open_linked_prs_fail_closed(self):
        with self.assertRaises(gh.UnsafeGitHubObservation): gh._select_pr([{"state":"open","number":1},{"state":"OPEN","number":2}])
    def test_falsy_labels_are_normalized(self): self.assertEqual(gh._labels([{"name":""},0,False]),{"","0","false"})
    def test_duplicate_current_head_adjudication_markers_fail_closed(self):
        payload=base64.urlsafe_b64encode(json.dumps({"head_sha":H2,"decision":"accept"},separators=(",",":")).encode()).decode(); marker=gh.adjudication_marker("test",46,H2); row={"id":10,"body":f"{marker}\n{marker}\n<!-- hermes-swarm-decision-b64:{payload} -->"}
        with self.assertRaises(gh.UnsafeGitHubObservation): gh.adjudication_publication(config(),46,H2,[row])
if __name__=="__main__": unittest.main()

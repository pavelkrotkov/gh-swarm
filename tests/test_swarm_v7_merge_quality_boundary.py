import sys, unittest
from pathlib import Path
ROOT = Path(__file__).parents[1]; SCRIPTS = ROOT / "skills" / "github-project-swarm" / "scripts"; TOOLS = ROOT / "tools"
for path in (SCRIPTS, TOOLS):
    if str(path) not in sys.path: sys.path.insert(0, str(path))
import swarm_v7_quality as quality
OWNED_MODULE_NAMES = ("swarm_v7_merge.py",)
class SwarmV7MergeQualityTests(unittest.TestCase):
    def test_merge_slice_is_consolidated(self): self.assertEqual({path.name for path in SCRIPTS.glob("swarm_v7_merge*.py")}, set(OWNED_MODULE_NAMES))
    def test_owned_boundary_is_active_and_small(self):
        self.assertTrue(set(OWNED_MODULE_NAMES) <= set(quality.ACTIVE_MODULE_NAMES)); self.assertLessEqual(quality.code_loc((quality.SCRIPTS/"swarm_v7_merge.py").read_text(encoding="utf-8")),100)
if __name__ == "__main__": unittest.main()

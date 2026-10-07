import sys, unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; SCRIPTS=ROOT/"skills"/"github-project-swarm"/"scripts"; TOOLS=ROOT/"tools"
for path in (SCRIPTS,TOOLS):
    if str(path) not in sys.path: sys.path.insert(0,str(path))
import swarm_v7_quality as quality
OWNED_MODULE_NAMES=("swarm_v7_merge.py","swarm_v7_merge_transport.py","swarm_v7_merge_ledger.py","swarm_v7_merge_findings.py")
class SwarmV7MergeQualityTests(unittest.TestCase):
    def test_merge_boundaries_are_active_and_small(self):
        self.assertEqual({path.name for path in SCRIPTS.glob("swarm_v7_merge*.py")},set(OWNED_MODULE_NAMES))
        self.assertTrue(set(OWNED_MODULE_NAMES)<=set(quality.ACTIVE_MODULE_NAMES))
        for name in OWNED_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text(encoding="utf-8")),70)
if __name__=="__main__": unittest.main()

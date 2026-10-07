import sys,unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import swarm_v7_quality as quality
class SwarmV7OwnedQualityTests(unittest.TestCase):
    def test_planner_boundaries_are_active_and_small(self):
        self.assertTrue(set(quality.PLANNER_MODULE_NAMES)<=set(quality.ACTIVE_MODULE_NAMES))
        for name in quality.PLANNER_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text()),70)
    def test_planner_core_path_keeps_six_target(self): self.assertEqual(quality.core_role(Path("swarm_v7.py"),"plan_issue"),"planner")
if __name__=="__main__": unittest.main()

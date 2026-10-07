import sys, unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import swarm_v7_quality as quality
OWNED_MODULE_NAMES=("swarm_v7_controller.py","swarm_v7_controller_runtime.py","swarm_v7_controller_execution.py","swarm_v7_execution.py")
class SwarmV7ExecutionQualityTests(unittest.TestCase):
    def test_execution_boundaries_are_active_and_small(self):
        self.assertTrue(set(OWNED_MODULE_NAMES)<=set(quality.ACTIVE_MODULE_NAMES))
        for name in OWNED_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text(encoding="utf-8")),80)
if __name__=="__main__": unittest.main()

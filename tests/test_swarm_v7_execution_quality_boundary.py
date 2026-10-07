import sys,unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import swarm_v7_quality as quality
OWNED=("swarm_v7_controller_execution.py","swarm_v7_controller_review_actions.py","swarm_v7_controller_worker.py","swarm_v7_review.py","swarm_v7_review_spec.py","swarm_v7_execution.py")
class SwarmV7ExecutionQualityTests(unittest.TestCase):
    def test_execution_boundaries_are_active_and_small(self):
        self.assertTrue(set(OWNED)<=set(quality.ACTIVE_MODULE_NAMES))
        for name in OWNED: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text()),70)
if __name__=="__main__": unittest.main()

import sys, unittest
from pathlib import Path
ROOT = Path(__file__).parents[1]; TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path: sys.path.insert(0, str(TOOLS))
import swarm_v7_quality as quality
OWNED_MODULE_NAMES = ("swarm_v7_controller.py", "swarm_v7_review.py", "swarm_v7_kanban.py")
RETIRED_MODULES = ("swarm_v7_execution.py", "swarm_v7_controller_execution.py", "swarm_v7_review_execution.py", "swarm_v7_review_tasks.py", "swarm_v7_review_ledger.py", "swarm_v7_review_slots.py", "swarm_v7_review_types.py", "swarm_v7_review_validation.py")
class SwarmV7ExecutionQualityTests(unittest.TestCase):
    def test_owned_boundary_is_active_and_consolidated(self):
        self.assertTrue(set(OWNED_MODULE_NAMES) <= set(quality.ACTIVE_MODULE_NAMES))
        for name in OWNED_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text(encoding="utf-8")),100)
    def test_retired_fragmentation_stays_deleted(self):
        for name in RETIRED_MODULES: self.assertFalse((quality.SCRIPTS / name).exists(), name)
if __name__ == "__main__": unittest.main()

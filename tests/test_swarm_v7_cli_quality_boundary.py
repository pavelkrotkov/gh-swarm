import sys, unittest
from pathlib import Path
ROOT = Path(__file__).parents[1]; TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path: sys.path.insert(0, str(TOOLS))
import swarm_v7_quality as quality
class SwarmV7CliQualityTests(unittest.TestCase):
    def test_owned_boundary_is_active_and_consolidated(self):
        self.assertTrue(set(quality.CLI_MODULE_NAMES) <= set(quality.ACTIVE_MODULE_NAMES)); self.assertTrue(set(quality.CLI_CONTROLLER_MODULE_NAMES) <= set(quality.CORE_CONTROLLER_MODULE_NAMES))
        for name in quality.CLI_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text(encoding="utf-8")),70)
if __name__ == "__main__": unittest.main()

import sys,unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import swarm_v7_quality as quality
class SwarmV7CliQualityTests(unittest.TestCase):
    def test_cli_boundaries_are_active_and_small(self):
        self.assertTrue(set(quality.CLI_MODULE_NAMES)<=set(quality.ACTIVE_MODULE_NAMES))
        for name in quality.CLI_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text()),70)
if __name__=="__main__": unittest.main()

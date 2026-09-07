import sys, unittest
from pathlib import Path
ROOT = Path(__file__).parents[1]; TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path: sys.path.insert(0, str(TOOLS))
import swarm_v7_quality as quality
OWNED_MODULE_NAMES = ("swarm_v7_cli_process.py", "swarm_v7_kanban.py", "swarm_v7_workspace.py")
RETIRED_MODULES = ("swarm_v7_execution.py", "swarm_v7_workspace_git.py", "swarm_v7_workspace_branch.py", "swarm_v7_workspace_handoff.py", "swarm_v7_workspace_identity.py", "swarm_v7_workspace_inventory.py", "swarm_v7_workspace_process.py", "swarm_v7_workspace_scalars.py", "swarm_v7_workspace_state.py", "swarm_v7_workspace_types.py", "swarm_v7_workspace_worktree.py")
class SwarmV7AdapterQualityTests(unittest.TestCase):
    def test_owned_boundary_is_active_and_small(self):
        self.assertTrue(set(OWNED_MODULE_NAMES) <= set(quality.ACTIVE_MODULE_NAMES))
        for name in OWNED_MODULE_NAMES: self.assertLessEqual(quality.code_loc((quality.SCRIPTS/name).read_text(encoding="utf-8")),100)
    def test_retired_adapter_fragmentation_stays_deleted(self):
        for name in RETIRED_MODULES: self.assertFalse((quality.SCRIPTS / name).exists(), name)
if __name__ == "__main__": unittest.main()

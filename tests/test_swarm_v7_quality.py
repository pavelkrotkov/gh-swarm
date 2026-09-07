import sys, unittest
from pathlib import Path
ROOT=Path(__file__).parents[1]; TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import swarm_v7_quality as quality
class SwarmV7QualityTests(unittest.TestCase):
    def fixture(self,cli="value = 1\n",**extra): return {quality.PLUGIN_REL:"value = 1\n",quality.CLI_REL:cli,**extra}
    def test_scope_includes_plugin_and_dynamic_cli(self): self.assertEqual(quality.derive_runtime_scope(self.fixture()),(quality.PLUGIN_REL,quality.CLI_REL))
    def test_reachable_local_module_changes_count_and_loc(self):
        base=self.fixture(); extended=self.fixture(cli="import helper\nvalue=1\n",**{"scripts/helper.py":"first=1\nsecond=2\n"}); a=quality.runtime_metrics(base); b=quality.runtime_metrics(extended); self.assertEqual(b[1],a[1]+1); self.assertEqual(b[0],a[0]+3)
    def test_unreachable_files_are_not_counted(self):
        sources=self.fixture(**{"scripts/unreachable.py":"raise RuntimeError\n","tests/test_runtime.py":"raise RuntimeError\n","tools/helper.py":"raise RuntimeError\n"}); self.assertEqual(quality.derive_runtime_scope(sources),(quality.PLUGIN_REL,quality.CLI_REL))
    def test_unresolved_local_import_and_missing_dynamic_edge_fail_closed(self):
        with self.assertRaisesRegex(quality.RuntimeScopeError,"unresolved required local import"): quality.derive_runtime_scope(self.fixture(cli="import swarm_v7_missing\n"))
        with self.assertRaisesRegex(quality.RuntimeScopeError,"dynamic runtime edge is unresolved"): quality.derive_runtime_scope({quality.PLUGIN_REL:"value=1\n"})
    def test_runtime_meets_absolute_size_profile(self):
        loc,modules=quality.runtime_metrics(quality.working_runtime_sources()); self.assertLessEqual(loc,quality.FINAL_RUNTIME_LOC); self.assertLessEqual(modules,quality.MAX_WHOLE_RUNTIME_MODULES)
    def test_absolute_complexity_and_core_target(self):
        branches="".join(f"    if x == {i}:\n        return {i}\n" for i in range(8)); source=f"def inherited(x):\n{branches}    return -1\n"; failures,_=quality.complexity_failures(Path("swarm_v7_github.py"),source); self.assertTrue(any("cyclomatic=9 > 8" in row for row in failures))
        branches="".join(f"    if x == {i}:\n        return {i}\n" for i in range(6)); source=f"def plan_issue(x):\n{branches}    return -1\n"; failures,_=quality.complexity_failures(Path("swarm_v7.py"),source); self.assertTrue(any("cyclomatic=7 > 6" in row and "core=planner" in row for row in failures))
    def test_direct_module_cognitive_nesting_and_function_loc_are_absolute(self):
        nested="def deep(x):\n    if x:\n        if x:\n            if x:\n                if x:\n                    if x:\n                        return 1\n    return 0\n"; metric=quality.function_metrics(nested)[0]; failures=quality.qualification_metric_failures(Path("x.py"),quality.COHESION_REVIEW_LOC+1,[metric]); self.assertTrue(any("cohesion_limit" in row for row in failures)); self.assertTrue(any("nesting=5" in row for row in failures))
    def test_public_quality_policy_has_no_private_history_dependency(self):
        text=(ROOT/"tools/swarm_v7_quality.py").read_text(); self.assertNotIn("PRE_V7_BASE_SHA",text); self.assertNotIn("WHOLE_RUNTIME_BASE_SHA",text); self.assertEqual(quality.make_parser().parse_args([]).mode,quality.QUALIFICATION)
    def test_canonical_ci_runs_absolute_quality_gate(self):
        ci=(ROOT/"tools/ci_validate.py").read_text(); self.assertIn('"tools/swarm_v7_quality.py","--qualification"',ci)
if __name__=="__main__": unittest.main()

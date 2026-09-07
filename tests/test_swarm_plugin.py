import argparse
import importlib.util
import os, sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
PLUGIN = ROOT / "skills" / "github-project-swarm" / "hermes-plugin" / "__init__.py"
SPEC = importlib.util.spec_from_file_location("swarm_hermes_plugin", PLUGIN)
assert SPEC and SPEC.loader
plugin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(plugin)

COMMANDS = {
    "init", "status", "reconcile", "pause", "resume", "doctor", "validate",
    "explain", "prepare", "activate", "disable",
}


def make_runtime(root: Path, body: str = "print('ok')\n") -> Path:
    skill = root / "github-project-swarm"
    (skill / "scripts").mkdir(parents=True)
    (root / ".skillfleet-meta").mkdir(parents=True)
    (root / ".skillfleet-meta" / "github-project-swarm.json").write_text(
        '{"kind":"first-party"}\n', encoding="utf-8"
    )
    (skill / "SKILL.md").write_text("---\nname: github-project-swarm\n---\n", encoding="utf-8")
    (skill / "scripts" / "swarm_v7_cli.py").write_text(body, encoding="utf-8")
    return skill


class FakeContext:
    def __init__(self):
        self.registration = None

    def register_cli_command(self, **kwargs):
        self.registration = kwargs


class SwarmHermesPluginTests(unittest.TestCase):
    def test_registers_only_the_v7_swarm_surface(self):
        ctx = FakeContext()
        plugin.register(ctx)
        self.assertEqual(ctx.registration["name"], "swarm")
        parser = argparse.ArgumentParser(); sys.modules.pop("swarm_v7_cli", None)
        with patch.object(plugin, "_resolve_cli", return_value=ROOT / "skills" / "github-project-swarm" / "scripts" / "swarm_v7_cli.py"), patch.object(sys, "path", [p for p in sys.path if "github-project-swarm/scripts" not in p]): plugin._setup_cli(parser)
        choices = parser._subparsers._group_actions[0].choices
        self.assertEqual(set(choices), COMMANDS)
        parsed = parser.parse_args(["reconcile", "--all", "--dry-run", "--json"])
        self.assertEqual(parsed.swarm_command, "reconcile")
        self.assertTrue(parsed.all)
        self.assertTrue(parsed.dry_run)
        self.assertTrue(parsed.json)

    def test_removed_legacy_commands_and_flags_do_not_parse(self):
        parser = argparse.ArgumentParser()
        with patch.object(plugin, "_resolve_cli", return_value=ROOT / "skills" / "github-project-swarm" / "scripts" / "swarm_v7_cli.py"): plugin._setup_cli(parser)
        with self.assertRaises(SystemExit):
            parser.parse_args(["sync-prompt-profile"])
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "init", "--issues", "1", "--worker", "w", "--reviewer", "r",
                "--max-review-rounds", "3",
            ])

    def test_resolves_cli_only_from_skillfleet_runtime_after_checkout_is_removed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "checkout"
            source.mkdir()
            runtime = base / "runtime" / "current"
            make_runtime(runtime)
            source.rmdir()
            with patch.object(plugin, "_iter_skill_roots", return_value=iter([runtime])):
                resolved = plugin._resolve_cli()
        self.assertEqual(resolved.name, "swarm_v7_cli.py")
        self.assertIn("runtime", str(resolved))
        self.assertNotIn("checkout", str(resolved))

    def test_atomic_current_switch_changes_resolved_cli_without_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td) / "runtime"
            first = runtime / "releases" / "first"
            second = runtime / "releases" / "second"
            make_runtime(first, "print('first')\n")
            make_runtime(second, "print('second')\n")
            current = runtime / "current"
            current.symlink_to(first, target_is_directory=True)
            with patch.object(plugin, "_iter_skill_roots", return_value=iter([current])):
                before = plugin._resolve_cli()
            current_new = runtime / ".current.new"
            current_new.symlink_to(second, target_is_directory=True)
            os.replace(current_new, current)
            with patch.object(plugin, "_iter_skill_roots", return_value=iter([current])):
                after = plugin._resolve_cli()
        self.assertIn("first", str(before))
        self.assertIn("second", str(after))
        self.assertNotEqual(before, after)

    def test_unmanaged_local_shadow_cannot_override_skillfleet_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            shadow_root = base / "hermes-skills"
            shadow = shadow_root / "github-project-swarm"
            (shadow / "scripts").mkdir(parents=True)
            (shadow / "SKILL.md").write_text("shadow\n", encoding="utf-8")
            (shadow / "scripts" / "swarm_v7_cli.py").write_text("print('shadow')\n", encoding="utf-8")
            runtime = base / "skillfleet-runtime" / "current"
            make_runtime(runtime)
            with patch.object(plugin, "_iter_skill_roots", return_value=iter([shadow_root, runtime])):
                resolved = plugin._resolve_cli()
        self.assertIn("skillfleet-runtime", str(resolved))
        self.assertNotIn("hermes-skills", str(resolved))

    def test_multiple_distinct_skillfleet_runtimes_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            first = base / "runtime-one" / "current"
            second = base / "runtime-two" / "current"
            make_runtime(first)
            make_runtime(second)
            with patch.object(plugin, "_iter_skill_roots", return_value=iter([first, second])):
                with self.assertRaisesRegex(RuntimeError, "multiple Skillfleet runtimes"):
                    plugin._resolve_cli()

    def test_local_shadow_without_skillfleet_runtime_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "hermes-skills"
            shadow = root / "github-project-swarm"
            (shadow / "scripts").mkdir(parents=True)
            (shadow / "SKILL.md").write_text("shadow\n", encoding="utf-8")
            (shadow / "scripts" / "swarm_v7_cli.py").write_text("print('shadow')\n", encoding="utf-8")
            with patch.object(plugin, "_iter_skill_roots", return_value=iter([root])):
                with self.assertRaisesRegex(RuntimeError, "active Skillfleet runtime"):
                    plugin._resolve_cli()

    def test_plugin_contains_no_checkout_or_legacy_runtime_contract(self):
        text = PLUGIN.read_text(encoding="utf-8")
        self.assertNotIn("agent-skillfleet/skills/github-project-swarm", text)
        self.assertNotIn("lifecycle.py", text)
        self.assertNotIn("swarm_v6", text)
        self.assertIn("swarm_v7_cli.py", text)
        self.assertIn(".skillfleet-meta", text)


if __name__ == "__main__":
    unittest.main()

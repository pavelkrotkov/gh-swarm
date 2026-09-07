import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
BOOTSTRAP = ROOT / "skills" / "github-project-swarm" / "scripts" / "bootstrap.sh"
MARKER = "managed by agent-skillfleet github-project-swarm bootstrap\n"


class SwarmBootstrapTests(unittest.TestCase):
    def _environment(self, base: Path, *, active: bool = False) -> dict[str, str]:
        home = base / "home"
        hermes_home = home / ".hermes"
        fakebin = base / "bin"
        fakebin.mkdir(parents=True)
        home.mkdir(parents=True)
        systemctl = fakebin / "systemctl"
        systemctl.write_text(
            "#!/bin/sh\n"
            "if [ \"$1 $2\" = '--user show-environment' ]; then exit 0; fi\n"
            "if [ \"$1 $2 $3\" = '--user is-active --quiet' ]; then\n"
            "  [ \"${SWARM_ACTIVE:-0}\" = 1 ] && exit 0 || exit 3\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        systemctl.chmod(0o755)
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hermes.chmod(0o755)
        return os.environ | {
            "HOME": str(home),
            "HERMES_HOME": str(hermes_home),
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "SWARM_ACTIVE": "1" if active else "0",
        }

    def test_active_reconcile_refuses_before_plugin_or_unit_modification(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            env = self._environment(base, active=True)
            home = Path(env["HOME"])
            plugin = Path(env["HERMES_HOME"]) / "plugins" / "github-project-swarm"
            plugin.mkdir(parents=True)
            (plugin / ".agent-skillfleet-managed").write_text(MARKER, encoding="utf-8")
            sentinel = plugin / "__init__.py"
            sentinel.write_text("old plugin\n", encoding="utf-8")
            unit = home / ".config" / "systemd" / "user" / "hermes-swarm-reconcile.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("old unit\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(BOOTSTRAP)], cwd=ROOT, env=env, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("reconciliation is active", result.stderr)
            self.assertEqual("old plugin\n", sentinel.read_text(encoding="utf-8"))
            self.assertEqual("old unit\n", unit.read_text(encoding="utf-8"))

    def test_unmanaged_plugin_is_refused_without_modification(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            env = self._environment(base)
            hermes_home = Path(env["HERMES_HOME"])
            plugin = hermes_home / "plugins" / "github-project-swarm"
            plugin.mkdir(parents=True)
            sentinel = plugin / "manual.py"
            sentinel.write_text("manual plugin content\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(BOOTSTRAP)], cwd=ROOT, env=env, text=True, capture_output=True, check=False
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("unmanaged Hermes swarm plugin", result.stderr)
            self.assertEqual("manual plugin content\n", sentinel.read_text(encoding="utf-8"))
            self.assertFalse((plugin / ".agent-skillfleet-managed").exists())
            self.assertFalse((Path(env["HOME"]) / ".config" / "systemd" / "user").exists())

    def test_unmanaged_legacy_shadow_is_preserved_and_ignored_by_migration(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            env = self._environment(base)
            shadow = Path(env["HERMES_HOME"]) / "skills" / "github-project-swarm"
            shadow.mkdir(parents=True)
            sentinel = shadow / "keep-me.txt"
            sentinel.write_text("manual\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(BOOTSTRAP)], cwd=ROOT, env=env, text=True, capture_output=True, check=False
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("manual\n", sentinel.read_text(encoding="utf-8"))
            self.assertIn("preserving unmanaged legacy swarm skill", result.stderr)
            plugin = Path(env["HERMES_HOME"]) / "plugins" / "github-project-swarm"
            self.assertTrue((plugin / "plugin.yaml").is_file())
            self.assertTrue((plugin / "__init__.py").is_file())

    def test_exact_legacy_managed_shadow_is_archived_not_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            env = self._environment(base)
            hermes_home = Path(env["HERMES_HOME"])
            shadow = hermes_home / "skills" / "github-project-swarm"
            shadow.mkdir(parents=True)
            (shadow / ".agent-skillfleet-managed").write_text(MARKER, encoding="utf-8")
            (shadow / "old-controller.txt").write_text("legacy managed copy\n", encoding="utf-8")
            result = subprocess.run(
                ["bash", str(BOOTSTRAP)], cwd=ROOT, env=env, text=True, capture_output=True, check=False
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(shadow.exists())
            archives = list((hermes_home / "legacy-managed-skills").glob("github-project-swarm.*"))
            self.assertEqual(1, len(archives))
            self.assertEqual(
                "legacy managed copy\n", (archives[0] / "old-controller.txt").read_text(encoding="utf-8")
            )

    def test_bootstrap_is_inert_and_gateway_independent(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        for forbidden in (
            "hermes swarm reconcile",
            "hermes-gateway.service",
            "kanban",
            "git branch",
            "git worktree",
        ):
            self.assertNotIn(forbidden, text)
        result = subprocess.run(["bash", "-n", str(BOOTSTRAP)], text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()

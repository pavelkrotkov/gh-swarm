import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "github-project-swarm" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
workspace = importlib.import_module("swarm_v7_workspace")


class HostQualificationTests(unittest.TestCase):
    def test_swarm_state_can_be_isolated_without_relocating_hermes_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            env["HERMES_SWARM_STATE_DIR"] = td
            code = (
                "import sys; "
                f"sys.path.insert(0, {str(SCRIPTS)!r}); "
                "import swarm_v7_cli; print(swarm_v7_cli.STATE)"
            )
            proc = subprocess.run([sys.executable, "-c", code], env=env, text=True, capture_output=True, check=True)
        self.assertEqual(proc.stdout.strip(), td)

    def test_prepared_identity_recovers_empty_cursor_and_durable_branch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bare, seed, clone = root / "origin.git", root / "seed", root / "work"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            for key, value in (("user.name", "test"), ("user.email", "test@example.invalid")):
                subprocess.run(["git", "-C", str(seed), "config", key, value], check=True)
            (seed / "README").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(seed), "add", "README"], check=True)
            subprocess.run(["git", "-C", str(seed), "commit", "-m", "fixture"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(seed), "remote", "add", "origin", str(bare)], check=True)
            subprocess.run(["git", "-C", str(seed), "push", "-u", "origin", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
            subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
            adapter = workspace.GitWorkspace(clone)
            branch = workspace.branch_name("demo", 1)
            worktree = workspace.worktree_path(clone, "demo", 1)
            spec = workspace.WorkspaceSpec(str(bare.resolve()), "main", branch, worktree)
            adapter.prepare(spec, started=False)
            for key, value in (("user.name", "test"), ("user.email", "test@example.invalid")):
                subprocess.run(["git", "-C", str(worktree), "config", key, value], check=True)
            (worktree / "durable").write_text("durable\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(worktree), "add", "durable"], check=True)
            subprocess.run(["git", "-C", str(worktree), "commit", "-m", "durable"], check=True, capture_output=True)
            head = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
            ).stdout.strip()
            subprocess.run(["git", "-C", str(worktree), "push", "origin", f"HEAD:refs/heads/{branch}"], check=True)
            subprocess.run(["git", "-C", str(clone), "worktree", "remove", "--force", str(worktree)], check=True)
            subprocess.run(["git", "-C", str(clone), "branch", "-D", branch], check=True, capture_output=True)
            adapter.prepare(spec, started=False)
            recovered = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"], text=True, capture_output=True, check=True
            ).stdout.strip()
            self.assertEqual(head, recovered)
            self.assertTrue(worktree.is_dir())

    def test_host_runner_keeps_fakes_at_github_boundary(self):
        runner = (ROOT / "tools" / "qualify_swarm_v7_host.py").read_text(encoding="utf-8")
        fake = (ROOT / "tools" / "swarm_v7_fake_gh.py").read_text(encoding="utf-8")
        self.assertNotIn("import swarm_v7", runner)
        self.assertNotIn("unittest.mock", runner)
        self.assertIn('["hermes", "swarm"', runner)
        self.assertIn('["git", "init", "--bare"', runner)
        self.assertIn('"--max-retries", "1"', runner)
        self.assertIn('"--assignee", assignee', runner)
        self.assertIn("dispatcher did not create a worker run", runner)
        self.assertIn('"comment_dispositions": [], "required_changes": []', runner)
        self.assertIn("durable adjudication did not converge to merge", runner)
        self.assertIn('proc.returncode == 0 and elapsed < 2.5 and "EXECUTION_STALLED action=none" in proc.stdout', runner)
        self.assertIn("SKILLFLEET_FAKE_GH_STATE", fake)
        self.assertNotIn("hermes kanban", fake)
        self.assertNotIn("swarm_v7", fake)

    def test_fake_github_pr_issue_comments_accept_filesystem_repo(self):
        with tempfile.TemporaryDirectory() as td:
            repo = str((Path(td) / "origin.git").resolve()); state = Path(td) / "fake.json"
            state.write_text(json.dumps({"repo": repo, "prs": {"101": {"comments": [{"id": 7}]}}}), encoding="utf-8")
            env = os.environ.copy(); env["SKILLFLEET_FAKE_GH_STATE"] = str(state)
            endpoint = f"repos/{repo}/issues/101/comments?per_page=100&page=1"
            proc = subprocess.run([sys.executable, str(ROOT / "tools" / "swarm_v7_fake_gh.py"), "api", "--method", "GET", endpoint], env=env, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(proc.stdout), [{"id": 7}])

    def test_host_commands_are_documented_and_not_part_of_fast_test_target(self):
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        docs = (ROOT / "docs" / "swarm-v7-host-qualification.md").read_text(encoding="utf-8")
        self.assertIn("qualify-swarm-host:", makefile); self.assertIn("qualify-swarm-dispatcher:", makefile)
        self.assertIn("tools/qualify_swarm_v7_host.py", makefile)
        self.assertIn("make qualify-swarm-host", docs); self.assertIn("make qualify-swarm-dispatcher", docs)
        test_body = makefile.split("test:", 1)[1].split("\n\n", 1)[0]
        self.assertNotIn("qualify_swarm_v7_host.py", test_body)


if __name__ == "__main__":
    unittest.main()

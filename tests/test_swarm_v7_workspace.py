import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "github-project-swarm" / "scripts"
sys.path.insert(0, str(SCRIPTS))
ws = importlib.import_module("swarm_v7_workspace")
kb = importlib.import_module("swarm_v7_kanban")


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v7-workspace-")
        self.root = Path(self.temp.name); self.origin = self.root / "origin.git"
        self.seed = self.root / "seed"; self.repo = self.root / "repo"
        self._git("init", "--bare", str(self.origin), cwd=self.root)
        self._git("init", "-b", "main", cwd=self.seed, create=True)
        self._git("config", "user.email", "tests@example.invalid", cwd=self.seed)
        self._git("config", "user.name", "Tests", cwd=self.seed)
        (self.seed / "base.txt").write_text("base\n")
        self._git("add", ".", cwd=self.seed); self._git("commit", "-m", "base", cwd=self.seed)
        self._git("remote", "add", "origin", str(self.origin), cwd=self.seed)
        self._git("push", "-u", "origin", "main", cwd=self.seed)
        self._git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.origin)
        self._git("clone", str(self.origin), str(self.repo), cwd=self.root)
        self._git("config", "user.email", "tests@example.invalid", cwd=self.repo)
        self._git("config", "user.name", "Tests", cwd=self.repo)
        self.branch = ws.branch_name("test", 48); self.worktree = ws.worktree_path(self.repo, "test", 48); self.spec = ws.WorkspaceSpec(str(self.origin), "main", self.branch, self.worktree); self.git = ws.GitWorkspace(self.repo)
    def tearDown(self): self.temp.cleanup()
    def _git(self, *args, cwd, create=False):
        if create: Path(cwd).mkdir(parents=True, exist_ok=True)
        return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()
    def advance_main(self, text):
        p = self.seed / "base.txt"; p.write_text(p.read_text() + text + "\n"); self._git("add", ".", cwd=self.seed); self._git("commit", "-m", text, cwd=self.seed); sha = self._git("rev-parse", "HEAD", cwd=self.seed); self._git("push", "origin", "main", cwd=self.seed); return sha
    def remote_branch(self):
        ref = f"refs/heads/{self.branch}"; out = self._git("ls-remote", "--heads", str(self.origin), ref, cwd=self.root); return out.split()[0] if out else None


class DeterministicWorkspaceTests(GitFixture):
    def test_initial_branch_uses_exact_fresh_remote_default_sha(self):
        expected = self.advance_main("fresh"); base = self.git.prepare(self.spec, started=False); self.assertEqual(expected, base); self.assertEqual(expected, self._git("rev-parse", self.branch, cwd=self.repo)); self.assertEqual(expected, self._git("rev-parse", "HEAD", cwd=self.worktree))
    def test_dependent_branch_contains_merged_predecessor_via_fresh_default(self):
        predecessor = self.advance_main("merged predecessor"); base = self.git.prepare(self.spec, started=False); self.assertEqual(predecessor, base); self.assertEqual(0, subprocess.run(["git", "merge-base", "--is-ancestor", predecessor, self.branch], cwd=self.repo).returncode)
    def test_wrong_binding_fails_before_branch_or_worktree_creation(self):
        bad = ws.WorkspaceSpec("owner/not-this-repo", "main", self.branch, self.worktree)
        with self.assertRaisesRegex(ws.WorkspaceError, "does not match configured repo"): self.git.prepare(bad, started=False)
        self.assertNotEqual(0, subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{self.branch}"], cwd=self.repo).returncode); self.assertFalse(self.worktree.exists())
    def test_fresh_identity_reclaims_orphan_local_branch_and_converges(self):
        orphan=self._git("rev-parse","HEAD",cwd=self.repo); self._git("branch",self.branch,cwd=self.repo); expected=self.advance_main("fresh"); base=self.git.prepare(self.spec,started=False)
        self.assertEqual(expected,base); self.assertNotEqual(orphan,self._git("rev-parse",self.branch,cwd=self.repo)); self.assertEqual(expected,self._git("rev-parse","HEAD",cwd=self.worktree)); self.assertEqual(expected,self.git.prepare(self.spec,started=False))
    def test_fresh_identity_preserves_prepared_marker(self):
        base=self.git.prepare(self.spec,started=False); self._git("worktree","remove","--force",str(self.worktree),cwd=self.repo); self.assertFalse(self.worktree.exists()); self.assertEqual(base,self.git.prepare(self.spec,started=False)); self.assertTrue(self.worktree.exists())
    def test_fresh_identity_fails_closed_on_pr_remote_and_active_worktree(self):
        with self.subTest("PR"):
            with self.assertRaises(ws.WorkspaceCollision): self.git.prepare(self.spec,started=False,pr_exists=True)
        self._git("branch",self.branch,cwd=self.repo); self._git("push","origin",f"{self.branch}:refs/heads/{self.branch}",cwd=self.repo)
        with self.subTest("remote"):
            with self.assertRaises(ws.WorkspaceCollision): self.git.prepare(self.spec,started=False)
        self._git("push","origin","--delete",self.branch,cwd=self.repo); self._git("branch","-D",self.branch,cwd=self.repo); active=self.root/"active"; self._git("worktree","add","-b",self.branch,str(active),"main",cwd=self.repo)
        with self.subTest("active worktree"):
            with self.assertRaises(ws.WorkspaceError): self.git.prepare(self.spec,started=False)
        self.assertEqual(self.branch,self._git("branch","--show-current",cwd=active)); self.assertEqual(self._git("rev-parse","main",cwd=self.repo),self._git("rev-parse",self.branch,cwd=self.repo))
    def test_crash_after_commit_before_push_preserves_local_candidate_for_retry(self):
        base = self.git.prepare(self.spec, started=False); (self.worktree / "change.txt").write_text("candidate\n"); self._git("add", ".", cwd=self.worktree); self._git("commit", "-m", "candidate", cwd=self.worktree); candidate = self._git("rev-parse", "HEAD", cwd=self.worktree)
        self.assertIsNone(self.remote_branch()); self.assertEqual(base, self.git.prepare(self.spec, started=True)); self.assertEqual(candidate, self._git("rev-parse", self.branch, cwd=self.repo)); self.assertIsNone(self.remote_branch())
    def test_missing_worktree_reconstructs_from_durable_remote_branch(self):
        self.git.prepare(self.spec, started=False); (self.worktree / "change.txt").write_text("durable\n"); self._git("add", ".", cwd=self.worktree); self._git("commit", "-m", "durable", cwd=self.worktree); durable = self._git("rev-parse", "HEAD", cwd=self.worktree); self._git("push", "-u", "origin", self.branch, cwd=self.worktree); self._git("worktree", "remove", "--force", str(self.worktree), cwd=self.repo); self._git("branch", "-D", self.branch, cwd=self.repo); self.git.prepare(self.spec, started=True)
        self.assertTrue(self.worktree.exists()); self.assertEqual(durable, self._git("rev-parse", "HEAD", cwd=self.worktree))
    def test_recovery_refuses_wrong_existing_worktree(self):
        self.git.prepare(self.spec, started=False); self._git("switch", "-c", "wrong", cwd=self.worktree)
        with self.assertRaisesRegex(ws.WorkspaceError, "not the expected"): self.git.prepare(self.spec, started=True)


class WorkerContractTests(unittest.TestCase):
    def test_worker_owns_commit_push_pr_and_exact_head_verification(self):
        body = kb.worker_body("owner/repo", 48, "swarm/test/48", "main", "1" * 40, "Implement the issue")
        for phrase in ("Commit every intended change", "git status --porcelain", "git push -u origin HEAD:refs/heads/swarm/test/48", "Exactly one may exist", "non-draft", "full head SHA equals PUSHED_SHA exactly", "limited to added/modified lines", "filter machine-readable findings to changed lines", "preserving file-level findings", "PEP 723", "Do not merge"): self.assertIn(phrase, body)
    def test_v7_controller_boundaries_do_not_build_normal_push_or_pr_create_commands(self):
        for candidate in SCRIPTS.glob("swarm_v7*.py"):
            text = candidate.read_text(); self.assertNotIn('["git", "push"', text); self.assertNotIn('["gh", "pr", "create"', text)
    def test_git_worktree_adapter_stays_within_guardrail(self):
        path = SCRIPTS / "swarm_v7_workspace.py"; lines = [line for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]; self.assertLessEqual(len(lines), 180)


if __name__ == "__main__": unittest.main()

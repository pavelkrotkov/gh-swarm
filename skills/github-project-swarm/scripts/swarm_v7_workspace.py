# Deterministic worktree policy built only from durable Git facts.
# One swarm issue owns one branch/worktree; prepared markers distinguish recovery from collision.
# Workers remain the only owners of commit, push, and PR publication.
# A fresh identity rejects remote/worktree collisions unless a durable prepared marker proves recovery.
# Local-only orphan branches may be reclaimed only before any task/PR durable evidence exists.
# Diverged local/remote branches fail closed; fast-forwardable remote authority is never rewritten.
# Prepared markers are keyed by repository, branch and resolved worktree path to prevent cross-swarm reuse.
# Git worktree prune/add is used only after branch ownership has been established.
from collections import namedtuple
import hashlib, re
from pathlib import Path
from swarm_v7_git import GitRepository, WorkspaceError
WorkspaceSpec=namedtuple("WorkspaceSpec","repo default_branch branch worktree")
class WorkspaceCollision(WorkspaceError): pass
class GitWorkspace(GitRepository):
    def ensure_branch(self,branch,base,local,remote,started):
        if not local: self.out(["branch",branch,remote if remote else base]); return  # Git creation closes races after the snapshot.
        if not remote or self.ancestor(remote,local): return
        if self.ancestor(local,remote): raise WorkspaceError("local branch is behind durable remote branch; reconstruct from remote")
        raise WorkspaceError("local and remote swarm branch have diverged")
    def ensure_worktree(self,branch,path):
        if path.exists():
            if self.out(["symbolic-ref","--quiet","--short","HEAD"],cwd=path,check=False)==branch and self.common_dir(path).samefile(self.common_dir()): return
            raise WorkspaceError(f"worktree path is not the expected {branch} checkout")
        self.out(["worktree","prune"]); path.parent.mkdir(parents=True,exist_ok=True); self.out(["worktree","add",str(path),branch])
    def _marker(self,spec): return self.common_dir()/"hermes-swarm"/"prepared"/hashlib.sha256(f"{spec.repo}\0{spec.branch}\0{Path(spec.worktree).resolve()}".encode()).hexdigest()
    def _claim(self,spec,started,pr_exists,collision,orphan):
        if started: return True,any((collision,pr_exists))
        if pr_exists: raise WorkspaceCollision("fresh swarm identity collision: matching PR already exists")
        if not collision: return False,False
        if self._marker(spec).is_file(): return True,True
        if orphan: self.out(["branch","-D",spec.branch]); return False,False  # Git refuses an active worktree branch.
        raise WorkspaceCollision("fresh swarm identity collision")
    def prepare(self,spec,*,started,pr_exists=False):
        if not all((spec.repo,spec.default_branch,spec.branch)): raise ValueError("repo/default/branch are required")
        self.validate_binding(spec.repo); default,local,remote=self.refresh(spec.default_branch,spec.branch); path=Path(spec.worktree); started,recovered=self._claim(spec,started,pr_exists,any((local,remote,path.exists())),all((local,not remote,not path.exists()))); self.ensure_branch(spec.branch,default,local if started else None,remote,started); self.ensure_worktree(spec.branch,path); (marker:=self._marker(spec)).parent.mkdir(parents=True,exist_ok=True); marker.touch()  # Marker converts a later fresh reconcile into recovery.
        return default
def branch_name(swarm,issue):
    if not re.fullmatch(r"[A-Za-z0-9._-]+",swarm or "") or issue<1: raise ValueError("invalid swarm identity")
    return f"swarm/{swarm}/{issue}"
def worktree_path(repo_path,swarm,issue): branch_name(swarm,issue); repo=Path(repo_path).resolve(); return repo.parent/f".{repo.name}-swarm-worktrees"/f"{swarm}-{issue}"


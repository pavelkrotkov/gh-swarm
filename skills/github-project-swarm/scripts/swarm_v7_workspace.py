# Deterministic crash-safe Git workspace authority.
# Repository/origin binding, remote snapshots, ancestry and worktree ownership are Git
# facts; one swarm/issue maps to one branch/worktree. Recovery requires durable Git facts
# or the exact prepared marker. Workers alone own commit, push and PR publication.
from collections import namedtuple
import hashlib, re
from pathlib import Path
from swarm_v7_cli_process import run_process
from swarm_v7_github import exact_sha
_GITHUB=re.compile(r"(?:github\.com[/:])([^/]+/[^/]+?)(?:\.git)?$")
WorkspaceSpec=namedtuple("WorkspaceSpec","repo default_branch branch worktree")
class WorkspaceError(RuntimeError): pass
class WorkspaceCollision(WorkspaceError): pass
def _local_origin(origin,expected):
    try: return Path(origin).samefile(Path(expected))
    except OSError: return False
class GitWorkspace:
    def __init__(self,repo_path,timeout_s=30.0): self.repo_path,self.timeout_s=Path(repo_path).resolve(),timeout_s
    def run(self,args,*,cwd=None,check=True): return run_process(["git",*args],cwd=cwd or self.repo_path,check=check,timeout=self.timeout_s,error_type=WorkspaceError)
    def out(self,args,*,cwd=None,check=True): return self.run(args,cwd=cwd,check=check).stdout.strip()
    def common_dir(self,cwd=None): return Path(self.out(["rev-parse","--path-format=absolute","--git-common-dir"],cwd=cwd))
    def validate_binding(self,expected):
        top=Path(self.out(["rev-parse","--show-toplevel"]))
        if not top.samefile(self.repo_path): raise WorkspaceError(f"repo_path resolves to {top}, expected {self.repo_path}")
        origin=self.out(["remote","get-url","origin"]); match=_GITHUB.search(origin.rstrip("/"))
        if (match and match.group(1).lower()==expected.removesuffix(".git").lower()) or (not match and _local_origin(origin,expected)): return
        raise WorkspaceError(f"origin {origin!r} does not match configured repo {expected!r}")
    def _head(self,ref,missing=False):
        proc=self.run(["rev-parse","--verify","--quiet",f"{ref}^{{commit}}"],check=False)
        if proc.returncode==0: return exact_sha(proc.stdout.strip())
        if proc.returncode==1 and missing: return None
        raise WorkspaceError(proc.stderr.strip() or f"cannot inspect {ref}")
    def refresh(self,default,branch):
        self.out(["fetch","--prune","origin","+refs/heads/*:refs/remotes/origin/*"]); return self._head(f"refs/remotes/origin/{default}"),self._head(f"refs/heads/{branch}",True),self._head(f"refs/remotes/origin/{branch}",True)
    def ancestor(self,first,second):
        proc=self.run(["merge-base","--is-ancestor",first,second],check=False)
        if proc.returncode in (0,1): return proc.returncode==0
        raise WorkspaceError(proc.stderr.strip() or "git merge-base failed")
    def ensure_branch(self,branch,base,local,remote,started):
        if not started and any((local,remote)): raise WorkspaceError("fresh workspace branch appeared during preparation")
        if not local:
            self.out(["branch",branch,remote if remote else base]); return
        if not remote or self.ancestor(remote,local): return
        if self.ancestor(local,remote): raise WorkspaceError("local branch is behind durable remote branch; reconstruct from remote")
        raise WorkspaceError("local and remote swarm branch have diverged")
    def ensure_worktree(self,branch,path):
        if path.exists():
            current=self.out(["symbolic-ref","--quiet","--short","HEAD"],cwd=path,check=False)
            if current==branch and self.common_dir(path).samefile(self.common_dir()): return
            raise WorkspaceError(f"worktree path is not the expected {branch} checkout")
        self.out(["worktree","prune"]); path.parent.mkdir(parents=True,exist_ok=True); self.out(["worktree","add",str(path),branch])
    def _marker(self,spec): key=f"{spec.repo}\0{spec.branch}\0{Path(spec.worktree).resolve()}".encode(); return self.common_dir()/"hermes-swarm"/"prepared"/hashlib.sha256(key).hexdigest()
    def _claim(self,spec,started,pr_exists,collision,orphan):
        if started: return True,bool(collision or pr_exists)
        if pr_exists: raise WorkspaceCollision("fresh swarm identity collision: matching PR already exists")
        if not collision: return False,False
        if self._marker(spec).is_file(): return True,True
        if orphan: self.out(["branch","-D",spec.branch]); return False,False
        raise WorkspaceCollision("fresh swarm identity collision")
    def prepare(self,spec,*,started,pr_exists=False):
        if not all((spec.repo,spec.default_branch,spec.branch)): raise ValueError("repo/default/branch are required")
        self.validate_binding(spec.repo); default,local,remote=self.refresh(spec.default_branch,spec.branch); path=Path(spec.worktree); collision=bool(local or remote or path.exists()); orphan=bool(local and not remote and not path.exists()); started,recovered=self._claim(spec,started,pr_exists,collision,orphan); local=None if not started else local; self.ensure_branch(spec.branch,default,local,remote,started); self.ensure_worktree(spec.branch,path); marker=self._marker(spec); marker.parent.mkdir(parents=True,exist_ok=True); marker.touch()
        return default if not recovered else exact_sha(self.out(["merge-base",f"refs/remotes/origin/{spec.default_branch}",f"refs/heads/{spec.branch}"]))
def branch_name(swarm,issue):
    if not re.fullmatch(r"[A-Za-z0-9._-]+",swarm or "") or issue<1: raise ValueError("invalid swarm identity")
    return f"swarm/{swarm}/{issue}"
def worktree_path(repo_path,swarm,issue):
    branch_name(swarm,issue); repo=Path(repo_path).resolve(); return repo.parent/f".{repo.name}-swarm-worktrees"/f"{swarm}-{issue}"

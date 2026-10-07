# Low-level Git trust boundary for repository binding, refs, and ancestry.
# Every read is bounded through the shared subprocess transport and exact SHAs are validated.
# No workflow phase or retry decision is stored here.
# Repository binding accepts the configured GitHub origin or an explicitly local samefile origin only.
# Ref reads resolve commits to full SHAs before worktree policy consumes them.
# Ancestry returns only Git's 0/1 result; transport errors are never interpreted as false.
# Common-dir identity prevents a different repository checkout from satisfying worktree ownership.
import re
from pathlib import Path
from swarm_v7_cli_process import run_process
from swarm_v7_github import exact_sha
_GITHUB=re.compile(r"(?:github\.com[/:])([^/]+/[^/]+?)(?:\.git)?$")
class WorkspaceError(RuntimeError): pass
def _local_origin(origin,expected):
    try: return Path(origin).samefile(Path(expected))
    except OSError: return False
class GitRepository:
    def __init__(self,repo_path,timeout_s=30.0): self.repo_path,self.timeout_s=Path(repo_path).resolve(),timeout_s
    def run(self,args,*,cwd=None,check=True): return run_process(["git",*args],cwd=cwd or self.repo_path,check=check,timeout=self.timeout_s,error_type=WorkspaceError)
    def out(self,args,*,cwd=None,check=True): return self.run(args,cwd=cwd,check=check).stdout.strip()
    def common_dir(self,cwd=None): return Path(self.out(["rev-parse","--path-format=absolute","--git-common-dir"],cwd=cwd))
    def validate_binding(self,expected):
        if not Path(self.out(["rev-parse","--show-toplevel"])).samefile(self.repo_path): raise WorkspaceError(f"repo_path does not resolve to {self.repo_path}")
        origin=self.out(["remote","get-url","origin"])
        if not (((match:=_GITHUB.search(origin.rstrip("/"))) and match.group(1).lower()==expected.removesuffix(".git").lower()) or (not match and _local_origin(origin,expected))): raise WorkspaceError(f"origin {origin!r} does not match configured repo {expected!r}")
    def _head(self,ref,missing=False):
        if (code:=(proc:=self.run(["rev-parse","--verify","--quiet",f"{ref}^{{commit}}"],check=False)).returncode)==0: return exact_sha(proc.stdout.strip())
        if code==1 and missing: return None
        raise WorkspaceError(proc.stderr.strip() or f"cannot inspect {ref}")
    def refresh(self,default,branch):
        self.out(["fetch","--prune","origin","+refs/heads/*:refs/remotes/origin/*"]); return self._head(f"refs/remotes/origin/{default}"),self._head(f"refs/heads/{branch}",True),self._head(f"refs/remotes/origin/{branch}",True)
    def ancestor(self,first,second):
        if (code:=(proc:=self.run(["merge-base","--is-ancestor",first,second],check=False)).returncode) in (0,1): return code==0
        raise WorkspaceError(proc.stderr.strip() or "git merge-base failed")

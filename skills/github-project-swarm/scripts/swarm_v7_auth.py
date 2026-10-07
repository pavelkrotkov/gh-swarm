# Worker GitHub auth is projected from the operator's gh config without copying token variables.
# Profile and config paths are canonicalized before any write; symlinked .env files fail closed.
# Auth is verified with token environment variables removed, so projected config is the only credential source.
# Replacement of the profile .env is atomic and permissioned 0600.
# Existing non-GitHub environment entries are preserved byte-for-byte apart from trailing newline normalization.
# A missing profile, hosts.yml or successful gh auth check aborts before Kanban task creation.
import os,pathlib,re,tempfile
from swarm_v7_cli_process import run_process
_TOKEN_KEYS={"GH_TOKEN","GITHUB_TOKEN","GH_ENTERPRISE_TOKEN","GITHUB_ENTERPRISE_TOKEN"}
def _auth_paths(assignee):
    home=os.path.realpath(os.path.expanduser(os.environ.get("HERMES_HOME","~/.hermes"))); profiles=os.path.join(home,"profiles"); name=str(assignee or ""); profile=os.path.realpath(os.path.join(profiles,name)); config=os.path.realpath(os.path.expanduser(os.environ.get("GH_CONFIG_DIR",os.path.join(os.environ.get("XDG_CONFIG_HOME","~/.config"),"gh")))); env=os.path.join(profile,".env")
    if not name or os.path.dirname(profile)!=profiles or not os.path.isdir(profile) or not os.path.isfile(os.path.join(config,"hosts.yml")) or os.path.islink(env): raise RuntimeError(f"GitHub CLI auth/profile unavailable for Hermes worker {name!r}; run `gh auth login`, ensure {profile} exists without a symlinked .env, or set GH_CONFIG_DIR")
    return profile,config,env
def _auth_env(config):
    env={key:value for key,value in os.environ.items() if key not in _TOKEN_KEYS}; env["GH_CONFIG_DIR"]=config; return env
def _project_auth(profile,config,env):
    text=pathlib.Path(env).read_text(encoding="utf-8") if os.path.exists(env) else ""; projected=(re.sub(r"(?m)^GH_CONFIG_DIR=.*(?:\n|$)","",text).rstrip("\n")+f"\nGH_CONFIG_DIR={config}\n").lstrip("\n")
    with tempfile.NamedTemporaryFile("w",dir=profile,delete=False,encoding="utf-8") as out: out.write(projected); out.flush(); os.fsync(out.fileno()); os.fchmod(out.fileno(),0o600); tmp=out.name
    os.replace(tmp,env)
def ensure_worker_github_auth(assignee):
    profile,config,env=_auth_paths(assignee); auth=run_process(("gh","auth","status","--active","--hostname","github.com"),check=False,env=_auth_env(config))
    if auth.returncode: raise RuntimeError(f"GitHub CLI auth unavailable through projected config {config}; run `GH_CONFIG_DIR={config} gh auth login` before swarm dispatch")
    _project_auth(profile,config,env)

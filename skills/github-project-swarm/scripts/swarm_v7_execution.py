# Immutable execution identities and task specifications shared by controller and Kanban.
# Semantic keys are issue-scoped for implementation and exact-head scoped thereafter.
# Worker profile preparation projects GitHub CLI config without copying credentials.
# Task completion remains liveness evidence; durable GitHub/git artifacts decide workflow state.
from collections import namedtuple
from enum import Enum
import os, pathlib, re, shlex, tempfile
from pathlib import Path
from swarm_v7_cli_process import run_process
from swarm_v7_github import adjudication_marker, exact_sha, review_marker
TaskSpec=namedtuple("TaskSpec","title body workspace model assignee provider skills branch max_retries max_runtime completion_contract",defaults=(None,(),None,1,"30m","local-only")); Outcome=Enum("Outcome",{name:name.lower() for name in "ACTIVE SUCCESS FAILURE".split()},type=str); TaskFacts=namedtuple("TaskFacts","task_id status outcome raw has_run",defaults=(True,))
ExactHeadTarget=namedtuple("ExactHeadTarget","repo issue pr_number head workspace assignee"); SlotState=Enum("SlotState",{name:name for name in "SATISFIED ACTIVE EXHAUSTED NOT_READY".split()},type=str); SlotResult=namedtuple("SlotResult","state semantic_key task_id attempt reason",defaults=(None,None,"")); ReviewExecutionError=RuntimeError
_TEMPLATE=(Path(__file__).resolve().parents[1]/"references"/"swarm_v7_worker_runtime.txt").read_text(encoding="utf-8")
_R=Path(__file__).resolve().parents[1]/"references"; _REVIEWER=(_R/"swarm_v7_reviewer_runtime.txt").read_text(); _ADJ=(_R/"swarm_v7_adjudicator_runtime.txt").read_text()
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
def attempt_key(key,attempt=1):
    if not key or attempt<1: raise ValueError("semantic key is required and attempt must be positive")
    return key if attempt==1 else f"{key}:a{attempt}"
def semantic_key(swarm,issue,kind,*,head=None,slot=None):
    prefix=f"swarm:{swarm}:issue:{issue}:"
    if kind=="implementation": return prefix+kind
    if kind=="review" and slot and slot>0: return f"{prefix}review:v{slot}:{exact_sha(str(head))}"
    if kind in {"adjudication","revision"}: return f"{prefix}{kind}:{exact_sha(str(head))}"
    raise ValueError("invalid semantic execution identity")
def create_args(spec,key,attempt=1):
    if spec.branch and not spec.workspace.startswith("worktree"): raise ValueError("--branch is only valid for worktree workspaces")
    args=["create",spec.title,"--body",spec.body,"--workspace",spec.workspace,"--completion-contract",spec.completion_contract,"--max-retries",str(spec.max_retries),"--max-runtime",spec.max_runtime,"--idempotency-key",attempt_key(key,attempt),"--assignee",spec.assignee]; args.extend(("--branch",spec.branch)*bool(spec.branch))
    for skill in spec.skills: args.extend(("--skill",skill))
    args.extend(("--model",spec.model)); args.extend(("--provider",spec.provider)*bool(spec.provider)); return args
def worker_body(repo,issue,branch,default_branch,base_sha,issue_text,*,revision=False): exact_sha(base_sha); return _TEMPLATE.format(operation="revision" if revision else "implementation",repo=repo,issue=issue,branch=branch,default_branch=default_branch,base_sha=base_sha,issue_text=issue_text.strip())
def _need(ok,message,error=ValueError):
    if not ok: raise error(message)
def _target(config,target):
    workspace=str(target.workspace or "").strip(); _need(target.repo==config.repo and target.issue in config.issues,"review target does not match swarm configuration"); _need(target.pr_number>=1,"PR number must be positive"); exact_sha(target.head); _need(workspace.startswith("dir:") and len(workspace)>4,"review/adjudication workspace must be a stable dir: launcher, not an implementation worktree")
    return workspace
def _model(value):
    parts=shlex.split(value); _need(len(parts)==1 or len(parts)==3 and parts[1]=="--provider",f"unsupported model specification: {value!r}")
    return parts[0],None if len(parts)==1 else parts[2]
def reviewer_task_spec(config,target,slot):
    workspace=_target(config,target); _need(1<=slot<=len(config.reviewer_models),"reviewer slot is out of range")
    model,provider=_model(config.reviewer_models[slot-1]); body=_REVIEWER.format(repo=target.repo,pr_number=target.pr_number,head=target.head,slot=slot,marker=review_marker(config.swarm_id,target.issue,slot,target.head)); return TaskSpec(f"[review {target.head[:8]}] #{target.issue} reviewer {slot}",body,workspace,model,target.assignee,provider=provider,skills=("github-project-reviewer",))
def adjudicator_task_spec(config,target):
    workspace=_target(config,target); model,provider=_model(config.adjudicator_model); body=_ADJ.format(repo=target.repo,pr_number=target.pr_number,head=target.head,head_repr=repr(target.head),marker=adjudication_marker(config.swarm_id,target.issue,target.head)); return TaskSpec(f"[adjudicate {target.head[:8]}] #{target.issue}",body,workspace,model,target.assignee,provider=provider,skills=("github-project-adjudicator",))

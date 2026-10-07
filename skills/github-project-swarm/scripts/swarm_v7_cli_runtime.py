# Initialization, validation, operator configuration, and service administration.
# Reads validate repository/GitHub/Kanban contracts before state creation; service actions touch swarm units only.
import re,shlex
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from swarm_v7 import ManifestV7
from swarm_v7_cli_process import run_command, subprocess_timeout
import swarm_v7_cli_state as state
from swarm_v7_cli_state import locked, manifest_path, selected, save, load, journal
from swarm_v7_controller import ActionResult, RuntimeManifest, plan_once
from swarm_v7_github import GhReader
from swarm_v7_kanban import KanbanAdapter
from swarm_v7_workspace import GitWorkspace
_REQUIRED=("ponytail","github-project-reviewer","github-project-adjudicator","github-project-swarm"); _TIMER="hermes-swarm-reconcile.timer"; _SERVICE="hermes-swarm-reconcile.service"
def _model(value):
    if len(parts:=shlex.split(value))==1: return parts[0]
    if len(parts)==3 and parts[1]=="--provider": return shlex.join(parts)
    raise ValueError(f"invalid model spec: {value!r}")
def _issues(args,repo,reader):
    numbers=list(map(int,filter(str.strip,args.issues.split(",")))) if args.issues else [int(row["number"]) for row in reader.list(f"repos/{repo}/issues/{args.epic}/sub_issues")]
    if not numbers: raise RuntimeError("No issues found; use an epic with native sub-issues or --issues")
    if any(str(reader.get(f"repos/{repo}/issues/{number}").get("state")).upper()!="OPEN" for number in numbers): raise RuntimeError("issue set contains non-open issues")
    return numbers
def _repo(args,cwd): return args.repo if args.repo else run_command(["gh","repo","view","--json","nameWithOwner","-q",".nameWithOwner"],cwd)
def _validated_runtime(args):
    timeout=subprocess_timeout(); cwd=str(Path(args.repo_path).resolve()); repo=_repo(args,cwd); GitWorkspace(cwd,timeout_s=timeout).validate_binding(repo); reader=GhReader(timeout_s=timeout); numbers=_issues(args,repo,reader); default=reader.get(f"repos/{repo}").get("default_branch")
    if not default: raise RuntimeError("GitHub did not return a default branch")
    reviewers=tuple(map(_model,args.reviewer)); seed=args.epic if args.epic is not None else numbers[0]; name=args.name if args.name else f"{repo.split('/')[-1]}-{seed}"; swarm=re.sub(r"[^a-z0-9-]+","-",name.lower()).strip("-")[:50]
    if manifest_path(swarm).exists(): raise RuntimeError(f"swarm already exists: {swarm}")
    adjudicator=_model(args.adjudicator) if args.adjudicator else reviewers[0]; config=ManifestV7(swarm,repo,default,tuple(numbers),_model(args.worker),reviewers,adjudicator,args.ci_mode=="required",paused=args.paused,merge_policy=args.merge_policy); return RuntimeManifest(config,cwd,args.board if args.board else swarm,args.assignee,args.max_execution_attempts,args.max_runtime,{})
def init(args,reconcile_fn=None):
    runtime=_validated_runtime(args); KanbanAdapter(runtime.board,runtime.repo_path,subprocess_timeout()).create_board(f"GitHub swarm {runtime.config.repo}"); save(runtime)
    if not runtime.config.paused and reconcile_fn is not None and (errors:=reconcile_fn(runtime)): raise RuntimeError("initial reconciliation encountered errors:\n"+"\n".join(errors))
    print(f"Initialized {runtime.config.swarm_id}: {len(runtime.config.issues)} issues, schema=7, board={runtime.board}, merge={runtime.config.merge_policy}, {'paused' if runtime.config.paused else 'active'}"); print(f"Manifest: {manifest_path(runtime.config.swarm_id)}"); return runtime
def doctor(args):
    for cmd in (["git","--version"],["gh","--version"],["hermes","--version"],["gh","auth","status"]): run_command(cmd)
    if missing:=[skill for skill in _REQUIRED if skill not in run_command(["env","COLUMNS=1000","hermes","skills","list"])]: raise RuntimeError(f"missing required skills: {', '.join(missing)}")
    timeout=subprocess_timeout(); KanbanAdapter("__contract_probe__",timeout_s=timeout).probe_contract()
    if args.repo and not GhReader(timeout_s=timeout).get(f"repos/{args.repo}").get("default_branch"): raise RuntimeError(f"cannot read repository {args.repo}")
    _timer_health(); print("doctor: ok; schema-7 adapters readable; no writes performed")
def validate(*,repo=None,name=None,all_swarms=True):
    doctor(SimpleNamespace(repo=repo)); paths=selected(name=name,all_swarms=all_swarms if not name else False)
    for path in paths:
        runtime=load(path); plans=tuple(plan_once(runtime,issue) for issue in runtime.config.issues); bad=next((item for item in plans if item.observation.planner.unsafe_reason),None)
        if bad: raise RuntimeError(f"{runtime.config.swarm_id} #{bad.observation.github.issue_number}: {bad.observation.planner.unsafe_reason}")
    print("validate: ok; no swarm actions performed")
def systemctl(*args,check=True): return run_command(["systemctl","--user",*args],check=check)
def _timer_health():
    values=dict(line.split("=",1) for line in systemctl("show",_TIMER,"-p","ActiveState","-p","NextElapseUSecMonotonic",check=False).splitlines() if "=" in line); dead=values.get("ActiveState")=="active" and values.get("NextElapseUSecMonotonic") in {"","0"}
    if dead and systemctl("show",_SERVICE,"-p","ActiveState","--value",check=False) not in {"active","activating"}: raise RuntimeError(f"{_TIMER} is active but has no next elapse; run `systemctl --user restart {_TIMER}`")
def prepare(): print("prepare: schema 7 needs no prompt/profile projection; execution artifacts are prepared lazily")
def activate(*,repo=None): validate(repo=repo,all_swarms=True); systemctl("daemon-reload"); systemctl("enable","--now",_TIMER); _timer_health(); print(f"activated {_TIMER}")
def disable(): systemctl("disable","--now",_TIMER,check=False); systemctl("stop",_SERVICE,check=False); print("disabled Hermes swarm reconciliation; Hermes gateway was not touched")
def retire(args):
    reason=args.reason.strip(); path=selected(name=args.name)[0]
    if not reason: raise RuntimeError("--reason must be non-empty")
    with locked(state.STATE/f".reconcile.{path.stem}.lock"):
        runtime=load(path); issue=args.issue
        if issue not in runtime.config.issues: raise RuntimeError(f"issue #{issue} is not active in swarm {runtime.config.swarm_id}")
        tasks=KanbanAdapter(runtime.board,runtime.repo_path,subprocess_timeout()).block_issue(runtime.config.swarm_id,issue,f"retired by operator: {reason}"); runtime.config=replace(runtime.config,issues=tuple(number for number in runtime.config.issues if number!=issue)); runtime.retired_issues[str(issue)]=reason; save(runtime); journal(runtime,issue,None,ActionResult("retired",tasks,reason),0)
    print(f"{runtime.config.swarm_id} [{runtime.config.repo}] #{issue}: retired from active scope — {reason}")
def configure(args,**changes):
    for path in selected(name=args.name,all_swarms=getattr(args,"all",False)):
        with locked(state.STATE/f".reconcile.{path.stem}.lock"):
            runtime=load(path); runtime.config=replace(runtime.config,**changes); save(runtime); print(f"{runtime.config.swarm_id}: "+", ".join(f"{key}={value}" for key,value in changes.items()))

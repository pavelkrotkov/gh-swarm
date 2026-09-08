#!/usr/bin/env python3
# Closed schema-7 CLI lifecycle: parsing, durable config/cursors, views, reconcile, admin.
# Local state never supplies semantic workflow truth; GitHub is re-observed by plan_once.
# Writes are atomic/fsynced, reconcile is flock-serialized, and the journal is diagnostics.
# Service administration controls only swarm units and never touches the Hermes gateway.
import argparse, errno, json, os, re, shlex, sys, tempfile, time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from swarm_v7 import ManifestV7
from swarm_v7_cli_process import run_command, subprocess_timeout
from swarm_v7_controller import ActionResult, RuntimeManifest, apply_plan, observation_payload, plan_once, plan_payload
from swarm_v7_github import GhReader
from swarm_v7_kanban import KanbanAdapter
from swarm_v7_workspace import GitWorkspace
try: import fcntl
except ImportError: fcntl=None
HOME=Path(os.environ.get("HERMES_HOME",Path.home()/".hermes")).expanduser(); STATE=Path(os.environ.get("HERMES_SWARM_STATE_DIR",HOME/"swarms")).expanduser(); _REQUIRED=("ponytail","github-project-reviewer","github-project-adjudicator","github-project-swarm"); _TIMER="hermes-swarm-reconcile.timer"; _SERVICE="hermes-swarm-reconcile.service"
def manifest_path(swarm_id): return STATE/f"{swarm_id}.json"
def manifests(): STATE.mkdir(parents=True,exist_ok=True); return sorted(STATE.glob("*.json"))
def selected(*,name=None,all_swarms=False):
    if name:
        path=manifest_path(name)
        if not path.exists(): raise RuntimeError(f"unknown swarm {name}")
        return [path]
    if len(paths:=manifests())==1 or all_swarms: return paths
    raise RuntimeError("Specify --name or --all")
@contextmanager
def locked(path,*,nonblocking=False):
    if fcntl is None: raise RuntimeError("swarm reconcile locking requires POSIX flock support")
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,"w",encoding="utf-8") as handle: fcntl.flock(handle,fcntl.LOCK_EX|(fcntl.LOCK_NB if nonblocking else 0)); yield
def _fsync_directory(path):
    if os.name=="nt": return
    fd=os.open(path,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try: os.fsync(fd)
    except OSError as exc:
        if exc.errno not in (errno.EINVAL,errno.ENOTSUP): raise
    finally: os.close(fd)
def save(runtime):
    STATE.mkdir(parents=True,exist_ok=True); target=manifest_path(runtime.config.swarm_id); fd,tmp=tempfile.mkstemp(prefix=f".{runtime.config.swarm_id}.",suffix=".tmp",dir=STATE)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out: json.dump(runtime.to_dict(),out,ensure_ascii=False,indent=2); out.write("\n"); out.flush(); os.fsync(out.fileno())
        os.replace(tmp,target); _fsync_directory(STATE)
    finally: Path(tmp).unlink(missing_ok=True)
def load(path):
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,dict): raise RuntimeError(f"{path}: swarm manifest must be a JSON object")
    if raw.get("schema")!=7: raise RuntimeError(f"{path}: unsupported swarm schema {raw.get('schema')!r}; schema 5/6 migration is intentionally disabled. Initialize a fresh v7 swarm.")
    return RuntimeManifest.from_dict(raw)
def journal(runtime,issue,planned,result,elapsed_ms,error=None):
    fields=dict.fromkeys(("phase","action","would_action","reason","pr_head","intent_key")) if planned is None else plan_payload(planned.plan); row={"ts":time.time(),"swarm":runtime.config.swarm_id,"repo":runtime.config.repo,"issue":issue,"task_ids":[] if result is None else list(result.task_ids),"outcome":"error" if error else "none" if result is None else result.outcome,"elapsed_ms":elapsed_ms,"error":None if error is None else str(error),**fields}; STATE.mkdir(parents=True,exist_ok=True)
    with open(STATE/f"{runtime.config.swarm_id}.journal.jsonl","a",encoding="utf-8") as out: out.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n")
def _model(value):
    parts=shlex.split(value)
    if len(parts)==1: return parts[0]
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
    adjudicator=_model(args.adjudicator) if args.adjudicator else reviewers[0]; config=ManifestV7(swarm,repo,default,tuple(numbers),_model(args.worker),reviewers,adjudicator,args.ci_mode=="required",paused=args.paused); return RuntimeManifest(config,cwd,args.board if args.board else swarm,args.assignee,args.max_execution_attempts,args.max_runtime,{})
def init(args,reconcile_fn=None):
    runtime=_validated_runtime(args); KanbanAdapter(runtime.board,runtime.repo_path,subprocess_timeout()).create_board(f"GitHub swarm {runtime.config.repo}"); save(runtime)
    if not runtime.config.paused and reconcile_fn is not None and (errors:=reconcile_fn(runtime)): raise RuntimeError("initial reconciliation encountered errors:\n"+"\n".join(errors))
    print(f"Initialized {runtime.config.swarm_id}: {len(runtime.config.issues)} issues, schema=7, board={runtime.board}, {'paused' if runtime.config.paused else 'active'}"); print(f"Manifest: {manifest_path(runtime.config.swarm_id)}"); return runtime
def doctor(args):
    for cmd in (["git","--version"],["gh","--version"],["hermes","--version"],["gh","auth","status"]): run_command(cmd)
    skills=run_command(["env","COLUMNS=1000","hermes","skills","list"]); missing=[skill for skill in _REQUIRED if skill not in skills]
    if missing: raise RuntimeError(f"missing required skills: {', '.join(missing)}")
    timeout=subprocess_timeout(); KanbanAdapter("__contract_probe__",timeout_s=timeout).probe_contract()
    if args.repo and not GhReader(timeout_s=timeout).get(f"repos/{args.repo}").get("default_branch"): raise RuntimeError(f"cannot read repository {args.repo}")
    _timer_health(); print("doctor: ok; schema-7 adapters readable; no writes performed")
def validate(*,repo=None,name=None,all_swarms=True):
    doctor(SimpleNamespace(repo=repo))
    for path in selected(name=name,all_swarms=all_swarms if not name else False):
        runtime=load(path)
        for issue in runtime.config.issues: plan_once(runtime,issue)
    print("validate: ok; no swarm actions performed")
def systemctl(*args,check=True): return run_command(["systemctl","--user",*args],check=check)
def _timer_health():
    values=dict(line.split("=",1) for line in systemctl("show",_TIMER,"-p","ActiveState","-p","NextElapseUSecMonotonic",check=False).splitlines() if "=" in line); dead=values.get("ActiveState")=="active" and values.get("NextElapseUSecMonotonic") in {"","0"}
    if dead and systemctl("show",_SERVICE,"-p","ActiveState","--value",check=False) not in {"active","activating"}: raise RuntimeError(f"{_TIMER} is active but has no next elapse; run `systemctl --user restart {_TIMER}`")
def prepare(): print("prepare: schema 7 needs no prompt/profile projection; execution artifacts are prepared lazily")
def activate(*,repo=None): validate(repo=repo,all_swarms=True); systemctl("daemon-reload"); systemctl("enable","--now",_TIMER); _timer_health(); print(f"activated {_TIMER}")
def disable(): systemctl("disable","--now",_TIMER,check=False); systemctl("stop",_SERVICE,check=False); print("disabled Hermes swarm reconciliation; Hermes gateway was not touched")
def _snapshot(runtime,issue,planned): return {"swarm":runtime.config.swarm_id,"repo":runtime.config.repo,"issue":issue,"observation":observation_payload(planned.observation),"plan":plan_payload(planned.plan)}
def _render(row):
    plan=row["plan"]; action=plan["action"] or (f"suppressed:{plan['would_action']}" if plan["would_action"] else "none"); head=f" head={plan['pr_head'][:12]}" if plan.get("pr_head") else ""; return f"{row['swarm']} #{row['issue']}: {plan['phase']} action={action}{head} — {plan['reason']}"
def dry_run(*,name=None,all_swarms=False,json_output=False):
    rows=[]; _timer_health()
    for path in selected(name=name,all_swarms=all_swarms):
        runtime=load(path); rows.extend(_snapshot(runtime,issue,plan_once(runtime,issue)) for issue in runtime.config.issues)
    print(json.dumps(rows,ensure_ascii=False,sort_keys=True) if json_output else "\n".join(map(_render,rows)) if rows else "dry-run: no swarms configured")
def explain(*,name,issue,json_output=False):
    runtime=load(selected(name=name)[0])
    if issue not in runtime.config.issues: raise RuntimeError(f"issue #{issue} is not configured in swarm {runtime.config.swarm_id}")
    row=_snapshot(runtime,issue,plan_once(runtime,issue)); print(json.dumps(row,ensure_ascii=False,sort_keys=True) if json_output else _render(row))
def reconcile_runtime(runtime):
    errors=[]
    for issue in runtime.config.issues:
        started=time.monotonic(); planned=result=error=None
        try:
            planned=plan_once(runtime,issue); result=apply_plan(runtime,planned)
            if planned.plan.action is not None: save(runtime)
        except Exception as exc: error=f"{runtime.config.swarm_id} #{issue}: {exc}"; errors.append(error)
        journal(runtime,issue,planned,result,int((time.monotonic()-started)*1000),error)
    return errors
def reconcile(args):
    if args.dry_run: return dry_run(name=args.name,all_swarms=args.all,json_output=args.json)
    if args.json: raise RuntimeError("--json is only valid with reconcile --dry-run")
    errors=[]
    for path in selected(name=args.name,all_swarms=args.all):
        try:
            with locked(STATE/f".reconcile.{path.stem}.lock",nonblocking=True): errors.extend(reconcile_runtime(load(path)))
        except BlockingIOError: print(f"{path.stem}: reconcile already running; skipped",file=sys.stderr)
        except Exception as exc: errors.append(f"{path.stem}: {exc}")
    if errors: raise RuntimeError("reconciliation encountered errors:\n"+"\n".join(errors))
def pause(args,value):
    for path in selected(name=args.name,all_swarms=args.all):
        with locked(STATE/f".reconcile.{path.stem}.lock"):
            runtime=load(path); runtime.config=replace(runtime.config,paused=value); save(runtime); print(f"{runtime.config.swarm_id}: {'paused' if value else 'resumed'}")
def _selection(parser): parser.add_argument("--name"); parser.add_argument("--all",action="store_true")
def build_parser(handlers,root=None):
    root=root or argparse.ArgumentParser(prog="hermes-swarm"); sub=root.add_subparsers(dest="swarm_command",required=True); p=sub.add_parser("init"); p.add_argument("--repo"); p.add_argument("--repo-path",default="."); group=p.add_mutually_exclusive_group(required=True); group.add_argument("--epic",type=int); group.add_argument("--issues"); p.add_argument("--name"); p.add_argument("--board"); p.add_argument("--assignee",required=True); p.add_argument("--worker",required=True); p.add_argument("--reviewer",action="append",required=True); p.add_argument("--adjudicator"); p.add_argument("--max-runtime",default="8h"); p.add_argument("--max-execution-attempts",type=int,default=3); p.add_argument("--ci-mode",choices=["required","none"],default="required"); p.add_argument("--paused",action="store_true"); p.set_defaults(fn=handlers["init"])
    for name in ("status","reconcile","pause","resume"):
        p=sub.add_parser(name); _selection(p)
        if name=="reconcile": p.add_argument("--dry-run",action="store_true"); p.add_argument("--json",action="store_true")
        p.set_defaults(fn=handlers[name])
    p=sub.add_parser("doctor"); p.add_argument("--repo"); p.set_defaults(fn=handlers["doctor"]); p=sub.add_parser("validate"); p.add_argument("--repo"); _selection(p); p.set_defaults(fn=handlers["validate"]); p=sub.add_parser("explain"); p.add_argument("--name",required=True); p.add_argument("--issue",type=int,required=True); p.add_argument("--json",action="store_true"); p.set_defaults(fn=handlers["explain"])
    for name in ("prepare","disable"): sub.add_parser(name).set_defaults(fn=handlers[name])
    p=sub.add_parser("activate"); p.add_argument("--repo"); p.set_defaults(fn=handlers["activate"]); return root
def _parser():
    handlers={"init":lambda args:init(args,reconcile_runtime),"status":lambda args:dry_run(name=args.name,all_swarms=args.all),"reconcile":reconcile,"pause":lambda args:pause(args,True),"resume":lambda args:pause(args,False),"doctor":doctor,"validate":lambda args:validate(repo=args.repo,name=args.name,all_swarms=args.all or not args.name),"explain":lambda args:explain(name=args.name,issue=args.issue,json_output=args.json),"prepare":lambda _:prepare(),"activate":lambda args:activate(repo=args.repo),"disable":lambda _:disable()}; return build_parser(handlers)
def main(): args=_parser().parse_args(); args.fn(args)
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"hermes-swarm: {exc}",file=sys.stderr); raise SystemExit(1)

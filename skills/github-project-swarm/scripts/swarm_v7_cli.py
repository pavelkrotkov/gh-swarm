#!/usr/bin/env python3
# Closed schema-7 CLI: read-only views, one-pass reconcile, parser, and command dispatch.
# State durability and operator initialization/admin live in cohesive sibling boundaries.
import argparse,json,sys,time,uuid
from swarm_v7 import Action
from swarm_v7_cli_process import subprocess_timeout
from swarm_v7_cli_state import STATE, manifest_path, selected, locked, load, save, journal, _apply_with_receipt, _merge_attribution, _reconcile_context
from swarm_v7_cli_runtime import _REQUIRED, _SERVICE, _TIMER, _timer_health, activate, configure, disable, doctor, init, prepare, retire, systemctl, validate
from swarm_v7_controller import ActionResult, observation_payload, plan_once, plan_payload
from swarm_v7_kanban import KanbanAdapter
_SUMMARY=("success","partial_failure")
def _snapshot(runtime,issue,planned): return {"swarm":runtime.config.swarm_id,"repo":runtime.config.repo,"issue":issue,"merge_policy":runtime.config.merge_policy,"observation":observation_payload(planned.observation,runtime.config),"plan":plan_payload(planned.plan),"merge_attribution":_merge_attribution(runtime,issue,planned)}
def _render(row): plan=row["plan"]; action=plan["action"] or (f"suppressed:{plan['would_action']}" if plan["would_action"] else "none"); pr=(row["observation"]["pr"] or {}).get("number","-"); head=(plan.get("pr_head") or "-")[:12]; attribution=(row.get("merge_attribution") or {}).get("state","-"); return f"{row['swarm']} [{row['repo']}] #{row['issue']}: state={row['observation']['issue_state']} merge={row['merge_policy']} {plan['phase']} action={action} pr=#{pr} head={head} gates={json.dumps(row['observation']['gates'],separators=(',',':'))} merge_source={attribution} — {plan['reason']}"
def dry_run(*,name=None,all_swarms=False,json_output=False):
    rows=[]; runtimes=[]; _timer_health(); paths=selected(name=name,all_swarms=all_swarms)
    for path in paths: runtime=load(path); runtimes.append(runtime); rows.extend(_snapshot(runtime,issue,plan_once(runtime,issue)) for issue in runtime.config.issues)
    empty=", ".join(f"{runtime.config.swarm_id} merge={runtime.config.merge_policy}" for runtime in runtimes); print(json.dumps(rows,ensure_ascii=False,sort_keys=True) if json_output else "\n".join(map(_render,rows)) if rows else f"no active issues in selected swarms: {empty}" if paths else "dry-run: no swarms configured")
def explain(*,name,issue,json_output=False):
    runtime=load(selected(name=name)[0])
    if issue not in runtime.config.issues: raise RuntimeError(f"issue #{issue} retired from swarm {runtime.config.swarm_id} [{runtime.config.repo}]: {runtime.retired_issues[str(issue)]}" if str(issue) in runtime.retired_issues else f"issue #{issue} is not configured in swarm {runtime.config.swarm_id}")
    row=_snapshot(runtime,issue,plan_once(runtime,issue)); print(json.dumps(row,ensure_ascii=False,sort_keys=True) if json_output else _render(row))
def reconcile_runtime(runtime,correlation_id=None,rows=None):
    errors=[]; sweep=KanbanAdapter(runtime.board,runtime.repo_path,subprocess_timeout()).watchdog(); correlation_id,rows=_reconcile_context(correlation_id,rows)
    if sweep.get("skipped_locked"): raise RuntimeError("Kanban watchdog pass skipped: dispatcher lock busy")
    for issue in runtime.config.issues:
        started=time.monotonic(); planned=result=error=None
        try:
            if (planned:=plan_once(runtime,issue)).plan.action is Action.MERGE: runtime=load(manifest_path(runtime.config.swarm_id)); planned=plan_once(runtime,issue)
            result=_apply_with_receipt(runtime,planned,correlation_id)
            if planned.plan.action is not None: save(runtime)
        except Exception as exc: error=f"{runtime.config.swarm_id} #{issue}: {exc}"; errors.append(error)
        rows.append(journal(runtime,issue,planned,result,int((time.monotonic()-started)*1000),error,correlation_id=correlation_id))
    return errors
def reconcile(args):
    if args.dry_run: return dry_run(name=args.name,all_swarms=args.all,json_output=args.json)
    correlation_id=uuid.uuid4().hex; errors=[]; swarms=[]; partial=False
    for path in selected(name=args.name,all_swarms=args.all):
        summary={"swarm":path.stem,"status":"success","issues":[],"errors":[]}
        try:
            with locked(STATE/f".reconcile.{path.stem}.lock",nonblocking=True): current=reconcile_runtime(load(path),correlation_id=correlation_id,rows=summary["issues"]); errors.extend(current); summary["errors"].extend(current); summary["status"]=_SUMMARY[bool(current)]
        except BlockingIOError: summary["status"]="skipped_busy"; partial=True; print(f"{path.stem}: reconcile already running; skipped",file=sys.stderr)
        except Exception as exc: error=f"{path.stem}: {exc}"; errors.append(error); summary["errors"].append(error); summary["status"]="partial_failure"
        swarms.append(summary)
    if args.json: print(json.dumps({"correlation_id":correlation_id,"status":_SUMMARY[max(bool(errors),partial)],"swarms":swarms},ensure_ascii=False,sort_keys=True))
    if errors: raise RuntimeError("reconciliation encountered errors:\n"+"\n".join(errors))
def _selection(parser): parser.add_argument("--name"); parser.add_argument("--all",action="store_true")
def build_parser(handlers,root=None):
    root=root or argparse.ArgumentParser(prog="hermes-swarm"); sub=root.add_subparsers(dest="swarm_command",required=True); p=sub.add_parser("init"); p.add_argument("--repo"); p.add_argument("--repo-path",default="."); group=p.add_mutually_exclusive_group(required=True); group.add_argument("--epic",type=int); group.add_argument("--issues"); p.add_argument("--name"); p.add_argument("--board"); p.add_argument("--assignee",required=True); p.add_argument("--worker",required=True); p.add_argument("--reviewer",action="append",required=True); p.add_argument("--adjudicator"); p.add_argument("--max-runtime",default="8h"); p.add_argument("--max-execution-attempts",type=int,default=3); p.add_argument("--ci-mode",choices=["required","none"],default="required"); p.add_argument("--merge-policy",choices=["automatic","manual"],required=True); p.add_argument("--paused",action="store_true"); p.set_defaults(fn=handlers["init"])
    for name in ("status","reconcile","pause","resume"):
        p=sub.add_parser(name); _selection(p)
        (p.add_argument("--dry-run",action="store_true") if name=="reconcile" else None); (p.add_argument("--json",action="store_true") if name in {"status","reconcile"} else None)
        p.set_defaults(fn=handlers[name])
    p=sub.add_parser("doctor"); p.add_argument("--repo"); p.set_defaults(fn=handlers["doctor"]); p=sub.add_parser("validate"); p.add_argument("--repo"); _selection(p); p.set_defaults(fn=handlers["validate"]); p=sub.add_parser("explain"); p.add_argument("--name",required=True); p.add_argument("--issue",type=int,required=True); p.add_argument("--json",action="store_true"); p.set_defaults(fn=handlers["explain"]); p=sub.add_parser("retire"); p.add_argument("--name",required=True); p.add_argument("--issue",type=int,required=True); p.add_argument("--reason",required=True); p.set_defaults(fn=handlers["retire"]); p=sub.add_parser("merge-policy"); p.add_argument("--name",required=True); p.add_argument("policy",choices=["automatic","manual"]); p.set_defaults(fn=handlers["merge-policy"])
    for name in ("prepare","disable"): sub.add_parser(name).set_defaults(fn=handlers[name])
    p=sub.add_parser("activate"); p.add_argument("--repo"); p.set_defaults(fn=handlers["activate"]); return root
def _parser(): handlers={"init":lambda args:init(args,reconcile_runtime),"status":lambda args:dry_run(name=args.name,all_swarms=args.all,json_output=args.json),"reconcile":reconcile,"pause":lambda args:configure(args,paused=True),"resume":lambda args:configure(args,paused=False),"doctor":doctor,"validate":lambda args:validate(repo=args.repo,name=args.name,all_swarms=args.all or not args.name),"explain":lambda args:explain(name=args.name,issue=args.issue,json_output=args.json),"retire":retire,"merge-policy":lambda args:configure(args,merge_policy=args.policy),"prepare":lambda _:prepare(),"activate":lambda args:activate(repo=args.repo),"disable":lambda _:disable()}; return build_parser(handlers)
def main(): args=_parser().parse_args(); args.fn(args)
if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"hermes-swarm: {exc}",file=sys.stderr); raise SystemExit(1)


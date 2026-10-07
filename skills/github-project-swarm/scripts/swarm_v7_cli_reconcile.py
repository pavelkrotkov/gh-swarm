# Reconcile applies at most one fresh planned action per issue per pass.
# The Kanban watchdog runs before planning; a skipped dispatcher lock fails the pass closed.
# A planned merge reloads the manifest and replans under the swarm lock to invalidate stale policy.
# Per-swarm failures are isolated while process exit remains nonzero for real errors.
# Busy nonblocking locks are reported as partial/skipped rather than fabricated execution errors.
# JSON reconcile output carries the same issue journal rows written by the live pass.
import json,sys,time,uuid
from swarm_v7 import Action
from swarm_v7_cli_process import subprocess_timeout
from swarm_v7_cli_manifest import STATE,manifest_path,selected,locked,load,save
from swarm_v7_cli_journal import _apply_with_receipt,_reconcile_context,journal
from swarm_v7_controller import plan_once
from swarm_v7_kanban import KanbanAdapter
from swarm_v7_cli_views import dry_run
_SUMMARY=("success","partial_failure")
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

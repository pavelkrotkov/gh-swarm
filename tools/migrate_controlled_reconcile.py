#!/usr/bin/env python3
"""Retire one known local reconcile path in favor of the native schema-7 controller."""
import argparse, fcntl, json, os, shutil, subprocess, time
from collections import Counter
from pathlib import Path

LEGACY_TIMER="research-fabric-controlled-reconcile.timer"; LEGACY_SERVICE="research-fabric-controlled-reconcile.service"; GLOBAL_TIMER="hermes-swarm-reconcile.timer"; GLOBAL_SERVICE="hermes-swarm-reconcile.service"; ACTIVE_TASKS={"todo","ready","running","review"}

def run(*args,check=True):
    proc=subprocess.run(args,text=True,capture_output=True,timeout=30)
    if check and proc.returncode: raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(args)}")
    return proc

def state_dir(): return Path(os.environ.get("HERMES_SWARM_STATE_DIR",Path.home()/".hermes/swarms")).expanduser()
def manifest_path(name): return state_dir()/f"{name}.json"
def unit_path(unit): return Path.home()/".config/systemd/user"/unit
def unit_state(unit): return {"active":run("systemctl","--user","is-active",unit,check=False).stdout.strip(),"enabled":run("systemctl","--user","is-enabled",unit,check=False).stdout.strip()}
def active_tasks(board):
    rows=json.loads(run("hermes","kanban","--board",board,"list","--json").stdout or "[]")
    return [row.get("task",row) for row in rows if str(row.get("task",row).get("status") or "").lower() in ACTIVE_TASKS]
def _manifest(name):
    path=manifest_path(name); raw=json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema")!=7: raise RuntimeError(f"{path}: schema 7 required")
    runtime=raw.get("runtime") or {}; board=str(runtime.get("board") or "").strip()
    if not board: raise RuntimeError(f"{path}: runtime.board missing")
    return raw,board,path
def _capabilities(board): return {"merge_policy":"automatic" in run("hermes","swarm","merge-policy","--help").stdout,"completion_contract":"--completion-contract" in run("hermes","kanban","--board",board,"create","--help").stdout}
def _release(): return str((Path(os.environ.get("AGENT_SKILLFLEET_RUNTIME",Path.home()/".local/share/agent-skillfleet-runtime")).expanduser()/"current").resolve())
def preflight(name,legacy_script=None):
    raw,board,path=_manifest(name); schedulers={unit:unit_state(unit) for unit in (LEGACY_TIMER,LEGACY_SERVICE,GLOBAL_TIMER,GLOBAL_SERVICE)}
    manifest={"path":str(path),"schema":raw.get("schema"),"repo":raw.get("repo"),"paused":raw.get("paused"),"merge_policy":raw.get("merge_policy"),"board":board,"issues":list(raw.get("issues") or [])}
    return {"release":_release(),"capabilities":_capabilities(board),"schedulers":schedulers,"manifest":manifest,"active_tasks":active_tasks(board),"legacy_script":str(Path(legacy_script).expanduser()) if legacy_script else None}
def require_ready(report):
    if not all(report["capabilities"].values()): raise RuntimeError("loaded controller lacks native merge-policy/completion-contract support")
    if report["manifest"]["paused"] is not True: raise RuntimeError("migration requires the target swarm to start paused")
def wait_inactive(unit,timeout):
    deadline=time.monotonic()+timeout
    while unit_state(unit)["active"] in {"active","activating","deactivating"}:
        if time.monotonic()>=deadline: raise RuntimeError(f"timed out waiting for {unit}")
        time.sleep(.2)
def wait_lock(name,timeout):
    path=state_dir()/f".reconcile.{name}.lock"; path.parent.mkdir(parents=True,exist_ok=True); deadline=time.monotonic()+timeout
    with open(path,"a+",encoding="utf-8") as handle:
        while True:
            try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB); fcntl.flock(handle,fcntl.LOCK_UN); return
            except BlockingIOError:
                if time.monotonic()>=deadline: raise RuntimeError(f"timed out waiting for {path}")
                time.sleep(.2)
def backup(name,legacy_script=None):
    target=state_dir()/"migration-backups"/f"{name}-{time.time_ns()}"; target.mkdir(parents=True)
    paths=(manifest_path(name),unit_path(LEGACY_TIMER),unit_path(LEGACY_SERVICE),Path(legacy_script).expanduser() if legacy_script else None)
    for path in paths:
        if path and path.is_file() and not path.is_symlink(): shutil.copy2(path,target/path.name)
    return target
def safe_dry_run(name):
    rows=json.loads(run("hermes","swarm","reconcile","--dry-run","--name",name,"--json").stdout or "[]")
    if any((row.get("observation") or {}).get("unsafe_reason") for row in rows): raise RuntimeError("dry-run reports unsafe GitHub/execution state")
    return rows
def journal_offset(name):
    path=state_dir()/f"{name}.journal.jsonl"; return path.stat().st_size if path.exists() else 0
def new_journal(name,offset):
    path=state_dir()/f"{name}.journal.jsonl"
    if not path.exists(): return []
    with open(path,"r",encoding="utf-8") as handle: handle.seek(offset); return [json.loads(line) for line in handle if line.strip()]
def _dupes(values): return [key for key,count in Counter(values).items() if count>1]
def _task_evidence(board):
    tasks=active_tasks(board); missing=[str(row.get("id") or row.get("task_id") or "?") for row in tasks if not row.get("idempotency_key")]; return tasks,missing,_dupes([row["idempotency_key"] for row in tasks if row.get("idempotency_key")])
def _merge_evidence(rows):
    keys=[row["intent_key"] for row in rows if row.get("action")=="merge" and row.get("outcome")=="requested" and row.get("intent_key")]; return keys,_dupes(keys)
def verify_no_duplicates(board,rows):
    tasks,missing,task_dupes=_task_evidence(board); merge_keys,merge_dupes=_merge_evidence(rows)
    if missing or task_dupes or merge_dupes: raise RuntimeError(f"duplicate reconciliation evidence is not provably unique: missing_task_keys={missing}, tasks={task_dupes}, merges={merge_dupes}")
    return {"active_tasks":len(tasks),"merge_requests":len(merge_keys)}
def reconcile_once(name):
    proc=run("hermes","swarm","reconcile","--name",name)
    if "already running; skipped" in proc.stderr: wait_lock(name,30); run("hermes","swarm","reconcile","--name",name)
def rollback(name):
    try: run("hermes","swarm","pause","--name",name)
    except Exception: pass
def _activate_global():
    current=unit_state(GLOBAL_TIMER)
    if current["active"]!="active" or current["enabled"]!="enabled": run("hermes","swarm","activate")
def _postcheck(final,policy):
    legacy=final["schedulers"]
    if legacy[LEGACY_TIMER]["active"]=="active" or legacy[LEGACY_SERVICE]["active"] in {"active","activating"}: raise RuntimeError("legacy reconciliation path is still active")
    if final["manifest"]["paused"] or final["manifest"]["merge_policy"]!=policy: raise RuntimeError("native manifest read-back does not match requested mode")
def migrate(name,policy,timeout,legacy_script=None):
    report=preflight(name,legacy_script); require_ready(report); quiesced=False
    try:
        run("systemctl","--user","disable","--now",LEGACY_TIMER); quiesced=True; wait_inactive(LEGACY_SERVICE,timeout); wait_lock(name,timeout); archive=backup(name,legacy_script); run("hermes","swarm","pause","--name",name)
        run("hermes","swarm","merge-policy","--name",name,policy); run("hermes","swarm","validate","--name",name); safe_dry_run(name); offset=journal_offset(name); run("hermes","swarm","resume","--name",name); reconcile_once(name); rows=new_journal(name,offset)
        if report["manifest"]["issues"] and not rows: raise RuntimeError("standard reconciliation pass produced no journal evidence")
        check=verify_no_duplicates(report["manifest"]["board"],rows); _activate_global(); final=preflight(name,legacy_script); _postcheck(final,policy); return {"backup":str(archive),"verification":check,"final":final}
    except Exception:
        if quiesced: rollback(name)
        raise
def parser():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--name",required=True); p.add_argument("--merge-policy",choices=("automatic","manual"),default="automatic"); p.add_argument("--legacy-script"); p.add_argument("--timeout",type=float,default=120); p.add_argument("--apply",action="store_true"); return p
def main():
    args=parser().parse_args(); result=migrate(args.name,args.merge_policy,args.timeout,args.legacy_script) if args.apply else preflight(args.name,args.legacy_script); print(json.dumps(result,indent=2,sort_keys=True))
if __name__=="__main__": main()

#!/usr/bin/env python3
"""One-shot migration from the known local controlled-reconcile workaround."""
from __future__ import annotations
import argparse, fcntl, json, os, shutil, subprocess, tempfile, time
from pathlib import Path

HOME=Path(os.environ.get("HERMES_HOME",Path.home()/".hermes")).expanduser()
STATE=Path(os.environ.get("HERMES_SWARM_STATE_DIR",HOME/"swarms")).expanduser()
UNIT_DIR=Path(os.environ.get("HOME",str(Path.home()))).expanduser()/".config/systemd/user"
RUNTIME_ROOT=Path(os.environ.get("AGENT_SKILLFLEET_RUNTIME",Path.home()/".local/share/agent-skillfleet-runtime")).expanduser()
ACTIVE={"active","activating","reloading"}; TASK_ACTIVE={"todo","ready","running","review"}

def run_cmd(cmd,*,check=True):
    proc=subprocess.run(cmd,text=True,capture_output=True,timeout=60)
    if check and proc.returncode: raise RuntimeError(f"{' '.join(cmd)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout

def _manifest(name):
    path=STATE/f"{name}.json"; raw=json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema")!=7 or raw.get("id")!=name: raise RuntimeError(f"{path}: expected schema-7 manifest for {name}")
    board=str((raw.get("runtime") or {}).get("board") or "").strip()
    if not board: raise RuntimeError(f"{path}: runtime.board is required")
    return path,raw,board

def _unit(unit,runner=run_cmd):
    text=runner(["systemctl","--user","show",unit,"-p","LoadState","-p","ActiveState","-p","UnitFileState"],check=False)
    return {key:value for line in text.splitlines() if "=" in line for key,value in (line.split("=",1),)}

def _task_rows(board,runner=run_cmd,active_only=True):
    raw=json.loads(runner(["hermes","kanban","--board",board,"list","--json"]) or "[]")
    if not isinstance(raw,list): raise RuntimeError("Hermes Kanban list contract must return a JSON array")
    rows=[item.get("task",item) for item in raw if isinstance(item,dict)]
    return [row for row in rows if not active_only or str(row.get("status") or "").lower() in TASK_ACTIVE]

def lock_free(name):
    path=STATE/f".reconcile.{name}.lock"
    if not path.exists(): return True
    with open(path,"r+",encoding="utf-8") as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return False
        fcntl.flock(handle,fcntl.LOCK_UN); return True

def preflight(name,runner=run_cmd,probe=lock_free):
    path,raw,board=_manifest(name); current=RUNTIME_ROOT/"current"
    try: release=current.resolve(strict=True)
    except FileNotFoundError as exc: raise RuntimeError(f"active Skillfleet runtime is missing: {current}") from exc
    help_text=runner(["hermes","swarm","--help"]); create_help=runner(["hermes","kanban","--board",board,"create","--help"]); legacy=f"{name}-controlled-reconcile"
    units={unit:_unit(unit,runner) for unit in (f"{legacy}.timer",f"{legacy}.service","hermes-swarm-reconcile.timer","hermes-swarm-reconcile.service")}; workers=[{key:row.get(key) for key in ("id","status","title","idempotency_key")} for row in _task_rows(board,runner)]
    return {"controller_release":str(release),"hermes_version":runner(["hermes","--version"]).strip(),"capabilities":{"merge_policy":"merge-policy" in help_text,"completion_contract":"--completion-contract" in create_help},"manifest":{"path":str(path),"repo":raw.get("repo"),"paused":raw.get("paused"),"merge_policy":raw.get("merge_policy"),"board":board,"issues":list(raw.get("issues") or [])},"units":units,"in_flight":workers,"lock_free":probe(name)}

def _require_ready(report,*,lock=False):
    if not all(report["capabilities"].values()): raise RuntimeError("native merge-policy/completion-contract capability is missing")
    if report["manifest"].get("paused") is not True: raise RuntimeError("migration requires the target schema-7 manifest to be paused")
    if lock and not report["lock_free"]: raise RuntimeError("swarm reconcile lock is busy")

def wait_quiescent(name,runner=run_cmd,sleep=time.sleep,probe=lock_free,timeout=180):
    service=f"{name}-controlled-reconcile.service"; deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if _unit(service,runner).get("ActiveState") not in ACTIVE and probe(name): return
        sleep(0.2)
    raise RuntimeError(f"timed out waiting for {service} and swarm lock to quiesce")

def backup(name,legacy_script,report):
    script=Path(legacy_script).expanduser().resolve()
    if script.name!="controlled_reconcile.py" or not script.is_file(): raise RuntimeError("--legacy-script must name the existing controlled_reconcile.py")
    manifest,_,_=_manifest(name); root=HOME/"swarm-migration-backups"; root.mkdir(parents=True,exist_ok=True); target=Path(tempfile.mkdtemp(prefix=f"{name}-",dir=root))
    for source in (manifest,STATE/f"{name}.journal.jsonl",script,UNIT_DIR/f"{name}-controlled-reconcile.service",UNIT_DIR/f"{name}-controlled-reconcile.timer"):
        if source.is_file(): shutil.copy2(source,target/source.name)
    (target/"preflight.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return target

def _journal(name):
    path=STATE/f"{name}.journal.jsonl"
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def _dry_run(name,runner):
    rows=json.loads(runner(["hermes","swarm","reconcile","--dry-run","--name",name,"--json"]) or "[]")
    if any((row.get("observation") or {}).get("unsafe_reason") for row in rows): raise RuntimeError("native dry-run reported unsafe GitHub/execution state")
    return rows

def _new_journal(name,before,issues,sleep,timeout):
    deadline=time.monotonic()+timeout
    while True:
        rows=_journal(name)[before:]; seen={int(row.get("issue")) for row in rows if row.get("issue") is not None}
        if not issues or set(map(int,issues))<=seen: return rows
        if time.monotonic()>=deadline: return rows
        sleep(0.2)

def _verify_tasks(board,runner):
    keys=[]
    for row in _task_rows(board,runner,False):
        if key:=row.get("idempotency_key"): keys.append(str(key))
    if len(keys)!=len(set(keys)): raise RuntimeError("duplicate Kanban idempotency keys detected after cutover")

def _verify_journal(rows,issues):
    seen=set(); merges=[]
    for row in rows:
        if row.get("issue") is not None: seen.add(int(row["issue"]))
        if row.get("error"): raise RuntimeError("standard reconciliation journal contains an error")
        if row.get("action")=="merge": merges.append((row.get("issue"),row.get("pr_head")))
    if set(map(int,issues))-seen: raise RuntimeError("standard reconciliation did not journal every active issue")
    if len(merges)!=len(set(merges)): raise RuntimeError("duplicate exact-head merge requests detected during cutover")

def _verify(name,before,runner,sleep=time.sleep,timeout=180):
    _,raw,board=_manifest(name); _verify_tasks(board,runner); _verify_journal(_new_journal(name,before,raw.get("issues") or [],sleep,timeout),raw.get("issues") or [])

def _timer_ready(state): return state.get("ActiveState") in ACTIVE and state.get("UnitFileState") in {"enabled","enabled-runtime"}

def _verify_final(name,policy,legacy_timer,report):
    _,raw,_=_manifest(name)
    if raw.get("paused") or raw.get("merge_policy")!=policy: raise RuntimeError("native manifest read-back does not match requested active policy")
    units=report["units"]; legacy=units[legacy_timer]; service=units[legacy_timer.removesuffix(".timer")+".service"]
    if legacy.get("ActiveState") in ACTIVE or legacy.get("UnitFileState") in {"enabled","enabled-runtime"} or service.get("ActiveState") in ACTIVE or not _timer_ready(units["hermes-swarm-reconcile.timer"]): raise RuntimeError("scheduler read-back does not show legacy quiesced and standard timer active/enabled")

def _pause(name,runner):
    try: runner(["hermes","swarm","pause","--name",name]); return None
    except Exception as exc: return str(exc)

def migrate(name,policy,legacy_script,*,runner=run_cmd,sleep=time.sleep,probe=lock_free,timeout=180):
    if timeout<=0: raise ValueError("timeout must be positive")
    report=preflight(name,runner,probe); _require_ready(report); legacy_timer=f"{name}-controlled-reconcile.timer"; runner(["systemctl","--user","disable","--now",legacy_timer])
    try:
        wait_quiescent(name,runner,sleep,probe,timeout); report=preflight(name,runner,probe); _require_ready(report,lock=True); saved=backup(name,legacy_script,report); before=len(_journal(name)); standard_was_ready=_timer_ready(report["units"]["hermes-swarm-reconcile.timer"])
        runner(["hermes","swarm","pause","--name",name]); runner(["hermes","swarm","merge-policy","--name",name,policy]); runner(["hermes","swarm","validate","--name",name]); _dry_run(name,runner); runner(["hermes","swarm","resume","--name",name]); runner(["hermes","swarm","reconcile","--name",name]); _verify(name,before,runner,sleep,timeout)
        if not standard_was_ready: runner(["hermes","swarm","activate"])
        final=preflight(name,runner,probe); _verify_final(name,policy,legacy_timer,final); return {"backup":str(saved),"preflight":report,"final":final}
    except Exception as exc:
        pause_error=_pause(name,runner); suffix=f"; rollback pause failed: {pause_error}" if pause_error else "; target swarm left paused; legacy controller remains disabled"
        raise RuntimeError(f"cutover failed: {exc}{suffix}") from exc

def _parser():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--name",required=True); p.add_argument("--legacy-script"); p.add_argument("--merge-policy",choices=("automatic","manual")); p.add_argument("--apply",action="store_true"); p.add_argument("--wait-seconds",type=int,default=180); return p

def main():
    args=_parser().parse_args()
    if args.apply:
        if not args.legacy_script or not args.merge_policy: raise RuntimeError("--apply requires --legacy-script and --merge-policy")
        result=migrate(args.name,args.merge_policy,args.legacy_script,timeout=args.wait_seconds)
    else: result=preflight(args.name)
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=="__main__":
    try: main()
    except Exception as exc: print(f"controlled-reconcile migration: {exc}",file=os.sys.stderr); raise SystemExit(1)

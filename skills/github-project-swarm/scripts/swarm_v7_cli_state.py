# Crash-safe local runtime configuration, attempt cursors, and diagnostic journal.
# Semantic workflow truth is deliberately absent: every reconcile re-observes GitHub.
# Manifest replacement is atomic and fsynced; the journal records intent/outcome but never authorizes work.
import errno,json,os,tempfile,time,uuid
from contextlib import contextmanager
from pathlib import Path
from swarm_v7 import Action
from swarm_v7_controller import RuntimeManifest, apply_plan, observation_payload, plan_payload
from swarm_v7_merge import MergeRequestError
try: import fcntl
except ImportError: fcntl=None
HOME=Path(os.environ.get("HERMES_HOME",Path.home()/".hermes")).expanduser(); STATE=Path(os.environ.get("HERMES_SWARM_STATE_DIR",HOME/"swarms")).expanduser()
def manifest_path(swarm_id): return STATE/f"{swarm_id}.json"
def manifests(): STATE.mkdir(parents=True,exist_ok=True); return sorted(STATE.glob("*.json"))
def selected(*,name=None,all_swarms=False):
    if name:
        if not (path:=manifest_path(name)).exists(): raise RuntimeError(f"unknown swarm {name}")
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
def _journal_outcome(error,result): return "error" if error else "none" if result is None else result.outcome
def journal(runtime,issue,planned,result,elapsed_ms,error=None,*,correlation_id=None,event="reconcile",receipt=None):
    fields=dict.fromkeys(("phase","action","would_action","reason","pr_head","intent_key")) if planned is None else plan_payload(planned.plan); gates=[] if planned is None else observation_payload(planned.observation,runtime.config)["gates"]; row={"ts":time.time(),"correlation_id":correlation_id,"event":event,"swarm":runtime.config.swarm_id,"repo":runtime.config.repo,"issue":issue,"task_ids":[] if result is None else list(result.task_ids),"outcome":_journal_outcome(error,result),"elapsed_ms":elapsed_ms,"error":None if error is None else str(error),"detail":None if result is None else result.detail,"gates":gates,**fields,**(receipt or {})}; STATE.mkdir(parents=True,exist_ok=True)
    with open(STATE/f"{runtime.config.swarm_id}.journal.jsonl","a",encoding="utf-8") as out: out.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n"); return row
def _merge_attribution(runtime,issue,planned):
    pr=planned.observation.github.pull_request
    if pr is None: return None
    path=STATE/f"{runtime.config.swarm_id}.journal.jsonl"; rows=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines(keepends=True) if line.endswith("\n")] if path.exists() else []; matches=list(filter(lambda row:(row.get("issue"),row.get("pr"),row.get("head"))==(issue,pr.number,pr.head),rows))
    intent=next(filter(lambda row:row.get("event")=="merge_intent",reversed(matches)),None); cid=(intent or {}).get("correlation_id"); outcome=next(filter(lambda row:(row.get("event"),row.get("correlation_id"))==("merge_outcome",cid),reversed(matches)),None); value=(outcome or {}).get("merge_outcome")
    state={(False,False,None):"none",(True,False,None):"observed_external",(True,True,None):"confirmed_after_unknown_request_outcome",(True,True,"unknown"):"confirmed_after_unknown_request_outcome",(True,True,"requested"):"controller_request_confirmed",(True,True,"github_confirmed"):"controller_request_confirmed",(True,True,"rejected"):"observed_external_after_rejected_request",(False,True,None):"outcome_unknown",(False,True,"unknown"):"outcome_unknown",(False,True,"requested"):"request_attempted",(False,True,"rejected"):"request_rejected"}.get((bool(pr.merged_at),bool(intent),value))
    return {"state":state,"correlation_id":cid,"request_outcome":value,"merged_at":pr.merged_at,"merge_sha":getattr(pr,"merge_sha",None)}
def _reconcile_context(correlation_id,rows): return correlation_id or uuid.uuid4().hex,[] if rows is None else rows

# Kanban task/run rows are normalized into execution liveness only.
# Unknown statuses fail through the closed status map rather than being guessed successful.
# Terminal cleanup ownership is proven from generated branch/publication markers.
# Running-run ordering and timeout grace are deterministic across CLI result order.
import time
from swarm_v7_execution import Outcome,TaskFacts
_STATUS={**{name:Outcome.ACTIVE for name in ("todo","ready","running","review")},"done":Outcome.SUCCESS,**{name:Outcome.FAILURE for name in ("blocked","archived","triage")}}; _RETRY_GRACE_S=120
KanbanExecutionError=RuntimeError
def _task(raw):
    row=raw.get("task",raw) if isinstance(raw,dict) else {}; task_id=row.get("id") or row.get("task_id") or row.get("taskId")
    if not task_id: raise KanbanExecutionError("Hermes Kanban task response is malformed or missing id")
    return row,str(task_id)
# Closed runs under a running card, or open runs past their own limit, are stale execution facts.
# Give Hermes two default dispatcher ticks to launch its internal retry before swarm replay.
# Run ordering is normalized before this check; CLI result order is not an execution contract.
# Terminal cleanup blocks matching active cards instead of archiving/deleting them.
# Blocked cards preserve task/run evidence and repeated cleanup becomes a no-op.
# Board names and issue numbers can collide; branch/publication markers bind cards to one swarm.
# Ownership reads only fixed generated header lines; copied issue text below them is untrusted.
# Marker type is bound to task title so review/adjudication text cannot claim worker ownership.
def _owned(title,lines,swarm,issue): return len(lines)>2 and lines[2]==f"Expected branch: swarm/{swarm}/{issue}" if title.startswith(("[implement]","[revise]")) else len(lines)>2 and lines[2].startswith(f"Required publication marker: <!-- hermes-swarm-review:{swarm}:{issue}:") if title.startswith("[review ") else len(lines)>1 and lines[1].startswith(f"Required adjudication marker: <!-- hermes-swarm-adjudication:{swarm}:{issue}:") if title.startswith("[adjudicate ") else False
def _issue_task(row,swarm,issue): title=str(row.get("title") or ""); number=title.partition("] #")[2].split(" ",1)[0]; return _STATUS.get(str(row.get("status") or "").strip().lower()) is Outcome.ACTIVE and number==str(issue) and _owned(title,str(row.get("body") or "").splitlines(),swarm,issue)
def _running_run(status,runs): return runs[-1] if status=="running" and runs else {}
def _run_state(status,runs): run=_running_run(status,runs); ended=run.get("ended_at"); now=time.time(); started,limit=run.get("started_at"),run.get("max_runtime_seconds"); return (f"run_{run.get('outcome')}",Outcome.FAILURE) if ended is not None and now-ended>=_RETRY_GRACE_S else ("timed_out",Outcome.FAILURE) if ended is None and None not in (started,limit) and now-started>=limit+_RETRY_GRACE_S else (status,_STATUS[status])

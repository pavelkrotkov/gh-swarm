from collections import namedtuple
from enum import Enum
from pathlib import Path
import shlex
from swarm_v7_github import adjudication_marker, exact_sha, review_marker
from swarm_v7_kanban import Outcome, TaskSpec, semantic_key
# Slots are satisfied only by durable current-head GitHub publication. Task completion
# merely waits for publication; failed attempts stay bounded under the same identity.
ExactHeadTarget=namedtuple("ExactHeadTarget","repo issue pr_number head workspace assignee"); SlotState=Enum("SlotState",{name:name for name in "SATISFIED ACTIVE WAITING_PUBLICATION EXHAUSTED NOT_READY".split()},type=str); SlotResult=namedtuple("SlotResult","state semantic_key task_id attempt reason",defaults=(None,None,"")); ReviewExecutionError=RuntimeError
_R=Path(__file__).resolve().parents[1]/"references"; _REVIEWER=(_R/"swarm_v7_reviewer_runtime.txt").read_text(); _ADJ=(_R/"swarm_v7_adjudicator_runtime.txt").read_text()
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
def _slot(satisfied,key,spec,adapter,attempts,wait_success=True):
    if satisfied: return SlotResult(SlotState.SATISFIED,key,reason="durable exact-head GitHub publication exists")
    if attempts<1: raise ValueError("max_attempts must be positive")
    for attempt in range(1,attempts+1):
        task=adapter.create(spec,key,attempt); outcome=adapter.observe(task).outcome
        if outcome is Outcome.ACTIVE: return SlotResult(SlotState.ACTIVE,key,task,attempt,"execution attempt is active")
        if outcome is Outcome.SUCCESS and wait_success: return SlotResult(SlotState.WAITING_PUBLICATION,key,task,attempt,"task is done; wait for durable GitHub publication")
    return SlotResult(SlotState.EXHAUSTED,key,task,attempts,"bounded execution attempts failed without publication")
def _slots(config,target,rows):
    slots=[row.slot for row in rows if row.head==target.head]; _need(not any(slot<1 or slot>len(config.reviewer_models) for slot in slots),"reviewer publication is outside configured slot range",ReviewExecutionError); _need(len(slots)==len(set(slots)),"duplicate reviewer publication for current head",ReviewExecutionError); return set(slots)
def reconcile_reviewers(config,target,rows,adapter,max_attempts=2):
    _target(config,target); present=_slots(config,target,rows); return tuple(_slot(slot in present,semantic_key(config.swarm_id,target.issue,"review",slot=slot,head=target.head),reviewer_task_spec(config,target,slot),adapter,max_attempts) for slot in range(1,len(config.reviewer_models)+1))
def reconcile_adjudication(config,target,reviewers,rows,adapter,max_attempts=2):
    _target(config,target); key=semantic_key(config.swarm_id,target.issue,"adjudication",head=target.head)
    if len(_slots(config,target,reviewers))!=len(config.reviewer_models): return SlotResult(SlotState.NOT_READY,key,reason="current head reviewer slots are incomplete")
    current=[row for row in rows if row.head==target.head]; _need(len(current)<=1,"duplicate adjudication publications for current head",ReviewExecutionError)
    return _slot(bool(current),key,adjudicator_task_spec(config,target),adapter,max_attempts,False)

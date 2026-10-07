# Exact-head publication reconciliation is independent for every configured reviewer slot.
# Existing durable publications satisfy slots without replaying failed local task history.
# Adjudication cannot dispatch until every reviewer slot is durably published for the same head.
# Bounded attempts end in EXHAUSTED/NOT_READY rather than synthesizing semantic approval.
from swarm_v7_execution import Outcome,semantic_key
from swarm_v7_review_spec import ExactHeadTarget,ReviewExecutionError,SlotResult,SlotState,adjudicator_task_spec,reviewer_task_spec,_target,_model
def _review_slot(satisfied,key,spec,adapter,attempts,retry_success=False):
    if satisfied: return SlotResult(SlotState.SATISFIED,key,reason="durable exact-head GitHub publication exists")
    if not attempts: raise ValueError("attempt range must not be empty")
    for attempt in attempts:
        task=adapter.create(spec,key,attempt); outcome=adapter.observe(task).outcome
        if outcome is Outcome.ACTIVE or outcome is Outcome.SUCCESS and not retry_success: return SlotResult({Outcome.ACTIVE:SlotState.ACTIVE,Outcome.SUCCESS:SlotState.EXHAUSTED}[outcome],key,task,attempt,{Outcome.ACTIVE:"execution attempt is active",Outcome.SUCCESS:"task ended successfully without durable publication"}[outcome])
    return SlotResult(SlotState.EXHAUSTED,key,task,attempt,"bounded execution attempts ended without publication")
def _review_slots(config,target,rows):
    slots=[row.slot for row in rows if row.head==target.head]
    if any(slot<1 or slot>len(config.reviewer_models) for slot in slots): raise ReviewExecutionError("reviewer publication is outside configured slot range")
    if len(slots)!=len(set(slots)): raise ReviewExecutionError("duplicate reviewer publication for current head")
    return set(slots)
def reconcile_reviewers(config,target,rows,adapter,attempts):
    present=_review_slots(config,target,rows)
    return tuple(_review_slot(slot in present,semantic_key(config.swarm_id,target.issue,"review",slot=slot,head=target.head),reviewer_task_spec(config,target,slot),adapter,attempts[slot-1]) for slot in range(1,len(config.reviewer_models)+1))
def reconcile_adjudication(config,target,reviewers,rows,adapter,attempts):
    key=semantic_key(config.swarm_id,target.issue,"adjudication",head=target.head)
    if len(_review_slots(config,target,reviewers))!=len(config.reviewer_models): return SlotResult(SlotState.NOT_READY,key,reason="current head reviewer slots are incomplete")
    current=[row for row in rows if row.head==target.head]
    if len(current)>1: raise ReviewExecutionError("duplicate adjudication publications for current head")
    return _review_slot(bool(current),key,adjudicator_task_spec(config,target),adapter,attempts,True)


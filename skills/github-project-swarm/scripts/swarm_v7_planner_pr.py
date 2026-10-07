# Reduce one normalized exact-head PR observation; this module performs no I/O.
# Base freshness precedes CI, CI precedes review, and disputed reviews precede adjudication.
# Merge policy is applied only after current-head review/adjudication evidence is satisfied.
# Unknown mergeability remains distinct from a blocked merge.
from swarm_v7_model import Action, AdjudicationDecision, CiState, ExecutionState, MergeGate, Phase, ReviewState, _CI, _EXEC, _REVIEW, _STALL
def _merge(obs,config,reason):
    fixed={MergeGate.BLOCKED:(Phase.MERGE_BLOCKED,None,"merge authorization is blocked by current GitHub gates"),MergeGate.UNKNOWN:(_STALL,None,"merge gate state is unknown")}.get(obs.merge_gate)
    return fixed or {"manual":(Phase.AWAITING_MANUAL_MERGE,None,f"manual merge policy; {reason}"),"automatic":(Phase.READY_TO_MERGE,Action.MERGE,reason)}.get(config.merge_policy,(_STALL,None,"merge policy is unknown"))
def _first(rows):
    for condition,decision in rows:
        if condition: return decision
    return None
def _adjudication(obs,config):
    if obs.adjudication is ExecutionState.RUNNING: return Phase.ADJUDICATION_RUNNING,None,"adjudication is running"
    if obs.adjudication is ExecutionState.FAILED: return _STALL,None,"adjudication task failed"
    if obs.adjudication_decision is AdjudicationDecision.ACCEPT: return _merge(obs,config,"adjudication accepted current PR head")
    return {AdjudicationDecision.REVISE:(Phase.NEEDS_REVISION,Action.START_REVISION,"adjudication requires revision"),AdjudicationDecision.NONE:(Phase.NEEDS_ADJUDICATION,Action.START_ADJUDICATION,"review outcomes require adjudication")}.get(obs.adjudication_decision,(_STALL,None,"adjudication decision is unknown"))
def with_pr(obs,config):
    decision=_first(((obs.revision is ExecutionState.RUNNING,(Phase.REVISION_RUNNING,None,"revision task is running")),(obs.implementation in _EXEC,_EXEC.get(obs.implementation)),(obs.revision is ExecutionState.FAILED,(_STALL,None,"revision task failed")),(not obs.base_current,(Phase.NEEDS_REVISION,Action.START_REVISION,"current PR head does not contain the fresh default-branch base")),(config.ci_required and obs.ci in _CI,_CI.get(obs.ci)),(obs.review in _REVIEW,_REVIEW.get(obs.review))))
    if decision: return decision
    return _merge(obs,config,"review approved current PR head") if obs.review is not ReviewState.DISPUTED else _adjudication(obs,config)

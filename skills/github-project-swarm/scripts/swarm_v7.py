# Pure schema-7 workflow planner.
# One normalized observation produces one phase and at most one exact-head action.
# No I/O or persisted semantic outcome is consulted here.
from swarm_v7_model import Action, AdjudicationDecision, CiState, DependencyState, ExecutionState, ManifestV7, MergeGate, Observation, Phase, Plan, ReviewState, _CI, _DEP, _EXEC, _FORBIDDEN, _REVIEW, _SHA, _STALL

def _merge(obs,config,reason):
    fixed={MergeGate.BLOCKED:(Phase.MERGE_BLOCKED,None,"merge authorization is blocked by current GitHub gates"),MergeGate.UNKNOWN:(_STALL,None,"merge gate state is unknown")}.get(obs.merge_gate)
    return fixed or {"manual":(Phase.AWAITING_MANUAL_MERGE,None,f"manual merge policy; {reason}"),"automatic":(Phase.READY_TO_MERGE,Action.MERGE,reason)}.get(config.merge_policy,(_STALL,None,"merge policy is unknown"))
def _unsafe(obs):
    if obs.unsafe_reason: return _STALL,None,f"unsafe observation: {obs.unsafe_reason}"
    if obs.issue_number<=0: return _STALL,None,"issue number must be positive"
    if obs.pr_head is not None and not _SHA.fullmatch(obs.pr_head): return _STALL,None,"PR head must be an exact 40-character lowercase hex SHA"
    scoped=any((obs.ci is not CiState.NOT_APPLICABLE,obs.review is not ReviewState.NONE,obs.adjudication is not ExecutionState.IDLE,obs.adjudication_decision is not AdjudicationDecision.NONE,obs.revision is not ExecutionState.IDLE,not obs.base_current))
    return (_STALL,None,"PR-scoped evidence exists without a PR head") if obs.pr_head is None and scoped else None
def _first(rows):
    for condition,decision in rows:
        if condition: return decision
    return None
def _adjudication(obs,config):
    if obs.adjudication is ExecutionState.RUNNING: return Phase.ADJUDICATION_RUNNING,None,"adjudication is running"
    if obs.adjudication is ExecutionState.FAILED: return _STALL,None,"adjudication task failed"
    if obs.adjudication_decision is AdjudicationDecision.ACCEPT: return _merge(obs,config,"adjudication accepted current PR head")
    return {AdjudicationDecision.REVISE:(Phase.NEEDS_REVISION,Action.START_REVISION,"adjudication requires revision"),AdjudicationDecision.NONE:(Phase.NEEDS_ADJUDICATION,Action.START_ADJUDICATION,"review outcomes require adjudication")}.get(obs.adjudication_decision,(_STALL,None,"adjudication decision is unknown"))
def _with_pr(obs,config):
    decision=_first(((obs.revision is ExecutionState.RUNNING,(Phase.REVISION_RUNNING,None,"revision task is running")),(obs.implementation in _EXEC,_EXEC.get(obs.implementation)),(obs.revision is ExecutionState.FAILED,(_STALL,None,"revision task failed")),(not obs.base_current,(Phase.NEEDS_REVISION,Action.START_REVISION,"current PR head does not contain the fresh default-branch base")),(config.ci_required and obs.ci in _CI,_CI.get(obs.ci)),(obs.review in _REVIEW,_REVIEW.get(obs.review))))
    if decision: return decision
    return _merge(obs,config,"review approved current PR head") if obs.review is not ReviewState.DISPUTED else _adjudication(obs,config)
def _decision(obs,config):
    if bad:=_unsafe(obs): return bad
    if obs.issue_number not in config.issues: return _STALL,None,"issue is not configured for this swarm"
    if obs.merged: return Phase.MERGED,None,"pull request is merged and source issue is closed"
    if obs.merge_confirmed: return Phase.READY_TO_MERGE,Action.MERGE,"pull request is merged; source issue needs closure"
    if obs.dependency in _DEP: return _DEP[obs.dependency]
    if obs.pr_head is None: return _EXEC.get(obs.implementation,(Phase.NEEDS_IMPLEMENTATION,Action.START_IMPLEMENTATION,"no pull request exists"))
    return _with_pr(obs,config)
def plan_issue(obs:Observation,config:ManifestV7)->Plan:
    phase,action,reason=_decision(obs,config); intent=None if action is None else f"issue:{obs.issue_number}:{action.value.lower()}:{obs.pr_head or ''}".rstrip(":"); return Plan(phase,None,f"paused; would {action.value}: {reason}",obs.pr_head,intent,action) if config.paused and action else Plan(phase,action,reason,obs.pr_head,intent)


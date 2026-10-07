# Validate observation shape before selecting any phase or action.
# Issue membership and GitHub-confirmed merge/dependency facts precede execution liveness.
# A PR-scoped fact without an exact PR head is unsafe, never a best-effort transition.
# The no-PR path consults implementation liveness only.
from swarm_v7_model import AdjudicationDecision, CiState, DependencyState, ExecutionState, Phase, Action, ReviewState, _DEP, _EXEC, _SHA, _STALL
from swarm_v7_planner_pr import with_pr
def _unsafe(obs):
    if obs.unsafe_reason: return _STALL,None,f"unsafe observation: {obs.unsafe_reason}"
    if obs.issue_number<=0: return _STALL,None,"issue number must be positive"
    if obs.pr_head is not None and not _SHA.fullmatch(obs.pr_head): return _STALL,None,"PR head must be an exact 40-character lowercase hex SHA"
    scoped=any((obs.ci is not CiState.NOT_APPLICABLE,obs.review is not ReviewState.NONE,obs.adjudication is not ExecutionState.IDLE,obs.adjudication_decision is not AdjudicationDecision.NONE,obs.revision is not ExecutionState.IDLE,not obs.base_current))
    return (_STALL,None,"PR-scoped evidence exists without a PR head") if obs.pr_head is None and scoped else None
def decide(obs,config):
    if bad:=_unsafe(obs): return bad
    if obs.issue_number not in config.issues: return _STALL,None,"issue is not configured for this swarm"
    if obs.merged: return Phase.MERGED,None,"pull request is merged and source issue is closed"
    if obs.merge_confirmed: return Phase.READY_TO_MERGE,Action.MERGE,"pull request is merged; source issue needs closure"
    if obs.dependency in _DEP: return _DEP[obs.dependency]
    if obs.pr_head is None: return _EXEC.get(obs.implementation,(Phase.NEEDS_IMPLEMENTATION,Action.START_IMPLEMENTATION,"no pull request exists"))
    return with_pr(obs,config)

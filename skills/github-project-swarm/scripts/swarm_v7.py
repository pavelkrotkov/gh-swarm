# Stable public schema-7 planning API.
# The planner delegates only to pure reducers and never performs I/O.
from swarm_v7_manifest import ManifestV7
from swarm_v7_manifest_parse import _FORBIDDEN
from swarm_v7_model import Action, AdjudicationDecision, CiState, DependencyState, ExecutionState, MergeGate, Observation, Phase, Plan, ReviewState
from swarm_v7_planner_decision import decide
def plan_issue(obs:Observation,config:ManifestV7)->Plan:
    phase,action,reason=decide(obs,config); intent=None if action is None else f"issue:{obs.issue_number}:{action.value.lower()}:{obs.pr_head or ''}".rstrip(":"); return Plan(phase,None,f"paused; would {action.value}: {reason}",obs.pr_head,intent,action) if config.paused and action else Plan(phase,action,reason,obs.pr_head,intent)

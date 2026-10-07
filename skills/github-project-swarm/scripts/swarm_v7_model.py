# Planner evidence is normalized before any phase/action decision is made.
# Enums distinguish missing/unknown evidence from negative evidence; callers must not collapse them.
# Observation contains fresh external facts only and carries no local acceptance/completion cache.
# Decision tables below encode precedence but perform no I/O.
from dataclasses import dataclass
from enum import Enum
import re
def _enum(name,values): return Enum(name,{v:v for v in values.split()},type=str)
Phase=_enum("Phase","MERGED WAITING_DEPENDENCY NEEDS_IMPLEMENTATION IMPLEMENTATION_RUNNING WAITING_CI NEEDS_REVIEW REVIEW_RUNNING NEEDS_ADJUDICATION ADJUDICATION_RUNNING NEEDS_REVISION REVISION_RUNNING AWAITING_MANUAL_MERGE READY_TO_MERGE MERGE_BLOCKED EXECUTION_STALLED"); Action=_enum("Action","START_IMPLEMENTATION START_REVIEW START_ADJUDICATION START_REVISION MERGE"); DependencyState=_enum("DependencyState","READY BLOCKED UNKNOWN"); ExecutionState=_enum("ExecutionState","IDLE RUNNING FAILED"); CiState=_enum("CiState","NOT_APPLICABLE PENDING PASSED FAILED UNKNOWN"); ReviewState=_enum("ReviewState","NONE RUNNING APPROVED CHANGES_REQUESTED DISPUTED UNKNOWN"); AdjudicationDecision=_enum("AdjudicationDecision","NONE ACCEPT REVISE UNKNOWN"); MergeGate=_enum("MergeGate","READY BLOCKED UNKNOWN")
@dataclass(frozen=True)
class Observation:
    issue_number:int; merged:bool=False; dependency:DependencyState=DependencyState.READY; pr_head:str|None=None; implementation:ExecutionState=ExecutionState.IDLE; ci:CiState=CiState.NOT_APPLICABLE; review:ReviewState=ReviewState.NONE; adjudication:ExecutionState=ExecutionState.IDLE; adjudication_decision:AdjudicationDecision=AdjudicationDecision.NONE; revision:ExecutionState=ExecutionState.IDLE; merge_gate:MergeGate=MergeGate.READY; merge_confirmed:bool=False; unsafe_reason:str|None=None; base_current:bool=True
@dataclass(frozen=True)
class Plan:
    phase:Phase; action:Action|None; reason:str; pr_head:str|None; intent_key:str|None; would_action:Action|None=None
_STALL=Phase.EXECUTION_STALLED; _SHA=re.compile(r"^[0-9a-f]{40}$"); _DEP={DependencyState.BLOCKED:(Phase.WAITING_DEPENDENCY,None,"a dependency is not merged"),DependencyState.UNKNOWN:(_STALL,None,"dependency state is unknown")}; _EXEC={ExecutionState.RUNNING:(Phase.IMPLEMENTATION_RUNNING,None,"implementation task is running"),ExecutionState.FAILED:(_STALL,None,"implementation task failed")}; _CI={CiState.UNKNOWN:(_STALL,None,"required CI state is unknown"),CiState.NOT_APPLICABLE:(_STALL,None,"required CI state is unknown"),CiState.PENDING:(Phase.WAITING_CI,None,"required CI is pending"),CiState.FAILED:(Phase.NEEDS_REVISION,Action.START_REVISION,"required CI failed")}; _REVIEW={ReviewState.NONE:(Phase.NEEDS_REVIEW,Action.START_REVIEW,"current PR head has no completed review"),ReviewState.RUNNING:(Phase.REVIEW_RUNNING,None,"review is running for current PR head"),ReviewState.CHANGES_REQUESTED:(Phase.NEEDS_REVISION,Action.START_REVISION,"review requested changes"),ReviewState.UNKNOWN:(_STALL,None,"review state is unknown")}


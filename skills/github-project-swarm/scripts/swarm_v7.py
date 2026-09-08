# Schema-7 configuration and pure workflow planning.
# The manifest stores operator configuration only; semantic GitHub truth is reconstructed.
# The planner receives one normalized observation and emits one exact-head action intent.
# Neither layer performs I/O or restores semantic outcome from local state.
from dataclasses import dataclass
from enum import Enum
import re
_FORBIDDEN=frozenset("state finished completed completion acceptance accepted current_task review round repairs ci_head edges dependencies".split()); _ALLOWED={"schema","id","repo","default_branch","issues","models","ci_mode","no_merge_labels","paused"}; _DEFAULT_LABELS=("no-merge","do-not-merge","hold-merge")
def _need(ok,message):
    if not ok: raise ValueError(message)
def _text(value,name): _need(isinstance(value,str) and bool(value.strip()),f"{name} must be a non-empty string"); return value
def _items(value,message,required=True): _need(isinstance(value,(list,tuple)) and (bool(value) or not required),message); return tuple(value)
@dataclass(frozen=True)
class ManifestV7:
    swarm_id:str; repo:str; default_branch:str; issues:tuple[int,...]; worker_model:str; reviewer_models:tuple[str,...]; adjudicator_model:str; ci_required:bool=True; no_merge_labels:tuple[str,...]=_DEFAULT_LABELS; paused:bool=False; schema:int=7
    @classmethod
    def from_dict(cls,raw):
        _need(not (bad:=set(raw)&_FORBIDDEN),f"schema 7 forbids semantic state keys: {sorted(bad)}"); _need(not (bad:=set(raw)-_ALLOWED),f"unknown schema-7 manifest keys: {sorted(bad)}"); _need(raw.get("schema")==7,"schema must be 7")
        models=raw.get("models"); _need(isinstance(models,dict),"models must be a mapping"); _need(set(models)=={"worker","reviewers","adjudicator"},"models must contain only worker, reviewers, and adjudicator")
        reviewers=tuple(_text(v,"models.reviewers") for v in _items(models.get("reviewers"),"reviewer models must be a non-empty sequence")); worker=_text(models.get("worker"),"models.worker"); adjudicator=_text(models.get("adjudicator"),"models.adjudicator")
        mode=raw.get("ci_mode","required"); _need(mode in {"required","none"},"ci_mode must be 'required' or 'none'"); labels=_items(raw.get("no_merge_labels",_DEFAULT_LABELS),"no_merge_labels must be a sequence of non-empty strings",False); _need(all(isinstance(x,str) and bool(x) for x in labels),"no_merge_labels must be a sequence of non-empty strings")
        paused=raw.get("paused",False); _need(isinstance(paused,bool),"paused must be boolean"); identity=tuple(_text(raw.get(name),name) for name in ("id","repo","default_branch")); issues=_items(raw.get("issues"),"issues must be a non-empty sequence"); _need(all(type(x) is int and x>0 for x in issues),"issues must contain positive integers")
        return cls(*identity,issues,worker,reviewers,adjudicator,mode=="required",labels,paused)
    def to_dict(self): return {"schema":7,"id":self.swarm_id,"repo":self.repo,"default_branch":self.default_branch,"issues":list(self.issues),"models":{"worker":self.worker_model,"reviewers":list(self.reviewer_models),"adjudicator":self.adjudicator_model},"ci_mode":"required" if self.ci_required else "none","no_merge_labels":list(self.no_merge_labels),"paused":self.paused}
def _enum(name,values): return Enum(name,{v:v for v in values.split()},type=str)
Phase=_enum("Phase","MERGED WAITING_DEPENDENCY NEEDS_IMPLEMENTATION IMPLEMENTATION_RUNNING WAITING_CI NEEDS_REVIEW REVIEW_RUNNING NEEDS_ADJUDICATION ADJUDICATION_RUNNING NEEDS_REVISION REVISION_RUNNING READY_TO_MERGE EXECUTION_STALLED"); Action=_enum("Action","START_IMPLEMENTATION START_REVIEW START_ADJUDICATION START_REVISION MERGE"); DependencyState=_enum("DependencyState","READY BLOCKED UNKNOWN"); ExecutionState=_enum("ExecutionState","IDLE RUNNING FAILED"); CiState=_enum("CiState","NOT_APPLICABLE PENDING PASSED FAILED UNKNOWN"); ReviewState=_enum("ReviewState","NONE RUNNING APPROVED CHANGES_REQUESTED DISPUTED UNKNOWN"); AdjudicationDecision=_enum("AdjudicationDecision","NONE ACCEPT REVISE UNKNOWN"); MergeGate=_enum("MergeGate","READY BLOCKED UNKNOWN")
@dataclass(frozen=True)
class Observation:
    issue_number:int; merged:bool=False; dependency:DependencyState=DependencyState.READY; pr_head:str|None=None; implementation:ExecutionState=ExecutionState.IDLE; ci:CiState=CiState.NOT_APPLICABLE; review:ReviewState=ReviewState.NONE; adjudication:ExecutionState=ExecutionState.IDLE; adjudication_decision:AdjudicationDecision=AdjudicationDecision.NONE; revision:ExecutionState=ExecutionState.IDLE; merge_gate:MergeGate=MergeGate.READY; merge_confirmed:bool=False; unsafe_reason:str|None=None
@dataclass(frozen=True)
class Plan:
    phase:Phase; action:Action|None; reason:str; pr_head:str|None; intent_key:str|None; would_action:Action|None=None
_STALL=Phase.EXECUTION_STALLED; _SHA=re.compile(r"^[0-9a-f]{40}$"); _DEP={DependencyState.BLOCKED:(Phase.WAITING_DEPENDENCY,None,"a dependency is not merged"),DependencyState.UNKNOWN:(_STALL,None,"dependency state is unknown")}; _EXEC={ExecutionState.RUNNING:(Phase.IMPLEMENTATION_RUNNING,None,"implementation task is running"),ExecutionState.FAILED:(_STALL,None,"implementation task failed")}; _CI={CiState.UNKNOWN:(_STALL,None,"required CI state is unknown"),CiState.NOT_APPLICABLE:(_STALL,None,"required CI state is unknown"),CiState.PENDING:(Phase.WAITING_CI,None,"required CI is pending"),CiState.FAILED:(Phase.NEEDS_REVISION,Action.START_REVISION,"required CI failed")}; _REVIEW={ReviewState.NONE:(Phase.NEEDS_REVIEW,Action.START_REVIEW,"current PR head has no completed review"),ReviewState.RUNNING:(Phase.REVIEW_RUNNING,None,"review is running for current PR head"),ReviewState.CHANGES_REQUESTED:(Phase.NEEDS_REVISION,Action.START_REVISION,"review requested changes"),ReviewState.UNKNOWN:(_STALL,None,"review state is unknown")}
def _merge(obs,reason):
    fixed={MergeGate.BLOCKED:"merge gate blocks the current PR head",MergeGate.UNKNOWN:"merge gate state is unknown"}.get(obs.merge_gate); return (_STALL,None,fixed) if fixed else (Phase.READY_TO_MERGE,Action.MERGE,reason)
def _unsafe(obs):
    if obs.unsafe_reason: return _STALL,None,f"unsafe observation: {obs.unsafe_reason}"
    if obs.issue_number<=0: return _STALL,None,"issue number must be positive"
    if obs.pr_head is not None and not _SHA.fullmatch(obs.pr_head): return _STALL,None,"PR head must be an exact 40-character lowercase hex SHA"
    scoped=any((obs.ci is not CiState.NOT_APPLICABLE,obs.review is not ReviewState.NONE,obs.adjudication is not ExecutionState.IDLE,obs.adjudication_decision is not AdjudicationDecision.NONE,obs.revision is not ExecutionState.IDLE)); return (_STALL,None,"PR-scoped evidence exists without a PR head") if obs.pr_head is None and scoped else None
def _with_pr(obs,config):
    for condition,decision in ((obs.revision is ExecutionState.RUNNING,(Phase.REVISION_RUNNING,None,"revision task is running")),(obs.implementation in _EXEC,_EXEC.get(obs.implementation)),(obs.revision is ExecutionState.FAILED,(_STALL,None,"revision task failed")),(config.ci_required and obs.ci in _CI,_CI.get(obs.ci)),(obs.review in _REVIEW,_REVIEW.get(obs.review))):
        if condition: return decision
    if obs.review is not ReviewState.DISPUTED: return _merge(obs,"review approved current PR head")
    if obs.adjudication is ExecutionState.RUNNING: return Phase.ADJUDICATION_RUNNING,None,"adjudication is running"
    if obs.adjudication is ExecutionState.FAILED: return _STALL,None,"adjudication task failed"
    if obs.adjudication_decision is AdjudicationDecision.ACCEPT: return _merge(obs,"adjudication accepted current PR head")
    return {AdjudicationDecision.REVISE:(Phase.NEEDS_REVISION,Action.START_REVISION,"adjudication requires revision"),AdjudicationDecision.NONE:(Phase.NEEDS_ADJUDICATION,Action.START_ADJUDICATION,"review outcomes require adjudication")}.get(obs.adjudication_decision,(_STALL,None,"adjudication decision is unknown"))
def _decision(obs,config):
    bad=_unsafe(obs)
    if bad: return bad
    if obs.issue_number not in config.issues: return _STALL,None,"issue is not configured for this swarm"
    if obs.merged: return Phase.MERGED,None,"pull request is merged and source issue is closed"
    if obs.merge_confirmed: return Phase.READY_TO_MERGE,Action.MERGE,"pull request is merged; source issue needs closure"
    if obs.dependency in _DEP: return _DEP[obs.dependency]
    if obs.pr_head is None: return _EXEC.get(obs.implementation,(Phase.NEEDS_IMPLEMENTATION,Action.START_IMPLEMENTATION,"no pull request exists"))
    return _with_pr(obs,config)
def plan_issue(obs:Observation,config:ManifestV7)->Plan:
    phase,action,reason=_decision(obs,config); intent=None if action is None else f"issue:{obs.issue_number}:{action.value.lower()}:{obs.pr_head or ''}".rstrip(":"); return Plan(phase,None,f"paused; would {action.value}: {reason}",obs.pr_head,intent,action) if config.paused and action else Plan(phase,action,reason,obs.pr_head,intent)

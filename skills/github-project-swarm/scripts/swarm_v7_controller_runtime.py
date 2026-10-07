# Fresh observation and execution-liveness projection for the single controller plan.
# GitHub supplies semantic truth; persisted cursors identify bounded attempts only.
# Local workspace/Kanban failures become unsafe planner input rather than semantic completion.
from collections import namedtuple
from dataclasses import dataclass,field,replace
import time
from swarm_v7 import AdjudicationDecision, DependencyState, ExecutionState, ManifestV7, ReviewState, plan_issue
from swarm_v7_workspace import GitWorkspace, branch_name
from swarm_v7_github import GhReader, observe_issue as observe_github
from swarm_v7_kanban import KanbanAdapter, Outcome, semantic_key
_CONFIG={"schema","id","repo","default_branch","issues","models","ci_mode","no_merge_labels","paused","merge_policy"}; _STARTUP_GRACE_S=300
def _need(ok,message):
    if not ok: raise ValueError(message)
def _retired(value): _need(isinstance(value,dict),"retired_issues must be a mapping"); _need(all(str(issue).isdigit() and int(issue)>0 and isinstance(reason,str) and bool(reason.strip()) for issue,reason in value.items()),"retired_issues must map positive issue numbers to non-empty reasons"); return {str(issue):reason for issue,reason in value.items()}
def _runtime_values(data):
    rt=data.get("runtime"); _need(isinstance(rt,dict),"schema-7 runtime configuration is missing"); repo_path,board,assignee=(str(rt.get(key) or "").strip() for key in ("repo_path","board","assignee")); attempts=int(rt.get("max_execution_attempts",2)); cursors=rt.get("execution_cursors",{}); runtime=str(rt.get("max_runtime","30m")).strip(); retired=_retired(rt.get("retired_issues",{})); _need(bool(repo_path and board and assignee),"invalid schema-7 runtime configuration: repo_path/board/assignee is required"); _need(attempts>0,"invalid schema-7 runtime configuration: max_execution_attempts must be positive"); _need(isinstance(cursors,dict),"execution_cursors must be a mapping"); _need(bool(runtime),"invalid schema-7 runtime configuration: max_runtime is required"); return repo_path,board,assignee,attempts,runtime,dict(cursors),retired
@dataclass
class RuntimeManifest:
    config:ManifestV7; repo_path:str; board:str; assignee:str; max_attempts:int; max_runtime:str; cursors:dict; retired_issues:dict=field(default_factory=dict)
    @classmethod
    def from_dict(cls,raw): data=dict(raw); _need(data.get("schema")==7,f"unsupported swarm schema {data.get('schema')!r}; v7 does not migrate schema 5/6 manifests; initialize a fresh schema-7 swarm"); bad=set(data)-(_CONFIG|{"runtime"}); _need(not bad,f"schema-7 runtime manifest forbids legacy/unknown fields: {sorted(bad)}"); return cls(ManifestV7.from_dict({key:data[key] for key in _CONFIG if key in data}),*_runtime_values(data))
    def to_dict(self): return {**self.config.to_dict(),"runtime":{"repo_path":self.repo_path,"board":self.board,"assignee":self.assignee,"max_execution_attempts":self.max_attempts,"max_runtime":self.max_runtime,"execution_cursors":self.cursors,"retired_issues":self.retired_issues}}
IssueObservation=namedtuple("IssueObservation","github planner execution"); PlannedIssue=namedtuple("PlannedIssue","observation plan"); ActionResult=namedtuple("ActionResult","outcome task_ids detail",defaults=((),"")); ExecutionContext=namedtuple("ExecutionContext","runtime observed reader kanban workspace merger")
def _starved(facts,cursor): return facts.outcome is Outcome.ACTIVE and not facts.has_run and ((age:=time.time()-float(cursor.get("created_at") or 0))<0 or age>=_STARTUP_GRACE_S)
def _attempts(runtime,key,status=""): _need(runtime.max_attempts>0,"max_execution_attempts must be positive"); cursor=runtime.cursors.get(key); used=int(cursor.get("attempt") or 0) if isinstance(cursor,dict) else 0; return range(max(1,used),max(runtime.max_attempts,used+(1 if status.startswith("blocked:") else 0))+1)
def _publication_outcome(required,outcome,attempt,limit): return (Outcome.FAILURE,attempt) if required and outcome is Outcome.SUCCESS else (outcome,limit)
def _slot(runtime,key,kanban,execution,publication_required=False):
    cursor=runtime.cursors.get(key)
    if not isinstance(cursor,dict) or not cursor.get("task_id"): return ExecutionState.IDLE,None
    attempt=int(cursor.get("attempt") or 1); facts=kanban.observe(str(cursor["task_id"])); execution[key]=f"{facts.status}:a{attempt}"; outcome,limit=_publication_outcome(publication_required,facts.outcome,attempt,runtime.max_attempts)
    if _starved(facts,cursor): return ExecutionState.FAILED,f"execution task {facts.task_id} has no worker run after {_STARTUP_GRACE_S}s startup grace"
    if outcome in {Outcome.ACTIVE,Outcome.SUCCESS}: return {Outcome.ACTIVE:ExecutionState.RUNNING,Outcome.SUCCESS:ExecutionState.IDLE}[outcome],None
    return (ExecutionState.FAILED,f"execution attempts exhausted for {key}") if all((attempt>=limit,facts.status!="blocked")) else (ExecutionState.IDLE,None)
def _reviews(runtime,github,kanban,execution):
    pr=github.pull_request; present=set(map(lambda row:row.slot,pr.reviewers)); missing=set(range(1,len(runtime.config.reviewer_models)+1))-present
    if not missing: return ReviewState.DISPUTED,None
    rows=[_slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"review",slot=slot,head=pr.head),kanban,execution,True) for slot in sorted(missing)]; unsafe=next(filter(None,(reason for _,reason in rows)),None)
    if unsafe: return ReviewState.UNKNOWN,unsafe
    return (ReviewState.RUNNING if any(state is ExecutionState.RUNNING for state,_ in rows) else ReviewState.NONE),None
def _overlay(runtime,github,kanban,execution):
    if github.pull_request is None:
        state,unsafe=_slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"implementation"),kanban,execution)
        if unsafe: raise RuntimeError(unsafe)
        return replace(github.planner,implementation=state)
    pr=github.pull_request; review,unsafe=_reviews(runtime,github,kanban,execution); adjudication,a_bad=(ExecutionState.IDLE,None) if github.planner.adjudication_decision in {AdjudicationDecision.ACCEPT,AdjudicationDecision.REVISE} else _slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"adjudication",head=pr.head),kanban,execution); revision,r_bad=_slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"revision",head=pr.head),kanban,execution); return replace(github.planner,review=review,adjudication=adjudication,revision=revision,unsafe_reason=unsafe or a_bad or r_bad or github.planner.unsafe_reason)
def _base_current(runtime,github,workspace):
    if (pr:=github.pull_request) is None or github.planner.dependency is not DependencyState.READY: return True
    workspace.validate_binding(runtime.config.repo); default=workspace.refresh(runtime.config.default_branch,branch_name(runtime.config.swarm_id,github.issue_number))[0]; return workspace.ancestor(default,pr.head)
def _default(value,factory): return factory() if value is None else value
def observe_issue(runtime,issue_number,*,reader=None,kanban=None,workspace=None):
    github=observe_github(replace(runtime.config,issues=runtime.config.issues+tuple(map(int,runtime.retired_issues))),issue_number,_default(reader,GhReader))
    if github.unsafe_reason or getattr(github.pull_request,"merged_at",None): return IssueObservation(github,github.planner,{})
    execution={}; actual_workspace=_default(workspace,lambda:GitWorkspace(runtime.repo_path))
    try: planner=_overlay(runtime,github,_default(kanban,lambda:KanbanAdapter(runtime.board,runtime.repo_path)),execution); planner=replace(planner,base_current=_base_current(runtime,github,actual_workspace))
    except Exception as exc: planner=replace(github.planner,unsafe_reason=f"execution observation failed: {exc}")
    return IssueObservation(github,planner,execution)
def plan_once(runtime,issue_number,*,reader=None,kanban=None,workspace=None,planner=plan_issue): observed=observe_issue(runtime,issue_number,reader=reader,kanban=kanban,workspace=workspace); return PlannedIssue(observed,planner(observed.planner,runtime.config))
def plan_payload(plan): return {"phase":plan.phase.value,"action":plan.action.value if plan.action else None,"would_action":plan.would_action.value if plan.would_action else None,"reason":plan.reason,"pr_head":plan.pr_head,"intent_key":plan.intent_key}
def _config_gates(config,pr): held=() if pr is None else tuple(sorted(set(pr.labels)&{x.lower() for x in config.no_merge_labels})); return (("paused","operator pause" if config.paused else None),("manual_merge_mode","manual" if config.merge_policy=="manual" else None),("hold_label",",".join(held)))
def _planner_gates(observed,config): planner=observed.planner; github=observed.github; dep={"BLOCKED":"dependency_wait","UNKNOWN":"dependency_unknown"}.get(planner.dependency.value); ci={"UNKNOWN":"ci_missing_evidence","PENDING":"ci_pending","FAILED":"ci_failed"}.get(planner.ci.value) if config.ci_required else None; review={"NONE":"review_missing","RUNNING":"review_pending","CHANGES_REQUESTED":"review_changes","UNKNOWN":"review_unknown"}.get(planner.review.value) if github.pull_request is not None else None; adjudication={"NONE":"adjudication_pending","REVISE":"adjudication_revision","UNKNOWN":"adjudication_unknown"}.get(planner.adjudication_decision.value) if planner.review is ReviewState.DISPUTED else None; return (("observation_failure",github.unsafe_reason),("execution_failure",planner.unsafe_reason if planner.unsafe_reason and not github.unsafe_reason else None),(dep,{"dependency_wait":"blocked","dependency_unknown":"unknown"}.get(dep)),(ci,{"ci_missing_evidence":"unknown","ci_pending":"pending","ci_failed":"failed"}.get(ci)),(review,planner.review.value.lower()),(adjudication,planner.adjudication_decision.value.lower()))
def _shape_gates(config,pr,planner): return () if pr is None else (("stale_base","current PR head misses fresh default branch" if not planner.base_current else None),("pr_not_open",pr.state if pr.state!="OPEN" else None),("draft","true" if pr.draft else None),("wrong_base",pr.base if pr.base!=config.default_branch else None))
def _mergeability_gates(pr): return () if pr is None else (("mergeability_unknown",pr.merge_state if pr.mergeable is None or pr.merge_state in {"","UNKNOWN"} else None),("mergeability_blocked",pr.merge_state if pr.mergeable is False or pr.merge_state not in {"CLEAN","UNSTABLE","","UNKNOWN"} else None))
def _pull_payload(pr):
    if pr is None: return None
    return {"number":pr.number,"url":pr.url,"head":pr.head,"base":pr.base,"state":pr.state,"draft":pr.draft,"merged_at":pr.merged_at,"merge_sha":getattr(pr,"merge_sha",None)}
def observation_payload(observed,config):
    pr=observed.github.pull_request; planner=observed.planner
    raw=() if pr is not None and pr.merged_at else (*_config_gates(config,pr),*_planner_gates(observed,config),*_shape_gates(config,pr,planner),*_mergeability_gates(pr))
    gates=[{"code":code,"detail":str(detail)} for code,detail in raw if code and detail]
    blockers=[{"issue":row.issue_number,"state":row.state,"internal":row.internal,"merged_at":row.merged_at} for row in observed.github.blockers]
    return {"issue_state":observed.github.issue_state,"blockers":blockers,"pr":_pull_payload(pr),"execution":dict(observed.execution),"base_current":planner.base_current,"unsafe_reason":planner.unsafe_reason,"gates":gates}

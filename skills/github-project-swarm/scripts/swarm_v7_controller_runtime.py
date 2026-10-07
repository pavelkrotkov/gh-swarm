# Kanban state is execution liveness only; durable GitHub publications decide semantic completion.
# Startup grace is restart-safe because creation time is persisted with the attempt cursor.
# Review slots are exact-head keyed; task success without publication remains failed evidence.
# Retry extension applies only to blocked attempts under the same semantic identity.
# Fresh GitHub authority is overlaid with execution liveness and Git ancestry before pure planning.
# Dependency readiness precedes base ancestry; merged/unsafe observations bypass local execution reads.
# Adapter failures become one unsafe observation reason rather than partial local truth.
# plan_once is the sole observe-to-plan handoff used by views and live reconcile.
from collections import namedtuple
from dataclasses import replace
import time
from swarm_v7 import AdjudicationDecision,DependencyState,ExecutionState,ReviewState,plan_issue
from swarm_v7_workspace import GitWorkspace,branch_name
from swarm_v7_github import GhReader,observe_issue as observe_github
from swarm_v7_kanban import KanbanAdapter,Outcome,semantic_key
IssueObservation=namedtuple("IssueObservation","github planner execution"); PlannedIssue=namedtuple("PlannedIssue","observation plan"); ActionResult=namedtuple("ActionResult","outcome task_ids detail",defaults=((),"")); ExecutionContext=namedtuple("ExecutionContext","runtime observed reader kanban workspace merger")
def _need(ok,message):
    if not ok: raise ValueError(message)
_STARTUP_GRACE_S=300
def _default(value,factory): return factory() if value is None else value
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
def observe_issue(runtime,issue_number,*,reader=None,kanban=None,workspace=None):
    github=observe_github(replace(runtime.config,issues=runtime.config.issues+tuple(map(int,runtime.retired_issues))),issue_number,_default(reader,GhReader))
    if github.unsafe_reason or getattr(github.pull_request,"merged_at",None): return IssueObservation(github,github.planner,{})
    execution={}; actual_workspace=_default(workspace,lambda:GitWorkspace(runtime.repo_path))
    try: planner=_overlay(runtime,github,_default(kanban,lambda:KanbanAdapter(runtime.board,runtime.repo_path)),execution); planner=replace(planner,base_current=_base_current(runtime,github,actual_workspace))
    except Exception as exc: planner=replace(github.planner,unsafe_reason=f"execution observation failed: {exc}")
    return IssueObservation(github,planner,execution)
def plan_once(runtime,issue_number,*,reader=None,kanban=None,workspace=None,planner=plan_issue): observed=observe_issue(runtime,issue_number,reader=reader,kanban=kanban,workspace=workspace); return PlannedIssue(observed,planner(observed.planner,runtime.config))

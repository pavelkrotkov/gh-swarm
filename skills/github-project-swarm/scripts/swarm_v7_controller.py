# Fresh GitHub observation, Kanban liveness, pure planning, and one selected side effect.
# GitHub owns semantic truth; cursors identify attempts only and are re-observed after restart.
# Execution may prepare worktrees or launch bounded tasks, but completion never becomes
# approval, merge completion, dependency release, or other semantic workflow state.
from collections import namedtuple
from dataclasses import dataclass, replace
from pathlib import Path; import time
from swarm_v7 import Action, AdjudicationDecision, ExecutionState, ManifestV7, ReviewState, plan_issue
from swarm_v7_github import GhReader, observe_issue as observe_github
from swarm_v7_kanban import KanbanAdapter, Outcome, TaskSpec, semantic_key, worker_body
from swarm_v7_merge import GhMerger, request_exact_head_merge
from swarm_v7_review import ExactHeadTarget, _model, reconcile_adjudication, reconcile_reviewers
from swarm_v7_workspace import GitWorkspace, WorkspaceSpec, branch_name, worktree_path
_CONFIG={"schema","id","repo","default_branch","issues","models","ci_mode","no_merge_labels","paused"}; _STARTUP_GRACE_S=300
def _need(ok,message):
    if not ok: raise ValueError(message)
def _runtime_values(data):
    rt=data.get("runtime"); _need(isinstance(rt,dict),"schema-7 runtime configuration is missing"); repo_path,board,assignee=(str(rt.get(key) or "").strip() for key in ("repo_path","board","assignee")); attempts=int(rt.get("max_execution_attempts",2)); cursors=rt.get("execution_cursors",{}); runtime=str(rt.get("max_runtime","30m")).strip(); _need(bool(repo_path and board and assignee),"invalid schema-7 runtime configuration: repo_path/board/assignee is required"); _need(attempts>0,"invalid schema-7 runtime configuration: max_execution_attempts must be positive"); _need(isinstance(cursors,dict),"execution_cursors must be a mapping"); _need(bool(runtime),"invalid schema-7 runtime configuration: max_runtime is required"); return repo_path,board,assignee,attempts,runtime,dict(cursors)
@dataclass
class RuntimeManifest:
    config:ManifestV7; repo_path:str; board:str; assignee:str; max_attempts:int; max_runtime:str; cursors:dict
    @classmethod
    def from_dict(cls,raw):
        data=dict(raw); _need(data.get("schema")==7,f"unsupported swarm schema {data.get('schema')!r}; v7 does not migrate schema 5/6 manifests; initialize a fresh schema-7 swarm"); bad=set(data)-(_CONFIG|{"runtime"}); _need(not bad,f"schema-7 runtime manifest forbids legacy/unknown fields: {sorted(bad)}"); return cls(ManifestV7.from_dict({key:data[key] for key in _CONFIG if key in data}),*_runtime_values(data))
    def to_dict(self): return {**self.config.to_dict(),"runtime":{"repo_path":self.repo_path,"board":self.board,"assignee":self.assignee,"max_execution_attempts":self.max_attempts,"max_runtime":self.max_runtime,"execution_cursors":self.cursors}}
IssueObservation=namedtuple("IssueObservation","github planner execution"); PlannedIssue=namedtuple("PlannedIssue","observation plan"); ActionResult=namedtuple("ActionResult","outcome task_ids detail",defaults=((),"")); ExecutionContext=namedtuple("ExecutionContext","runtime observed reader kanban workspace merger")
def _starved(facts,cursor):
    age=time.time()-float(cursor.get("created_at") or 0); return facts.outcome is Outcome.ACTIVE and not facts.has_run and (age<0 or age>=_STARTUP_GRACE_S)
def _slot(runtime,key,kanban,execution):
    cursor=runtime.cursors.get(key)
    if not isinstance(cursor,dict) or not cursor.get("task_id"): return ExecutionState.IDLE,None
    attempt=int(cursor.get("attempt") or 1); facts=kanban.observe(str(cursor["task_id"])); execution[key]=f"{facts.status}:a{attempt}"
    if _starved(facts,cursor): return ExecutionState.FAILED,f"execution task {facts.task_id} has no worker run after {_STARTUP_GRACE_S}s startup grace"
    if facts.outcome in {Outcome.ACTIVE,Outcome.SUCCESS}: return {Outcome.ACTIVE:ExecutionState.RUNNING,Outcome.SUCCESS:ExecutionState.IDLE}[facts.outcome],None
    return (ExecutionState.FAILED,f"execution attempts exhausted for {key}") if attempt>=runtime.max_attempts else (ExecutionState.IDLE,None)
def _reviews(runtime,github,kanban,execution):
    pr=github.pull_request; present=set(map(lambda row:row.slot,pr.reviewers)); missing=set(range(1,len(runtime.config.reviewer_models)+1))-present
    if not missing: return ReviewState.DISPUTED,None
    rows=[_slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"review",slot=slot,head=pr.head),kanban,execution) for slot in sorted(missing)]; unsafe=next(filter(None,(reason for _,reason in rows)),None)
    if unsafe: return ReviewState.UNKNOWN,unsafe
    return (ReviewState.RUNNING if any(state is ExecutionState.RUNNING for state,_ in rows) else ReviewState.NONE),None
def _overlay(runtime,github,kanban,execution):
    if github.pull_request is None:
        state,unsafe=_slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"implementation"),kanban,execution)
        if unsafe: raise RuntimeError(unsafe)
        return replace(github.planner,implementation=state)
    pr=github.pull_request; review,unsafe=_reviews(runtime,github,kanban,execution); adjudication,a_bad=(ExecutionState.IDLE,None) if github.planner.adjudication_decision in {AdjudicationDecision.ACCEPT,AdjudicationDecision.REVISE} else _slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"adjudication",head=pr.head),kanban,execution); revision,r_bad=_slot(runtime,semantic_key(runtime.config.swarm_id,github.issue_number,"revision",head=pr.head),kanban,execution); return replace(github.planner,review=review,adjudication=adjudication,revision=revision,unsafe_reason=unsafe or a_bad or r_bad or github.planner.unsafe_reason)
def observe_issue(runtime,issue_number,*,reader=None,kanban=None):
    github=observe_github(runtime.config,issue_number,reader if reader is not None else GhReader())
    if github.unsafe_reason or getattr(github.pull_request,"merged_at",None): return IssueObservation(github,github.planner,{})
    execution={}
    try: planner=_overlay(runtime,github,kanban if kanban is not None else KanbanAdapter(runtime.board,runtime.repo_path),execution)
    except Exception as exc: planner=replace(github.planner,unsafe_reason=f"execution observation failed: {exc}")
    return IssueObservation(github,planner,execution)
def plan_once(runtime,issue_number,*,reader=None,kanban=None,planner=plan_issue):
    observed=observe_issue(runtime,issue_number,reader=reader,kanban=kanban); return PlannedIssue(observed,planner(observed.planner,runtime.config))
def plan_payload(plan): return {"phase":plan.phase.value,"action":plan.action.value if plan.action else None,"would_action":plan.would_action.value if plan.would_action else None,"reason":plan.reason,"pr_head":plan.pr_head,"intent_key":plan.intent_key}
def observation_payload(observed):
    pr=observed.github.pull_request; pull=None if pr is None else {"number":pr.number,"url":pr.url,"head":pr.head,"base":pr.base,"state":pr.state,"draft":pr.draft,"merged_at":pr.merged_at}; return {"issue_state":observed.github.issue_state,"blockers":[{"issue":row.issue_number,"state":row.state,"internal":row.internal,"merged_at":row.merged_at} for row in observed.github.blockers],"pr":pull,"execution":dict(observed.execution),"unsafe_reason":observed.planner.unsafe_reason}
def dispatch_attempts(runtime,adapter,key,spec):
    _need(runtime.max_attempts>0,"max_execution_attempts must be positive")
    for attempt in range(1,runtime.max_attempts+1):
        task=adapter.create(spec,key,attempt); runtime.cursors[key]={"task_id":task,"attempt":attempt,"created_at":time.time()}; facts=adapter.observe(task)
        if facts.outcome is not Outcome.FAILURE: return ActionResult(facts.outcome.value,(task,),f"attempt {attempt}: {facts.status}")
    return ActionResult("exhausted",(task,),"bounded execution attempts exhausted")
def _worker(ctx,plan,revision):
    issue=ctx.observed.github.issue_number; branch=branch_name(ctx.runtime.config.swarm_id,issue); path=worktree_path(ctx.runtime.repo_path,ctx.runtime.config.swarm_id,issue); kind=plan.action.value.removeprefix("START_").lower(); key=semantic_key(ctx.runtime.config.swarm_id,issue,kind,head=plan.pr_head if revision else None); base=ctx.workspace.prepare(WorkspaceSpec(ctx.runtime.config.repo,ctx.runtime.config.default_branch,branch,path),started=isinstance(ctx.runtime.cursors.get(key),dict) or revision,pr_exists=ctx.observed.github.pull_request is not None); row=ctx.reader.get(f"repos/{ctx.runtime.config.repo}/issues/{issue}"); text=str(row.get("body") or "") if isinstance(row,dict) else ""
    if revision: text+=f"\n\nApply only the exact-head GitHub adjudication for {plan.pr_head}. Re-read that durable decision before editing."
    model,provider=_model(ctx.runtime.config.worker_model); spec=TaskSpec(f"[{'revise' if revision else 'implement'}] #{issue}",worker_body(ctx.runtime.config.repo,issue,branch,ctx.runtime.config.default_branch,base,text,revision=revision),f"dir:{path}",model,ctx.runtime.assignee,provider=provider,skills=("ponytail",),max_runtime=ctx.runtime.max_runtime); return dispatch_attempts(ctx.runtime,ctx.kanban,key,spec)
def _target(ctx):
    pr=ctx.observed.github.pull_request
    if pr is None: raise RuntimeError("review action has no observed PR")
    return pr,ExactHeadTarget(ctx.runtime.config.repo,ctx.observed.github.issue_number,pr.number,pr.head,f"dir:{Path(ctx.runtime.repo_path).resolve()}",ctx.runtime.assignee)
def _remember(runtime,results):
    tasks=[]
    for result in results:
        if result.task_id and result.attempt: runtime.cursors[result.semantic_key]={"task_id":result.task_id,"attempt":result.attempt,"created_at":time.time()}; tasks.append(result.task_id)
    return ActionResult("dispatched",tuple(tasks),", ".join(result.state.value for result in results))
def _start_review(ctx,adjudicate):
    pr,target=_target(ctx); rows=() if pr.adjudication is None else (pr.adjudication,); results=(reconcile_adjudication(ctx.runtime.config,target,pr.reviewers,rows,ctx.kanban,ctx.runtime.max_attempts),) if adjudicate else reconcile_reviewers(ctx.runtime.config,target,pr.reviewers,ctx.kanban,ctx.runtime.max_attempts); return _remember(ctx.runtime,results)
def _merge_action(ctx,plan):
    result=request_exact_head_merge(ctx.runtime.config,ctx.observed.github.issue_number,plan.pr_head or "",ctx.reader,ctx.merger); return ActionResult(result.state.value.lower(),detail=result.reason)
def _handlers(): return {Action.START_IMPLEMENTATION:lambda c,p:_worker(c,p,False),Action.START_REVISION:lambda c,p:_worker(c,p,True),Action.START_REVIEW:lambda c,p:_start_review(c,False),Action.START_ADJUDICATION:lambda c,p:_start_review(c,True),Action.MERGE:_merge_action}
def _default(value,factory): return factory() if value is None else value
def apply_plan(runtime,planned,*,reader=None,kanban=None,workspace=None,merger=None,executors=None):
    if planned.plan.action is None: return ActionResult("suppressed" if planned.plan.would_action else "noop",detail=_need(not planned.observation.planner.unsafe_reason,planned.observation.planner.unsafe_reason) or planned.plan.reason)
    handler=_default(executors,_handlers).get(planned.plan.action)
    if handler is None: raise RuntimeError(f"no executor registered for planned action {planned.plan.action.value}")
    ctx=ExecutionContext(runtime,planned.observation,_default(reader,GhReader),_default(kanban,lambda:KanbanAdapter(runtime.board,runtime.repo_path)),_default(workspace,lambda:GitWorkspace(runtime.repo_path)),_default(merger,GhMerger)); return handler(ctx,planned.plan)

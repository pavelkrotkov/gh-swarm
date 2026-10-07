# Apply exactly one planned side effect with bounded, restart-safe execution identities.
# Review/adjudication dispatch is exact-head scoped; implementation/revision workers own durable PR publication.
# Merge mutation remains delegated to the fresh-authority merge boundary.
from pathlib import Path
import time
from swarm_v7 import Action, Phase
from swarm_v7_controller_runtime import ActionResult, ExecutionContext, _attempts, _need
from swarm_v7_execution import ExactHeadTarget, Outcome, ReviewExecutionError, SlotResult, SlotState, TaskSpec, _model, _target as _validate_target, adjudicator_task_spec, reviewer_task_spec, semantic_key, worker_body
from swarm_v7_github import GhReader
from swarm_v7_kanban import KanbanAdapter
from swarm_v7_merge import GhMerger, request_exact_head_merge
from swarm_v7_workspace import GitWorkspace, WorkspaceSpec, branch_name, worktree_path

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
    _validate_target(config,target); present=_review_slots(config,target,rows)
    return tuple(_review_slot(slot in present,semantic_key(config.swarm_id,target.issue,"review",slot=slot,head=target.head),reviewer_task_spec(config,target,slot),adapter,attempts[slot-1]) for slot in range(1,len(config.reviewer_models)+1))
def reconcile_adjudication(config,target,reviewers,rows,adapter,attempts):
    _validate_target(config,target); key=semantic_key(config.swarm_id,target.issue,"adjudication",head=target.head)
    if len(_review_slots(config,target,reviewers))!=len(config.reviewer_models): return SlotResult(SlotState.NOT_READY,key,reason="current head reviewer slots are incomplete")
    current=[row for row in rows if row.head==target.head]
    if len(current)>1: raise ReviewExecutionError("duplicate adjudication publications for current head")
    return _review_slot(bool(current),key,adjudicator_task_spec(config,target),adapter,attempts,True)
def dispatch_attempts(runtime,adapter,key,spec):
    for attempt in _attempts(runtime,key,"blocked:"):
        task=adapter.create(spec,key,attempt); runtime.cursors[key]={"task_id":task,"attempt":attempt,"created_at":time.time()}; facts=adapter.observe(task)
        if facts.outcome is not Outcome.FAILURE: return ActionResult(facts.outcome.value,(task,),f"attempt {attempt}: {facts.status}")
    return ActionResult("exhausted",(task,),"bounded execution attempts exhausted")
def _worker_note(ctx,plan,revision,branch,base): return (f"\n\nRe-read exact-head GitHub CI/review/adjudication feedback for {plan.pr_head} before editing." if revision else "")+(f"\n\nBefore any other work, merge exact prepared base {base} into {branch}; resolve conflicts by preserving only issue-scoped changes, then continue. Do not rebase or force-push." if not ctx.workspace.ancestor(base,f"refs/heads/{branch}") else "")
def _worker(ctx,plan,revision):
    issue=ctx.observed.github.issue_number; branch=branch_name(ctx.runtime.config.swarm_id,issue); path=worktree_path(ctx.runtime.repo_path,ctx.runtime.config.swarm_id,issue); kind="revision" if revision else "implementation"; key=semantic_key(ctx.runtime.config.swarm_id,issue,kind,head=plan.pr_head if revision else None); base=ctx.workspace.prepare(WorkspaceSpec(ctx.runtime.config.repo,ctx.runtime.config.default_branch,branch,path),started=isinstance(ctx.runtime.cursors.get(key),dict) or revision,pr_exists=ctx.observed.github.pull_request is not None); row=ctx.reader.get(f"repos/{ctx.runtime.config.repo}/issues/{issue}"); text=(str(row.get("body") or "") if isinstance(row,dict) else "")+_worker_note(ctx,plan,revision,branch,base)
    model,provider=_model(ctx.runtime.config.worker_model); spec=TaskSpec(f"[{'revise' if revision else 'implement'}] #{issue}",worker_body(ctx.runtime.config.repo,issue,branch,ctx.runtime.config.default_branch,base,text,revision=revision),f"dir:{path}",model,ctx.runtime.assignee,provider=provider,skills=("ponytail",),max_runtime=ctx.runtime.max_runtime,completion_contract=ctx.runtime.config.repo); return dispatch_attempts(ctx.runtime,ctx.kanban,key,spec)
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
    pr,target=_target(ctx); rows=() if pr.adjudication is None else (pr.adjudication,); key=semantic_key(ctx.runtime.config.swarm_id,target.issue,"adjudication",head=target.head) if adjudicate else None; attempts=_attempts(ctx.runtime,key,ctx.observed.execution.get(key,"")) if adjudicate else tuple(_attempts(ctx.runtime,key,ctx.observed.execution.get(key,"")) for slot in range(1,len(ctx.runtime.config.reviewer_models)+1) for key in (semantic_key(ctx.runtime.config.swarm_id,target.issue,"review",slot=slot,head=target.head),)); results=(reconcile_adjudication(ctx.runtime.config,target,pr.reviewers,rows,ctx.kanban,attempts),) if adjudicate else reconcile_reviewers(ctx.runtime.config,target,pr.reviewers,ctx.kanban,attempts); return _remember(ctx.runtime,results)
def _merge_action(ctx,plan): result=request_exact_head_merge(ctx.runtime.config,ctx.observed.github.issue_number,plan.pr_head or "",ctx.reader,ctx.merger); return ActionResult(result.state.value.lower(),detail=result.reason)
def _handlers(): return {Action.START_IMPLEMENTATION:lambda c,p:_worker(c,p,False),Action.START_REVISION:lambda c,p:_worker(c,p,True),Action.START_REVIEW:lambda c,p:_start_review(c,False),Action.START_ADJUDICATION:lambda c,p:_start_review(c,True),Action.MERGE:_merge_action}
def _default(value,factory): return factory() if value is None else value
def _terminal_action(runtime,planned,kanban): issue=planned.observation.github.issue_number; reason=f"stale/cancelled: source issue #{issue} is closed and its PR is merged"; tasks=_default(kanban,lambda:KanbanAdapter(runtime.board,runtime.repo_path)).block_issue(runtime.config.swarm_id,issue,reason); return ActionResult("cancelled" if tasks else "noop",tasks,reason)
def _idle_action(runtime,planned,kanban): return _terminal_action(runtime,planned,kanban) if planned.plan.phase is Phase.MERGED and not runtime.config.paused else ActionResult("suppressed" if planned.plan.would_action else "noop",detail=_need(not planned.observation.planner.unsafe_reason,planned.observation.planner.unsafe_reason) or planned.plan.reason)
def apply_plan(runtime,planned,*,reader=None,kanban=None,workspace=None,merger=None,executors=None):
    if planned.plan.action is None: return _idle_action(runtime,planned,kanban)
    handler=_default(executors,_handlers).get(planned.plan.action)
    if handler is None: raise RuntimeError(f"no executor registered for planned action {planned.plan.action.value}")
    ctx=ExecutionContext(runtime,planned.observation,_default(reader,GhReader),_default(kanban,lambda:KanbanAdapter(runtime.board,runtime.repo_path)),_default(workspace,lambda:GitWorkspace(runtime.repo_path)),_default(merger,GhMerger)); return handler(ctx,planned.plan)


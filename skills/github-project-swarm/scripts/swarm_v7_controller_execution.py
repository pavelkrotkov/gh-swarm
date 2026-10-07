# Apply executes at most one action chosen by the pure planner and never invents a fallback action.
# Merge delegates to fresh exact-SHA merge authority; terminal cleanup only blocks stale execution cards.
# Reader/Kanban/workspace/merger defaults are constructed lazily at the selected side-effect boundary.
from swarm_v7 import Action,Phase
from swarm_v7_controller_manifest import ActionResult,ExecutionContext,_need
from swarm_v7_controller_review_actions import _remember,_start_review,_target
from swarm_v7_controller_worker import _worker
from swarm_v7_github import GhReader
from swarm_v7_kanban import KanbanAdapter
from swarm_v7_merge import GhMerger,request_exact_head_merge
from swarm_v7_workspace import GitWorkspace
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

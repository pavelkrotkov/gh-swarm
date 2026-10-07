# Review/adjudication actions bind the stable launcher to the observed PR number and exact head.
# Attempt ranges are derived independently for each exact-head semantic slot.
# Dispatched task IDs are persisted immediately with creation timestamps for restart safety.
from pathlib import Path
import time
from swarm_v7_controller_manifest import ActionResult
from swarm_v7_controller_liveness import _attempts
from swarm_v7_execution import semantic_key
from swarm_v7_review import ExactHeadTarget,reconcile_adjudication,reconcile_reviewers
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

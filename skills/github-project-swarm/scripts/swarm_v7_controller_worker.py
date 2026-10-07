# Implementation/revision dispatch prepares deterministic Git worktree state before creating a task.
# The worker, not the controller, owns commit, push and PR publication.
# A revision re-reads exact-head feedback and merges the freshly fetched default base before editing.
# Cursors are persisted before observing the created task so a crash cannot lose its attempt identity.
import time
from swarm_v7_controller_manifest import ActionResult
from swarm_v7_controller_observation import _attempts
from swarm_v7_execution import TaskSpec,Outcome,parse_model,semantic_key,worker_body
from swarm_v7_workspace import WorkspaceSpec,branch_name,worktree_path
def dispatch_attempts(runtime,adapter,key,spec):
    for attempt in _attempts(runtime,key,"blocked:"):
        task=adapter.create(spec,key,attempt); runtime.cursors[key]={"task_id":task,"attempt":attempt,"created_at":time.time()}; facts=adapter.observe(task)
        if facts.outcome is not Outcome.FAILURE: return ActionResult(facts.outcome.value,(task,),f"attempt {attempt}: {facts.status}")
    return ActionResult("exhausted",(task,),"bounded execution attempts exhausted")
def _worker_note(ctx,plan,revision,branch,base): return (f"\n\nRe-read exact-head GitHub CI/review/adjudication feedback for {plan.pr_head} before editing." if revision else "")+(f"\n\nBefore any other work, merge exact prepared base {base} into {branch}; resolve conflicts by preserving only issue-scoped changes, then continue. Do not rebase or force-push." if not ctx.workspace.ancestor(base,f"refs/heads/{branch}") else "")
def _worker(ctx,plan,revision):
    issue=ctx.observed.github.issue_number; branch=branch_name(ctx.runtime.config.swarm_id,issue); path=worktree_path(ctx.runtime.repo_path,ctx.runtime.config.swarm_id,issue); kind="revision" if revision else "implementation"; key=semantic_key(ctx.runtime.config.swarm_id,issue,kind,head=plan.pr_head if revision else None); base=ctx.workspace.prepare(WorkspaceSpec(ctx.runtime.config.repo,ctx.runtime.config.default_branch,branch,path),started=isinstance(ctx.runtime.cursors.get(key),dict) or revision,pr_exists=ctx.observed.github.pull_request is not None); row=ctx.reader.get(f"repos/{ctx.runtime.config.repo}/issues/{issue}"); text=(str(row.get("body") or "") if isinstance(row,dict) else "")+_worker_note(ctx,plan,revision,branch,base)
    model,provider=parse_model(ctx.runtime.config.worker_model); spec=TaskSpec(f"[{'revise' if revision else 'implement'}] #{issue}",worker_body(ctx.runtime.config.repo,issue,branch,ctx.runtime.config.default_branch,base,text,revision=revision),f"dir:{path}",model,ctx.runtime.assignee,provider=provider,skills=("ponytail",),max_runtime=ctx.runtime.max_runtime,completion_contract=ctx.runtime.config.repo); return dispatch_attempts(ctx.runtime,ctx.kanban,key,spec)

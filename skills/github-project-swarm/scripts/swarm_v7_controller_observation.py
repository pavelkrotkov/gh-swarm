# Fresh GitHub authority is overlaid with execution liveness and Git ancestry before pure planning.
# Dependency readiness precedes base ancestry; merged/unsafe GitHub observations bypass local execution reads.
# Adapter failures become one unsafe observation reason rather than partial local truth.
# plan_once is the sole observe-to-plan handoff used by views and live reconcile.
from dataclasses import replace
from swarm_v7 import DependencyState,plan_issue
from swarm_v7_controller_manifest import IssueObservation,PlannedIssue
from swarm_v7_controller_liveness import _overlay
from swarm_v7_workspace import GitWorkspace,branch_name
from swarm_v7_github import GhReader,observe_issue as observe_github
from swarm_v7_kanban import KanbanAdapter
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


# Issue observation composes validated GitHub linkage, dependencies and exact-head PR evidence.
# Closed issues without GitHub-confirmed merged PR evidence fail closed.
# Any read/shape ambiguity becomes one unsafe planner observation rather than partial truth.
from swarm_v7 import DependencyState,ManifestV7,MergeGate,Observation
from swarm_v7_github_transport import GhReader
from swarm_v7_github_scalars import GitHubReadError,UnsafeGitHubObservation,exact_sha,mapping,native_head,nested_text,positive_int
from swarm_v7_github_pr_links import _labels,_same_repo,_linked_prs,_select_pr
from swarm_v7_github_links import BlockerObservation,_dependency_observation,_issue_branch
from swarm_v7_github_pr import GitHubIssueObservation,PullRequestObservation,_merge_gate,_pr_observation,_with_pr
from swarm_v7_github_ci import checks,ci_state,_run_state,_status_state
from swarm_v7_github_publication import AdjudicationExecutionError,AdjudicationPublication,ReviewerPublication,adjudication_marker,review_marker
from swarm_v7_github_review import review_publications
from swarm_v7_github_adjudication import adjudication_publication,payload,_recover_adjudication
def _observe_issue(config,issue,reader):
    row=mapping(reader.get(f"repos/{config.repo}/issues/{issue}"),"issue"); state=str(row.get("state") or "").upper(); blockers,dependency=_dependency_observation(config,reader.list(f"repos/{config.repo}/issues/{issue}/dependencies/blocked_by"),reader); pr=_select_pr(_linked_prs(reader,config.repo,issue,state,_issue_branch(config,issue)),_issue_branch(config,issue,state))
    if pr is not None: return _with_pr(config,issue,state,blockers,dependency,pr,reader)
    if state!="OPEN": reason=f"issue is {state.lower()} and no merged PR is confirmed"; return GitHubIssueObservation(issue,state,blockers,None,Observation(issue,dependency=dependency,merge_gate=MergeGate.UNKNOWN,unsafe_reason=reason),reason)
    return GitHubIssueObservation(issue,state,blockers,None,Observation(issue,dependency=dependency))
def observe_issue(config:ManifestV7,issue:int,reader=None):
    try: return _observe_issue(config,issue,reader if reader is not None else GhReader())
    except Exception as exc:
        reason=f"GitHub observation failed: {exc}"; return GitHubIssueObservation(issue,"UNKNOWN",(),None,Observation(issue,dependency=DependencyState.UNKNOWN,merge_gate=MergeGate.UNKNOWN,unsafe_reason=reason),reason)


# Pull normalization binds exact head/base, labels and GitHub mergeability into immutable evidence.
# Hold labels, draft/state/base mismatch block merge; unknown native mergeability remains UNKNOWN.
# CI/review/adjudication facts are collected for the same exact head before planner projection.
from collections import namedtuple
from swarm_v7 import MergeGate,Observation
from swarm_v7_github_ci import checks,ci_state
from swarm_v7_github_publication import AdjudicationPublication,ReviewerPublication
from swarm_v7_github_review import review_publications
from swarm_v7_github_adjudication import _recover_adjudication
from swarm_v7_github_scalars import UnsafeGitHubObservation,exact_sha,nested_text,positive_int
from swarm_v7_github_pr_links import _labels
PullRequestObservation=namedtuple("PullRequestObservation","number url state base head draft mergeable merge_state merged_at merge_sha labels reviewers adjudication"); GitHubIssueObservation=namedtuple("GitHubIssueObservation","issue_number issue_state blockers pull_request planner unsafe_reason",defaults=(None,))
def _merge_gate(config,pr):
    if pr.merged_at: return MergeGate.READY
    blocked=any((pr.state!="OPEN",pr.draft,pr.base!=config.default_branch,pr.merge_state not in {"CLEAN","UNSTABLE","","UNKNOWN"},bool(set(pr.labels)&{x.lower() for x in config.no_merge_labels})))
    if blocked: return MergeGate.BLOCKED
    if pr.mergeable is None or pr.merge_state in {"","UNKNOWN"}: return MergeGate.UNKNOWN
    return MergeGate.READY if pr.mergeable else MergeGate.BLOCKED
def _pr_observation(pr,number,head,reviewers,adjudication): return PullRequestObservation(number,str(pr.get("html_url",pr.get("url",""))),str(pr.get("state") or "").upper(),nested_text(pr,"base","ref"),head,bool(pr.get("draft")),pr.get("mergeable") if isinstance(pr.get("mergeable"),bool) else None,str(pr.get("mergeable_state") or "").upper(),str(pr.get("merged_at")) if pr.get("merged_at") else None,pr.get("merge_commit_sha") if pr.get("merged_at") else None,tuple(sorted(_labels(pr.get("labels")))),reviewers,adjudication)
def _with_pr(config,issue,state,blockers,dependency,pr,reader):
    head=exact_sha(nested_text(pr,"head","sha")); number=positive_int(pr.get("number"),"PR number"); raw=checks(reader,config.repo,head); reviewers,review_state=review_publications(config,issue,head,reader.list(f"repos/{config.repo}/pulls/{number}/reviews")); adjudication,decision=_recover_adjudication(config,issue,head,reader.list(f"repos/{config.repo}/issues/{number}/comments")); observed=_pr_observation(pr,number,head,reviewers,adjudication); confirmed=observed.merged_at is not None; merged=confirmed and state=="CLOSED"
    if state=="CLOSED" and not confirmed: raise UnsafeGitHubObservation("issue closed without GitHub-confirmed PR mergedAt")
    planner=Observation(issue,merged,dependency,head,ci=ci_state(config,raw),review=review_state,adjudication_decision=decision,merge_gate=_merge_gate(config,observed),merge_confirmed=confirmed); return GitHubIssueObservation(issue,state,blockers,observed,planner)

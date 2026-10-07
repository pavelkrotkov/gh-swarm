# Read-only GitHub semantic authority for issue, dependency, PR, and merge-gate observation.
# Transport, exact-head publications, and CI reduction live in narrow trust boundaries.
# This module composes those fresh facts into the planner Observation and fails closed on ambiguity.
from collections import namedtuple
from swarm_v7 import AdjudicationDecision, CiState, DependencyState, ManifestV7, MergeGate, Observation, ReviewState
from swarm_v7_github_transport import GhReader, GitHubReadError, UnsafeGitHubObservation, exact_sha, mapping, native_head, nested_text, positive_int
from swarm_v7_github_publication import AdjudicationExecutionError, AdjudicationPublication, ReviewerPublication, adjudication_marker, adjudication_publication, payload, review_marker, review_publications, _recover_adjudication
from swarm_v7_github_ci import checks, ci_state, _run_state, _status_state
BlockerObservation=namedtuple("BlockerObservation","issue_number state internal merged_at"); PullRequestObservation=namedtuple("PullRequestObservation","number url state base head draft mergeable merge_state merged_at merge_sha labels reviewers adjudication"); GitHubIssueObservation=namedtuple("GitHubIssueObservation","issue_number issue_state blockers pull_request planner unsafe_reason",defaults=(None,))
def _labels(value): return {str(row.get("name") if isinstance(row,dict) else row).lower() for row in value} if isinstance(value,list) else set()
def _same_repo(issue,repo): value=str(issue.get("repository_url") or "").rstrip("/"); return not value or value==f"https://api.github.com/repos/{repo}"
def _closure_pr_ok(pr,number): return positive_int(pr.get("number"),"PR number")==number and bool(pr.get("merged_at"))
def _closure_pr(reader,repo,node): node=mapping(node,"closure reference"); number=positive_int(node.get("number"),"closure PR number"); pr=mapping(reader.get(f"repos/{repo}/pulls/{number}"),f"PR {number}") if nested_text(node,"repository","nameWithOwner")==repo and node.get("merged") else mapping(None,"valid closure reference"); return pr if _closure_pr_ok(pr,number) else mapping(None,"confirmed closure PR")
def _closure_prs(reader,repo,issue): owner,name=repo.split("/",1); query=f'query($endCursor:String){{repository(owner:"{owner}",name:"{name}"){{issue(number:{issue}){{closedByPullRequestsReferences(first:100,after:$endCursor){{nodes{{number,merged,repository{{nameWithOwner}}}} pageInfo{{hasNextPage,endCursor}}}}}}}}}}'; pages=reader.graphql(query); pages=[pages] if isinstance(pages,dict) else _rows(pages); nodes=[node for data in pages for node in _rows(mapping(mapping(mapping(data.get("repository"),"repository").get("issue"),"issue").get("closedByPullRequestsReferences"),"closure references").get("nodes"))]; return None if not nodes else [_closure_pr(reader,repo,node) for node in nodes if node.get("merged")]
def _cross_reference(event,repo): source=event.get("source") if event.get("event")=="cross-referenced" else None; linked=source.get("issue") if isinstance(source,dict) else None; return positive_int(linked.get("number"),"linked PR number") if isinstance(linked,dict) and _same_repo(linked,repo) and isinstance(linked.get("pull_request"),dict) else None
def _timeline_prs(reader,repo,issue): numbers={number for event in reader.list(f"repos/{repo}/issues/{issue}/timeline") if (number:=_cross_reference(event,repo)) is not None}; return [mapping(reader.get(f"repos/{repo}/pulls/{number}"),f"PR {number}") for number in sorted(numbers)]
def _linked_prs(reader,repo,issue,issue_state=None,branch=None): prs=_closure_prs(reader,repo,issue) if issue_state=="CLOSED" else None; return ([pr for pr in _branch_prs(_timeline_prs(reader,repo,issue),branch) if pr.get("merged_at")] if issue_state=="CLOSED" else _timeline_prs(reader,repo,issue)) if prs is None else prs
def _branch_prs(prs,branch): return prs if branch is None else [pr for pr in prs if isinstance(pr.get("head"),dict) and pr["head"].get("ref")==branch]
def _select_pr(prs,branch=None):
    prs=_branch_prs(prs,branch); opened=[pr for pr in prs if str(pr.get("state") or "").lower()=="open"]
    if len(opened)>1: raise UnsafeGitHubObservation("multiple open PRs are linked to the issue")
    return next(iter(opened),max((pr for pr in prs if pr.get("merged_at")),key=lambda pr:str(pr.get("merged_at")),default=None))
def _merged_at(reader,repo,issue,branch=None): return max((str(pr["merged_at"]) for pr in _branch_prs(_linked_prs(reader,repo,issue),branch) if pr.get("merged_at")),default=None)
def _issue_branch(config,issue,state=None): return None if state=="CLOSED" else f"swarm/{config.swarm_id}/{issue}"
def _dependency_observation(config,rows,reader):
    facts=[]
    for row in rows:
        number=positive_int(row.get("number"),"blocker issue number"); state=str(row.get("state") or "").upper(); internal=number in config.issues; facts.append(BlockerObservation(number,state,internal,_merged_at(reader,config.repo,number,_issue_branch(config,number,state)) if internal else None))
    blocked=any(fact.merged_at is None if fact.internal else fact.state=="OPEN" for fact in facts); return tuple(facts),DependencyState.BLOCKED if blocked else DependencyState.READY
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
def _observe_issue(config,issue,reader):
    row=mapping(reader.get(f"repos/{config.repo}/issues/{issue}"),"issue"); state=str(row.get("state") or "").upper(); blockers,dependency=_dependency_observation(config,reader.list(f"repos/{config.repo}/issues/{issue}/dependencies/blocked_by"),reader); pr=_select_pr(_linked_prs(reader,config.repo,issue,state,_issue_branch(config,issue)),_issue_branch(config,issue,state))
    if pr is not None: return _with_pr(config,issue,state,blockers,dependency,pr,reader)
    if state!="OPEN": reason=f"issue is {state.lower()} and no merged PR is confirmed"; return GitHubIssueObservation(issue,state,blockers,None,Observation(issue,dependency=dependency,merge_gate=MergeGate.UNKNOWN,unsafe_reason=reason),reason)
    return GitHubIssueObservation(issue,state,blockers,None,Observation(issue,dependency=dependency))
def observe_issue(config:ManifestV7,issue:int,reader=None):
    try: return _observe_issue(config,issue,reader if reader is not None else GhReader())
    except Exception as exc:
        reason=f"GitHub observation failed: {exc}"; return GitHubIssueObservation(issue,"UNKNOWN",(),None,Observation(issue,dependency=DependencyState.UNKNOWN,merge_gate=MergeGate.UNKNOWN,unsafe_reason=reason),reason)


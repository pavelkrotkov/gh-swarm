# Read-only GitHub authority for schema-7 planning and exact-head evidence.
# Every request is a bounded GET. Markers index native GitHub rows but do not create
# authority: shape, scope, slot, native commit, exact head, CI and ambiguity checks fail
# closed before normalized facts reach planning or the separate merge mutation owner.
import base64, json, re
from collections import namedtuple
from swarm_v7 import AdjudicationDecision, CiState, DependencyState, ManifestV7, MergeGate, Observation, ReviewState
from swarm_v7_cli_process import run_command
class GitHubReadError(RuntimeError): pass
class UnsafeGitHubObservation(RuntimeError): pass
BlockerObservation=namedtuple("BlockerObservation","issue_number state internal merged_at"); ReviewerPublication=namedtuple("ReviewerPublication","slot head"); AdjudicationPublication=namedtuple("AdjudicationPublication","head data"); PullRequestObservation=namedtuple("PullRequestObservation","number url state base head draft mergeable merge_state merged_at labels reviewers adjudication"); GitHubIssueObservation=namedtuple("GitHubIssueObservation","issue_number issue_state blockers pull_request planner unsafe_reason",defaults=(None,))
_SHA=re.compile(r"^[0-9a-f]{40}$"); _REVIEW=re.compile(r"<!-- hermes-swarm-review:(?P<swarm>[^:]+):(?P<issue>\d+):v(?P<slot>\d+):(?P<head>[0-9a-f]{40}) -->"); _ADJ=re.compile(r"<!-- hermes-swarm-adjudication:(?P<swarm>[^:]+):(?P<issue>\d+):(?P<head>[0-9a-f]{40}) -->"); _DECISION=re.compile(r"<!-- hermes-swarm-decision-b64:([A-Za-z0-9_=-]+) -->"); _OK={"success","neutral","skipped"}; _BAD={"failure","timed_out","action_required","startup_failure"}
def exact_sha(value):
    if not _SHA.fullmatch(value): raise ValueError("full 40-character lowercase SHA required")
    return value
def positive_int(value,name):
    if type(value) is not int or value<=0: raise UnsafeGitHubObservation(f"{name} must be a positive integer")
    return value
def mapping(value,name):
    if not isinstance(value,dict): raise GitHubReadError(f"{name} is not an object")
    return value
def nested_text(row,key,child):
    value=row.get(key,{}).get(child) if isinstance(row.get(key),dict) else None
    if not isinstance(value,str) or not value: raise UnsafeGitHubObservation(f"missing {key}.{child}")
    return value
def native_head(row,head):
    if (value:=row.get("commit_id")) is not None and exact_sha(str(value).lower())!=head: raise UnsafeGitHubObservation(f"native GitHub commit_id does not match claimed head {head}")
class GhReader:
    def __init__(self,timeout_s=30.0):
        if timeout_s<=0: raise ValueError("timeout_s must be positive")
        self.timeout_s=timeout_s
    def get(self,endpoint):
        try: return json.loads(run_command(["gh","api","--method","GET","-H","Accept: application/vnd.github+json",endpoint],timeout=self.timeout_s))
        except json.JSONDecodeError as exc: raise GitHubReadError(f"GitHub returned invalid JSON for {endpoint}") from exc
        except RuntimeError as exc: raise GitHubReadError(str(exc)) from exc
    def list(self,endpoint):
        rows=[]
        for page in range(1,101):
            value=self.get(f"{endpoint}{'&' if '?' in endpoint else '?'}per_page=100&page={page}")
            if not isinstance(value,list): raise GitHubReadError(f"expected a list from {endpoint}")
            rows.extend(row for row in value if isinstance(row,dict))
            if len(value)<100: return rows
        raise GitHubReadError(f"pagination limit exceeded for {endpoint}")
def review_marker(swarm,issue,slot,head):
    head=exact_sha(head)
    if not swarm or ":" in swarm or issue<=0 or slot<=0: raise ValueError("invalid review marker identity")
    return f"<!-- hermes-swarm-review:{swarm}:{issue}:v{slot}:{head} -->"
def adjudication_marker(swarm,issue,head):
    head=exact_sha(head)
    if not swarm or ":" in swarm or issue<=0: raise ValueError("invalid adjudication marker identity")
    return f"<!-- hermes-swarm-adjudication:{swarm}:{issue}:{head} -->"
def _scoped(body,pattern,prefix,swarm,issue,kind):
    matches=[m for m in pattern.finditer(body) if m.group("swarm")==swarm and int(m.group("issue"))==issue]
    if body.count(prefix)!=len(matches): raise UnsafeGitHubObservation(f"malformed or non-v7 {kind} publication")
    return matches
def _review_row(config,issue,head,row,found):
    prefix=f"<!-- hermes-swarm-review:{config.swarm_id}:{issue}:"
    for match in _scoped(str(row.get("body") or ""),_REVIEW,prefix,config.swarm_id,issue,"review"):
        if match.group("head")!=head: continue
        slot=int(match.group("slot")); native_head(row,head)
        if slot<1 or slot>len(config.reviewer_models): raise UnsafeGitHubObservation(f"unexpected reviewer slot {slot}")
        if slot in found: raise UnsafeGitHubObservation(f"duplicate reviewer publication for slot {slot} and head {head}")
        found[slot]=ReviewerPublication(slot,head)
def review_publications(config,issue,head,rows):
    found={}
    for row in rows: _review_row(config,issue,head,row,found)
    pubs=tuple(found[slot] for slot in sorted(found)); state=ReviewState.NONE if not pubs else ReviewState.DISPUTED if len(pubs)==len(config.reviewer_models) else ReviewState.RUNNING; return pubs,state
def payload(body,head):
    matches=_DECISION.findall(body)
    if len(matches)!=1: raise UnsafeGitHubObservation("adjudication requires exactly one machine-readable decision payload")
    try: value=json.loads(base64.urlsafe_b64decode(matches[0].encode()).decode())
    except Exception as exc: raise UnsafeGitHubObservation("invalid adjudication decision payload") from exc
    if not isinstance(value,dict): raise UnsafeGitHubObservation("invalid adjudication decision payload")
    if exact_sha(str(value.get("head_sha") or ""))!=head: raise UnsafeGitHubObservation("adjudication payload head does not match current PR head")
    return value
def adjudication_publication(config,issue,head,rows):
    current=[]; prefix=f"<!-- hermes-swarm-adjudication:{config.swarm_id}:{issue}:"
    for row in rows:
        matches=tuple(filter(lambda match:match.group("head")==head,_scoped(str(row.get("body")),_ADJ,prefix,config.swarm_id,issue,"adjudication")))
        if len(matches)>1: raise UnsafeGitHubObservation(f"duplicate adjudication markers for head {head}")
        if matches: native_head(row,head); current.append(row)
    if not current: return None,AdjudicationDecision.NONE
    if len(current)!=1: raise UnsafeGitHubObservation(f"duplicate adjudication publications for head {head}")
    data=payload(str(current[0].get("body")),head); raw=str(data.get("decision")).lower(); decision={"accept":AdjudicationDecision.ACCEPT,"changes":AdjudicationDecision.REVISE,"revise":AdjudicationDecision.REVISE}.get(raw)
    if decision is None: raise UnsafeGitHubObservation("invalid adjudication decision")
    return AdjudicationPublication(head,data),decision
def _rows(value):
    if not isinstance(value,list) or not all(isinstance(row,dict) for row in value): raise GitHubReadError("check/status rows are not object lists")
    return value
def checks(reader,repo,head):
    runs=mapping(reader.get(f"repos/{repo}/commits/{head}/check-runs?filter=latest"),"check runs"); status=mapping(reader.get(f"repos/{repo}/commits/{head}/status"),"commit status"); return _rows(runs.get("check_runs") or []),_rows(status.get("statuses") or [])
def _run_state(runs):
    if not all(str(row.get("status")).lower()=="completed" for row in runs): return CiState.PENDING
    values={str(row.get("conclusion")).lower() for row in runs}
    if values&_BAD: return CiState.FAILED
    return CiState.PASSED if values<=_OK else CiState.PENDING
def _status_state(rows):
    values={str(row.get("state") or "").lower() for row in rows}
    if values&{"failure","error"}: return CiState.FAILED
    return CiState.PENDING if "pending" in values else CiState.PASSED
def ci_state(config,raw):
    if not config.ci_required: return CiState.NOT_APPLICABLE
    runs,statuses=raw
    if not runs and not statuses: return CiState.UNKNOWN
    run=_run_state(runs)
    if run is CiState.PENDING: return run
    states={run,_status_state(statuses)}
    if CiState.FAILED in states: return CiState.FAILED
    return CiState.PENDING if CiState.PENDING in states else CiState.PASSED
def _labels(value): return {str(row.get("name") if isinstance(row,dict) else row).lower() for row in value} if isinstance(value,list) else set()
def _same_repo(issue,repo): value=str(issue.get("repository_url") or "").rstrip("/"); return not value or value==f"https://api.github.com/repos/{repo}"
def _linked_prs(reader,repo,issue):
    numbers=set()
    for event in reader.list(f"repos/{repo}/issues/{issue}/timeline"):
        source=event.get("source") if event.get("event")=="cross-referenced" else None; linked=source.get("issue") if isinstance(source,dict) else None
        if isinstance(linked,dict) and _same_repo(linked,repo) and isinstance(linked.get("pull_request"),dict): numbers.add(positive_int(linked.get("number"),"linked PR number"))
    return [mapping(reader.get(f"repos/{repo}/pulls/{number}"),f"PR {number}") for number in sorted(numbers)]
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
    blocked=any((pr.state!="OPEN",pr.draft,pr.base!=config.default_branch,bool(set(pr.labels)&{x.lower() for x in config.no_merge_labels})))
    if blocked: return MergeGate.BLOCKED
    if pr.mergeable is None or pr.merge_state in {"","UNKNOWN"}: return MergeGate.UNKNOWN
    return MergeGate.READY if pr.mergeable else MergeGate.BLOCKED
def _pr_observation(pr,number,head,reviewers,adjudication):
    return PullRequestObservation(number,str(pr.get("html_url") or pr.get("url") or ""),str(pr.get("state") or "").upper(),nested_text(pr,"base","ref"),head,bool(pr.get("draft")),pr.get("mergeable") if isinstance(pr.get("mergeable"),bool) else None,str(pr.get("mergeable_state") or "").upper(),str(pr.get("merged_at")) if pr.get("merged_at") else None,tuple(sorted(_labels(pr.get("labels")))),reviewers,adjudication)
def _with_pr(config,issue,state,blockers,dependency,pr,reader):
    head=exact_sha(nested_text(pr,"head","sha")); number=positive_int(pr.get("number"),"PR number"); raw=checks(reader,config.repo,head); reviewers,review_state=review_publications(config,issue,head,reader.list(f"repos/{config.repo}/pulls/{number}/reviews")); adjudication,decision=adjudication_publication(config,issue,head,reader.list(f"repos/{config.repo}/issues/{number}/comments")); observed=_pr_observation(pr,number,head,reviewers,adjudication); confirmed=observed.merged_at is not None; merged=confirmed and state=="CLOSED"
    if state=="CLOSED" and not confirmed: raise UnsafeGitHubObservation("issue closed without GitHub-confirmed PR mergedAt")
    planner=Observation(issue,merged,dependency,head,ci=ci_state(config,raw),review=review_state,adjudication_decision=decision,merge_gate=_merge_gate(config,observed),merge_confirmed=confirmed); return GitHubIssueObservation(issue,state,blockers,observed,planner)
def _observe_issue(config,issue,reader):
    row=mapping(reader.get(f"repos/{config.repo}/issues/{issue}"),"issue"); state=str(row.get("state") or "").upper(); blockers,dependency=_dependency_observation(config,reader.list(f"repos/{config.repo}/issues/{issue}/dependencies/blocked_by"),reader); pr=_select_pr(_linked_prs(reader,config.repo,issue),_issue_branch(config,issue))
    if pr is not None: return _with_pr(config,issue,state,blockers,dependency,pr,reader)
    if state!="OPEN": raise UnsafeGitHubObservation("issue is not open and no merged PR is confirmed")
    return GitHubIssueObservation(issue,state,blockers,None,Observation(issue,dependency=dependency))
def observe_issue(config:ManifestV7,issue:int,reader=None):
    try: return _observe_issue(config,issue,reader if reader is not None else GhReader())
    except Exception as exc:
        reason=f"GitHub observation failed: {exc}"; return GitHubIssueObservation(issue,"UNKNOWN",(),None,Observation(issue,dependency=DependencyState.UNKNOWN,merge_gate=MergeGate.UNKNOWN,unsafe_reason=reason),reason)

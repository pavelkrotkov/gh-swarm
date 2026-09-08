# Fresh-authority exact-SHA GitHub merge mutation and adjudication ledger validation.
# Every request re-observes GitHub, checks the immutable candidate head, finding ledger,
# CI, mergeability and operator policy, then sends that same SHA. API success is only
# REQUESTED; a later fresh merged_at plus closed source issue is workflow completion.
from collections import namedtuple
from enum import Enum
import json
from swarm_v7 import AdjudicationDecision, CiState, ReviewState
from swarm_v7_cli_process import run_command
from swarm_v7_github import GhReader, UnsafeGitHubObservation, adjudication_publication, exact_sha, mapping, native_head, observe_issue, positive_int, review_marker
class MergeAuthorityError(RuntimeError): pass
class MergeRequestError(RuntimeError): pass
MergeResultState=Enum("MergeResultState",{x:x for x in "REQUESTED GITHUB_CONFIRMED".split()},type=str); MergeResult=namedtuple("MergeResultBase","state pr_number head merged_at",defaults=(None,)); MergeResult.reason=property(lambda r:f"GitHub confirmed exact head {r.head} merged at {r.merged_at} and source issue closed" if r.state is MergeResultState.GITHUB_CONFIRMED else f"exact-head merge requested for {r.head}")
class GhMerger:
    def __init__(self,timeout_s=30.0,runner=None):
        if timeout_s<=0: raise ValueError("timeout_s must be positive")
        self.timeout_s=timeout_s; self.runner=runner if runner is not None else (lambda cmd,payload,timeout:run_command(cmd,timeout=timeout,input_text=payload))
    def merge(self,repo,number,head):
        head=exact_sha(str(head).strip().lower()); cmd=["gh","api","--method","PUT","-H","Accept: application/vnd.github+json",f"repos/{repo}/pulls/{number}/merge","--input","-"]
        try: response=json.loads(self.runner(cmd,json.dumps({"sha":head},separators=(",",":")),self.timeout_s))
        except json.JSONDecodeError as exc: raise MergeRequestError("GitHub merge API returned invalid JSON") from exc
        except RuntimeError as exc: raise MergeRequestError(str(exc)) from exc
        if not isinstance(response,dict): raise MergeRequestError("GitHub merge API response is not an object")
        if response.get("merged") is not True: raise MergeRequestError(str(response.get("message") or "GitHub did not merge the exact head"))
        return response
    def close_issue(self,repo,number): return self.runner(["gh","api","--method","PATCH","-H","Accept: application/vnd.github+json",f"repos/{repo}/issues/{number}","--input","-"],'{"state":"closed"}',self.timeout_s)
def _objects(value,name):
    if not isinstance(value,list) or not all(isinstance(row,dict) for row in value): raise ValueError(f"adjudication {name} must be a JSON array of objects")
    return value
def _finding_id(markers,head,row):
    body=str(row.get("body") or ""); matched=[marker for marker in markers if marker in body]
    if not matched: return None
    if len(matched)!=1 or body.count(matched[0])!=1: raise ValueError("review finding has ambiguous exact-head publication marker")
    native_head(row,head); return positive_int(row.get("id"),"review finding comment id")
def _findings(config,issue,head,rows):
    markers=tuple(review_marker(config.swarm_id,issue,slot,head) for slot in range(1,len(config.reviewer_models)+1)); values=[value for row in rows if (value:=_finding_id(markers,head,row)) is not None]
    if len(values)!=len(set(values)): raise ValueError(f"duplicate review finding comment id {next(value for value in values if values.count(value)>1)}")
    return set(values)
def _dispositions(data):
    seen,fixes=set(),set()
    for row in _objects(data.get("comment_dispositions"),"comment_dispositions"):
        ident=positive_int(row.get("github_comment_id"),"disposition github_comment_id"); kind=str(row.get("disposition") or "").lower()
        if ident in seen or kind not in {"fix","accepted-risk","reject"}: raise ValueError(f"invalid or duplicate disposition for finding {ident}")
        seen.add(ident); fixes.add(ident) if kind=="fix" else None
    return seen,fixes
def _required(data):
    sources=[]
    for row in _objects(data.get("required_changes"),"required_changes"):
        if not isinstance(values:=row.get("source_comment_ids"),list) or not values: raise ValueError("required change must cite one or more finding comments")
        sources.extend(positive_int(value,"required-change source comment id") for value in values)
    if len(sources)!=len(set(sources)): raise ValueError("duplicate required-change source")
    return set(sources)
def adjudication_ledger_error(config,issue,pr,reader):
    try:
        comments=reader.list(f"repos/{config.repo}/issues/{pr.number}/comments"); inline=reader.list(f"repos/{config.repo}/pulls/{pr.number}/comments"); findings=_findings(config,issue,pr.head,[*comments,*inline]); publication,_=adjudication_publication(config,issue,pr.head,comments)
        if publication is None: raise ValueError("exactly one current-head adjudication publication is required")
        seen,fixes=_dispositions(publication.data); required=_required(publication.data)
        if seen!=findings: raise ValueError(f"adjudication dispositions mismatch findings; missing={sorted(findings-seen)} extra={sorted(seen-findings)}")
        if fixes!=required or fixes: raise ValueError("ACCEPT adjudication has inconsistent or unresolved required changes")
    except (KeyError,TypeError,ValueError,UnsafeGitHubObservation) as exc: return f"invalid exact-head adjudication ledger: {exc}"
    return None
def _reason(ok,message): return None if ok else message
def _blockers(config,github,pr,head,ledger):
    expected=CiState.PASSED if config.ci_required else CiState.NOT_APPLICABLE; held=set(pr.labels)&{x.lower() for x in config.no_merge_labels}; gates=(github.unsafe_reason,_reason(github.issue_number in config.issues,"issue is not configured for this swarm"),_reason(pr.state=="OPEN" and not pr.draft,"pull request is not open and non-draft"),_reason(pr.base==config.default_branch,"pull request targets the wrong base branch"),_reason(pr.head==head,"current GitHub PR head differs from the exact head being considered"),_reason(github.planner.review is ReviewState.DISPUTED,"current exact head does not have every configured reviewer slot"),ledger,_reason(github.planner.adjudication_decision is AdjudicationDecision.ACCEPT,"current exact-head adjudication is not ACCEPT"),_reason(github.planner.ci is expected,"CI policy is not satisfied for the exact head"),_reason(pr.mergeable is True and pr.merge_state in {"CLEAN","UNSTABLE"},"GitHub merge state is incompatible with automatic merge"),_reason(not held,"no-merge label applies"),_reason(not config.paused,"swarm is paused")); return [reason for reason in gates if reason]
def _confirmed(pr,head):
    if pr is None: raise MergeAuthorityError("fresh GitHub observation has no pull request")
    if not pr.merged_at: return None
    if pr.head!=head: raise MergeAuthorityError("GitHub-confirmed merged PR head differs from requested head")
    return MergeResult(MergeResultState.GITHUB_CONFIRMED,pr.number,pr.head,pr.merged_at)
def _close_source_issue(config,github,reader,writer):
    if github.issue_number not in config.issues: raise MergeAuthorityError("issue is not configured for this swarm")
    if github.issue_state!="CLOSED": writer.close_issue(config.repo,github.issue_number)
    if str(mapping(reader.get(f"repos/{config.repo}/issues/{github.issue_number}"),"issue").get("state") or "").upper()!="CLOSED": raise MergeAuthorityError("GitHub source issue is not CLOSED after confirmed merge")
def request_exact_head_merge(config,issue_number,expected_head,reader=None,merger=None):
    head=exact_sha(str(expected_head).strip().lower()); actual_reader=reader if reader is not None else GhReader(); actual_merger=merger if merger is not None else GhMerger(); github=observe_issue(config,issue_number,actual_reader); pr=github.pull_request; confirmed=_confirmed(pr,head)
    if confirmed is not None: _close_source_issue(config,github,actual_reader,actual_merger); return confirmed
    if blockers:=_blockers(config,github,pr,head,None if github.unsafe_reason else adjudication_ledger_error(config,issue_number,pr,actual_reader)): raise MergeAuthorityError("; ".join(blockers))
    actual_merger.merge(config.repo,pr.number,head); return MergeResult(MergeResultState.REQUESTED,pr.number,head)

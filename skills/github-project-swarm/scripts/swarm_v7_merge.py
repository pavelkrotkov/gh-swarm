# Fresh-authority exact-SHA GitHub merge mutation.
# Every request re-observes GitHub and checks current head, ledger, CI, mergeability, and operator policy.
# API success is only REQUESTED; fresh merged_at plus source issue closure is completion.
from collections import namedtuple
from enum import Enum
import json
from swarm_v7 import AdjudicationDecision, CiState, ReviewState
from swarm_v7_cli_process import run_command
from swarm_v7_github import GhReader, exact_sha, mapping, observe_issue
from swarm_v7_merge_ledger import _dispositions, _finding_id, _findings, _objects, _required, adjudication_ledger_error
class MergeAuthorityError(RuntimeError): pass
class MergeRequestError(RuntimeError): pass
MergeResultState=Enum("MergeResultState",{x:x for x in "REQUESTED GITHUB_CONFIRMED".split()},type=str); MergeResult=namedtuple("MergeResultBase","state pr_number head merged_at merge_sha",defaults=(None,None)); MergeResult.reason=property(lambda r:f"GitHub confirmed exact head {r.head} merged at {r.merged_at}" if r.state is MergeResultState.GITHUB_CONFIRMED else f"exact-head merge requested for {r.head}")
class GhMerger:
    def __init__(self,timeout_s=30.0,runner=None):
        if timeout_s<=0: raise ValueError("timeout_s must be positive")
        self.timeout_s=timeout_s; self.runner=runner if runner is not None else (lambda cmd,payload,timeout:run_command(cmd,timeout=timeout,input_text=payload))
    def merge(self,repo,number,head):
        head=exact_sha(str(head).strip().lower()); cmd=["gh","api","--method","PUT","-H","Accept: application/vnd.github+json",f"repos/{repo}/pulls/{number}/merge","--input","-"]
        try: response=json.loads(self.runner(cmd,json.dumps({"sha":head},separators=(",",":")),self.timeout_s))
        except (json.JSONDecodeError,RuntimeError) as exc: raise MergeRequestError(str(exc)) from exc
        if not isinstance(response,dict): raise MergeRequestError("GitHub merge API response is not an object")
        if response.get("merged") is not True: raise MergeRequestError(str(response.get("message") or "GitHub did not merge the exact head"))
        return response
    def close_issue(self,repo,number): return self.runner(["gh","api","--method","PATCH","-H","Accept: application/vnd.github+json",f"repos/{repo}/issues/{number}","--input","-"],'{"state":"closed"}',self.timeout_s)
def _reason(ok,message): return None if ok else message
def _blockers(config,github,pr,head,ledger):
    expected=CiState.PASSED if config.ci_required else CiState.NOT_APPLICABLE; held=set(pr.labels)&{x.lower() for x in config.no_merge_labels}; gates=(github.unsafe_reason,_reason(github.issue_number in config.issues,"issue is not configured for this swarm"),_reason(config.merge_policy=="automatic","merge policy does not authorize automatic merge"),_reason(pr.state=="OPEN" and not pr.draft,"pull request is not open and non-draft"),_reason(pr.base==config.default_branch,"pull request targets the wrong base branch"),_reason(pr.head==head,"current GitHub PR head differs from the exact head being considered"),_reason(github.planner.review is ReviewState.DISPUTED,"current exact head does not have every configured reviewer slot"),ledger,_reason(github.planner.adjudication_decision is AdjudicationDecision.ACCEPT,"current exact-head adjudication is not ACCEPT"),_reason(github.planner.ci is expected,"CI policy is not satisfied for the exact head"),_reason(pr.mergeable is True and pr.merge_state in {"CLEAN","UNSTABLE"},"GitHub merge state is incompatible with automatic merge"),_reason(not held,"no-merge label applies"),_reason(not config.paused,"swarm is paused")); return [reason for reason in gates if reason]
def _confirmed(pr,head):
    if pr is None: raise MergeAuthorityError("fresh GitHub observation has no pull request")
    if not pr.merged_at: return None
    if pr.head!=head: raise MergeAuthorityError("GitHub-confirmed merged PR head differs from requested head")
    return MergeResult(MergeResultState.GITHUB_CONFIRMED,pr.number,pr.head,pr.merged_at,getattr(pr,"merge_sha",None))
def _confirm_after_request(config,issue,head,pr,reader,writer): fresh=observe_issue(config,issue,reader); confirmed=None if fresh.unsafe_reason or fresh.pull_request is None else _confirmed(fresh.pull_request,head); return confirmed or MergeResult(MergeResultState.REQUESTED,pr.number,head)
def _close_source_issue(config,github,reader,writer):
    if github.issue_number not in config.issues: raise MergeAuthorityError("issue is not configured for this swarm")
    if github.issue_state!="CLOSED": writer.close_issue(config.repo,github.issue_number)
    if str(mapping(reader.get(f"repos/{config.repo}/issues/{github.issue_number}"),"issue").get("state") or "").upper()!="CLOSED": raise MergeAuthorityError("GitHub source issue is not CLOSED after confirmed merge")
def request_exact_head_merge(config,issue_number,expected_head,reader=None,merger=None):
    head=exact_sha(str(expected_head).strip().lower()); actual_reader=reader if reader is not None else GhReader(); actual_merger=merger if merger is not None else GhMerger(); github=observe_issue(config,issue_number,actual_reader); pr=github.pull_request; confirmed=_confirmed(pr,head)
    if confirmed is not None: _close_source_issue(config,github,actual_reader,actual_merger); return confirmed
    if blockers:=_blockers(config,github,pr,head,None if github.unsafe_reason else adjudication_ledger_error(config,issue_number,pr,actual_reader)): raise MergeAuthorityError("; ".join(blockers))
    actual_merger.merge(config.repo,pr.number,head); return _confirm_after_request(config,issue_number,head,pr,actual_reader,actual_merger)


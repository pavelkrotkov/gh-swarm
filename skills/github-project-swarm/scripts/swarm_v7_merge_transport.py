# Merge transport sends the immutable expected head SHA and validates GitHub's response.
# A successful API response is only REQUESTED; semantic completion requires later fresh merged_at.
# Source-issue closure is a separate explicit mutation after GitHub confirms the merge.
from collections import namedtuple
from enum import Enum
import json
from swarm_v7_cli_process import run_command
from swarm_v7_github import exact_sha
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

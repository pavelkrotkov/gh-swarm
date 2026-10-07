# Bounded GitHub CLI transport plus scalar/shape validation.
# This boundary parses bytes and identities only; it does not infer workflow state.
import json,re
from swarm_v7_cli_process import run_command
class GitHubReadError(RuntimeError): pass
class UnsafeGitHubObservation(RuntimeError): pass
_SHA=re.compile(r"^[0-9a-f]{40}$")
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
def native_head(row,head,review=False):
    if review and not all((row.get("commit_id"),str(row.get("state") or "").upper()=="COMMENTED",row.get("submitted_at"))): raise UnsafeGitHubObservation("review publication must be a submitted COMMENT review bound to the exact head")
    if (value:=row.get("commit_id")) is not None and exact_sha(str(value).lower())!=head: raise UnsafeGitHubObservation(f"native GitHub commit_id does not match claimed head {head}")
class GhReader:
    def __init__(self,timeout_s=30.0):
        if timeout_s<=0: raise ValueError("timeout_s must be positive")
        self.timeout_s=timeout_s
    def get(self,endpoint):
        try: return json.loads(run_command(["gh","api","--method","GET","-H","Accept: application/vnd.github+json",endpoint],timeout=self.timeout_s))
        except (json.JSONDecodeError,RuntimeError) as exc: raise GitHubReadError(f"GitHub returned invalid JSON for {endpoint}" if isinstance(exc,json.JSONDecodeError) else str(exc)) from exc
    def text(self,endpoint):
        try: return run_command(["gh","api","--allow-escape-sequences","--method","GET",endpoint],timeout=self.timeout_s)
        except RuntimeError as exc: raise GitHubReadError(str(exc)) from exc
    def graphql(self,query): result=json.loads(run_command(["gh","api","graphql","--paginate","--slurp","-f",f"query={query}"],timeout=self.timeout_s)); return [mapping(row.get("data") if not row.get("errors") else None,"GraphQL data") for row in _rows(result)]
    def list(self,endpoint):
        rows=[]
        for page in range(1,101):
            value=self.get(f"{endpoint}{'&' if '?' in endpoint else '?'}per_page=100&page={page}")
            if not isinstance(value,list): raise GitHubReadError(f"expected a list from {endpoint}")
            rows.extend(row for row in value if isinstance(row,dict))
            if len(value)<100: return rows
        raise GitHubReadError(f"pagination limit exceeded for {endpoint}")
def _rows(value):
    if not isinstance(value,list) or not all(isinstance(row,dict) for row in value): raise GitHubReadError("check/status rows are not object lists")
    return value

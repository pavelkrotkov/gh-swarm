# Scalar/shape validation is the first GitHub trust boundary.
# Exact SHA and positive-ID checks reject malformed authority before any state reduction.
# Native review commit IDs, when present, must equal the claimed exact head.
# Missing nested text is unsafe evidence, not an empty/default value.
import re
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
def _rows(value):
    if not isinstance(value,list) or not all(isinstance(row,dict) for row in value): raise GitHubReadError("check/status rows are not object lists")
    return value


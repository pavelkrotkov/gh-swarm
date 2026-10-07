# Validate the exact-head adjudication ledger before any merge mutation.
# Every native reviewer finding is dispositioned exactly once and ACCEPT carries no unresolved fixes.
from swarm_v7_github import UnsafeGitHubObservation, adjudication_publication, native_head, positive_int, review_marker
def _objects(value,name):
    if not isinstance(value,list) or not all(isinstance(row,dict) for row in value): raise ValueError(f"adjudication {name} must be a JSON array of objects")
    return value
def _one_marker(markers,body):
    matched=[marker for marker in markers if marker in body]
    if not matched: return None
    if len(matched)!=1: raise ValueError("review finding has ambiguous exact-head publication marker")
    marker=matched[0]
    if body.count(marker)!=1: raise ValueError("review finding has ambiguous exact-head publication marker")
    return marker
def _finding_id(markers,head,row):
    if _one_marker(markers,str(row.get("body") or "")) is None: return None
    try: native_head(row,head); return positive_int(row.get("id"),"review finding comment id")
    except UnsafeGitHubObservation as exc: raise ValueError("native GitHub finding commit_id differs from current PR head") from exc
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

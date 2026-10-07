# Ledger orchestration compares all current-head findings with one adjudication publication.
# ACCEPT is merge-authoritative only when every finding is dispositioned and no required fix remains.
# Invalid ledger shape becomes one merge blocker string; the validation path performs no writes.
from swarm_v7_github import UnsafeGitHubObservation,adjudication_publication
from swarm_v7_merge_findings import _dispositions,_findings,_required
def adjudication_ledger_error(config,issue,pr,reader):
    try:
        comments=reader.list(f"repos/{config.repo}/issues/{pr.number}/comments"); inline=reader.list(f"repos/{config.repo}/pulls/{pr.number}/comments"); findings=_findings(config,issue,pr.head,[*comments,*inline]); publication,_=adjudication_publication(config,issue,pr.head,comments)
        if publication is None: raise ValueError("exactly one current-head adjudication publication is required")
        seen,fixes=_dispositions(publication.data); required=_required(publication.data)
        if seen!=findings: raise ValueError(f"adjudication dispositions mismatch findings; missing={sorted(findings-seen)} extra={sorted(seen-findings)}")
        if fixes!=required or fixes: raise ValueError("ACCEPT adjudication has inconsistent or unresolved required changes")
    except (KeyError,TypeError,ValueError,UnsafeGitHubObservation) as exc: return f"invalid exact-head adjudication ledger: {exc}"
    return None


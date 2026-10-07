# Exact-head reviewer and adjudication publication evidence.
# Marker shape, slot scope, native commit identity, duplicates, and payload head all fail closed.
# Kanban success cannot synthesize a publication.
import base64,json,re
from collections import namedtuple
from swarm_v7 import AdjudicationDecision, ReviewState
from swarm_v7_github_transport import UnsafeGitHubObservation, exact_sha, native_head
class AdjudicationExecutionError(UnsafeGitHubObservation): pass
ReviewerPublication=namedtuple("ReviewerPublication","slot head"); AdjudicationPublication=namedtuple("AdjudicationPublication","head data")
_REVIEW=re.compile(r"<!-- hermes-swarm-review:(?P<swarm>[^:]+):(?P<issue>\d+):v(?P<slot>\d+):(?P<head>[0-9a-f]{40}) -->"); _ADJ=re.compile(r"<!-- hermes-swarm-adjudication:(?P<swarm>[^:]+):(?P<issue>\d+):(?P<head>[0-9a-f]{40}) -->"); _DECISION=re.compile(r"<!-- hermes-swarm-decision-b64:([A-Za-z0-9_=-]{32,1048576}) -->")
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
        slot=int(match.group("slot")); native_head(row,head,True)
        if slot<1 or slot>len(config.reviewer_models): raise UnsafeGitHubObservation(f"unexpected reviewer slot {slot}")
        if slot in found: raise UnsafeGitHubObservation(f"duplicate reviewer publication for slot {slot} and head {head}")
        found[slot]=ReviewerPublication(slot,head)
def review_publications(config,issue,head,rows):
    found={}
    for row in rows: _review_row(config,issue,head,row,found)
    pubs=tuple(found[slot] for slot in sorted(found)); state=ReviewState.NONE if not pubs else ReviewState.DISPUTED if len(pubs)==len(config.reviewer_models) else ReviewState.RUNNING; return pubs,state
def payload(body,head):
    matches=_DECISION.findall(body)
    if len(matches)!=1: raise AdjudicationExecutionError("adjudication requires exactly one machine-readable decision payload")
    try:
        token=matches[0]+"="*((-len(matches[0]))%4); value=json.loads(base64.b64decode(token.encode(),altchars=b"-_",validate=True).decode())
    except Exception as exc: raise AdjudicationExecutionError("invalid adjudication decision payload") from exc
    if not isinstance(value,dict): raise AdjudicationExecutionError("invalid adjudication decision payload")
    if not _SHA.fullmatch(payload_head:=str(value.get("head_sha") or "")) or payload_head!=head: raise AdjudicationExecutionError("adjudication payload head does not match current PR head")
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
    if decision is None: raise AdjudicationExecutionError("invalid adjudication decision")
    return AdjudicationPublication(head,data),decision
def _recover_adjudication(config,issue,head,rows):
    try: return adjudication_publication(config,issue,head,rows)
    except AdjudicationExecutionError: return None,AdjudicationDecision.NONE

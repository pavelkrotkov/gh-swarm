# Adjudication payloads are machine-readable exact-head evidence, not prose interpretation.
# Exactly one decision payload and one current-head publication are required.
# Malformed decision payloads are recoverable execution failures; duplicate publications remain unsafe.
# ACCEPT/REVISE vocabulary is closed and the payload head must equal the current PR head.
# URL-safe base64 is decoded with strict validation and exactly one payload marker.
# Recovery suppresses malformed decision payloads only so a fresh adjudication attempt can replace them.
import base64,json,re
from swarm_v7 import AdjudicationDecision
from swarm_v7_github_scalars import UnsafeGitHubObservation,_SHA,native_head
from swarm_v7_github_publication import AdjudicationExecutionError,AdjudicationPublication,_ADJ,_scoped
_DECISION=re.compile(r"<!-- hermes-swarm-decision-b64:([A-Za-z0-9_=-]{32,1048576}) -->")
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

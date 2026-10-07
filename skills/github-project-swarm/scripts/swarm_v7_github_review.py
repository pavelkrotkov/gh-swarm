# Reviewer slots require submitted native COMMENT reviews bound to the exact current head.
# Slot numbers must match configured models and duplicate current-head publications are unsafe.
# A partial set remains RUNNING; only all configured slots produce DISPUTED for adjudication.
from swarm_v7 import ReviewState
from swarm_v7_github_scalars import UnsafeGitHubObservation,native_head
from swarm_v7_github_publication import ReviewerPublication,_REVIEW,_scoped
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

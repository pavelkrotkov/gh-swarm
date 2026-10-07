# Publication markers are indexes only; native GitHub commit identity remains authoritative.
# Marker scope rejects malformed same-prefix text so prose cannot impersonate a valid publication.
# Marker constructors validate swarm/issue/slot identity before producing durable publication keys.
import re
from collections import namedtuple
from swarm_v7_github_scalars import UnsafeGitHubObservation,exact_sha
class AdjudicationExecutionError(UnsafeGitHubObservation): pass
ReviewerPublication=namedtuple("ReviewerPublication","slot head"); AdjudicationPublication=namedtuple("AdjudicationPublication","head data")
_REVIEW=re.compile(r"<!-- hermes-swarm-review:(?P<swarm>[^:]+):(?P<issue>\d+):v(?P<slot>\d+):(?P<head>[0-9a-f]{40}) -->"); _ADJ=re.compile(r"<!-- hermes-swarm-adjudication:(?P<swarm>[^:]+):(?P<issue>\d+):(?P<head>[0-9a-f]{40}) -->")
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

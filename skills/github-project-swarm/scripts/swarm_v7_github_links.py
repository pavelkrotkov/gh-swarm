# Dependency evidence is reduced only after linked-PR discovery.
# Internal blockers require fresh merged_at; external blockers remain blocking while OPEN.
# Issue branch naming is ignored for CLOSED blockers so merged PR history remains discoverable.
from collections import namedtuple
from swarm_v7 import DependencyState
from swarm_v7_github_pr_links import _linked_prs,_merged_at
from swarm_v7_github_scalars import positive_int
BlockerObservation=namedtuple("BlockerObservation","issue_number state internal merged_at")
def _issue_branch(config,issue,state=None): return None if state=="CLOSED" else f"swarm/{config.swarm_id}/{issue}"
def _dependency_observation(config,rows,reader):
    facts=[]
    for row in rows:
        number=positive_int(row.get("number"),"blocker issue number"); state=str(row.get("state") or "").upper(); internal=number in config.issues; facts.append(BlockerObservation(number,state,internal,_merged_at(reader,config.repo,number,_issue_branch(config,number,state)) if internal else None))
    blocked=any(fact.merged_at is None if fact.internal else fact.state=="OPEN" for fact in facts); return tuple(facts),DependencyState.BLOCKED if blocked else DependencyState.READY


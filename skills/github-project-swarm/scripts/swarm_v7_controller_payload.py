# Structured blocker codes explain the same planner inputs used by real reconciliation.
# GitHub observation failures and execution failures remain distinct for operator diagnosis.
# Merged PRs have no live blockers; historical receipts do not manufacture current gates.
# Payload rendering is pure and cannot dispatch or persist work.
# PR shape/mergeability gates expose GitHub uncertainty separately from explicit blocking.
# Hold labels are normalized against configured no-merge labels before rendering.
from swarm_v7 import ReviewState
def plan_payload(plan): return {"phase":plan.phase.value,"action":plan.action.value if plan.action else None,"would_action":plan.would_action.value if plan.would_action else None,"reason":plan.reason,"pr_head":plan.pr_head,"intent_key":plan.intent_key}
def _config_gates(config,pr): held=() if pr is None else tuple(sorted(set(pr.labels)&{x.lower() for x in config.no_merge_labels})); return (("paused","operator pause" if config.paused else None),("manual_merge_mode","manual" if config.merge_policy=="manual" else None),("hold_label",",".join(held)))
def _planner_gates(observed,config): planner=observed.planner; github=observed.github; dep={"BLOCKED":"dependency_wait","UNKNOWN":"dependency_unknown"}.get(planner.dependency.value); ci={"UNKNOWN":"ci_missing_evidence","PENDING":"ci_pending","FAILED":"ci_failed"}.get(planner.ci.value) if config.ci_required else None; review={"NONE":"review_missing","RUNNING":"review_pending","CHANGES_REQUESTED":"review_changes","UNKNOWN":"review_unknown"}.get(planner.review.value) if github.pull_request is not None else None; adjudication={"NONE":"adjudication_pending","REVISE":"adjudication_revision","UNKNOWN":"adjudication_unknown"}.get(planner.adjudication_decision.value) if planner.review is ReviewState.DISPUTED else None; return (("observation_failure",github.unsafe_reason),("execution_failure",planner.unsafe_reason if planner.unsafe_reason and not github.unsafe_reason else None),(dep,{"dependency_wait":"blocked","dependency_unknown":"unknown"}.get(dep)),(ci,{"ci_missing_evidence":"unknown","ci_pending":"pending","ci_failed":"failed"}.get(ci)),(review,planner.review.value.lower()),(adjudication,planner.adjudication_decision.value.lower()))
def _shape_gates(config,pr,planner): return () if pr is None else (("stale_base","current PR head misses fresh default branch" if not planner.base_current else None),("pr_not_open",pr.state if pr.state!="OPEN" else None),("draft","true" if pr.draft else None),("wrong_base",pr.base if pr.base!=config.default_branch else None))
def _mergeability_gates(pr): return () if pr is None else (("mergeability_unknown",pr.merge_state if pr.mergeable is None or pr.merge_state in {"","UNKNOWN"} else None),("mergeability_blocked",pr.merge_state if pr.mergeable is False or pr.merge_state not in {"CLEAN","UNSTABLE","","UNKNOWN"} else None))
def _pull_payload(pr):
    if pr is None: return None
    return {"number":pr.number,"url":pr.url,"head":pr.head,"base":pr.base,"state":pr.state,"draft":pr.draft,"merged_at":pr.merged_at,"merge_sha":getattr(pr,"merge_sha",None)}
def observation_payload(observed,config):
    pr=observed.github.pull_request; planner=observed.planner
    raw=() if pr is not None and pr.merged_at else (*_config_gates(config,pr),*_planner_gates(observed,config),*_shape_gates(config,pr,planner),*_mergeability_gates(pr))
    gates=[{"code":code,"detail":str(detail)} for code,detail in raw if code and detail]
    blockers=[{"issue":row.issue_number,"state":row.state,"internal":row.internal,"merged_at":row.merged_at} for row in observed.github.blockers]
    return {"issue_state":observed.github.issue_state,"blockers":blockers,"pr":_pull_payload(pr),"execution":dict(observed.execution),"base_current":planner.base_current,"unsafe_reason":planner.unsafe_reason,"gates":gates}


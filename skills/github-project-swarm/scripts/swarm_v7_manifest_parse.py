# Parse untrusted manifest JSON before constructing the immutable configuration.
# Legacy semantic keys fail first so stale local state can never regain workflow authority.
# Model, issue, CI and merge-policy validation preserve the established fail-closed order.
# Defaults are operator policy defaults, never recovered semantic outcomes.
# Reviewer model validation completes before worker/adjudicator construction so error ordering stays deterministic.
from swarm_v7_manifest import _DEFAULT_LABELS
_FORBIDDEN=frozenset("state finished completed completion acceptance accepted current_task review round repairs ci_head edges dependencies".split()); _ALLOWED={"schema","id","repo","default_branch","issues","models","ci_mode","no_merge_labels","paused","merge_policy"}
def _need(ok,message):
    if not ok: raise ValueError(message)
def _text(value,name): _need(isinstance(value,str) and bool(value.strip()),f"{name} must be a non-empty string"); return value
def _items(value,message,required=True): _need(isinstance(value,(list,tuple)) and (bool(value) or not required),message); return tuple(value)
def parse_manifest(raw):
    _need(not (bad:=set(raw)&_FORBIDDEN),f"schema 7 forbids semantic state keys: {sorted(bad)}"); _need(not (bad:=set(raw)-_ALLOWED),f"unknown schema-7 manifest keys: {sorted(bad)}"); _need(raw.get("schema")==7,"schema must be 7")
    models=raw.get("models"); _need(isinstance(models,dict),"models must be a mapping"); _need(set(models)=={"worker","reviewers","adjudicator"},"models must contain only worker, reviewers, and adjudicator")
    reviewers=tuple(_text(v,"models.reviewers") for v in _items(models.get("reviewers"),"reviewer models must be a non-empty sequence")); worker=_text(models.get("worker"),"models.worker"); adjudicator=_text(models.get("adjudicator"),"models.adjudicator")
    mode=raw.get("ci_mode","required"); _need(mode in {"required","none"},"ci_mode must be 'required' or 'none'"); labels=_items(raw.get("no_merge_labels",_DEFAULT_LABELS),"no_merge_labels must be a sequence of non-empty strings",False); _need(all(isinstance(x,str) and bool(x) for x in labels),"no_merge_labels must be a sequence of non-empty strings"); policy=raw.get("merge_policy","manual"); _need(policy in {"automatic","manual"},"merge_policy must be 'automatic' or 'manual'")
    paused=raw.get("paused",False); _need(isinstance(paused,bool),"paused must be boolean"); identity=tuple(_text(raw.get(name),name) for name in ("id","repo","default_branch")); issues=_items(raw.get("issues"),"issues must be a sequence",False); _need(all(type(x) is int and x>0 for x in issues),"issues must contain positive integers")
    return (*identity,issues,worker,reviewers,adjudicator,mode=="required",labels,paused,policy)

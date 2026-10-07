# Manifest shape is operator configuration only; semantic workflow facts have no fields here.
# Serialization is intentionally lossless so restart cursors never become planner authority.
from dataclasses import dataclass
_DEFAULT_LABELS=("no-merge","do-not-merge","hold-merge")
@dataclass(frozen=True)
class ManifestV7:
    swarm_id:str; repo:str; default_branch:str; issues:tuple[int,...]; worker_model:str; reviewer_models:tuple[str,...]; adjudicator_model:str; ci_required:bool=True; no_merge_labels:tuple[str,...]=_DEFAULT_LABELS; paused:bool=False; merge_policy:str="manual"; schema:int=7
    @classmethod
    def from_dict(cls,raw):
        from swarm_v7_manifest_parse import parse_manifest
        return cls(*parse_manifest(raw))
    def to_dict(self): return {"schema":7,"id":self.swarm_id,"repo":self.repo,"default_branch":self.default_branch,"issues":list(self.issues),"models":{"worker":self.worker_model,"reviewers":list(self.reviewer_models),"adjudicator":self.adjudicator_model},"ci_mode":"required" if self.ci_required else "none","no_merge_labels":list(self.no_merge_labels),"paused":self.paused,"merge_policy":self.merge_policy}

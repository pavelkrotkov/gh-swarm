# Runtime manifests add execution restart cursors to immutable operator configuration only.
# Retired issue reasons are audit/operator state and remain visible to dependency observation.
# Cursors identify bounded attempts; task success never becomes review, merge or dependency authority.
# Runtime validation rejects legacy/unknown fields before controller observation starts.
# Retired membership is audit/operator state only and never authorizes a dependency release.
from collections import namedtuple
from dataclasses import dataclass,field
from swarm_v7 import ManifestV7
_CONFIG={"schema","id","repo","default_branch","issues","models","ci_mode","no_merge_labels","paused","merge_policy"}
def _need(ok,message):
    if not ok: raise ValueError(message)
def _retired(value): _need(isinstance(value,dict),"retired_issues must be a mapping"); _need(all(str(issue).isdigit() and int(issue)>0 and isinstance(reason,str) and bool(reason.strip()) for issue,reason in value.items()),"retired_issues must map positive issue numbers to non-empty reasons"); return {str(issue):reason for issue,reason in value.items()}
def _runtime_values(data):
    rt=data.get("runtime"); _need(isinstance(rt,dict),"schema-7 runtime configuration is missing"); repo_path,board,assignee=(str(rt.get(key) or "").strip() for key in ("repo_path","board","assignee")); attempts=int(rt.get("max_execution_attempts",2)); cursors=rt.get("execution_cursors",{}); runtime=str(rt.get("max_runtime","30m")).strip(); retired=_retired(rt.get("retired_issues",{})); _need(bool(repo_path and board and assignee),"invalid schema-7 runtime configuration: repo_path/board/assignee is required"); _need(attempts>0,"invalid schema-7 runtime configuration: max_execution_attempts must be positive"); _need(isinstance(cursors,dict),"execution_cursors must be a mapping"); _need(bool(runtime),"invalid schema-7 runtime configuration: max_runtime is required"); return repo_path,board,assignee,attempts,runtime,dict(cursors),retired
@dataclass
class RuntimeManifest:
    config:ManifestV7; repo_path:str; board:str; assignee:str; max_attempts:int; max_runtime:str; cursors:dict; retired_issues:dict=field(default_factory=dict)
    @classmethod
    def from_dict(cls,raw): data=dict(raw); _need(data.get("schema")==7,f"unsupported swarm schema {data.get('schema')!r}; v7 does not migrate schema 5/6 manifests; initialize a fresh schema-7 swarm"); bad=set(data)-(_CONFIG|{"runtime"}); _need(not bad,f"schema-7 runtime manifest forbids legacy/unknown fields: {sorted(bad)}"); return cls(ManifestV7.from_dict({key:data[key] for key in _CONFIG if key in data}),*_runtime_values(data))
    def to_dict(self): return {**self.config.to_dict(),"runtime":{"repo_path":self.repo_path,"board":self.board,"assignee":self.assignee,"max_execution_attempts":self.max_attempts,"max_runtime":self.max_runtime,"execution_cursors":self.cursors,"retired_issues":self.retired_issues}}
IssueObservation=namedtuple("IssueObservation","github planner execution"); PlannedIssue=namedtuple("PlannedIssue","observation plan"); ActionResult=namedtuple("ActionResult","outcome task_ids detail",defaults=((),"")); ExecutionContext=namedtuple("ExecutionContext","runtime observed reader kanban workspace merger")

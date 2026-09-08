from collections import namedtuple
from enum import Enum
import json
from pathlib import Path
from swarm_v7_cli_process import ensure_worker_github_auth, run_command
from swarm_v7_github import exact_sha
# Kanban owns execution attempts only. Semantic keys are issue-scoped for implementation
# and exact-head scoped for review/adjudication/revision. Task success is liveness,
# never GitHub workflow completion.
TaskSpec=namedtuple("TaskSpec","title body workspace model assignee provider skills branch max_retries max_runtime",defaults=(None,(),None,1,"30m")); Outcome=Enum("Outcome",{name:name.lower() for name in "ACTIVE SUCCESS FAILURE".split()},type=str); TaskFacts=namedtuple("TaskFacts","task_id status outcome raw has_run",defaults=(True,))
_STATUS={**{name:Outcome.ACTIVE for name in ("todo","ready","running","review")},"done":Outcome.SUCCESS,**{name:Outcome.FAILURE for name in ("blocked","archived","triage")}}; _REQUIRED=("--body","--workspace","--branch","--idempotency-key","--max-retries","--max-runtime","--assignee","--skill","--model","--provider"); _TEMPLATE=(Path(__file__).resolve().parents[1]/"references"/"swarm_v7_worker_runtime.txt").read_text(encoding="utf-8"); KanbanExecutionError=RuntimeError
def attempt_key(key,attempt=1):
    if not key or attempt<1: raise ValueError("semantic key is required and attempt must be positive")
    return key if attempt==1 else f"{key}:a{attempt}"
def semantic_key(swarm,issue,kind,*,head=None,slot=None):
    prefix=f"swarm:{swarm}:issue:{issue}:"
    if kind=="implementation": return prefix+kind
    if kind=="review" and slot and slot>0: return f"{prefix}review:v{slot}:{exact_sha(str(head))}"
    if kind in {"adjudication","revision"}: return f"{prefix}{kind}:{exact_sha(str(head))}"
    raise ValueError("invalid semantic execution identity")
def create_args(spec,key,attempt=1):
    if spec.branch and not spec.workspace.startswith("worktree"): raise ValueError("--branch is only valid for worktree workspaces")
    args=["create",spec.title,"--body",spec.body,"--workspace",spec.workspace,"--max-retries",str(spec.max_retries),"--max-runtime",spec.max_runtime,"--idempotency-key",attempt_key(key,attempt),"--assignee",spec.assignee]
    if spec.branch: args.extend(("--branch",spec.branch))
    for skill in spec.skills: args.extend(("--skill",skill))
    args.extend(("--model",spec.model))
    if spec.provider: args.extend(("--provider",spec.provider))
    return args
def worker_body(repo,issue,branch,default_branch,base_sha,issue_text,*,revision=False):
    exact_sha(base_sha); return _TEMPLATE.format(operation="revision" if revision else "implementation",repo=repo,issue=issue,branch=branch,default_branch=default_branch,base_sha=base_sha,issue_text=issue_text.strip())
def _task(raw):
    row=raw.get("task",raw) if isinstance(raw,dict) else {}; task_id=row.get("id") or row.get("task_id") or row.get("taskId")
    if not task_id: raise KanbanExecutionError("Hermes Kanban task response is malformed or missing id")
    return row,str(task_id)
class KanbanAdapter:
    def __init__(self,board,cwd=None,timeout_s=30.0,runner=None): self.board,self.cwd,self.timeout_s,self.runner,self.live=board,cwd,timeout_s,runner or (lambda cmd,cwd,timeout:run_command(cmd,cwd,timeout=timeout)),runner is None
    def _run(self,args): return self.runner(("hermes","kanban","--board",self.board,*args,"--json"),self.cwd,self.timeout_s)
    def create_board(self,name): self.runner(("hermes","kanban","boards","create",self.board,"--name",name),self.cwd,self.timeout_s)
    def create(self,spec,key,attempt=1):
        if self.live: ensure_worker_github_auth(spec.assignee); run_command(("hermes","-p",spec.assignee,"config","set","security.protected_instruction_files","false"),self.cwd,timeout=self.timeout_s)
        return _task(json.loads(self._run(create_args(spec,key,attempt)) or "{}"))[1]
    def observe(self,task_id): row,observed=_task(json.loads(self._run(("show",task_id)) or "{}")); status=str(row.get("status") or "").strip().lower(); runs=json.loads(self._run(("runs",task_id)) or "[]"); runs=runs.get("runs",runs.get("task_runs",())) if isinstance(runs,dict) else runs; return TaskFacts(observed,status,_STATUS[status],row,bool(runs))
    def probe_contract(self):
        prefix=("hermes","kanban","--board",self.board); version=self.runner(("hermes","--version"),self.cwd,self.timeout_s).strip(); self.runner(("hermes","kanban","boards","list","--json"),self.cwd,self.timeout_s); help_text=self.runner((*prefix,"create","--help"),self.cwd,self.timeout_s); self.runner((*prefix,"show","--help"),self.cwd,self.timeout_s)
        if missing:=[flag for flag in _REQUIRED if flag not in help_text]: raise KanbanExecutionError(f"Hermes Kanban create contract missing: {', '.join(missing)}")
        return version

# Hermes Kanban transport creates/observes/blocks execution cards but owns no semantic workflow state.
# Live create prepares worker GitHub auth before an attempt can be consumed.
# Watchdog reclamation changes liveness only and preserves durable task/run evidence.
import json
from swarm_v7_cli_process import run_command
from swarm_v7_auth import ensure_worker_github_auth
from swarm_v7_execution import TaskSpec,attempt_key,create_args,semantic_key,worker_body
from swarm_v7_kanban_state import KanbanExecutionError,Outcome,TaskFacts,_issue_task,_run_state,_task
_REQUIRED=("--body","--workspace","--branch","--completion-contract","--idempotency-key","--max-retries","--max-runtime","--assignee","--skill","--model","--provider")
class KanbanAdapter:
    def __init__(self,board,cwd=None,timeout_s=30.0,runner=None): self.board,self.cwd,self.timeout_s,self.runner,self.live=board,cwd,timeout_s,runner or (lambda cmd,cwd,timeout:run_command(cmd,cwd,timeout=timeout)),runner is None
    def _run(self,args): return self.runner(("hermes","kanban","--board",self.board,*args,"--json"),self.cwd,self.timeout_s)
    def create_board(self,name): self.runner(("hermes","kanban","boards","create",self.board,"--name",name),self.cwd,self.timeout_s)
    def watchdog(self): return json.loads(self._run(("dispatch","--max","0")) or "{}")
    def create(self,spec,key,attempt=1):
        if self.live: ensure_worker_github_auth(spec.assignee); run_command(("hermes","-p",spec.assignee,"config","set","security.protected_instruction_files","false"),self.cwd,timeout=self.timeout_s)
        return _task(json.loads(self._run(create_args(spec,key,attempt)) or "{}"))[1]
    def block_issue(self,swarm,issue,reason): ids=tuple(task for raw in json.loads(self._run(("list",)) or "[]") for row,task in (_task(raw),) if _issue_task(row,swarm,issue)); ids and self.runner(("hermes","kanban","--board",self.board,"block",ids[0],reason)+(( "--ids",*ids[1:]) if len(ids)>1 else ()),self.cwd,self.timeout_s); return ids
    def observe(self,task_id): row,observed=_task(json.loads(self._run(("show",task_id)) or "{}")); status=str(row.get("status") or "").strip().lower(); runs=json.loads(self._run(("runs",task_id)) or "[]"); runs=runs.get("runs",runs.get("task_runs",())) if isinstance(runs,dict) else runs; runs.sort(key=lambda row:(row.get("started_at") or 0,int(row.get("id") or 0))); status,outcome=_run_state(status,runs); return TaskFacts(observed,status,outcome,row,bool(runs))
    def probe_contract(self):
        prefix=("hermes","kanban","--board","default"); version=self.runner(("hermes","--version"),self.cwd,self.timeout_s).strip(); self.runner(("hermes","kanban","boards","list","--json"),self.cwd,self.timeout_s); create_help=self.runner((*prefix,"create","--help"),self.cwd,self.timeout_s); self.runner((*prefix,"show","--help"),self.cwd,self.timeout_s); self.runner((*prefix,"list","--help"),self.cwd,self.timeout_s); block_help=self.runner((*prefix,"block","--help"),self.cwd,self.timeout_s); dispatch_help=self.runner((*prefix,"dispatch","--help"),self.cwd,self.timeout_s); rows=json.loads(self.runner((*prefix,"list","--json"),self.cwd,self.timeout_s) or "[]")
        if not isinstance(rows,list): raise KanbanExecutionError("Hermes Kanban list contract must return a JSON array")
        tuple(map(_task,rows))
        if missing:=[flag for text,flags in ((create_help,_REQUIRED),(block_help,("--ids",)),(dispatch_help,("--max",))) for flag in flags if flag not in text]: raise KanbanExecutionError(f"Hermes Kanban command contract missing: {', '.join(missing)}")
        return version


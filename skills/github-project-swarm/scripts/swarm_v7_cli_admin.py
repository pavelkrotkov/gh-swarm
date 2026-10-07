# Service administration owns only swarm timer/service units; the Hermes gateway is never touched.
# Timer health fails closed when systemd reports an active timer with no next elapse.
# Retirement blocks active issue tasks before removing active membership and keeps an audit reason.
# Configuration changes serialize under the same per-swarm reconcile lock.
# Activation validates all configured swarms before enabling the shared timer.
# Retire preserves the issue reason and blocks matching active cards before membership changes.
from dataclasses import replace
from swarm_v7_cli_process import subprocess_timeout
from swarm_v7_cli_manifest import STATE, locked, selected, save, load
from swarm_v7_cli_journal import journal
from swarm_v7_controller import ActionResult
from swarm_v7_kanban import KanbanAdapter
from swarm_v7_cli_init import validate
from swarm_v7_cli_service import _SERVICE,_TIMER,_timer_health,systemctl
def prepare(): print("prepare: schema 7 needs no prompt/profile projection; execution artifacts are prepared lazily")
def activate(*,repo=None): validate(repo=repo,all_swarms=True); systemctl("daemon-reload"); systemctl("enable","--now",_TIMER); _timer_health(); print(f"activated {_TIMER}")
def disable(): systemctl("disable","--now",_TIMER,check=False); systemctl("stop",_SERVICE,check=False); print("disabled Hermes swarm reconciliation; Hermes gateway was not touched")
def retire(args):
    reason=args.reason.strip(); path=selected(name=args.name)[0]
    if not reason: raise RuntimeError("--reason must be non-empty")
    with locked(STATE/f".reconcile.{path.stem}.lock"):
        runtime=load(path); issue=args.issue
        if issue not in runtime.config.issues: raise RuntimeError(f"issue #{issue} is not active in swarm {runtime.config.swarm_id}")
        tasks=KanbanAdapter(runtime.board,runtime.repo_path,subprocess_timeout()).block_issue(runtime.config.swarm_id,issue,f"retired by operator: {reason}"); runtime.config=replace(runtime.config,issues=tuple(number for number in runtime.config.issues if number!=issue)); runtime.retired_issues[str(issue)]=reason; save(runtime); journal(runtime,issue,None,ActionResult("retired",tasks,reason),0)
    print(f"{runtime.config.swarm_id} [{runtime.config.repo}] #{issue}: retired from active scope — {reason}")
def configure(args,**changes):
    for path in selected(name=args.name,all_swarms=getattr(args,"all",False)):
        with locked(STATE/f".reconcile.{path.stem}.lock"):
            runtime=load(path); runtime.config=replace(runtime.config,**changes); save(runtime); print(f"{runtime.config.swarm_id}: "+", ".join(f"{key}={value}" for key,value in changes.items()))


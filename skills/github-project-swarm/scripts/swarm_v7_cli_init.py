# Initialization writes one validated runtime manifest, then optionally runs the same reconciler as steady state.
# Doctor and validate are read-only contract checks; unsafe observations fail validation explicitly.
# Required skills and adapter contracts are checked before operator activation.
from types import SimpleNamespace
from swarm_v7_cli_process import run_command,subprocess_timeout
from swarm_v7_cli_manifest import manifest_path,selected,save,load
from swarm_v7_cli_init_config import _validated_runtime
from swarm_v7_cli_service import _timer_health
from swarm_v7_controller import plan_once
from swarm_v7_github import GhReader
from swarm_v7_kanban import KanbanAdapter
_REQUIRED=("ponytail","github-project-reviewer","github-project-adjudicator","github-project-swarm")
def init(args,reconcile_fn=None):
    runtime=_validated_runtime(args); KanbanAdapter(runtime.board,runtime.repo_path,subprocess_timeout()).create_board(f"GitHub swarm {runtime.config.repo}"); save(runtime)
    if not runtime.config.paused and reconcile_fn is not None and (errors:=reconcile_fn(runtime)): raise RuntimeError("initial reconciliation encountered errors:\n"+"\n".join(errors))
    print(f"Initialized {runtime.config.swarm_id}: {len(runtime.config.issues)} issues, schema=7, board={runtime.board}, merge={runtime.config.merge_policy}, {'paused' if runtime.config.paused else 'active'}"); print(f"Manifest: {manifest_path(runtime.config.swarm_id)}"); return runtime
def doctor(args):
    for cmd in (["git","--version"],["gh","--version"],["hermes","--version"],["gh","auth","status"]): run_command(cmd)
    if missing:=[skill for skill in _REQUIRED if skill not in run_command(["env","COLUMNS=1000","hermes","skills","list"])]: raise RuntimeError(f"missing required skills: {', '.join(missing)}")
    timeout=subprocess_timeout(); KanbanAdapter("__contract_probe__",timeout_s=timeout).probe_contract()
    if args.repo and not GhReader(timeout_s=timeout).get(f"repos/{args.repo}").get("default_branch"): raise RuntimeError(f"cannot read repository {args.repo}")
    _timer_health(); print("doctor: ok; schema-7 adapters readable; no writes performed")
def validate(*,repo=None,name=None,all_swarms=True):
    doctor(SimpleNamespace(repo=repo)); paths=selected(name=name,all_swarms=all_swarms if not name else False)
    for path in paths:
        runtime=load(path); plans=tuple(plan_once(runtime,issue) for issue in runtime.config.issues); bad=next((item for item in plans if item.observation.planner.unsafe_reason),None)
        if bad: raise RuntimeError(f"{runtime.config.swarm_id} #{bad.observation.github.issue_number}: {bad.observation.planner.unsafe_reason}")
    print("validate: ok; no swarm actions performed")


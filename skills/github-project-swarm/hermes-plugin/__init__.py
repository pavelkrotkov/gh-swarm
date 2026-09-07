import os, sys
from pathlib import Path
_SKILL="github-project-swarm"; _CLI="swarm_v7_cli.py"
# Only an active Skillfleet runtime may supply the executable; local shadows fail closed.
def _iter_skill_roots():
    from agent.skill_utils import get_all_skills_dirs
    yield from map(lambda x:Path(x).expanduser(),get_all_skills_dirs())
def _candidate_cli(root):
    root=Path(root).expanduser(); skill=root if root.name==_SKILL else root/_SKILL; runtime=skill.parent; cli=skill/"scripts"/_CLI
    return cli.resolve() if (runtime/".skillfleet-meta"/f"{_SKILL}.json").is_file() and (skill/"SKILL.md").is_file() and cli.is_file() else None
def _resolve_cli():
    found={value for root in _iter_skill_roots() if (value:=_candidate_cli(root)) is not None}
    if len(found)==1: return found.pop()
    if not found: raise RuntimeError("github-project-swarm is not exposed by an active Skillfleet runtime; configure Hermes skills.external_dirs to Skillfleet runtime/current")
    raise RuntimeError("multiple Skillfleet runtimes expose github-project-swarm; make Hermes skills.external_dirs unambiguous")
def _setup_cli(parser):
    sys.path.insert(0,str(_resolve_cli().parent)); from swarm_v7_cli import build_parser
    build_parser({name:None for name in "init status reconcile pause resume doctor validate explain prepare activate disable".split()},parser)
def _handle_cli(_args):
    cli=_resolve_cli(); argv=sys.argv[2:] if len(sys.argv)>=2 and sys.argv[1]=="swarm" else []; os.execv(sys.executable,[sys.executable,str(cli),*argv])
def register(ctx): ctx.register_cli_command(name="swarm",help="control GitHub project swarms",description="Schema-7 GitHub-derived swarm lifecycle operations.",setup_fn=_setup_cli,handler_fn=_handle_cli)

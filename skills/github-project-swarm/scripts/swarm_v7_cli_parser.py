# Parser construction is the sole CLI command surface definition.
# Handler wiring reuses the same concrete functions used programmatically and by the Hermes plugin.
# Selection flags are shared only by commands whose semantics support one/all swarms.
# Removed legacy commands have no parser aliases or compatibility branches.
import argparse
from swarm_v7_cli_admin import activate,configure,disable,prepare,retire
from swarm_v7_cli_init import doctor,init,validate
from swarm_v7_cli_reconcile import reconcile,reconcile_runtime
from swarm_v7_cli_views import dry_run,explain
def _selection(parser): parser.add_argument("--name"); parser.add_argument("--all",action="store_true")
def build_parser(handlers,root=None):
    root=root or argparse.ArgumentParser(prog="hermes-swarm"); sub=root.add_subparsers(dest="swarm_command",required=True); p=sub.add_parser("init"); p.add_argument("--repo"); p.add_argument("--repo-path",default="."); group=p.add_mutually_exclusive_group(required=True); group.add_argument("--epic",type=int); group.add_argument("--issues"); p.add_argument("--name"); p.add_argument("--board"); p.add_argument("--assignee",required=True); p.add_argument("--worker",required=True); p.add_argument("--reviewer",action="append",required=True); p.add_argument("--adjudicator"); p.add_argument("--max-runtime",default="8h"); p.add_argument("--max-execution-attempts",type=int,default=3); p.add_argument("--ci-mode",choices=["required","none"],default="required"); p.add_argument("--merge-policy",choices=["automatic","manual"],required=True); p.add_argument("--paused",action="store_true"); p.set_defaults(fn=handlers["init"])
    for name in ("status","reconcile","pause","resume"):
        p=sub.add_parser(name); _selection(p)
        (p.add_argument("--dry-run",action="store_true") if name=="reconcile" else None); (p.add_argument("--json",action="store_true") if name in {"status","reconcile"} else None)
        p.set_defaults(fn=handlers[name])
    p=sub.add_parser("doctor"); p.add_argument("--repo"); p.set_defaults(fn=handlers["doctor"]); p=sub.add_parser("validate"); p.add_argument("--repo"); _selection(p); p.set_defaults(fn=handlers["validate"]); p=sub.add_parser("explain"); p.add_argument("--name",required=True); p.add_argument("--issue",type=int,required=True); p.add_argument("--json",action="store_true"); p.set_defaults(fn=handlers["explain"]); p=sub.add_parser("retire"); p.add_argument("--name",required=True); p.add_argument("--issue",type=int,required=True); p.add_argument("--reason",required=True); p.set_defaults(fn=handlers["retire"]); p=sub.add_parser("merge-policy"); p.add_argument("--name",required=True); p.add_argument("policy",choices=["automatic","manual"]); p.set_defaults(fn=handlers["merge-policy"])
    for name in ("prepare","disable"): sub.add_parser(name).set_defaults(fn=handlers[name])
    p=sub.add_parser("activate"); p.add_argument("--repo"); p.set_defaults(fn=handlers["activate"]); return root
def _parser(): handlers={"init":lambda args:init(args,reconcile_runtime),"status":lambda args:dry_run(name=args.name,all_swarms=args.all,json_output=args.json),"reconcile":reconcile,"pause":lambda args:configure(args,paused=True),"resume":lambda args:configure(args,paused=False),"doctor":doctor,"validate":lambda args:validate(repo=args.repo,name=args.name,all_swarms=args.all or not args.name),"explain":lambda args:explain(name=args.name,issue=args.issue,json_output=args.json),"retire":retire,"merge-policy":lambda args:configure(args,merge_policy=args.policy),"prepare":lambda _:prepare(),"activate":lambda args:activate(repo=args.repo),"disable":lambda _:disable()}; return build_parser(handlers)
def main(): args=_parser().parse_args(); args.fn(args)

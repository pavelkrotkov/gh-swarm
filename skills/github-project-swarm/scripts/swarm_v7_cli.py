#!/usr/bin/env python3
# Executable/public CLI boundary; implementation lives in cohesive command owners.
from swarm_v7_cli_manifest import HOME,STATE,locked,load,manifest_path,manifests,save,selected
from swarm_v7_cli_journal import _apply_with_receipt,_merge_attribution,journal
from swarm_v7_cli_init import _REQUIRED,doctor,init,validate
from swarm_v7_cli_admin import _SERVICE,_TIMER,_timer_health,activate,configure,disable,prepare,retire,systemctl
from swarm_v7_cli_views import _render,_snapshot,dry_run,explain
from swarm_v7_cli_reconcile import reconcile,reconcile_runtime
from swarm_v7_cli_parser import _parser,build_parser,main
if __name__=="__main__":
    import sys
    try: main()
    except Exception as exc: print(f"hermes-swarm: {exc}",file=sys.stderr); raise SystemExit(1)

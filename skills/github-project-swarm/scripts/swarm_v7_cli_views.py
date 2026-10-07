# Status, dry-run and explain share the exact same fresh plan used by real reconcile.
# Read-only views never persist cursors, dispatch tasks, publish reviews or request merges.
# Merge attribution is derived from diagnostic receipts plus the current GitHub observation.
import json
from swarm_v7_cli_admin import _timer_health
from swarm_v7_cli_manifest import selected,load
from swarm_v7_cli_journal import _merge_attribution
from swarm_v7_controller import observation_payload,plan_once,plan_payload
def _snapshot(runtime,issue,planned): return {"swarm":runtime.config.swarm_id,"repo":runtime.config.repo,"issue":issue,"merge_policy":runtime.config.merge_policy,"observation":observation_payload(planned.observation,runtime.config),"plan":plan_payload(planned.plan),"merge_attribution":_merge_attribution(runtime,issue,planned)}
def _render(row): plan=row["plan"]; action=plan["action"] or (f"suppressed:{plan['would_action']}" if plan["would_action"] else "none"); pr=(row["observation"]["pr"] or {}).get("number","-"); head=(plan.get("pr_head") or "-")[:12]; attribution=(row.get("merge_attribution") or {}).get("state","-"); return f"{row['swarm']} [{row['repo']}] #{row['issue']}: state={row['observation']['issue_state']} merge={row['merge_policy']} {plan['phase']} action={action} pr=#{pr} head={head} gates={json.dumps(row['observation']['gates'],separators=(',',':'))} merge_source={attribution} — {plan['reason']}"
def dry_run(*,name=None,all_swarms=False,json_output=False):
    rows=[]; runtimes=[]; _timer_health(); paths=selected(name=name,all_swarms=all_swarms)
    for path in paths: runtime=load(path); runtimes.append(runtime); rows.extend(_snapshot(runtime,issue,plan_once(runtime,issue)) for issue in runtime.config.issues)
    empty=", ".join(f"{runtime.config.swarm_id} merge={runtime.config.merge_policy}" for runtime in runtimes); print(json.dumps(rows,ensure_ascii=False,sort_keys=True) if json_output else "\n".join(map(_render,rows)) if rows else f"no active issues in selected swarms: {empty}" if paths else "dry-run: no swarms configured")
def explain(*,name,issue,json_output=False):
    runtime=load(selected(name=name)[0])
    if issue not in runtime.config.issues: raise RuntimeError(f"issue #{issue} retired from swarm {runtime.config.swarm_id} [{runtime.config.repo}]: {runtime.retired_issues[str(issue)]}" if str(issue) in runtime.retired_issues else f"issue #{issue} is not configured in swarm {runtime.config.swarm_id}")
    row=_snapshot(runtime,issue,plan_once(runtime,issue)); print(json.dumps(row,ensure_ascii=False,sort_keys=True) if json_output else _render(row))

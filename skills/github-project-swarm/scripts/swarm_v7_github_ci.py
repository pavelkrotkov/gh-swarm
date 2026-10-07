# Reduce current-head GitHub CI evidence without guessing missing state.
# Successful Actions checks must bind both GitHub's head_sha and the checkout receipt to the exact head.
import re
from swarm_v7 import CiState
from swarm_v7_github_transport import mapping, _rows
_OK={"success","neutral","skipped"}; _BAD={"failure","timed_out","action_required","startup_failure"}; _JOB=re.compile(r"/actions/runs/\d+/job/(\d+)(?:$|[/?#])"); _RECEIPT=re.compile(r"HERMES_CHECKOUT_SHA=([0-9a-f]{40})\b"); _CHECKOUT=re.compile(r"git log -1 --format=%H\r?\n[^\r\n]*\b([0-9a-f]{40})\b")
def _actions_success(row): app=row.get("app"); return isinstance(app,dict) and app.get("slug")=="github-actions" and str(row.get("status")).lower()=="completed" and str(row.get("conclusion")).lower()=="success"
def _bind_checkout(reader,repo,head,row):
    item=dict(row); needs=_actions_success(item); match=_JOB.search(str(item.get("details_url") or "")); log=reader.text(f"repos/{repo}/actions/jobs/{match.group(1)}/logs") if needs and match else ""; values=set(_RECEIPT.findall(log))|set(_CHECKOUT.findall(log)); item["_exact_checkout"]=not needs or str(item.get("head_sha") or "").lower()==head and values=={head}; return item
def checks(reader,repo,head): runs=mapping(reader.get(f"repos/{repo}/commits/{head}/check-runs?filter=latest"),"check runs"); status=mapping(reader.get(f"repos/{repo}/commits/{head}/status"),"commit status"); return [_bind_checkout(reader,repo,head,row) for row in _rows(runs.get("check_runs") or [])],_rows(status.get("statuses") or [])
def _run_state(runs):
    if not all(str(row.get("status")).lower()=="completed" for row in runs): return CiState.PENDING
    values={str(row.get("conclusion")).lower() for row in runs}; return CiState.FAILED if values&_BAD else CiState.PASSED if values<=_OK and all(map(lambda row:row.get("_exact_checkout",True),runs)) else CiState.PENDING
def _status_state(rows): values={str(row.get("state") or "").lower() for row in rows}; return CiState.FAILED if values&{"failure","error"} else CiState.PENDING if "pending" in values else CiState.PASSED
def ci_state(config,raw):
    if not config.ci_required: return CiState.NOT_APPLICABLE
    runs,statuses=raw
    if not runs and not statuses: return CiState.UNKNOWN
    run=_run_state(runs)
    if run is CiState.PENDING: return run
    states={run,_status_state(statuses)}
    if CiState.FAILED in states: return CiState.FAILED
    return CiState.PENDING if CiState.PENDING in states else CiState.PASSED

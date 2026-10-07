# Journal rows are diagnostics and merge-attribution receipts, never workflow authority.
# Merge intent is recorded before mutation so an interrupted request remains attributable after restart.
# Request success is not completion: only a later fresh GitHub merged_at confirms the merge.
# Unknown request outcomes stay unknown until GitHub resolves them.
# Journal writes are append-only complete JSON lines so torn trailing writes are ignored by attribution.
# Correlation IDs bind intent and outcome without becoming workflow identity.
# External merges remain distinguishable from controller-requested merges.
import json,time,uuid
from swarm_v7 import Action
from swarm_v7_controller import apply_plan, observation_payload, plan_payload
from swarm_v7_merge import MergeRequestError
from swarm_v7_cli_manifest import STATE
def _journal_outcome(error,result): return "error" if error else "none" if result is None else result.outcome
def journal(runtime,issue,planned,result,elapsed_ms,error=None,*,correlation_id=None,event="reconcile",receipt=None):
    fields=dict.fromkeys(("phase","action","would_action","reason","pr_head","intent_key")) if planned is None else plan_payload(planned.plan); gates=[] if planned is None else observation_payload(planned.observation,runtime.config)["gates"]; row={"ts":time.time(),"correlation_id":correlation_id,"event":event,"swarm":runtime.config.swarm_id,"repo":runtime.config.repo,"issue":issue,"task_ids":[] if result is None else list(result.task_ids),"outcome":_journal_outcome(error,result),"elapsed_ms":elapsed_ms,"error":None if error is None else str(error),"detail":None if result is None else result.detail,"gates":gates,**fields,**(receipt or {})}; STATE.mkdir(parents=True,exist_ok=True)
    with open(STATE/f"{runtime.config.swarm_id}.journal.jsonl","a",encoding="utf-8") as out: out.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n"); return row
def _merge_attribution(runtime,issue,planned):
    pr=planned.observation.github.pull_request
    if pr is None: return None
    path=STATE/f"{runtime.config.swarm_id}.journal.jsonl"; rows=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines(keepends=True) if line.endswith("\n")] if path.exists() else []; matches=list(filter(lambda row:(row.get("issue"),row.get("pr"),row.get("head"))==(issue,pr.number,pr.head),rows))
    intent=next(filter(lambda row:row.get("event")=="merge_intent",reversed(matches)),None); cid=(intent or {}).get("correlation_id"); outcome=next(filter(lambda row:(row.get("event"),row.get("correlation_id"))==("merge_outcome",cid),reversed(matches)),None); value=(outcome or {}).get("merge_outcome")
    state={(False,False,None):"none",(True,False,None):"observed_external",(True,True,None):"confirmed_after_unknown_request_outcome",(True,True,"unknown"):"confirmed_after_unknown_request_outcome",(True,True,"requested"):"controller_request_confirmed",(True,True,"github_confirmed"):"controller_request_confirmed",(True,True,"rejected"):"observed_external_after_rejected_request",(False,True,None):"outcome_unknown",(False,True,"unknown"):"outcome_unknown",(False,True,"requested"):"request_attempted",(False,True,"rejected"):"request_rejected"}.get((bool(pr.merged_at),bool(intent),value))
    return {"state":state,"correlation_id":cid,"request_outcome":value,"merged_at":pr.merged_at,"merge_sha":getattr(pr,"merge_sha",None)}
def _receipt(runtime,planned,outcome): pr=planned.observation.github.pull_request; planner=planned.observation.planner; return {"pr":pr.number,"head":pr.head,"policy":runtime.config.merge_policy,"gate_evidence":{"pr_url":pr.url,"issue_state":planned.observation.github.issue_state,"dependency":planner.dependency.value,"ci":planner.ci.value,"review":planner.review.value,"adjudication":planner.adjudication_decision.value,"merge_gate":planner.merge_gate.value,"base_current":planner.base_current,"blockers":observation_payload(planned.observation,runtime.config)["gates"]},"merge_outcome":outcome}
def _apply_with_receipt(runtime,planned,correlation_id):
    pr=planned.observation.github.pull_request; request=planned.plan.action is Action.MERGE and pr is not None and pr.merged_at is None
    if not request: return apply_plan(runtime,planned)
    journal(runtime,planned.observation.github.issue_number,planned,None,0,correlation_id=correlation_id,event="merge_intent",receipt=_receipt(runtime,planned,"intent"))
    try: result=apply_plan(runtime,planned)
    except Exception as exc: journal(runtime,planned.observation.github.issue_number,planned,None,0,exc,correlation_id=correlation_id,event="merge_outcome",receipt=_receipt(runtime,planned,"rejected" if isinstance(exc,MergeRequestError) else "unknown")); raise
    journal(runtime,planned.observation.github.issue_number,planned,result,0,correlation_id=correlation_id,event="merge_outcome",receipt=_receipt(runtime,planned,result.outcome)); return result
def _reconcile_context(correlation_id,rows): return correlation_id or uuid.uuid4().hex,[] if rows is None else rows

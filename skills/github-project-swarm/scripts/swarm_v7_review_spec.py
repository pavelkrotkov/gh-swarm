# Review/adjudication specs use a stable dir launcher and pin every instruction to the exact PR head.
# Model/provider syntax is shared with worker task identity and remains closed to arbitrary CLI fragments.
# Reviewer and adjudicator skills are explicit task requirements; no implementation worktree branch is supplied.
from collections import namedtuple
from enum import Enum
from pathlib import Path
from swarm_v7_execution import TaskSpec,parse_model
from swarm_v7_github import adjudication_marker,exact_sha,review_marker
ExactHeadTarget=namedtuple("ExactHeadTarget","repo issue pr_number head workspace assignee"); SlotState=Enum("SlotState",{name:name for name in "SATISFIED ACTIVE EXHAUSTED NOT_READY".split()},type=str); SlotResult=namedtuple("SlotResult","state semantic_key task_id attempt reason",defaults=(None,None,"")); ReviewExecutionError=RuntimeError
_R=Path(__file__).resolve().parents[1]/"references"; _REVIEWER=(_R/"swarm_v7_reviewer_runtime.txt").read_text(); _ADJ=(_R/"swarm_v7_adjudicator_runtime.txt").read_text()
def _need(ok,message,error=ValueError):
    if not ok: raise error(message)
def _target(config,target):
    workspace=str(target.workspace or "").strip(); _need(target.repo==config.repo and target.issue in config.issues,"review target does not match swarm configuration"); _need(target.pr_number>=1,"PR number must be positive"); exact_sha(target.head); _need(workspace.startswith("dir:") and len(workspace)>4,"review/adjudication workspace must be a stable dir: launcher, not an implementation worktree")
    return workspace
def _model(value): return parse_model(value)
def reviewer_task_spec(config,target,slot):
    workspace=_target(config,target); _need(1<=slot<=len(config.reviewer_models),"reviewer slot is out of range")
    model,provider=parse_model(config.reviewer_models[slot-1]); body=_REVIEWER.format(repo=target.repo,pr_number=target.pr_number,head=target.head,slot=slot,marker=review_marker(config.swarm_id,target.issue,slot,target.head)); return TaskSpec(f"[review {target.head[:8]}] #{target.issue} reviewer {slot}",body,workspace,model,target.assignee,provider=provider,skills=("github-project-reviewer",))
def adjudicator_task_spec(config,target):
    workspace=_target(config,target); model,provider=parse_model(config.adjudicator_model); body=_ADJ.format(repo=target.repo,pr_number=target.pr_number,head=target.head,head_repr=repr(target.head),marker=adjudication_marker(config.swarm_id,target.issue,target.head)); return TaskSpec(f"[adjudicate {target.head[:8]}] #{target.issue}",body,workspace,model,target.assignee,provider=provider,skills=("github-project-adjudicator",))

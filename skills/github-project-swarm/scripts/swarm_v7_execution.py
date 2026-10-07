# Immutable Kanban task identity and worker handoff contracts.
# Semantic keys use issue identity for implementation and exact head for review/revision work.
# Attempt suffixes are replay identities only; they never create new semantic workflow identities.
# Worker bodies pin repository, branch, base SHA and completion contract before dispatch.
# Worktree-only branch flags are rejected before Hermes invocation.
# Reviewer/worker model strings use the same closed provider syntax.
# Task specifications have no parent/dependency field; workflow dependencies stay in GitHub.
# Attempt numbering starts at one and preserves the unsuffixed semantic key for the first try.
# Worker task bodies are generated from the installed runtime template, not caller-supplied shell fragments.
from collections import namedtuple
from enum import Enum
from pathlib import Path
from swarm_v7_github import exact_sha
TaskSpec=namedtuple("TaskSpec","title body workspace model assignee provider skills branch max_retries max_runtime completion_contract",defaults=(None,(),None,1,"30m","local-only")); Outcome=Enum("Outcome",{name:name.lower() for name in "ACTIVE SUCCESS FAILURE".split()},type=str); TaskFacts=namedtuple("TaskFacts","task_id status outcome raw has_run",defaults=(True,))
_TEMPLATE=(Path(__file__).resolve().parents[1]/"references"/"swarm_v7_worker_runtime.txt").read_text(encoding="utf-8")
def attempt_key(key,attempt=1):
    if not key or attempt<1: raise ValueError("semantic key is required and attempt must be positive")
    return key if attempt==1 else f"{key}:a{attempt}"
def semantic_key(swarm,issue,kind,*,head=None,slot=None):
    prefix=f"swarm:{swarm}:issue:{issue}:"
    if kind=="implementation": return prefix+kind
    if kind=="review" and slot and slot>0: return f"{prefix}review:v{slot}:{exact_sha(str(head))}"
    if kind in {"adjudication","revision"}: return f"{prefix}{kind}:{exact_sha(str(head))}"
    raise ValueError("invalid semantic execution identity")
def create_args(spec,key,attempt=1):
    if spec.branch and not spec.workspace.startswith("worktree"): raise ValueError("--branch is only valid for worktree workspaces")
    args=["create",spec.title,"--body",spec.body,"--workspace",spec.workspace,"--completion-contract",spec.completion_contract,"--max-retries",str(spec.max_retries),"--max-runtime",spec.max_runtime,"--idempotency-key",attempt_key(key,attempt),"--assignee",spec.assignee]; args.extend(("--branch",spec.branch)*bool(spec.branch))
    for skill in spec.skills: args.extend(("--skill",skill))
    args.extend(("--model",spec.model)); args.extend(("--provider",spec.provider)*bool(spec.provider)); return args
def worker_body(repo,issue,branch,default_branch,base_sha,issue_text,*,revision=False): exact_sha(base_sha); return _TEMPLATE.format(operation="revision" if revision else "implementation",repo=repo,issue=issue,branch=branch,default_branch=default_branch,base_sha=base_sha,issue_text=issue_text.strip())
def parse_model(value):
    import shlex
    parts=shlex.split(value)
    if not (len(parts)==1 or len(parts)==3 and parts[1]=="--provider"): raise ValueError(f"unsupported model specification: {value!r}")
    return parts[0],None if len(parts)==1 else parts[2]

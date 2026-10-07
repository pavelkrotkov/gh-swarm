# Initialization configuration is derived only from repository/GitHub facts and operator arguments.
# Model/provider syntax is normalized before RuntimeManifest construction.
# Issue discovery requires every selected GitHub issue to remain OPEN.
# Repository binding and default-branch discovery complete before any local manifest write.
import re,shlex
from pathlib import Path
from swarm_v7 import ManifestV7
from swarm_v7_cli_process import run_command, subprocess_timeout
from swarm_v7_cli_manifest import manifest_path
from swarm_v7_controller import RuntimeManifest
from swarm_v7_github import GhReader
from swarm_v7_workspace import GitWorkspace
def _model(value):
    if len(parts:=shlex.split(value))==1: return parts[0]
    if len(parts)==3 and parts[1]=="--provider": return shlex.join(parts)
    raise ValueError(f"invalid model spec: {value!r}")
def _issues(args,repo,reader):
    numbers=list(map(int,filter(str.strip,args.issues.split(",")))) if args.issues else [int(row["number"]) for row in reader.list(f"repos/{repo}/issues/{args.epic}/sub_issues")]
    if not numbers: raise RuntimeError("No issues found; use an epic with native sub-issues or --issues")
    if any(str(reader.get(f"repos/{repo}/issues/{number}").get("state")).upper()!="OPEN" for number in numbers): raise RuntimeError("issue set contains non-open issues")
    return numbers
def _repo(args,cwd): return args.repo if args.repo else run_command(["gh","repo","view","--json","nameWithOwner","-q",".nameWithOwner"],cwd)
def _validated_runtime(args):
    timeout=subprocess_timeout(); cwd=str(Path(args.repo_path).resolve()); repo=_repo(args,cwd); GitWorkspace(cwd,timeout_s=timeout).validate_binding(repo); reader=GhReader(timeout_s=timeout); numbers=_issues(args,repo,reader); default=reader.get(f"repos/{repo}").get("default_branch")
    if not default: raise RuntimeError("GitHub did not return a default branch")
    reviewers=tuple(map(_model,args.reviewer)); seed=args.epic if args.epic is not None else numbers[0]; name=args.name if args.name else f"{repo.split('/')[-1]}-{seed}"; swarm=re.sub(r"[^a-z0-9-]+","-",name.lower()).strip("-")[:50]
    if manifest_path(swarm).exists(): raise RuntimeError(f"swarm already exists: {swarm}")
    adjudicator=_model(args.adjudicator) if args.adjudicator else reviewers[0]; config=ManifestV7(swarm,repo,default,tuple(numbers),_model(args.worker),reviewers,adjudicator,args.ci_mode=="required",paused=args.paused,merge_policy=args.merge_policy); return RuntimeManifest(config,cwd,args.board if args.board else swarm,args.assignee,args.max_execution_attempts,args.max_runtime,{})

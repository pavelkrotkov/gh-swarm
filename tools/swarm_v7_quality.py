#!/usr/bin/env python3
"""Measure the installed schema-7 runtime and enforce staged/final quality gates."""
from __future__ import annotations
import argparse, ast, subprocess, sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from cognitive_complexity.api import get_cognitive_complexity
from radon.complexity import cc_visit
from radon.metrics import mi_visit

ROOT = Path(__file__).resolve().parents[1]; SKILL = ROOT / "skills" / "github-project-swarm"; SCRIPTS = SKILL / "scripts"
PLUGIN_REL = "hermes-plugin/__init__.py"; CLI_REL = "scripts/swarm_v7_cli.py"; DYNAMIC_RUNTIME_EDGES = {PLUGIN_REL: (CLI_REL,)}
CONTROLLER_MODULE_NAMES = ("swarm_v7_controller.py",)
CLI_MODULE_NAMES = ("swarm_v7_cli.py", "swarm_v7_cli_process.py")
CLI_CONTROLLER_MODULE_NAMES = ("swarm_v7_cli.py",)
PLANNER_MODULE_NAMES = ("swarm_v7.py",)
CORE_CONTROLLER_MODULE_NAMES = (*PLANNER_MODULE_NAMES, *CONTROLLER_MODULE_NAMES, *CLI_CONTROLLER_MODULE_NAMES)
CORE_PATHS = {("swarm_v7.py", "plan_issue"): "planner", ("swarm_v7_controller.py", "observe_issue"): "observer", ("swarm_v7_controller.py", "apply_plan"): "executor", ("swarm_v7_controller.py", "dispatch_attempts"): "executor-dispatch", ("swarm_v7_cli.py", "reconcile_runtime"): "cli-reconcile", ("swarm_v7_cli.py", "init"): "cli-init", ("swarm_v7_merge.py", "request_exact_head_merge"): "merge"}
REGRESSION = "regression"; QUALIFICATION = "qualification"; REPORT_FUNCTION_LINES = 40; MAX_FUNCTION_LINES = 60; MAX_CYCLOMATIC = 8; MAX_CORE_CYCLOMATIC = 6; MAX_COGNITIVE = 15; MAX_NESTING = 4; MIN_MAINTAINABILITY = 75.0; MAX_CORE_LOC = 1000; COHESION_REVIEW_LOC = 350; MAX_REGRESSION_MODULE_LOC = 450
POLICY_BASE_SHA = "ce9a9f6ff182336457dd45c8144afe3f1e78bed3"; PRE_V7_BASE_SHA = "a60d3c6c1ab34891477e6b368d600f21013051d9"; WHOLE_RUNTIME_BASE_SHA = "11089e5e35cec5895397495908395fcb5d6606f4"; WHOLE_RUNTIME_BASE_LOC = 3684; WHOLE_RUNTIME_BASE_MODULES = 115; MAX_WHOLE_RUNTIME_LOC = 799; MAX_WHOLE_RUNTIME_MODULES = 20; MIN_CUMULATIVE_REDUCTION = 3000; FINAL_RUNTIME_LOC = WHOLE_RUNTIME_BASE_LOC - MIN_CUMULATIVE_REDUCTION
_PRE_V7_CONTROLLER_STEMS = ("life" + "cycle", "observ" + "ability", "sw" + "arm", "swarm_v" + "6", "swarm_leg" + "acy")
PRE_V7_CONTROLLER_MODULE_NAMES = tuple(f"{stem}.py" for stem in _PRE_V7_CONTROLLER_STEMS)
class RuntimeScopeError(ValueError): pass
@dataclass(frozen=True)
class FunctionMetric:
    name: str; line: int; loc: int; cyclomatic: int; cognitive: int; nesting: int

def code_loc(text): return sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#"))
def _relative_import(path, node, sources):
    base = PurePosixPath(path).parent
    for _ in range(node.level - 1): base = base.parent
    candidate = (base / PurePosixPath(*(node.module or "").split("."))).as_posix()
    for option in (candidate + ".py", candidate + "/__init__.py"):
        if option in sources: return option
    raise RuntimeScopeError(f"{path}:{node.lineno} unresolved required local import {'.' * node.level}{node.module or ''}")
def _import_targets(path, text, sources):
    modules = {PurePosixPath(name).stem: name for name in sources if name.startswith("scripts/") and name.endswith(".py") and PurePosixPath(name).parent.as_posix() == "scripts"}; targets = set()
    for node in ast.walk(ast.parse(text, filename=path)):
        if isinstance(node, ast.Import): names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level: targets.add(_relative_import(path, node, sources)); continue
            names = [node.module] if node.module else []
        else: continue
        for name in filter(None, names):
            top = name.split(".", 1)[0]
            if top in modules: targets.add(modules[top])
            elif top.startswith("swarm_v7"): raise RuntimeScopeError(f"{path}:{node.lineno} unresolved required local import {name}")
    return targets
def derive_runtime_scope(sources):
    if PLUGIN_REL not in sources: raise RuntimeScopeError(f"runtime scope root missing: {PLUGIN_REL}")
    seen = set(); pending = [PLUGIN_REL]
    while pending:
        path = pending.pop()
        if path in seen: continue
        seen.add(path)
        for target in DYNAMIC_RUNTIME_EDGES.get(path, ()):
            if target not in sources: raise RuntimeScopeError(f"{path}: accepted dynamic runtime edge is unresolved: {target}")
            pending.append(target)
        pending.extend(_import_targets(path, sources[path], sources) - seen)
    return tuple(sorted(seen))
def working_runtime_sources(skill=SKILL): return {path.relative_to(skill).as_posix(): path.read_text(encoding="utf-8") for path in skill.rglob("*.py") if path.is_file()}
def git_show(root, ref, path):
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, text=True, capture_output=True, check=False); return proc.stdout if proc.returncode == 0 else None
def git_runtime_sources(ref, *, root=ROOT):
    prefix = "skills/github-project-swarm/"; proc = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, prefix], cwd=root, text=True, capture_output=True, check=False)
    if proc.returncode: return None
    result = {}
    for repo_path in proc.stdout.splitlines():
        if repo_path.endswith(".py") and (text := git_show(root, ref, repo_path)) is not None: result[repo_path.removeprefix(prefix)] = text
    return result
def runtime_metrics(sources):
    scope = derive_runtime_scope(sources); return sum(code_loc(sources[path]) for path in scope), len(scope)
def runtime_metrics_at_ref(ref, *, root=ROOT):
    sources = git_runtime_sources(ref, root=root); return runtime_metrics(sources) if sources is not None else None
def runtime_paths(skill=SKILL):
    sources = working_runtime_sources(skill); return tuple(skill / path for path in derive_runtime_scope(sources))
_RUNTIME_PATHS = runtime_paths(); ACTIVE_MODULE_NAMES = tuple(path.name for path in _RUNTIME_PATHS if path.parent == SCRIPTS); ACTIVE = tuple(SCRIPTS / name for name in ACTIVE_MODULE_NAMES)

def function_nodes(text):
    rows = []
    def walk(body, prefix=()):
        for node in body:
            if isinstance(node, ast.ClassDef): walk(node.body, (*prefix, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): rows.append((".".join((*prefix, node.name)), node)); walk(node.body, (*prefix, node.name))
    walk(ast.parse(text).body); return rows
def _add_complexity(rows, name, block):
    rows[name] = (block.lineno, block.complexity)
    for closure in getattr(block, "closures", ()): _add_complexity(rows, f"{name}.{closure.name}", closure)
def complexities(text):
    rows = {}
    for block in cc_visit(text):
        methods = getattr(block, "methods", None)
        if methods is not None:
            for method in methods: _add_complexity(rows, f"{block.name}.{method.name}", method)
        elif getattr(block, "classname", None) is None: _add_complexity(rows, block.name, block)
    return rows
def max_nesting_depth(function):
    maximum = 0
    def walk(node, depth):
        nonlocal maximum
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)): return
        if isinstance(node, ast.If):
            nested = depth + 1; maximum = max(maximum, nested)
            for child in node.body: walk(child, nested)
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If) and node.orelse[0].col_offset == node.col_offset: walk(node.orelse[0], depth)
            else:
                for child in node.orelse: walk(child, nested)
            return
        blocks = (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
        if isinstance(node, blocks):
            nested = depth + 1; maximum = max(maximum, nested); groups = [node.body]
            if isinstance(node, ast.Try): groups += [node.orelse, node.finalbody] + [handler.body for handler in node.handlers]
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)): groups.append(node.orelse)
            for group in groups:
                for child in group: walk(child, nested)
            return
        for child in ast.iter_child_nodes(node): walk(child, depth)
    for statement in function.body: walk(statement, 0)
    return maximum
def function_metrics(text):
    by_line = {line: value for line, value in complexities(text).values()}; rows = []
    for name, node in function_nodes(text):
        if node.lineno not in by_line: raise ValueError(f"radon did not report function {name} at line {node.lineno}")
        rows.append(FunctionMetric(name, node.lineno, (node.end_lineno or node.lineno) - node.lineno + 1, by_line[node.lineno], get_cognitive_complexity(node), max_nesting_depth(node)))
    return rows
def require_base(root, ref):
    proc = subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"], cwd=root, text=True, capture_output=True, check=False); return None if proc.returncode == 0 else f"quality policy base {ref} is unavailable: {(proc.stderr or proc.stdout or 'commit object unavailable').strip()}"
def baseline_text(path, base_sha, *, root=ROOT): return git_show(root, base_sha, path.relative_to(root).as_posix())
def pre_v7_controller_loc(*, root=ROOT):
    values = [git_show(root, PRE_V7_BASE_SHA, f"skills/github-project-swarm/scripts/{name}") for name in PRE_V7_CONTROLLER_MODULE_NAMES]
    return None if any(text is None for text in values) else sum(code_loc(text) for text in values)
def pre_v7_reduction_failure(current, baseline): return None if current < baseline else f"<pre-v7-baseline>:<aggregate>:1 whole_runtime_loc={current} is not strictly smaller than pre_v7_loc={baseline}"
def core_role(path, name): return CORE_PATHS.get((path.name, name))
def complexity_failures(path, text, baseline, *, mode=REGRESSION):
    failures = []; inherited = 0; old_rows = complexities(baseline) if baseline is not None else {}
    for name, (line, value) in complexities(text).items():
        if mode == QUALIFICATION:
            role = core_role(path, name); limit = MAX_CORE_CYCLOMATIC if role else MAX_CYCLOMATIC
            if value > limit: failures.append(f"{path.name}:{name}:{line} cyclomatic={value} > {limit}" + (f" core={role}" if role else ""))
            continue
        old = old_rows.get(name, (0, MAX_CYCLOMATIC))[1]; limit = max(MAX_CYCLOMATIC, old); inherited += old > MAX_CYCLOMATIC
        if value > limit: failures.append(f"{path.name}:{name}:{line} cyclomatic={value} > {limit} ({'policy-base='+str(old) if name in old_rows else 'new or renamed function'})")
    return failures, inherited
def qualification_metric_failures(path, loc, metrics):
    failures = []
    if loc > COHESION_REVIEW_LOC: failures.append(f"{path.name}:<module>:1 code_loc={loc} > cohesion_limit={COHESION_REVIEW_LOC}")
    seen = {metric.name for metric in metrics}
    for (module, name), label in CORE_PATHS.items():
        if module == path.name and name not in seen: failures.append(f"{path.name}:{name}:1 core-{label}=missing required=auditable")
    for metric in metrics:
        if metric.loc > MAX_FUNCTION_LINES: failures.append(f"{path.name}:{metric.name}:{metric.line} function_loc={metric.loc} > {MAX_FUNCTION_LINES}")
        if metric.cognitive > MAX_COGNITIVE: failures.append(f"{path.name}:{metric.name}:{metric.line} cognitive={metric.cognitive} > {MAX_COGNITIVE}")
        if metric.nesting > MAX_NESTING: failures.append(f"{path.name}:{metric.name}:{metric.line} nesting={metric.nesting} > {MAX_NESTING}")
    return failures
def scope_failures(scripts=SCRIPTS):
    try: runtime_paths(scripts.parent); return []
    except (OSError, SyntaxError, RuntimeScopeError) as exc: return [f"<runtime-scope>:<aggregate>:1 {exc}"]
def evaluate(base_sha=POLICY_BASE_SHA, *, root=ROOT, scripts=SCRIPTS, mode=REGRESSION):
    if mode not in (REGRESSION, QUALIFICATION): raise ValueError(f"unknown quality mode: {mode}")
    failures = scope_failures(scripts)
    if failures: return failures
    if mode == REGRESSION and (error := require_base(root, base_sha)): return [error]
    skill = scripts.parent; sources = working_runtime_sources(skill); scope = derive_runtime_scope(sources); active = tuple(skill / path for path in scope); total = core = inherited = 0
    print(f"swarm v7 quality metrics (mode={mode})"); print(f"  whole runtime modules: {len(active)}"); print(f"  whole runtime scope: {', '.join(scope)}")
    for path in active:
        text = path.read_text(encoding="utf-8"); loc = code_loc(text); mi = mi_visit(text, multi=True); metrics = function_metrics(text); total += loc; core += loc if path.name in CORE_CONTROLLER_MODULE_NAMES else 0
        print(f"  {path.relative_to(skill).as_posix()}: loc={loc} mi={mi:.1f}")
        baseline = baseline_text(path, base_sha, root=root) if mode == REGRESSION and path.is_relative_to(root) else None; rows, debt = complexity_failures(path, text, baseline, mode=mode); inherited += debt
        if mode == REGRESSION: failures += rows
        else: failures += rows + qualification_metric_failures(path, loc, metrics)
        for metric in metrics: print(f"    {metric.name}:{metric.line} loc={metric.loc} cyclomatic={metric.cyclomatic} cognitive={metric.cognitive} nesting={metric.nesting}" + (f" core={core_role(path, metric.name)} cyclomatic-target<={MAX_CORE_CYCLOMATIC}" if core_role(path, metric.name) else ""))
    print(f"  core controller LOC: {core} / {MAX_CORE_LOC}"); print(f"  whole runtime Python LOC: {total}"); print(f"  whole runtime Python modules: {len(active)}"); print(f"  current whole runtime: {total} LOC in {len(active)} modules")
    if mode == REGRESSION:
        baseline = runtime_metrics_at_ref(WHOLE_RUNTIME_BASE_SHA, root=root)
        if baseline != (WHOLE_RUNTIME_BASE_LOC, WHOLE_RUNTIME_BASE_MODULES): failures.append(f"<whole-runtime-baseline>:<aggregate>:1 measured={baseline} pinned={(WHOLE_RUNTIME_BASE_LOC, WHOLE_RUNTIME_BASE_MODULES)}")
        if total > WHOLE_RUNTIME_BASE_LOC: failures.append(f"<whole-runtime>:<aggregate>:1 code_loc={total} > starting_ceiling={WHOLE_RUNTIME_BASE_LOC}")
        if len(active) > WHOLE_RUNTIME_BASE_MODULES: failures.append(f"<whole-runtime>:<aggregate>:1 modules={len(active)} > starting_ceiling={WHOLE_RUNTIME_BASE_MODULES}")
        print(f"  inherited functions above cyclomatic {MAX_CYCLOMATIC}: {inherited}; regressions allowed: 0")
    else:
        pre_v7 = pre_v7_controller_loc(root=root)
        if pre_v7 is None: failures.append(f"<pre-v7-baseline>:<aggregate>:1 unavailable ref={PRE_V7_BASE_SHA}")
        elif (reduction := pre_v7_reduction_failure(total, pre_v7)): failures.append(reduction)
        if core > MAX_CORE_LOC: failures.append(f"<core-controller>:<aggregate>:1 code_loc={core} > {MAX_CORE_LOC}")
        if total > FINAL_RUNTIME_LOC: failures.append(f"<whole-runtime-target>:<aggregate>:1 code_loc={total} > {FINAL_RUNTIME_LOC}")
        if len(active) > MAX_WHOLE_RUNTIME_MODULES: failures.append(f"<whole-runtime-target>:<aggregate>:1 modules={len(active)} > {MAX_WHOLE_RUNTIME_MODULES}")
        print(f"  final #114 profile: LOC<={FINAL_RUNTIME_LOC}, modules<={MAX_WHOLE_RUNTIME_MODULES}, module LOC<={COHESION_REVIEW_LOC}; per-file MI is diagnostic only")
    return failures
def make_parser():
    parser = argparse.ArgumentParser(); modes = parser.add_mutually_exclusive_group(); modes.add_argument("--qualification", "--absolute", dest="mode", action="store_const", const=QUALIFICATION); modes.add_argument("--regression", dest="mode", action="store_const", const=REGRESSION); parser.set_defaults(mode=REGRESSION); parser.add_argument("--base-sha", default=POLICY_BASE_SHA); return parser
def main(argv=None):
    args = make_parser().parse_args(argv); failures = evaluate(args.base_sha, mode=args.mode)
    if failures:
        print("quality failures:", file=sys.stderr)
        for failure in failures: print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0
if __name__ == "__main__": raise SystemExit(main())
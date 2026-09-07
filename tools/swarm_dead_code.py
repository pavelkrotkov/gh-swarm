#!/usr/bin/env python3
"""AST-based dead-code checks for the swarm runtime and its tests.

The check deliberately combines two signals:
* a structural AST pass that rejects retired controllers and unreferenced pure
  compatibility facades; and
* Vulture, which uses Python's AST and catches unused imports, unreachable code,
  and unused helpers. High-confidence findings are always failures. At lower
  confidence we fail unused function/class definitions while excluding known
  unittest discovery hooks and dunder protocol methods. Tests are scanned too.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path("skills/github-project-swarm/scripts")
PLUGIN = Path("skills/github-project-swarm/hermes-plugin")
ACTIVE_ROOTS = (
    Path("src/agent_skillfleet"),
    SCRIPTS,
    PLUGIN,
    Path("skills/github-project-swarm/templates/systemd"),
    Path("bin"),
    Path("tools"),
)
AST_SCAN_ROOTS = (Path("src/agent_skillfleet"), SCRIPTS, PLUGIN, Path("tests"), Path("tools"))
RETIRED_STEMS = (
    "life" + "cycle",
    "observ" + "ability",
    "sw" + "arm",
    "swarm_v" + "6",
    "swarm_leg" + "acy",
)
RETIRED_FILENAMES = tuple(f"{name}.py" for name in RETIRED_STEMS)
TEXT_EXTENSIONS = {"", ".py", ".sh", ".yaml", ".yml", ".service", ".timer"}
VULTURE_LINE = re.compile(
    r"^(?P<path>.*?):(?P<line>\d+): (?P<what>.+?) \((?P<confidence>\d+)% confidence(?:, \d+ lines?)?\)$"
)
UNUSED_DEF = re.compile(r"unused (?P<kind>function|method|class) ['\"](?P<name>[^'\"]+)['\"]")
TEST_HOOKS = {"setUp", "tearDown", "setUpClass", "tearDownClass", "load_tests"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def active_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for relative in ACTIVE_ROOTS:
        surface = root / relative
        if surface.is_file():
            result.append(surface)
        elif surface.is_dir():
            result.extend(path for path in surface.rglob("*") if path.is_file() and not path.is_symlink())
    return sorted(set(result))


def _python_findings(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno or 1}: cannot scan invalid Python: {exc.msg}"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(part in RETIRED_STEMS for part in alias.name.split(".")):
                    findings.append(f"{path}:{node.lineno}: retired direct import {alias.name!r}")
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".") if node.module else []
            names = [alias.name for alias in node.names]
            hit = next((name for name in (*parts, *names) if name in RETIRED_STEMS), None)
            if hit:
                findings.append(f"{path}:{node.lineno}: retired direct import {hit!r}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if any(name in node.value for name in RETIRED_FILENAMES):
                findings.append(f"{path}:{getattr(node, 'lineno', 1)}: retired runtime filename in executable string")
    return findings


def _text_findings(path: Path, text: str) -> list[str]:
    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if any(name in line for name in RETIRED_FILENAMES):
            findings.append(f"{path}:{lineno}: retired runtime filename in executable text")
    return findings


def retired_findings(root: Path) -> list[str]:
    findings: list[str] = []
    active_roots = [(root / relative).resolve(strict=False) for relative in ACTIVE_ROOTS]
    for path in active_files(root):
        if path.name in RETIRED_FILENAMES and any(_inside(path, surface) for surface in active_roots):
            findings.append(f"{path.relative_to(root)}: retired runtime file still exists")
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(root)
        if relative.as_posix() == "tools/swarm_dead_code.py":
            continue
        findings.extend(_python_findings(relative, text) if path.suffix == ".py" else _text_findings(relative, text))
    return findings


def python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for relative in AST_SCAN_ROOTS:
        surface = root / relative
        if surface.is_file() and surface.suffix == ".py":
            files.append(surface)
        elif surface.is_dir():
            files.extend(surface.rglob("*.py"))
    return sorted(set(path for path in files if path.is_file() and not path.is_symlink()))


def imported_modules(paths: list[Path]) -> set[str]:
    modules: set[str] = set()
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[0])
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                modules.add(node.args[0].value.split(".")[0])
    return modules


def _is_pure_facade(tree: ast.Module) -> bool:
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if not body:
        return False
    allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign)
    return all(isinstance(node, allowed) for node in body) and any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in body)


def facade_findings(root: Path) -> list[str]:
    paths = python_files(root)
    imports = imported_modules(paths)
    findings: list[str] = []
    scripts = root / SCRIPTS
    for path in sorted(scripts.glob("swarm_v7*.py")):
        module = path.stem
        if module in imports:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        if _is_pure_facade(tree):
            findings.append(f"{path.relative_to(root)}:1: unreferenced pure compatibility/re-export facade")
    return findings


def _vulture_targets(root: Path) -> list[str]:
    return [str((root / relative).resolve()) for relative in AST_SCAN_ROOTS if (root / relative).exists()]


def _keep_low_confidence(line: str, root: Path) -> bool:
    match = VULTURE_LINE.match(line)
    if not match:
        return False
    definition = UNUSED_DEF.search(match.group("what"))
    if definition is None:
        return False
    name = definition.group("name")
    path = Path(match.group("path")).resolve(strict=False)
    tests = (root / "tests").resolve(strict=False)
    if _inside(path, tests):
        return not (name.startswith("test_") or name.startswith("Test") or name in TEST_HOOKS)
    if name.startswith("__") and name.endswith("__"):
        return False
    return True


def vulture_findings(root: Path) -> list[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "vulture", *_vulture_targets(root), "--min-confidence", "60", "--sort-by-size"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    parsed = [line.strip() for line in proc.stdout.splitlines() if VULTURE_LINE.match(line.strip())]
    if proc.returncode not in (0, 1, 3) and not parsed:
        detail = (proc.stderr or proc.stdout or "vulture failed").strip()
        return [f"vulture infrastructure failure: {detail}"]
    findings: list[str] = []
    for line in parsed:
        match = VULTURE_LINE.match(line)
        if match is None:
            continue
        confidence = int(match.group("confidence"))
        if confidence >= 90 or _keep_low_confidence(line, root):
            try:
                relative = Path(match.group("path")).resolve(strict=False).relative_to(root.resolve(strict=False))
                line = f"{relative}:{match.group('line')}: {match.group('what')} ({confidence}% confidence)"
            except ValueError:
                pass
            findings.append(line)
    return findings


def scan(root: Path = ROOT) -> list[str]:
    return [*retired_findings(root), *facade_findings(root), *vulture_findings(root)]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    root = make_parser().parse_args(argv).root.resolve()
    findings = scan(root)
    if not findings:
        print("AST dead-code boundary: clean")
        return 0
    print("AST dead-code boundary failures:", file=sys.stderr)
    for finding in findings:
        print(f"  - {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Canonical CI validation for the standalone public Swarm beta."""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
SECRET_PATTERNS=(re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),re.compile(r"\bAKIA[0-9A-Z]{16}\b"),re.compile(r"\b(?:ghp|gho|github_pat)_[A-Za-z0-9_]{20,}\b"),re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"))
def run(cmd): subprocess.run(cmd,cwd=ROOT,check=True)
def tracked(): return [ROOT/p for p in subprocess.run(["git","ls-files"],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()]
def yaml_check(paths):
    for path in paths:
        if path.suffix in {".yml",".yaml"}: yaml.safe_load(path.read_text(encoding="utf-8"))
def secret_check(paths):
    failures=[]
    for path in paths:
        try: text=path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text): failures.append(f"{path.relative_to(ROOT)}: potential secret matches {pattern.pattern}")
    if failures: raise RuntimeError("secret scan failed:\n"+"\n".join(failures))
def main():
    paths=tracked(); yaml_check(paths); secret_check(paths)
    run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_swarm*.py","-v"])
    run([sys.executable,"tools/swarm_v7_quality.py","--qualification"])
    run([sys.executable,"tools/swarm_dead_code.py"])
    for path in paths:
        if path.suffix==".sh": run(["bash","-n",str(path.relative_to(ROOT))])
    print("gh-swarm validation: clean")
    return 0
if __name__=="__main__": raise SystemExit(main())

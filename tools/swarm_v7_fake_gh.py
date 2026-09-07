#!/usr/bin/env python3
"""Deterministic GitHub CLI shim for swarm-v7 host qualification only."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import sys
import time

STATE_ENV = "SKILLFLEET_FAKE_GH_STATE"


def _state_path() -> Path:
    value = os.environ.get(STATE_ENV)
    if not value:
        raise SystemExit(f"{STATE_ENV} is required")
    return Path(value)


def _with_state(mutator):
    path = _state_path()
    with open(path, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        data = json.load(handle)
        result = mutator(data)
        handle.seek(0)
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.truncate()
        return result


def _endpoint(args: list[str]) -> str:
    ignored = {"GET", "PUT", "Accept: application/vnd.github+json"}
    for value in reversed(args[1:]):
        if value.startswith("-") or value in ignored:
            continue
        if value == "-":
            continue
        return value
    return ""


def _page_free(endpoint: str) -> str:
    return endpoint.split("?", 1)[0]


def _record_and_fault(data: dict, method: str, endpoint: str) -> None:
    data.setdefault("requests", []).append({"method": method, "endpoint": endpoint, "ts": time.time()})
    for match, message in data.get("errors", {}).items():
        if match in endpoint:
            print(message, file=sys.stderr)
            raise SystemExit(1)
    hang = data.get("hang")
    if isinstance(hang, dict) and hang.get("match") in endpoint:
        if not hang.get("once") or not hang.get("consumed"):
            hang["consumed"] = True
            time.sleep(float(hang.get("seconds", 5)))


def _issue(data: dict, number: str) -> dict:
    row = data.get("issues", {}).get(str(number))
    if not isinstance(row, dict):
        raise SystemExit(f"fake gh: unknown issue {number}")
    return row


def _pr(data: dict, number: str) -> dict:
    row = data.get("prs", {}).get(str(number))
    if not isinstance(row, dict):
        raise SystemExit(f"fake gh: unknown PR {number}")
    return row


def _issue_get(data: dict, repo: str, bits: list[str], endpoint: str):
    if bits[2:] == ["comments"]: return _pr(data, bits[1]).get("comments", [])
    issue = _issue(data, bits[1]); tail = bits[2:]
    if not tail: return issue
    if tail == ["timeline"]:
        pr = issue.get("pr")
        if not pr: return []
        return [{"event": "cross-referenced", "source": {"issue": {
            "number": int(pr), "repository_url": f"https://api.github.com/repos/{repo}",
            "pull_request": {"url": f"https://api.github.com/repos/{repo}/pulls/{pr}"},
        }}}]
    if tail == ["dependencies", "blocked_by"]: return issue.get("blocked_by", [])
    raise SystemExit(f"fake gh: unsupported GET {endpoint}")


def _pr_get(data: dict, bits: list[str], endpoint: str):
    pr = _pr(data, bits[1]); tail = bits[2:]
    if not tail: return pr
    if tail == ["reviews"]: return pr.get("reviews", [])
    if tail == ["comments"]: return pr.get("inline_comments", [])
    raise SystemExit(f"fake gh: unsupported GET {endpoint}")


def _commit_get(data: dict, bits: list[str], endpoint: str):
    if len(bits) == 3 and bits[2] == "check-runs": return {"check_runs": data.get("checks", {}).get(bits[1], [])}
    if len(bits) == 3 and bits[2] == "status": return {"statuses": data.get("statuses", {}).get(bits[1], [])}
    raise SystemExit(f"fake gh: unsupported GET {endpoint}")


def _get(data: dict, endpoint: str):
    repo = str(data["repo"])
    prefix = f"repos/{repo}"
    path = _page_free(endpoint)
    if path == prefix:
        return {"default_branch": data.get("default_branch", "main")}
    if not path.startswith(prefix + "/"):
        raise SystemExit(f"fake gh: endpoint outside fixture repo: {endpoint}")
    bits = path[len(prefix) + 1:].split("/")
    if len(bits) < 2: raise SystemExit(f"fake gh: unsupported GET {endpoint}")
    if bits[0] == "issues": return _issue_get(data, repo, bits, endpoint)
    if bits[0] == "pulls": return _pr_get(data, bits, endpoint)
    if bits[0] == "commits": return _commit_get(data, bits, endpoint)
    raise SystemExit(f"fake gh: unsupported GET {endpoint}")


def _put(data: dict, endpoint: str):
    repo = str(data["repo"])
    prefix = f"repos/{repo}/pulls/"
    path = _page_free(endpoint)
    if not path.startswith(prefix) or not path.endswith("/merge"):
        raise SystemExit(f"fake gh: unsupported PUT {endpoint}")
    number = path[len(prefix):-len("/merge")]
    pr = _pr(data, number)
    payload = json.load(sys.stdin)
    if payload.get("sha") != pr.get("head", {}).get("sha"):
        return {"merged": False, "message": "head changed"}
    pr["merged_at"] = "2026-09-04T00:00:00Z"
    pr["state"] = "closed"
    return {"merged": True, "sha": payload["sha"], "message": "merged by qualification shim"}


def main() -> int:
    args = sys.argv[1:]
    if args == ["--version"]:
        print("gh version 99.0.0 (skillfleet qualification shim)")
        return 0
    if args[:2] == ["auth", "status"]:
        print("qualification shim: authenticated")
        return 0
    if args[:2] == ["repo", "view"]:
        print(_with_state(lambda data: data["repo"]))
        return 0
    if not args or args[0] != "api":
        print(f"fake gh: unsupported command: {' '.join(args)}", file=sys.stderr)
        return 2
    method = "GET"
    if "--method" in args:
        method = args[args.index("--method") + 1].upper()
    endpoint = _endpoint(args)
    def mutate(data):
        _record_and_fault(data, method, endpoint)
        return _get(data, endpoint) if method == "GET" else _put(data, endpoint)
    value = _with_state(mutate)
    print(json.dumps(value, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

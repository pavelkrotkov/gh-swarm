#!/usr/bin/env python3
"""Black-box qualification for an installed Hermes swarm-v7 runtime."""
from __future__ import annotations
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
FAKE_GH = ROOT / "tools" / "swarm_v7_fake_gh.py"
ACTIVE = {"todo", "ready", "running", "review"}
MARKER_PREFIX = "qualification-runtime-switch"
QUAL_ASSIGNEE = "__skillfleet_qualification__"


class QualificationError(RuntimeError):
    pass


class Harness:
    def __init__(self, root: Path, *, step_timeout: float, model: str):
        self.root = root
        self.step_timeout = step_timeout
        self.model = model
        self.state_dir = root / "swarm-state"
        self.fake_state = root / "fake-github.json"
        self.log_path = root / "qualification.jsonl"
        self.bin_dir = root / "bin"
        self.boards: list[str] = []
        self.manifests: list[Path] = []
        self.origin = root / "origin.git"
        self.work = root / "work"
        self.repo = str(self.origin.resolve())
        self.env = os.environ.copy()
        self.env["HERMES_SWARM_STATE_DIR"] = str(self.state_dir)
        self.env["SKILLFLEET_FAKE_GH_STATE"] = str(self.fake_state)
        self.env["PATH"] = f"{self.bin_dir}{os.pathsep}{self.env.get('PATH', '')}"

    def setup(self) -> None:
        self.state_dir.mkdir(parents=True)
        self.bin_dir.mkdir()
        wrapper = self.bin_dir / "gh"
        wrapper.write_text(f"#!/bin/sh\nexec {shlex_quote(sys.executable)} {shlex_quote(str(FAKE_GH))} \"$@\"\n", encoding="utf-8")
        wrapper.chmod(0o755)
        self._git_fixture()
        state = {
            "repo": self.repo,
            "default_branch": "main",
            "issues": {
                str(n): {"number": n, "state": "open", "body": f"qualification issue {n}", "blocked_by": [], "pr": None}
                for n in (1, 2, 3, 4)
            },
            "prs": {}, "checks": {}, "statuses": {}, "errors": {}, "requests": [],
        }
        self._write_state(state)

    def run(self, cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
            timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        merged_env = self.env.copy()
        if env:
            merged_env.update(env)
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, env=merged_env, text=True, capture_output=True,
                timeout=timeout or self.step_timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self._event(cmd, None, "", str(exc), int((time.monotonic() - started) * 1000))
            raise QualificationError(f"step timed out: {render(cmd)}") from exc
        self._event(cmd, proc.returncode, proc.stdout, proc.stderr, int((time.monotonic() - started) * 1000))
        if check and proc.returncode:
            raise QualificationError(
                f"command failed ({proc.returncode}): {render(cmd)}\n{proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc

    def swarm(self, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
        return self.run(["hermes", "swarm", *args], **kwargs)

    def kanban(self, board: str, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
        return self.run(["hermes", "kanban", "--board", board, *args], **kwargs)

    def git(self, *args: str, cwd: Path | None = None, **kwargs) -> subprocess.CompletedProcess[str]:
        return self.run(["git", *args], cwd=cwd or self.work, **kwargs)

    def init_swarm(self, name: str, issue: int, assignee: str = QUAL_ASSIGNEE) -> tuple[Path, str]:
        board = f"{name}-{uuid.uuid4().hex[:8]}"
        proc = self.swarm(
            "init", "--repo", self.repo, "--repo-path", str(self.work), "--issues", str(issue),
            "--name", name, "--board", board, "--assignee", assignee, "--worker", self.model, "--reviewer", self.model,
            "--adjudicator", self.model, "--max-execution-attempts", "2", "--max-runtime", "5m",
            "--ci-mode", "none", "--paused",
        )
        line = next((x for x in proc.stdout.splitlines() if x.startswith("Manifest: ")), "")
        if not line:
            raise QualificationError("installed hermes swarm init did not report its manifest")
        manifest = Path(line.split(": ", 1)[1]).resolve()
        if manifest.parent != self.state_dir.resolve():
            raise QualificationError(f"swarm state escaped qualification directory: {manifest}")
        self.boards.append(board)
        self.manifests.append(manifest)
        return manifest, board

    def manifest(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_manifest(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def clear_cursors(self, path: Path) -> None:
        data = self.manifest(path)
        data["runtime"]["execution_cursors"] = {}
        self.write_manifest(path, data)

    def cursors(self, path: Path) -> dict:
        return self.manifest(path)["runtime"]["execution_cursors"]

    def one_task(self, path: Path, contains: str) -> tuple[str, dict]:
        rows = [(k, v) for k, v in self.cursors(path).items() if contains in k]
        if len(rows) != 1:
            raise QualificationError(f"expected one cursor containing {contains!r}, got {rows}")
        return rows[0][0], rows[0][1]

    def task_status(self, board: str, task_id: str) -> str:
        raw = json.loads(self.kanban(board, "show", task_id, "--json").stdout)
        task = raw.get("task", raw)
        return str(task.get("status", "")).lower()

    def task_runs(self, board: str, task_id: str) -> list:
        raw = json.loads(self.kanban(board, "runs", task_id, "--json").stdout or "[]")
        return list(raw.get("runs", raw.get("task_runs", ())) if isinstance(raw, dict) else raw)

    def fake(self) -> dict:
        return json.loads(self.fake_state.read_text(encoding="utf-8"))

    def mutate_fake(self, fn) -> None:
        data = self.fake()
        fn(data)
        self._write_state(data)

    def add_pr(self, issue: int, number: int, head: str, branch: str) -> None:
        def mutate(data):
            data["issues"][str(issue)]["pr"] = number
            data["prs"][str(number)] = {
                "number": number, "html_url": f"https://qualification.invalid/pr/{number}",
                "state": "open", "base": {"ref": "main"}, "head": {"sha": head, "ref": branch},
                "draft": False, "mergeable": True, "mergeable_state": "clean",
                "merged_at": None, "labels": [], "reviews": [], "comments": [],
            }
        self.mutate_fake(mutate)

    def publish_review(self, pr: int, swarm: str, issue: int, head: str, slot: int = 1) -> None:
        marker = f"<!-- hermes-swarm-review:{swarm}:{issue}:v{slot}:{head} -->"
        self.mutate_fake(lambda data: data["prs"][str(pr)]["reviews"].append(
            {"id": 1000 + len(data["prs"][str(pr)]["reviews"]), "commit_id": head, "body": marker}
        ))

    def publish_adjudication(self, pr: int, swarm: str, issue: int, head: str) -> None:
        payload = base64.urlsafe_b64encode(
            json.dumps({"decision": "accept", "head_sha": head, "comment_dispositions": [], "required_changes": []}, separators=(",", ":")).encode()
        ).decode()
        body = (
            f"<!-- hermes-swarm-adjudication:{swarm}:{issue}:{head} -->\n"
            f"<!-- hermes-swarm-decision-b64:{payload} -->"
        )
        self.mutate_fake(lambda data: data["prs"][str(pr)]["comments"].append(
            {"id": 2000 + len(data["prs"][str(pr)]["comments"]), "body": body}
        ))

    def commit_push(self, worktree: Path, branch: str, label: str) -> str:
        target = worktree / f"{label}.txt"
        target.write_text(label + "\n", encoding="utf-8")
        self.git("add", target.name, cwd=worktree)
        self.git("commit", "-m", label, cwd=worktree)
        head = self.git("rev-parse", "HEAD", cwd=worktree).stdout.strip()
        self.git("push", "origin", f"HEAD:refs/heads/{branch}", cwd=worktree)
        return head

    def cleanup(self) -> None:
        for board in reversed(self.boards):
            self.run(["hermes", "kanban", "boards", "rm", board, "--delete"], check=False, timeout=10)
        for path in self.manifests:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def _git_fixture(self) -> None:
        seed = self.root / "seed"
        self.run(["git", "init", "--bare", str(self.origin)])
        self.run(["git", "init", "-b", "main", str(seed)])
        self.run(["git", "config", "user.name", "Skillfleet Qualification"], cwd=seed)
        self.run(["git", "config", "user.email", "qualification@example.invalid"], cwd=seed)
        (seed / "README.md").write_text("qualification\n", encoding="utf-8")
        self.run(["git", "add", "README.md"], cwd=seed)
        self.run(["git", "commit", "-m", "fixture"], cwd=seed)
        self.run(["git", "remote", "add", "origin", str(self.origin)], cwd=seed)
        self.run(["git", "push", "-u", "origin", "main"], cwd=seed)
        self.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=self.origin)
        self.run(["git", "clone", str(self.origin), str(self.work)])
        self.run(["git", "config", "user.name", "Skillfleet Qualification"], cwd=self.work)
        self.run(["git", "config", "user.email", "qualification@example.invalid"], cwd=self.work)

    def _write_state(self, data: dict) -> None:
        self.fake_state.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _event(self, cmd, rc, stdout, stderr, elapsed_ms) -> None:
        event = {
            "ts": time.time(), "command": cmd, "returncode": rc, "elapsed_ms": elapsed_ms,
            "stdout": stdout[-8000:], "stderr": stderr[-8000:],
        }
        with open(self.log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")


def shlex_quote(value: str) -> str:
    import shlex
    return shlex.quote(value)


def render(cmd: list[str]) -> str:
    return " ".join(shlex_quote(x) for x in cmd)


def assert_true(value, message: str) -> None:
    if not value:
        raise QualificationError(message)


def contract_probes(h: Harness) -> None:
    h.run(["hermes", "--version"])
    help_text = h.swarm("--help").stdout
    for command in ("init", "status", "reconcile", "pause", "resume", "doctor", "validate", "explain", "prepare", "activate", "disable"):
        assert_true(command in help_text, f"hermes swarm --help is missing {command}")
    h.run(["git", "--version"])
    h.run(["hermes", "kanban", "boards", "list", "--json"])
    create_help = h.run(["hermes", "kanban", "create", "--help"]).stdout
    for flag in ("--body", "--workspace", "--branch", "--idempotency-key", "--max-retries", "--max-runtime", "--assignee", "--model"):
        assert_true(flag in create_help, f"Hermes Kanban create contract missing {flag}")
    probe = f"qual-probe-{uuid.uuid4().hex[:8]}"
    h.run(["hermes", "kanban", "boards", "create", probe, "--name", "Skillfleet qualification probe"])
    h.boards.append(probe)
    args = [
        "create", "qualification contract probe", "--body", "no execution", "--workspace", f"dir:{h.work}",
        "--triage", "--idempotency-key", f"qualification:{uuid.uuid4().hex}", "--max-retries", "1",
        "--max-runtime", "1m", "--model", h.model, "--json",
    ]
    first = json.loads(h.kanban(probe, *args).stdout)
    second = json.loads(h.kanban(probe, *args).stdout)
    first_id = str(first.get("task", first).get("id") or first.get("task", first).get("task_id"))
    second_id = str(second.get("task", second).get("id") or second.get("task", second).get("task_id"))
    assert_true(first_id and first_id == second_id, "Hermes Kanban idempotency contract failed")
    assert_true(h.task_status(probe, first_id) == "triage", "qualification probe did not preserve triage status")
    h.kanban(probe, "runs", first_id, "--json")
    h.kanban(probe, "archive", first_id)


def dispatcher_scenario(h: Harness, assignee: str, observe_seconds: float) -> None:
    swarm = f"dispatcher-{uuid.uuid4().hex[:6]}"
    manifest, board = h.init_swarm(swarm, 1, assignee)
    h.swarm("resume", "--name", swarm)
    h.swarm("reconcile", "--name", swarm)
    _, cursor = h.one_task(manifest, ":implementation")
    task = str(cursor["task_id"]); deadline = time.monotonic() + observe_seconds
    while time.monotonic() < deadline and not h.task_runs(board, task): time.sleep(1)
    assert_true(bool(h.task_runs(board, task)), f"dispatcher did not create a worker run within {observe_seconds:g}s for assignee {assignee}")
    assert_true(h.task_status(board, task) not in {"todo", "ready"}, "worker run exists but dispatcher did not claim the swarm task")


def recovery_scenario(h: Harness) -> None:
    swarm = f"recovery-{uuid.uuid4().hex[:6]}"
    manifest, board = h.init_swarm(swarm, 1)
    h.swarm("status", "--name", swarm)
    branch = f"swarm/{swarm}/1"
    worktree = h.work.parent / f".{h.work.name}-swarm-worktrees" / f"{swarm}-1"
    assert_true(h.git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 1,
                "paused swarm created a branch")
    h.swarm("resume", "--name", swarm)
    h.swarm("reconcile", "--name", swarm)
    _, first = h.one_task(manifest, ":implementation")
    task1 = str(first["task_id"])
    assert_true(h.task_status(board, task1) in ACTIVE,
                "controller task became terminal; run qualification with the gateway/dispatcher inactive")
    h.clear_cursors(manifest)
    h.swarm("reconcile", "--name", swarm)
    _, replay = h.one_task(manifest, ":implementation")
    assert_true(str(replay["task_id"]) == task1, "crash-before-persistence duplicated the implementation task")

    h.git("push", "origin", f"{branch}:refs/heads/{branch}")
    h.kanban(board, "block", task1, "qualification retry")
    h.git("worktree", "remove", "--force", str(worktree))
    h.swarm("reconcile", "--name", swarm)
    assert_true(worktree.is_dir(), "durable branch did not reconstruct the missing worktree")
    _, retry = h.one_task(manifest, ":implementation")
    task2 = str(retry["task_id"])
    head = h.commit_push(worktree, branch, "durable-publication")
    h.kanban(board, "block", task2, "terminal after durable publication")
    h.add_pr(1, 101, head, branch)
    h.clear_cursors(manifest)
    h.swarm("reconcile", "--name", swarm)
    _, review = h.one_task(manifest, f":review:v1:{head}")
    review_task = str(review["task_id"])

    h.publish_review(101, swarm, 1, head)
    h.kanban(board, "block", review_task, "review publication survived")
    h.clear_cursors(manifest)
    h.swarm("reconcile", "--name", swarm)
    _, adjudication = h.one_task(manifest, f":adjudication:{head}")
    adj_task = str(adjudication["task_id"])

    h.publish_adjudication(101, swarm, 1, head)
    h.kanban(board, "block", adj_task, "adjudication publication survived")
    h.clear_cursors(manifest)
    h.swarm("reconcile", "--name", swarm)
    assert_true(h.fake()["prs"]["101"].get("merged_at"), "durable adjudication did not converge to merge")


def exact_head_visibility_scenario(h: Harness) -> None:
    swarm = f"headlag-{uuid.uuid4().hex[:6]}"
    manifest, _board = h.init_swarm(swarm, 2)
    branch = f"swarm/{swarm}/2"
    worktree = h.work.parent / f".{h.work.name}-swarm-worktrees" / f"{swarm}-2"
    h.swarm("resume", "--name", swarm)
    h.swarm("reconcile", "--name", swarm)
    h1 = h.commit_push(worktree, branch, "head-one")
    h.add_pr(2, 102, h1, branch)
    h.swarm("reconcile", "--name", swarm)
    h.publish_review(102, swarm, 2, h1)
    h2 = h.commit_push(worktree, branch, "head-two")
    lag = h.swarm("status", "--name", swarm).stdout
    assert_true(h1[:12] in lag, "visibility-delay probe did not observe the lagging GitHub head")
    h.mutate_fake(lambda data: data["prs"]["102"]["head"].update({"sha": h2}))
    h.clear_cursors(manifest)
    h.swarm("reconcile", "--name", swarm)
    keys = h.cursors(manifest)
    assert_true(any(f":review:v1:{h2}" in key for key in keys), "new exact head did not get a new reviewer slot")
    assert_true(not any(f":review:v1:{h1}" in key for key in keys), "stale-head cursor survived empty-cursor restart")


def cross_reference_attribution_scenario(h: Harness) -> None:
    swarm = f"xref-{uuid.uuid4().hex[:6]}"
    h.init_swarm(swarm, 4)
    h.add_pr(4, 104, "4" * 40, f"swarm/{swarm}/3")
    h.mutate_fake(lambda data: data["prs"]["104"].update({"state": "closed", "merged_at": "2026-09-05T00:00:00Z"}))
    status = h.swarm("status", "--name", swarm).stdout
    assert_true("NEEDS_IMPLEMENTATION" in status and "MERGED" not in status, "merged sibling cross-reference was attributed to an open issue")


def isolation_and_timeout_scenario(h: Harness) -> None:
    swarm = f"isolation-{uuid.uuid4().hex[:6]}"
    manifest, _board = h.init_swarm(swarm, 3)
    h.swarm("resume", "--name", swarm)
    lock_name = next(path.stem for path in h.manifests if "recovery-" in path.stem)
    lock = h.state_dir / f".reconcile.{lock_name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = h.swarm("reconcile", "--all", check=False)
    assert_true("already running; skipped" in proc.stderr, "per-swarm lock contention was not isolated")
    assert_true(bool(h.cursors(manifest)), "unrelated swarm did not progress while another lock was held")

    before = (h.state_dir / f"{swarm}.journal.jsonl").stat().st_size
    h.mutate_fake(lambda data: data["errors"].update({"/issues/1": "qualification injected GitHub failure"}))
    proc = h.swarm("reconcile", "--all", check=False)
    h.mutate_fake(lambda data: data["errors"].pop("/issues/1", None))
    assert_true(proc.returncode != 0, "injected swarm failure did not surface")
    after = (h.state_dir / f"{swarm}.journal.jsonl").stat().st_size
    assert_true(after > before, "one swarm failure prevented unrelated swarm observation")

    h.mutate_fake(lambda data: data.update({"hang": {"match": "/issues/3", "seconds": 5, "once": True}}))
    started = time.monotonic()
    proc = h.swarm(
        "status", "--name", swarm, check=False, timeout=3,
        env={"HERMES_SWARM_SUBPROCESS_TIMEOUT": "0.2"},
    )
    elapsed = time.monotonic() - started
    assert_true(proc.returncode == 0 and elapsed < 2.5 and "EXECUTION_STALLED action=none" in proc.stdout, "hung subprocess did not return bounded stalled status")
    h.mutate_fake(lambda data: data.pop("hang", None))


def systemd_contract(h: Harness) -> str | None:
    probe = h.run(["systemctl", "--user", "show-environment"], check=False, timeout=5)
    if probe.returncode:
        return None
    for unit in ("hermes-swarm-reconcile.timer", "hermes-swarm-reconcile.service"):
        active = h.run(["systemctl", "--user", "is-active", "--quiet", unit], check=False, timeout=5)
        assert_true(active.returncode != 0, f"{unit} must be inactive on the qualification host")
    service = h.run(["systemctl", "--user", "cat", "hermes-swarm-reconcile.service"], timeout=5).stdout
    assert_true("hermes swarm reconcile --all" in service, "systemd service does not invoke native swarm command")
    assert_true("TimeoutStartSec=" in service and "infinity" not in service.lower(), "systemd service timeout is not finite")
    assert_true("hermes-gateway.service" not in service, "swarm systemd unit references Hermes gateway")
    return h.run(
        ["systemctl", "--user", "show", "hermes-gateway.service", "-p", "ActiveState", "-p", "ExecMainPID"],
        check=False, timeout=5,
    ).stdout


def runtime_switch_probe(h: Harness, runtime_root: Path) -> None:
    current = runtime_root / "current"
    assert_true(current.is_symlink(), f"Skillfleet active runtime is not an atomic current symlink: {current}")
    active = current.resolve()
    meta = active / ".skillfleet-meta" / "github-project-swarm.json"
    cli = active / "github-project-swarm" / "scripts" / "swarm_v7_cli.py"
    assert_true(meta.is_file() and cli.is_file(), "active runtime lacks Skillfleet swarm provenance/runtime")
    candidate = runtime_root / f".qualification-{uuid.uuid4().hex}"
    marker = f"{MARKER_PREFIX}-{uuid.uuid4().hex[:8]}"
    shutil.copytree(active, candidate, symlinks=True)
    candidate_cli = candidate / "github-project-swarm" / "scripts" / "swarm_v7_cli.py"
    text = candidate_cli.read_text(encoding="utf-8")
    needle = 'print("prepare: schema 7 needs no prompt/profile projection; execution artifacts are prepared lazily")'
    assert_true(needle in text, "installed runtime prepare contract changed unexpectedly")
    candidate_cli.write_text(text.replace(needle, f'print("{marker}")', 1), encoding="utf-8")
    original = os.readlink(current)
    try:
        atomic_symlink(candidate, current)
        assert_true(marker in h.swarm("prepare").stdout, "hermes swarm did not follow the atomically switched runtime")
    finally:
        atomic_symlink(Path(original) if os.path.isabs(original) else current.parent / original, current)
    assert_true(marker not in h.swarm("prepare").stdout, "hermes swarm did not return to the restored active runtime")
    shutil.rmtree(candidate)


def atomic_symlink(target: Path, link: Path) -> None:
    tmp = link.parent / f".{link.name}.qualification-{uuid.uuid4().hex}"
    os.symlink(str(target), tmp)
    os.replace(tmp, link)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step-timeout", type=float, default=30)
    parser.add_argument("--overall-timeout", type=int, default=300)
    parser.add_argument("--model", default=os.environ.get("HERMES_SWARM_QUAL_MODEL", "__skillfleet_qualification__"))
    parser.add_argument("--runtime-root", type=Path, default=None)
    parser.add_argument("--dispatcher-only", action="store_true")
    parser.add_argument("--dispatcher-assignee", default=os.environ.get("HERMES_SWARM_QUAL_ASSIGNEE"))
    parser.add_argument("--dispatcher-observe-seconds", type=float, default=60)
    parser.add_argument("--keep-artifacts", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.step_timeout <= 0 or args.overall_timeout <= 0 or args.dispatcher_observe_seconds <= 0:
        raise SystemExit("timeouts must be positive")
    if args.dispatcher_only and not args.dispatcher_assignee:
        raise SystemExit("--dispatcher-only requires --dispatcher-assignee or HERMES_SWARM_QUAL_ASSIGNEE")
    runtime_root = args.runtime_root or Path(
        os.environ.get("AGENT_SKILLFLEET_RUNTIME", Path.home() / ".local" / "share" / "agent-skillfleet-runtime")
    )
    root = Path(tempfile.mkdtemp(prefix="skillfleet-swarm-v7-qualification-"))
    h = Harness(root, step_timeout=args.step_timeout, model=args.model)
    succeeded = False

    def alarm(_signum, _frame):
        raise QualificationError(f"overall qualification timeout exceeded ({args.overall_timeout}s)")

    signal.signal(signal.SIGALRM, alarm)
    signal.alarm(args.overall_timeout)
    gateway_before = None
    try:
        h.setup()
        gateway_before = systemd_contract(h)
        contract_probes(h)
        assert_true("prepare:" in h.swarm("prepare").stdout, "installed Skillfleet swarm runtime did not execute")
        if args.dispatcher_only:
            dispatcher_scenario(h, args.dispatcher_assignee, args.dispatcher_observe_seconds)
        else:
            recovery_scenario(h)
            exact_head_visibility_scenario(h)
            cross_reference_attribution_scenario(h)
            isolation_and_timeout_scenario(h)
            runtime_switch_probe(h, runtime_root.expanduser().resolve())
        if gateway_before is not None:
            gateway_after = h.run(
                ["systemctl", "--user", "show", "hermes-gateway.service", "-p", "ActiveState", "-p", "ExecMainPID"],
                check=False, timeout=5,
            ).stdout
            assert_true(gateway_before == gateway_after, "qualification changed hermes-gateway.service state")
        succeeded = True
        print("swarm-v7 dispatcher qualification: PASS" if args.dispatcher_only else "swarm-v7 host qualification: PASS")
        return 0
    except Exception as exc:
        label = "dispatcher" if args.dispatcher_only else "host"
        print(f"swarm-v7 {label} qualification: FAIL: {exc}", file=sys.stderr)
        print(f"diagnostics preserved at: {root}", file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
        try:
            h.cleanup()
        except Exception as cleanup_exc:
            print(f"cleanup warning: {cleanup_exc}", file=sys.stderr)
        if succeeded and not args.keep_artifacts:
            shutil.rmtree(root, ignore_errors=True)
        elif succeeded:
            print(f"diagnostics kept at: {root}")


if __name__ == "__main__":
    raise SystemExit(main())
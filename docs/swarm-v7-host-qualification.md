# Swarm v7 host qualification

Issue #54 adds a **host qualification** suite for the installed schema-7 swarm runtime. It is deliberately separate from the fast repository unit tests because it exercises the real Hermes CLI, the real Hermes Kanban database/CLI, real git branches/worktrees, the installed native swarm plugin, and Skillfleet `runtime/current`.

Run the complete recovery qualification on a dedicated Hermes host:

```bash
make qualify-swarm-host
```

The default command is the release gate for recovery/runtime behavior. A passing run proves the scenarios below against the installed runtime; it is not a substitute for `make test`, and `make test` never invokes it.

Run the dispatcher liveness gate separately with the gateway active and a real worker assignee:

```bash
HERMES_SWARM_QUAL_ASSIGNEE=sat-swarm \
HERMES_SWARM_QUAL_MODEL='<dispatchable-model>' \
make qualify-swarm-dispatcher
```

This creates one paused swarm, resumes/reconciles it, and requires the dispatched implementation task to leave `todo`/`ready` and gain a Kanban `task_runs` row within 60 seconds. Override the window with `--dispatcher-observe-seconds`. The runner never starts or stops the gateway.

## Preconditions

- `hermes`, `git`, and user-level Skillfleet deployment are installed.
- `runtime/current` is the active Skillfleet runtime and exposes `github-project-swarm`.
- The native `hermes swarm ...` plugin from that runtime is installed.
- `hermes-swarm-reconcile.timer` and `hermes-swarm-reconcile.service` are **inactive**. The suite refuses to stop them for you.
- For `make qualify-swarm-host`, the Hermes gateway/dispatcher should be inactive so qualification tasks remain execution facts rather than actually launching models. The suite never starts or stops the gateway; if a test task becomes terminal unexpectedly, the run fails with this prerequisite.
- For `make qualify-swarm-dispatcher`, the gateway/dispatcher must be active and `HERMES_SWARM_QUAL_ASSIGNEE` must name a worker identity it can claim. The selected model must be dispatchable on that host.
- The active runtime root is `${AGENT_SKILLFLEET_RUNTIME:-~/.local/share/agent-skillfleet-runtime}`. Override it with `--runtime-root` when the host uses a nonstandard location.

No live GitHub repository or GitHub credentials are required. The suite puts a deterministic `gh` shim first on `PATH`, exactly at the v7 GitHub adapter process boundary. It does **not** replace the planner/controller, Hermes/Kanban, git/worktree execution, plugin discovery, or Skillfleet runtime switching.

For the recovery qualification, `HERMES_SWARM_QUAL_MODEL` may be any syntactically valid model because the gateway must remain inactive. For the dispatcher gate, it must resolve to a model the configured assignee can actually launch.

## What is exercised

The runner probes `hermes --version`, `hermes swarm --help`, the Kanban create/show/runs/status surface, real idempotent creation, `dir:` workspace persistence, git/worktree behavior, and the installed systemd service contract when a user systemd manager is available. The service must call `hermes swarm reconcile --all`, have a finite timeout, and contain no gateway lifecycle action.

The dispatcher mode additionally verifies the production dispatch boundary: the swarm supplies an explicit `--assignee`, the in-gateway dispatcher claims the task, and a worker run record appears inside the observe window. This prevents an ACTIVE semantic key from silently retaining an empty `task_runs` history.

Crash/restart qualification then covers:

1. paused initialization is observation/configuration only;
2. task creation followed by a simulated crash before the task cursor reaches durable manifest state;
3. idempotent replay without duplicate semantic work;
4. missing worktree reconstruction from a durable deterministic branch;
5. implementation commit/push plus PR publication surviving controller cursor loss and terminal worker state;
6. exact-head reviewer publication surviving task failure/restart;
7. exact-head adjudication publication surviving task failure/restart and converging to merge;
8. GitHub PR-head visibility lag followed by a new exact-head reviewer slot;
9. empty/stale execution cursors losing to durable GitHub facts;
10. bounded GitHub subprocess hang/timeout behavior;
11. per-swarm reconcile lock contention;
12. one swarm failure while another swarm still observes/progresses;
13. installed command resolution following an atomic `runtime/current` switch and returning to the original runtime after restoration.

The runtime-switch probe copies the active immutable release into a temporary sibling release, adds a one-line marker to that **test copy**, atomically redirects `runtime/current`, invokes installed `hermes swarm prepare`, restores the original symlink in a `finally` block, verifies the marker disappears, and removes the test release. It never edits the source checkout or the active release.

## Isolation, cleanup, and diagnostics

Each run creates a directory named like:

```text
/tmp/skillfleet-swarm-v7-qualification-...
```

`HERMES_SWARM_STATE_DIR` points swarm manifests and journals into that directory without relocating `HERMES_HOME`, so the installed plugin remains the one under test. Kanban boards receive randomized names and are hard-deleted during cleanup. Git repositories, worktrees, fake GitHub state, and structured command logs are temporary.

On success the temporary directory is removed unless `--keep-artifacts` is passed. On failure, the runner still removes its temporary Kanban boards/manifests but preserves the temporary directory with `qualification.jsonl`, fake-GitHub request history/state, and git/worktree evidence, and prints its location.

Every external command has a per-step timeout (default 30 seconds) and the complete run has a hard timeout (default 300 seconds). The injected hang probe lowers the live swarm subprocess timeout to verify that a stuck GitHub subprocess fails boundedly instead of hanging reconciliation.

The suite never calls `hermes swarm activate`, never enables the timer, and never performs a gateway lifecycle action. When user systemd is available it snapshots the gateway service state before/after the run and fails if that state changes.

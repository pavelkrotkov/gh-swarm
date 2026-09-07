# Hermes Kanban contract used by swarm v7

Swarm v7 uses two cohesive execution-boundary modules:

- `swarm_v7_execution.py` owns immutable task identity/specification and the durable worker handoff contract.
- `swarm_v7_kanban.py` owns Hermes command transport and execution-status observation only.

## Probed CLI surface

`KanbanAdapter.probe_contract()` records `hermes --version` and verifies the commands the runtime actually uses:

```text
hermes kanban boards list --json
hermes kanban --board BOARD create --help
hermes kanban --board BOARD show --help
```

The create help must expose every flag the adapter uses:

```text
--body
--workspace
--branch
--idempotency-key
--max-retries
--max-runtime
--assignee
--skill
--model
--provider
```

Normal execution uses:

```text
hermes kanban --board BOARD create TITLE ... --idempotency-key KEY --json
hermes kanban --board BOARD show TASK --json
```

Command execution reuses the repository's shared bounded subprocess runner rather than maintaining a second process implementation.

## Task response contract

Create/show responses may expose the task directly or under a `task` object. A task ID is read from `id`, `task_id`, or `taskId`; `show` must provide a task `status`.

## Explicit status mapping

The supported Hermes status vocabulary is:

| Hermes status | V7 execution fact |
| --- | --- |
| `todo` | active |
| `ready` | active |
| `running` | active |
| `review` | active |
| `done` | success |
| `blocked` | failure |
| `archived` | failure |
| `triage` | failure |

Any other status is an unsafe/unknown execution observation and raises `UnknownKanbanStatus`; it is never guessed into success.

## Workspace and graph rules

The Hermes contract permits `--branch` only for a workspace whose value begins with `worktree`. In particular, `dir:...` plus `--branch` is rejected locally before Hermes is invoked.

The execution boundary intentionally has no parent/dependency argument. One Kanban card is one implementation, reviewer-slot, adjudication, or revision operation. Workflow dependencies remain GitHub/controller observations rather than a child Kanban graph.

## Idempotency and retries

Semantic keys contain durable workflow facts:

```text
swarm:SWARM:issue:N:implementation
swarm:SWARM:issue:N:review:vS:FULL_HEAD_SHA
swarm:SWARM:issue:N:adjudication:FULL_HEAD_SHA
swarm:SWARM:issue:N:revision:TRIGGERING_FULL_HEAD_SHA
```

Attempt 1 uses the semantic key directly. A bounded replay uses `:a2`, `:a3`, and so on. Reissuing the same semantic/attempt key relies on Hermes' `--idempotency-key` contract to return the existing task, so a controller crash after create but before local persistence does not duplicate work.

Task failure remains only an execution fact. Callers must check durable GitHub/git artifacts before deciding whether a failed attempt needs replay; the execution boundary never marks issues, dependencies, reviews, or merge authority semantically blocked.

## Worker handoff authority

The worker handoff contract still requires implementation/revision workers to commit intended changes, push the deterministic branch, create or reuse exactly one non-draft PR, and verify the published PR's full head SHA. Those Git/GitHub artifacts remain the durable handoff; Kanban success is never semantic completion.

---
name: github-project-swarm
description: Run a durable Hermes coding swarm from GitHub issues using GitHub-native dependencies, deterministic git bases, exact-head review/adjudication, explicit CI policy, Kanban execution, and exact-SHA automatic merge.
license: MIT
compatibility: Requires Hermes Agent with Kanban, Git, authenticated GitHub CLI, ponytail, github-project-reviewer, and github-project-adjudicator.
---

# GitHub Project Swarm

Schema 7 through native `hermes swarm ...` is the only supported runtime. Skillfleet `runtime/current` is the sole controller source and must be in Hermes `skills.external_dirs`. If the command is missing, run `bash <skill-dir>/scripts/bootstrap.sh` from the active runtime. Bootstrap installs only the Hermes plugin and user-systemd units, never a second skill copy.

The plugin accepts only a Skillfleet-provenanced `github-project-swarm` root and fails closed if none or multiple are visible. Bootstrap archives the exact old Skillfleet-managed local shadow and preserves unmanaged content.

Lifecycle:

```bash
hermes swarm validate --repo OWNER/REPO
hermes swarm prepare
hermes swarm activate
hermes swarm disable
```

Bootstrap is inert: it never reconciles, dispatches, enables the timer, or touches `hermes-gateway.service`, and refuses plugin/unit replacement while reconciliation is active. `doctor` and `validate` are read-only. External subprocesses are bounded; reconciliation uses per-swarm locks.

## Authority model

- GitHub owns issue/dependency state, PR/head/base, exact-head review/adjudication, CI, mergeability, and merge completion.
- Remote git/PR head is durable implementation state; Kanban tasks and worktrees are disposable execution state.
- Native GitHub `blocked by` is the dependency graph; downstream waits for confirmed predecessor merge.
- Review/adjudication markers use the full 40-character PR-head SHA.
- Merge re-reads head, publications, adjudication, CI, mergeability, pause, and no-merge policy. Only observed `merged_at` releases dependencies.
- The schema-7 manifest stores configuration and bounded execution cursors, never projected lifecycle/acceptance state.

Schema 5/6 manifests are not migrated or interpreted; initialize a fresh v7 swarm.

## Initialize

```bash
hermes swarm init --epic 42 \
  --assignee swarm-worker \
  --worker 'model --provider provider' \
  --reviewer 'model-a --provider provider-a' \
  --reviewer 'model-b --provider provider-b' \
  --ci-mode required
```

`--assignee` is the Hermes worker identity that the in-gateway Kanban dispatcher can claim; it is persisted and applied to implementation, revision, review, and adjudication tasks. Use `--paused` for configuration without dispatch. `--ci-mode required` fails closed on zero/pending/failing checks; use `none` only when CI is intentionally absent.

## Operate and diagnose

```bash
hermes swarm doctor --repo OWNER/REPO
hermes swarm reconcile --dry-run --name <swarm>
hermes swarm explain --name <swarm> --issue <n> --json
hermes swarm status --all
hermes swarm reconcile --all
hermes swarm pause --name <swarm>
hermes swarm resume --name <swarm>
```

Dry-run, explain, logging, and real reconcile use the same v7 plan. Dry-run/explain re-read GitHub and execution evidence but never save, dispatch, publish, or merge. Real reconciliation applies at most one planned action per issue.

Recovery is artifact-first and bounded: implementation uses git/PR evidence; reviewer/adjudicator recovery uses exact-head GitHub publications and idempotent Kanban keys. Exhausted attempts become fail-closed `EXECUTION_STALLED`. An ACTIVE task with no worker run by the next reconcile also fails closed instead of starving indefinitely.

The active implementation is `scripts/swarm_v7_cli.py` plus `swarm_v7*.py`. Historical schema-5/6 documents do not authorize the live runtime.

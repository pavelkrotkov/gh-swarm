---
name: github-project-swarm
description: Run a durable Hermes coding swarm from GitHub issues using GitHub-native dependencies, deterministic git bases, exact-head review/adjudication, explicit CI and merge policies, Kanban execution, and exact-SHA automatic merge.
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
- Merge re-reads head, publications, adjudication, CI, mergeability, pause, no-merge labels, and the per-swarm merge policy. `automatic` authorizes the controller only after every current-head gate passes; `manual` never authorizes a controller merge. Only observed `merged_at` releases dependencies.
- The schema-7 manifest stores configuration, explicit operator retire dispositions, and bounded execution cursors, never projected lifecycle/acceptance state.

Schema 5/6 manifests are not migrated or interpreted; initialize a fresh v7 swarm.

## Initialize

```bash
hermes swarm init --epic 42 \
  --assignee swarm-worker \
  --worker 'model --provider provider' \
  --reviewer 'model-a --provider provider-a' \
  --reviewer 'model-b --provider provider-b' \
  --ci-mode required \
  --merge-policy automatic
```

`--assignee` is the Hermes worker identity that the in-gateway Kanban dispatcher can claim; it is persisted and applied to implementation, revision, review, and adjudication tasks. `--merge-policy automatic|manual` is required on new swarms. Automatic mode may merge only after every fresh current-head gate passes; manual mode continues implementation/revision/review/adjudication and then reports `AWAITING_MANUAL_MERGE`. Use `--paused` for configuration without dispatch or merge. `--ci-mode required` fails closed on zero/pending/failing checks; use `none` only when CI is intentionally absent.

Existing schema-7 manifests without `merge_policy` migrate fail-closed to `manual`; no automatic authority is granted. Persist the intended policy explicitly with `hermes swarm merge-policy --name <swarm> manual|automatic` before relying on automatic merge.

## Operate and diagnose

```bash
hermes swarm doctor --repo OWNER/REPO
hermes swarm reconcile --dry-run --name <swarm>
hermes swarm explain --name <swarm> --issue <n> --json
hermes swarm retire --name <swarm> --issue <n> --reason 'closed outside the swarm'
hermes swarm merge-policy --name <swarm> automatic
hermes swarm status --all
hermes swarm reconcile --all
hermes swarm pause --name <swarm>
hermes swarm resume --name <swarm>
```

Dry-run, explain, logging, and real reconcile use the same v7 plan. Dry-run/explain re-read GitHub and execution evidence but never save, dispatch, publish, or merge. Real reconciliation applies at most one planned action per issue. Before any planned merge, reconciliation reloads the manifest under the per-swarm lock and replans, invalidating stale policy or head decisions. Retire explicitly removes an issue from active scope, records the reason in the runtime manifest and journal, and keeps it in dependency observation until GitHub confirms a merged predecessor PR.

Recovery is artifact-first and bounded per reconcile: implementation uses git/PR evidence; reviewer/adjudicator recovery uses exact-head GitHub publications and idempotent Kanban keys. Blocked attempts keep their immutable keys; later reconciles advance to the next `:aN` key, one fresh attempt after the configured initial bound, so transient provider failures can recover without operator state edits. Archived/triage failures still fail closed. A newly created ACTIVE task may remain `RUNNING` without a worker run for up to the persisted 300-second startup grace; after that it fails closed, and missing/future creation timestamps fail closed immediately.

The active implementation is `scripts/swarm_v7_cli.py` plus `swarm_v7*.py`. Historical schema-5/6 documents do not authorize the live runtime.

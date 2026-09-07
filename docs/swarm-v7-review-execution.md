# Swarm v7 exact-head review execution

Issue #49 makes review and adjudication durable semantic slots keyed by the exact PR head.
The execution layer is `skills/github-project-swarm/scripts/swarm_v7_review.py`.

## Identity

Reviewer slots use:

```text
swarm:SWARM:issue:N:review:vS:FULL_HEAD_SHA
```

Adjudication uses:

```text
swarm:SWARM:issue:N:adjudication:FULL_HEAD_SHA
```

Execution replacements add only `:a2`, `:a3`, and so on. They do not create semantic
review rounds.

## Durable satisfaction

GitHub publication is checked before Kanban task state. A valid exact-head reviewer or
adjudication publication satisfies its semantic slot even if the corresponding task later
ends in a failure status.

Without a publication:

- an active task remains active;
- a successful task enters publication-wait and is only re-observed on later reconciles;
- a failed task may receive the next bounded execution attempt for the same semantic key;
- exhausting bounded attempts stalls that execution slot without poisoning GitHub
  dependency truth.

There is no reconcile-tick counter or elapsed-time inference.

## Worktree independence

Review and adjudication cards run from a stable `dir:` launcher workspace and receive no
branch argument. Their contracts require GitHub PR/API inspection of the exact full head.
If local source is necessary, the agent creates a disposable detached checkout of the
target SHA. The implementation worktree can disappear without invalidating review or
adjudication.

## Head drift

When a PR advances from H1 to H2, H1 task/publication facts become historical. H2 gets new
reviewer semantic keys automatically. Adjudication is eligible only after every configured
reviewer publication for H2 is durable.

## Revision budget

Any bounded autonomous revision budget is derived from normalized durable adjudication
history by counting unique exact-head `REVISE` decisions. No local manifest lifecycle
counter is required or authoritative.

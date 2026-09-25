# Retiring the controlled-reconcile workaround

Issue #41 removes the host-local controlled_reconcile.py path without adding another scheduler. The supported end state is the native schema-7 controller plus the single global hermes-swarm-reconcile.timer.

## Preflight

Run the helper without --apply first:

    python tools/migrate_controlled_reconcile.py \
      --name research-fabric \
      --legacy-script /absolute/path/to/controlled_reconcile.py

The JSON report identifies the resolved Skillfleet runtime/current release, native merge-policy and completion-contract capabilities, legacy/global timer and service state, schema-7 manifest policy/pause state, and active Kanban tasks. Migration fails closed unless the target manifest already has paused=true; that keeps the ordinary global timer harmless while the legacy path drains.

## Cutover

After reviewing the preflight, authorize the one-shot cutover explicitly:

    python tools/migrate_controlled_reconcile.py \
      --name research-fabric \
      --merge-policy automatic \
      --legacy-script /absolute/path/to/controlled_reconcile.py \
      --apply

The helper performs only this bounded sequence:

1. disable/stop research-fabric-controlled-reconcile.timer only;
2. wait for an already-running research-fabric-controlled-reconcile.service and the target swarm reconcile lock to drain rather than killing them;
3. back up the target manifest, the two known legacy unit files, and the explicitly supplied legacy script when present;
4. keep the swarm paused and set the requested policy with hermes swarm merge-policy;
5. run native validate and a read-only native dry-run, rejecting unsafe GitHub/execution state;
6. resume and execute a real native reconciliation pass;
7. require fresh journal evidence for configured issues and verify active task idempotency keys plus merge-request intent keys are unique;
8. ensure the standard global timer is enabled through hermes swarm activate when needed, then read back scheduler and manifest state.

No per-PR approval is introduced in automatic mode. Current-head CI/review/adjudication/mergeability and no-merge/pause gates remain the controller's authority.

## Failure and rollback

Any failure after the dedicated timer is quiesced invokes native hermes swarm pause --name .... The helper never re-enables the legacy timer, never restores an older manifest over current task/cursor evidence, and never starts a second controller. The backup path is printed on success; on a failed run, inspect ~/.hermes/swarms/migration-backups/ (or the configured HERMES_SWARM_STATE_DIR) before retrying.

The standard global timer is shared by unrelated swarms and is not disabled as part of this migration.

## Artifact retirement

The helper deliberately does not delete scripts or unit files. After a successful read-back and at least one normal timer cycle, the operator may manually remove only these known workaround artifacts:

- ~/.config/systemd/user/research-fabric-controlled-reconcile.timer
- ~/.config/systemd/user/research-fabric-controlled-reconcile.service
- the exact controlled_reconcile.py path supplied to the helper

Then run systemctl --user daemon-reload. Do not remove or replace hermes-swarm-reconcile.timer, its service, other swarm manifests, or unrelated local units.

## Canary coverage

tests/test_swarm_migration.py exercises preflight reporting, an in-flight legacy reconcile that must drain, a successful native cutover, duplicate-evidence rejection, and a mid-cutover failure that leaves the swarm paused without restoring the legacy timer.

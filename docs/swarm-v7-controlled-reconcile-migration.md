# Retiring the local controlled-reconcile workaround

This migration is only for the historical `controlled_reconcile.py` + `<swarm>-controlled-reconcile.service/.timer` workaround. It does not add a scheduler and it never deletes local files or units. The supported steady state is the native schema-7 controller plus the single global `hermes-swarm-reconcile.timer`.

## Preflight

Run the helper from the active Skillfleet release without `--apply`:

```bash
RUNTIME="${AGENT_SKILLFLEET_RUNTIME:-$HOME/.local/share/agent-skillfleet-runtime}/current"
python "$RUNTIME/skills/github-project-swarm/scripts/migrate_controlled_reconcile.py" \
  --name research-fabric
```

The JSON report records the resolved controller release and Hermes version, native `merge-policy` and Kanban `--completion-contract` support, both legacy and global systemd paths, the schema-7 manifest/policy/pause state, active Kanban workers, and the per-swarm reconcile lock.

## Cut over research-fabric

Use `--apply` only after inspecting preflight. The target manifest must still be `paused=true`, matching the workaround's fail-closed on-disk state; otherwise apply refuses to start. The policy is intentionally mandatory:

```bash
python "$RUNTIME/skills/github-project-swarm/scripts/migrate_controlled_reconcile.py" \
  --name research-fabric \
  --legacy-script /absolute/path/to/controlled_reconcile.py \
  --merge-policy automatic \
  --apply
```

The helper disables only `research-fabric-controlled-reconcile.timer`. If its service is already running, it is allowed to finish; the helper waits for that service and the native per-swarm lock instead of killing either. It then backs up the manifest, journal, exact legacy script, and the two known legacy unit files under `$HERMES_HOME/swarm-migration-backups/`.

All controller changes after that use supported commands: native `pause`, `merge-policy`, `validate`, dry-run reconciliation, `resume`, and one real `reconcile`. The dry-run must have no unsafe GitHub/execution observation before resume. Post-pass verification rejects duplicate Kanban idempotency keys, reconciliation errors, a missing active-issue journal pass, or duplicate exact-head merge actions. If the global timer was not already both active and enabled, native `hermes swarm activate` enables it only after that pass succeeds. Final read-back requires the legacy timer disabled/inactive, its service inactive, and the global timer active/enabled.

Any cutover failure best-effort pauses the target swarm and leaves the legacy timer disabled. It never restores the unsafe dual-controller state. The backup, Kanban task/cursor evidence, journal, and GitHub PR evidence remain available for diagnosis and a later rerun.

## Retire the old files

After a successful read-back, removal is deliberately manual. Remove only the three known research-fabric artifacts if they are no longer needed:

```bash
rm /absolute/path/to/controlled_reconcile.py
rm "$HOME/.config/systemd/user/research-fabric-controlled-reconcile.service"
rm "$HOME/.config/systemd/user/research-fabric-controlled-reconcile.timer"
systemctl --user daemon-reload
```

Do not remove or disable `hermes-swarm-reconcile.service/.timer`, other swarm manifests, or unrelated user units.

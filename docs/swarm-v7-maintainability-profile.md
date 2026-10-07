# Swarm v7 maintainability profile

Issue #54 restores the qualification requirements from the final v7 gate: every reachable production module must have Radon 6.0.1 Maintenance Index **>75**, every production function must have cyclomatic complexity **<8**, and named core paths remain at **<=6**.

The former 10-module convergence deliberately traded per-file MI for a direct structural profile. Qualification later proved that replacement insufficient for the parent gate, so the runtime now uses a bounded set of cohesive trust/ownership boundaries instead of comment padding or one-helper files:

- planner model / pure decision engine;
- CLI state / operator runtime / reconcile surface;
- controller observation / execution;
- GitHub transport / publication / CI / issue observation;
- merge ledger / merge mutation;
- execution identity / Kanban transport;
- Git trust / worktree policy.

The reachable runtime is capped at 50 Python modules and 1,000 nonblank/noncomment Python LOC. The 50-module guard is an anti-fragmentation bound for this restored-MI architecture (49 modules in the current design) and remains far below the 115-module pre-convergence runtime; the parent qualification's size target remains 1,000 LOC. The LOC increase relative to the 687-LOC metric-replacement build is accepted only where it corresponds to these explicit ownership boundaries; compressed physical lines, hidden runtime code, padding comments, and threshold exceptions are not accepted.

Canonical validation is:

```bash
python tools/swarm_v7_quality.py --qualification
make check
```

Qualification uses Radon 6.0.1 `mi_visit(source, False)` exactly as #54 specifies, and reports MI, function LOC, cyclomatic and cognitive complexity, nesting, whole-runtime LOC/module count, and unresolved local imports.

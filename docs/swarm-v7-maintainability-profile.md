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

The reachable runtime remains capped at 20 Python modules and 1,000 nonblank/noncomment Python LOC, the parent qualification target. The LOC increase relative to the 687-LOC metric-replacement build is accepted only where it corresponds to these explicit ownership boundaries; compressed physical lines, hidden runtime code, padding comments, and threshold exceptions are not accepted.

Canonical validation is:

```bash
python tools/swarm_v7_quality.py --qualification
make check
```

Qualification reports MI, function LOC, cyclomatic and cognitive complexity, nesting, whole-runtime LOC/module count, and fails closed on unresolved local imports.

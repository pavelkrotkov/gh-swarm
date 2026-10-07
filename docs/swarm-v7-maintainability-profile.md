# Swarm v7 maintainability profile

Issue #54 restores the final-qualification Maintenance Index requirement that the earlier
10-module convergence had replaced with direct structural limits. The runtime scope remains
reachability-derived from the Hermes plugin; executable code is not excluded or moved to an
uncounted surface.

## Enforced profile

`python tools/swarm_v7_quality.py --qualification` and canonical `make check` enforce:

- Radon 6.0.1 `mi_visit(source, False) > 75` for every active `scripts/swarm_v7*.py` module;
- cyclomatic complexity < 8 for every production function, with named planner/executor/merge
  paths <= 6;
- cognitive complexity <= 15 and maximum nesting <= 4;
- no production function > 60 source lines;
- no active module > 350 counted code LOC;
- whole reachable runtime <= 1,000 counted Python LOC and <= 20 modules;
- core-controller aggregate <= 1,000 LOC.

The 1,000-LOC ceiling is the parent #55 qualification limit. The former 687-LOC stretch
target was introduced as part of the MI replacement; restoring MI requires a small number of
real responsibility/trust-boundary splits, so retaining that replacement ceiling would reward
the same compressed ownership that caused the qualification failure.

## Separation rules

Splits are limited to concrete boundaries already present in the behavior: normalized model
vs pure planning; CLI durable state vs operator initialization/admin vs reconcile; controller
observation vs execution; GitHub transport vs exact-head publication vs CI reduction; merge
ledger vs mutation; Git transport vs worktree policy; and immutable execution/task contracts.
No file-per-helper layer, compatibility stack, dynamic import inheritance, minification, or
scope exclusion is permitted.

Comments describe authority and crash-safety invariants only. They are not added in bulk to
raise MI; qualification uses the same Radon command cited by #54 and the direct complexity,
LOC, nesting, behavioral, dead-code, and host checks remain independent backstops.

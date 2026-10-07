# Swarm v7 maintainability profile

Issue #54 pairs a meaningful per-module Maintenance Index floor with an explicit anti-fragmentation ceiling.
The runtime scope remains reachability-derived from the Hermes plugin; executable code is not excluded or moved to an uncounted surface.

## Enforced profile

`python tools/swarm_v7_quality.py --qualification` and canonical `make check` enforce:

- Radon 6.0.1 `mi_visit(source, False) > 50` for every active production Python module;
- at most 20 active runtime Python modules;
- cyclomatic complexity < 8 for every production function, with named planner/observer/executor/merge paths <= 6;
- cognitive complexity <= 15 and maximum nesting <= 4;
- no production function > 60 source lines;
- no active module > 350 counted code LOC;
- whole reachable runtime <= 1,000 counted Python LOC;
- core-controller aggregate <= 1,000 LOC.

## Why the gates are paired

The earlier MI >75 experiment drove the reachable runtime toward 49 small modules primarily to improve Radon scores.
That is the wrong optimization. MI >50 retains a useful floor while the <=20-module ceiling forces genuine simplification,
consolidation and cohesive ownership instead of file-per-helper fragmentation.

Comments document authority, safety and recovery invariants that belong with the code. They must not be added as padding,
nor may code be minified, excluded from reachability, or split solely to improve the metric. Behavioral tests, dead-code
checks and exact-head CI remain independent backstops.

# Swarm v7 maintainability profile

Issue #114 closes the final quality follow-up after the #103 whole-runtime convergence.
The active runtime remains the reachability-derived scope rooted at the Hermes plugin; this
policy does not change what is counted.

## Why per-file MI > 75 is no longer an acceptance gate

At the #114 baseline (`0d41f30c23aad61e1abd1f4dccae7d89b9ad2dbf`) the complete active runtime is
690 counted Python LOC in 10 modules. The largest module is only 148 code LOC, every
function is already below 60 LOC, and cognitive complexity and nesting are already within
the absolute limits. Nevertheless Radon reports per-file Maintenance Index values from
17.4 to 62.4, so all ten files fail the historical `MI > 75` threshold.

That result is not aligned with the property the final convergence is trying to protect.
Radon MI is an aggregate of Halstead volume, cyclomatic complexity, source lines and a
comment term. Applied as a hard threshold to each very small runtime file, it can be
improved without simplifying behavior by adding comments or splitting cohesive ownership
into more files. Both responses conflict with #103/#114: comment padding is metric gaming,
and helper/file fragmentation would reverse the deliberate consolidation.

We therefore retain MI in qualification output as a diagnostic trend only. Runtime source
is not padded, split, or excluded to improve the number.

## Enforced direct profile

`python tools/swarm_v7_quality.py --qualification` and canonical `make check` enforce the
properties that MI was intended to proxy, directly:

- whole reachable runtime: at most 684 counted Python LOC and at most 20 modules;
- each active module: at most 350 counted code LOC;
- every production function: at most 60 source lines;
- cyclomatic complexity: at most 8 for every function;
- named planner/observer/executor/merge/CLI core paths: at most 6;
- cognitive complexity: at most 15;
- maximum nesting depth: at most 4;
- core-controller aggregate: at most 1000 counted LOC and strictly smaller than the pinned pre-v7 controller baseline;
- the runtime scope must remain reachability-derived from the active Hermes plugin and all required local imports must resolve.

The canonical validation pipeline additionally runs the full unit/behavior suite, source
and manifest validation, shell syntax checks, the AST dead-code boundary and secret scan.
Those checks preserve crash recovery, exact-head authority, plugin behavior, bounded
execution and the other runtime contracts while the direct profile constrains structural
complexity.

This is a metric replacement, not a silent threshold relaxation: only the aggregate
per-file MI predicate is retired, its measured value remains visible, and every direct
size/control-flow bound is enforced as a failing canonical gate.

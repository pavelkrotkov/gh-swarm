# gh-swarm

Public beta development home for the Hermes schema-7 GitHub coding swarm.

This repository contains:

- `github-project-swarm` — controller, GitHub authority, Kanban execution, exact-head review/adjudication, CI gating, merge authority, Hermes plugin, bootstrap and systemd integration;
- `github-project-reviewer` and `github-project-adjudicator` — companion skills required by Swarm;
- the Swarm test suite, host qualification harness, dead-code boundary, and structural quality gates.

## Status

**Beta / work in progress.** Active Swarm development happens here so pull requests can use GitHub Actions on a public repository. The private `agent-skillfleet` repository consumes these skills as locked external dependencies pinned to an exact commit. When Swarm is mature, it can be folded back into the private first-party Skillfleet.

## Validation

```bash
python -m pip install -c requirements/ci-constraints.txt PyYAML radon cognitive-complexity vulture
make check
```

Canonical CI runs the behavioral tests, absolute runtime quality profile (MI >75, CC <8 with core paths <=6, cognitive complexity, nesting, LOC and reachability), AST dead-code boundary, YAML/shell validation and a tracked-source secret scan.

Host-only recovery qualification remains separate from fast CI:

```bash
make qualify-swarm-host
```

See `docs/swarm-v7-host-qualification.md` for prerequisites.

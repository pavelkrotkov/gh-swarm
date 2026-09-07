# Swarm v7 implementation publication contract

Issue #48 moves durable implementation publication from the controller to the implementation/revision worker.

## Controller preparation

For a fresh implementation slot, the controller must first validate the configured repository/path binding, fetch the configured default branch, resolve the exact full `origin/<default>` SHA, and prove every GitHub-confirmed internal predecessor merge commit is an ancestor of that fetched default. It then creates the deterministic `swarm/<swarm>/<issue>` branch from exactly that SHA and attaches the deterministic worktree.

A fresh semantic identity fails closed if its expected branch, worktree, or branch PR already exists. Once the implementation slot has legitimately started, those artifacts become recovery evidence: an existing local branch can preserve a commit made before a crash, a remote branch can reconstruct a missing worktree, and a matching durable PR can satisfy the publication handoff even if the worker card dies afterward.

New issues are never based on another unmerged swarm branch. Dependencies are GitHub merge gates; each new branch starts only from a freshly fetched default branch after predecessor `mergedAt`/merge-commit facts are confirmed.

## Worker success contract

The implementation/revision worker owns publication. It may succeed only after it:

1. makes the minimum scoped change and validates it;
2. commits all intended changes and leaves the expected worktree clean on the exact configured swarm branch;
3. records the full commit SHA;
4. pushes only that exact branch, without force-push;
5. creates or reuses exactly one PR from that branch to the configured default branch;
6. ensures the PR is open and non-draft;
7. re-reads GitHub and verifies the PR base/ref and full head SHA equal the branch and pushed commit exactly;
8. only then completes the Kanban task.

The worker must not merge, mutate dependencies/swarm configuration, touch unrelated issues/PRs, or push another branch.

## Controller verification and recovery

The controller does not run a normal post-worker `git push` or `gh pr create` phase. It re-observes the remote branch and GitHub PR instead.

The durable implementation fact is one remote branch head plus exactly one open, non-draft matching PR whose full GitHub head SHA equals the remote branch head. If the PR still reports an older head after a push, publication is pending; review must not start until GitHub exposes the exact remote head.

A present local worktree must be clean, on the expected branch, and at the durable head before a worker handoff is accepted. A missing worktree is not semantic loss once the remote branch/PR is durable; it is disposable and can be reconstructed.

Crash boundaries are therefore handled as follows:

- commit before push: preserve/reconstruct the local candidate and use a bounded execution retry for the same semantic implementation slot;
- push before PR/task completion: recover the remote branch; a replacement may finish the missing PR publication without redoing implementation;
- valid branch + exact matching PR before task completion: treat the durable publication as satisfying implementation and do not duplicate work;
- missing worktree after publication: reconstruct it from the durable branch only if later execution needs it.

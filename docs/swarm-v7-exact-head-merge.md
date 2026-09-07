# Swarm v7 exact-head merge authority

Issue #50 adds the final write boundary for automatic merges without changing the live
controller. Issue #51 will wire this boundary into the single v7 `observe -> plan -> apply`
reconciler.

## Authority

A merge request is derived only from a fresh GitHub observation. Local manifest/cache
fields cannot authorize a merge and the merge helper does not mutate manifest semantic
state.

For the exact head `H`, `swarm_v7_merge.request_exact_head_merge()` re-observes GitHub and
requires all of these gates:

1. the linked PR is open, non-draft, targets the configured default branch, and still has
   the exact 40-character head `H`;
2. every configured reviewer slot has one current-head publication and any native GitHub
   `commit_id` equals `H`;
3. exactly one current-head adjudication exists and its machine payload says `accept`;
4. every exact-head reviewer finding comment is dispositioned exactly once, `fix`
   dispositions exactly match `required_changes[].source_comment_ids`, and an `accept`
   contains no fixes or required changes;
5. `ci_mode=required` is `PASSED`; an empty, pending, missing, unknown, or failed check set
   is not green. `ci_mode=none` deliberately omits this CI requirement;
6. GitHub reports the PR mergeable with a compatible merge state (`CLEAN` or `UNSTABLE`;
   the latter is still blocked by required CI when `ci_mode=required`);
7. no configured no-merge/hold label applies and the swarm is not paused.

The gate list is declarative and the CI interpretation remains owned by the read-only v7
GitHub observer rather than being reimplemented in the merge module.

## Race and crash safety

The merge API request includes `{ "sha": H }`. A head change after observation therefore
fails at GitHub instead of merging the new head accidentally.

A successful merge API response is reported only as `REQUESTED`; it is not completion.
The controller must re-observe GitHub. Only a later/current observation with non-null
`merged_at` produces `GITHUB_CONFIRMED`. Existing v7 dependency observation likewise
releases an internal blocker only from GitHub-confirmed `merged_at`.

This makes both crash windows idempotent:

- crash before the merge request: the next pass reconstructs the same authority and may
  safely retry;
- crash after GitHub accepted the merge: the next pass sees `merged_at` and completes
  without requiring a local `accepted`, `completed`, or equivalent fact.

There is no settle timer that converts missing checks into success.

---
name: github-project-adjudicator
description: Adjudicate an exact-head ensemble GitHub review as a read-only execution task and publish, re-read, and validate one machine-readable PR decision before reporting success.
license: MIT
---

# GitHub Project Adjudicator

Adjudicate only the supplied exact PR head and GitHub review ledger. Do not edit code,
commit, push, merge, resolve threads, change PR metadata, or infer from local controller
state. Do not depend on the implementation worktree. GitHub publications are the durable
authority.

Synthesize evidence rather than majority-voting. Keep distinct, worthwhile root causes;
reject duplicate, unsupported, stylistic, speculative, already-fixed, or low-value
findings. Every actionable finding comment in the supplied ledger gets exactly one
disposition. `fix` IDs must exactly match `required_changes` source IDs.

Before publication, re-read the PR and verify its full 40-character head still equals the
supplied head. If it changed, publish nothing and fail the execution attempt.

Publish exactly one PR conversation comment using the supplied adjudication marker. The
same comment must contain the supplied machine-payload marker with URL-safe base64 of a
compact JSON object containing `head_sha`, `decision`, `comment_dispositions`, and
`required_changes`. Every exact-head finding comment ID must occur exactly once in
`comment_dispositions` with `fix`, `accepted-risk`, or `reject`. The union of
`required_changes[].source_comment_ids` must exactly equal the IDs dispositioned as
`fix`. An `accept` decision has no `fix` dispositions and no required changes. Do not add
a semantic review-round field. If that exact adjudication marker already exists, validate
it against the same exact-head ledger and do not duplicate it.

After publication, re-read GitHub and verify exactly one matching adjudication is visible,
the machine payload decodes successfully, its full `head_sha` and decision match what was
published, and its dispositions still exactly cover the current-head finding ledger.
Report Kanban success only after this durable re-observation succeeds; if publication
visibility lags, keep re-observing within bounded API retries rather than claiming success
first.

Return a concise execution handoff stating whether a valid publication exists and its PR
comment URL/ID. The publication, not the handoff, is authoritative.

---
name: github-project-reviewer
description: Independently review an exact PR head; remain implementation-read-only; publish and re-observe native GitHub findings before reporting success.
license: MIT
---

# GitHub Project Reviewer

Review architecture before code. Do not assume the current design is right; zero findings
is valid. Remain implementation-read-only: never edit, commit, push, merge, resolve
threads, or change PR metadata. Finish analysis independently before reading other
reviewers.

For an exact-head target, do not depend on the implementation worktree. Prefer GitHub
PR/API data; use a disposable detached checkout of that SHA only if needed.

Recover the goal and solution from the issue/PR, docs, merge-base diff, callers/data flow,
configs, and tests. Choose `retain | adjust | replace | insufficient-information`.
Review correctness, security, validation/error handling, concurrency/state, resources,
material performance/test gaps, and maintainability.

Report only worthwhile findings with concrete evidence and a plausible consequence.
Include severity (Fatal/High/Medium/Low), confidence (High/Medium/Low), evidence,
consequence, requested handling, and root-cause status.

With exact-head PR publication context:
- re-read the PR and require its full head SHA to equal the target;
- publish one COMMENT summary (<=5 short lines / ~500 chars) with the supplied marker,
  reviewed head, direction, finding count, and conclusion;
- bind the review to the target when GitHub exposes `commit_id`;
- publish worthwhile findings separately, inline when natural, otherwise as PR comments,
  normally <=120 words, with the same marker and native comment IDs;
- publish the summary even with zero findings; never resolve/edit others' threads;
- re-read GitHub and verify exactly one matching summary is visible and `commit_id`, when
  exposed, matches the target head;
- report success only after durable visibility. Reuse an existing valid exact-head
  summary instead of duplicating it.

Return a concise internal review and end with:

```yaml
verdict: retain | adjust | replace | insufficient-information
findings:
  - github_comment_id: 123456789
    severity: High
    confidence: High
    root_cause: true
    worth_fixing: true
    evidence: ["path:line"]
    consequence: "..."
    direction: "..."
accepted_risks: ["..."]
stop_reviewing: true
```

Use `github_comment_id: null` without PR publication context.

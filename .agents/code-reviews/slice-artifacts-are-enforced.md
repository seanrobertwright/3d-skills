---
slice: slice-artifacts-are-enforced
title: "feat(agents): make the slice-artifact rule a rule, and enforce it"
author: "seanrobertwright"
reviewed: 2026-08-28
recommendation: approve
---

# Code review — `slice-artifacts-are-enforced`

Working-tree review, run before the PR was opened. This slice closes both findings
from the 2026-08-28 trajectory audit: Gap 1 by writing the rule where an agent
will read it, Violation 1 by making it mechanical.

| File | Change |
|---|---|
| `CLAUDE.md` | new "Shipping a slice" section (32 lines) |
| `.github/workflows/verify.yml` | new `slice-artifacts` job |
| `tests/test_ci_runs_the_gates.py` | 2 new tests |
| `.agents/audits/pr-trajectory-audit-2026-08-28.md` | #7 state corrected |
| `.claude/skills/pr-trajectory-audit/references/failure-patterns.md` | #7 state corrected |
| `.claude/post-execute.json` | `checks` gains the new job name |

## Findings

### 1 — MEDIUM · the grandfather list is the part that can rot

`test_this_repository_has_the_artifacts_the_ci_job_demands` carries:

```python
PRE_RULE = {"pr-1-review", "ci-hardware-free-lanes", "ams-feed-bisect-tooling"}
```

Three names, each a real slice that shipped before the rule existed. This is the
shape that goes wrong: a grandfather list is a tolerance, and tolerances get
widened by whoever is in a hurry.

Two properties make it safer than the usual version, and both are deliberate:

- **It grandfathers by name, not by predicate.** There is no "slices before date
  X" rule to satisfy — a new unpaired slice is simply not in the set and fails.
- **Removing a name can only make the check stricter.** The failure mode of a
  stale entry is a check that is *weaker than it could be*, never one that passes
  something it should catch.

`pr-1-review` is not a grandfathered lapse at all — it is PR #1's PHASE 6 diff
review, which has no execution-report counterpart by design. Noted in the comment
so it is not "cleaned up" later by someone who reads the set as a to-do list.

**Not fixed, and the honest option is named:** backfilling artifacts for #6 and
#7 would empty the set. Rejected — writing a retrospective code review for work
reviewed weeks ago produces a document that asserts a review happened when it did
not, which is the same class of false record the audit exists to catch. An empty
grandfather list bought with a fabricated artifact is worse than a three-name one.

### 2 — MEDIUM · the CI job is gated on `pull_request`, and that gate is load-bearing

`github.head_ref` is **empty** on a `push` event. Without the
`if: github.event_name == 'pull_request'` gate, every path becomes
`.agents/code-reviews/.md`, both `-f` tests fail, and the job would fail every
push to master — or, with a slightly different implementation, pass every one of
them by accident. The step *also* refuses explicitly on an empty `HEAD_REF`
rather than proceeding, so the two defences are independent. A test asserts the
gate string is present.

**Consequence, stated:** this check cannot see a slice that reaches master
without a PR. That path is already forbidden by the ship pipeline's PHASE 0a
("slice work never lands directly on the base branch"), but nothing here enforces
it, so the two rules lean on each other.

### 3 — LOW · a third required check changes what "green" means for the ship pipeline

`.claude/post-execute.json`'s `checks` array is what the pipeline waits on at
PHASE 5 and PHASE 8. Adding the job without adding its name would leave the
pipeline merging on two of three checks — quieter and worse than not adding the
job. Updated to `["lint", "verify (linux)", "slice artifacts"]`, using the job's
**`name:`**, which is what `gh pr checks` reports, not its YAML key.

### 4 — LOW · `CLAUDE.md` grew by a section, and it is already long

~32 lines onto a file that is the first thing an agent reads. Justified: the audit
found the failure was *specifically* that this file did not mention the artifacts,
so a shorter note elsewhere reproduces the gap. The section states the rule, the
filename convention, the disclosure requirement, and where the mechanical half
lives — and nothing else.

### 5 — LOW · corrections to already-merged artifacts

The audit report and the rubric both recorded PR #7 as OPEN; it merged at 16:45
on 2026-08-28, mid-audit. Corrected in both, and in the audit report the
correction is written as a visible `> **Corrected**` note rather than a silent
edit. An audit that quietly rewrites its own evidence is performing the failure it
exists to catch.

## What was verified, not assumed

- `verify.yml` parses as YAML; jobs are `lint`, `verify`, `slice-artifacts`;
  the new job's `if` and `name` read back as expected.
- `pytest tests/test_ci_runs_the_gates.py` — **9 passed**, including both new tests.
- `ruff check` clean; `ruff format` reformatted the new test block once, then clean
  at 76 files.
- `grep OPEN` over the rubric and audit report returns nothing.
- The job's own artifacts exist for this branch — this PR is the first real
  exercise of the check it adds.

## Recommendation

**Approve.** Finding 1 is the one to revisit if the grandfather set is ever
touched; the rest are accepted with reasons recorded.

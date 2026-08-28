---
audit: pr-trajectory-audit
scope: all PRs (#1, #2, #3, #6, #7)
audited: 2026-08-28
auditor: Claude Code (Workflow A)
---

# PR Trajectory Audit — seanrobertwright/3d-skills

Mined 5 PRs (2026-07-31 → 2026-08-07) against this repo's own documented AI layer:
`CLAUDE.md`, `.claude/post-execute.json`, `.claude/PRINT-GATE.md`, and
`.github/workflows/verify.yml`. Full methodology:
`.claude/skills/pr-trajectory-audit/references/mining-methodology.md`.

This audits the **process**, not the code. The question is never "is this change
good" — it is "did the trajectory follow the workflow this repo defined for it,
and did it do the self-validation it was supposed to do before claiming done."

## Summary

| Signal | Count |
|---|---|
| Documented AI-layer rules/steps identified and checked against | 12 |
| PRs referenced 2+ times by a later PR's body | 0 |
| Duplicate-title clusters found | 1 (false positive — see below) |
| Candidates deep-dived for this report | 5 of 5 (whole history) |
| Rule violations confirmed | 1 |
| Coverage gaps confirmed | 1 |

The pass surfaced one violation and one coverage gap, and they are the same story
seen from two sides: **every phase PR followed the ship pipeline completely, and
every non-phase PR dropped its entire review half** — because the only in-repo
signal that the pipeline exists is a `.agents/plans/phase-N-*.md` file, and
non-phase slices don't have one.

Worth stating up front, because the finding count understates it: the evidentiary
quality of these PR bodies is unusually high. #2 lists five defects found while
validating, with measured numbers. #6 documents two real CI-found defects with
runner output and explicitly retracts an earlier "verified on Windows" measurement
as non-transferable. #7 has a `## Not verified` section stating that neither new
script has been run against the printer. Nothing here is a candour problem.

---

## Finding 1 — Rule violation: the review half of the ship pipeline was dropped for every non-phase slice

**The documented rule.**

> `.claude/post-execute.json` —
> ```json
> "paths": {
>   "codeReviews": ".agents/code-reviews",
>   "executionReports": ".agents/execution-reports"
> }
> ```

> `ship:post-execute` PHASE 2 — *"Run **both**, in this order: 1.
> `commands.codeReview` → writes `<paths.codeReviews>/<slice>.md`  2.
> `commands.executionReport` → writes `<paths.executionReports>/<slice>.md`"*

> PHASE 7 — *"post the results as a PR comment — the durable record a future
> reader sees, which is why the table lives outside the transcript as well."*

> NOTES — *"Never report a phase as done that was skipped."*

**The claim.** Neither PR claims to have run the review phases. Both simply omit
the `## Review` and `## Validation` headings the PHASE 4 body template specifies
and substitute their own:

> [PR #6](https://github.com/seanrobertwright/3d-skills/pull/6) — "ci: run the
> three hardware-free validation lanes on every push and PR"
> Sections: `## What runs`, `## CI found two real defects on its first three runs`,
> `## Measured after the fixes`, `## Design notes`,
> `## The workflow is itself asserted`, `## Also included`, `## Noted, not fixed`

> [PR #7](https://github.com/seanrobertwright/3d-skills/pull/7) — "feat(tools):
> read-only diagnostics for the AMS feed bisect"
> Sections: `## The problem`, `## Why not permute more payload fields`,
> `## What this adds`, `## Design decisions, with reasons`, `## Safety`,
> `## Not verified`, `## Gates`

**The evidence.**

| PR | State | Slice | code-review | exec-report | `## Review` | PHASE 7 comment |
|---|---|---|---|---|---|---|
| #1 | MERGED 2026-07-31 | `phase-1-verification-loop` | yes | yes | yes | yes |
| #2 | MERGED 2026-08-02 | `phase-2-printability-and-preparation` | yes | yes | yes | yes |
| #3 | MERGED 2026-08-05 | `phase-3-printer-and-calibration` | yes | yes | yes | yes |
| #6 | MERGED 2026-08-06 | `ci-hardware-free-lanes` | **no** | **no** | **no** | **no** |
| #7 | MERGED 2026-08-28 16:45 | `ams-feed-bisect-tooling` | **no** | **no** | **no** | **no** |

- `ls .agents/code-reviews/` → `phase-1-…`, `phase-2-…`, `phase-3-…`,
  `pr-1-review.md`. `ls .agents/execution-reports/` → the three phase files only.
- `gh pr view 6 --json comments` and `gh pr view 7 --json comments` both return
  **zero** comments. The lone `review` object on each is
  `copilot-pull-request-reviewer [COMMENTED]` — a bot, satisfying nothing in the
  documented pipeline.
- `git log --all --diff-filter=D -- .agents/code-reviews .agents/execution-reports`
  returns nothing: the artifacts were never written, not written and removed.
- Tier 1 `ci_status` is **PASS** on both (`lint`, `verify (linux)`), so the
  automated gates did run. What is missing is the PHASE 6 human/agent lens over
  the diff, and the durable record of it.

**Verdict:** `FAIL` against PHASE 2 / PHASE 6 / PHASE 7 — on the file listing and
the empty comment threads, with no disclosure in either body that the phases were
skipped.

Fairness note on the two cases: **#6 is the weaker one.** It *introduced*
`.claude/post-execute.json`, so the explicit profile did not exist when the branch
was cut — though `.agents/code-reviews/` already did, and the pipeline's
auto-detection resolves to first-existing. **#7 is unambiguous**: the profile was
committed and in the tree a full day before its branch.

> **Corrected 2026-08-28.** This section originally read "PR #7 is also still
> open, so this one is fixable before it lands rather than a post-mortem." #7
> merged at 16:45 that day, while the audit was being written up. Both cases are
> now post-mortems, and Violation 1 is confirmed on **two merged PRs**, not one
> merged and one catchable. Recorded as a correction rather than edited away: an
> audit that quietly updates its own evidence is doing the thing it exists to
> catch.

**System-evolution fix.** Tighten enforcement, in this repo's own established
idiom. Nothing mechanical checks the requirement today —
`grep -rl "code-reviews\|execution-reports" tests/ .github/` returns no matches —
while `tests/test_ci_runs_the_gates.py` and `tests/test_printer_path_is_narrow.py`
both exist precisely because *"a guardrail that lives only in config is one edit
from being gone."* Add the third guard: a test asserting each slice on `master`
has both artifacts, or a CI step failing a PR whose body carries no `## Review`.
Pair it with Finding 2 — a check alone punishes an agent that was never told.

---

## Finding 2 — Coverage gap: `CLAUDE.md` never mentions the review or report artifacts

**No existing rule covers this.** This is not a violation of anything documented
in the file agents actually read. `CLAUDE.md` is ~300 lines, exhaustive about
measurement discipline and validation commands, and names `.agents/plans/` three
times. It mentions `.agents/code-reviews/` and `.agents/execution-reports/` zero
times:

```
$ grep -no "\.agents/[a-z-]*" CLAUDE.md | sort -u
25:.agents/plans
26:.agents/plans
27:.agents/plans
```

It never mentions `.claude/post-execute.json` or the ship pipeline either. The
full chain of custody for "this slice owes a code review and an execution report"
is therefore: a JSON config naming paths but stating no obligation → a skill
installed at **user level, outside the repository entirely**
(`~/.claude/plugins/cache/claude-ship/…`). An agent that reads `CLAUDE.md` cover
to cover — the documented right thing to do here — cannot learn the requirement
exists.

**The cluster.**

- [PR #6](https://github.com/seanrobertwright/3d-skills/pull/6) — "ci: run the three hardware-free validation lanes on every push and PR" — MERGED
- [PR #7](https://github.com/seanrobertwright/3d-skills/pull/7) — "feat(tools): read-only diagnostics for the AMS feed bisect" — MERGED 2026-08-28 16:45

**Why this is worth encoding.** Recurrence is **2 of 2** — 100% of the PRs where
no in-repo signal existed. The three phase PRs each had
`.agents/plans/phase-N-*.md` naming their own slice, so the convention was
discoverable from inside the repo and was followed every time. The correlation is
not with size or care (#6 is a careful, well-evidenced PR); it is with whether the
repo itself told the agent. That is a documentation gap, not a discipline one, and
it is the kind this project already treats as a defect class.

**System-evolution fix.** Add a short "Shipping a slice" section to `CLAUDE.md`:
every slice, phase or not, writes `.agents/code-reviews/<slice>.md` and
`.agents/execution-reports/<slice>.md`; the PR body carries `## Review` citing
both and `## Validation` naming the gate that ran; a deliberately skipped phase is
**stated in the body** rather than silently omitted.

---

## Tier 1 checks that produce no signal on this repo

Recorded here rather than in the rubric, which stays two-category by design. A
live review must report these as *inapplicable*, never as passing — a check that
silently no-ops reads identically to one that ran and found nothing.

- **`scope_blast_radius` — SKIP on 5 of 5, and on all future PRs.** The heuristic
  only fires on `fix(module):` titles. This repo uses `feat(threedp):`,
  `feat(tools):`, `ci:`, `fix(ci):`, `fix(tests):`. Zero signal, permanently.
- **`duplicate_vs_recent` — confirmed false positive on #1/#2/#3.** They match at
  57–62% purely on the shared `feat(threedp): Phase N — …` prefix. Branch names
  (`phase-1-verification-loop`, `phase-2-printability-and-preparation`,
  `phase-3-printer-and-calibration`) and the diffs confirm sequential, independent
  work. Never cite a duplicate finding between two `Phase N` PRs here.
- **`ci_status` — UNKNOWN on #1/#2/#3 is historically correct and now closed.**
  Those three merged with zero automated verification; #3 was 35 files,
  +7438/−288. It was disclosed in the bodies (*"This repository has no CI, so
  these local runs are the whole verification surface"*), tracked as issue #5, and
  fixed by #6. Both required checks now pass on #6 and #7. A future PR merging
  without `lint` and `verify (linux)` green is a **regression**, not a repeat of a
  tolerated condition.

## Compliance confirmed, not just violations

Two claims were spot-checked against the tree rather than taken from the body:

- PR #7 claims it closed the `tools/` loophole with
  `test_diagnostics_in_tools_still_go_through_the_one_send_path`. The test exists
  at `tests/test_printer_path_is_narrow.py:134` and does what the body says —
  scans `tools/**/*.py` for banned network imports. Claim holds.
- PR #2's `pytest -m slicer — 6 passed, 0 skipped` and PR #6's
  `470 passed, 19 deselected, 0 skipped` both report the skip/deselect counts
  `CLAUDE.md` requires rather than a bare pass. Claim holds.

One code-level observation, out of scope for a trajectory audit and **not** a
finding here: `test_diagnostics_in_tools_still_go_through_the_one_send_path`
opens with `if not tools.is_dir(): return`, which is a silent pass if `tools/` is
ever removed — the same "a gate that reports green for being absent" shape
`CLAUDE.md` names about self-skipping tests. Worth a look in a code review, not in
this one.

## What this audit does not check

- **Only the four AI-layer files listed at the top were read**, plus the
  `ship:post-execute` skill they configure. The eight `lril3d-*` skills' own
  internal preconditions were not audited against PR trajectories.
- **`PRD.md` was not read as a rule source.** `CLAUDE.md` names it the source of
  truth for scope; PR bodies were not checked against its §12 phase schedule.
- **Commit-level trajectory was not audited** — only PR-level artifacts, bodies,
  comments and CI status. A PR that reached a clean end state through a messy
  commit history reads as clean here.
- **The whole history is 5 PRs.** Both findings rest on a 3-vs-2 split. That is
  enough to act on a coverage gap whose mechanism is visible and explained, but it
  is not a large sample, and a third non-phase PR that carries its artifacts would
  genuinely weaken Finding 2.
- **This pass covers PRs opened up to 2026-08-07.** Re-run Workflow A after the
  next batch of merges.

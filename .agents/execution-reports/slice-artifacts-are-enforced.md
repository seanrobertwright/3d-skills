---
slice: slice-artifacts-are-enforced
title: "feat(agents): make the slice-artifact rule a rule, and enforce it"
executed: 2026-08-28
base: master @ 78f8dc5
---

# Execution report — `slice-artifacts-are-enforced`

Closes both findings of the 2026-08-28 trajectory audit. Gap 1 by writing the rule
where an agent will actually read it; Violation 1 by making it mechanical. The two
halves are deliberate and neither works alone — a rule with no check is what the
audit found failing, and a check with no rule punishes an agent that was never told.

## What was done

1. **`CLAUDE.md` gains a "Shipping a slice" section.** Placed there specifically
   because that file's silence *was* Gap 1: it named `.agents/plans/` three times
   and the two artifact directories zero times, so the obligation existed only in
   `.claude/post-execute.json` and in a skill installed outside the repository.
2. **`.github/workflows/verify.yml` gains a `slice-artifacts` job.** On
   `pull_request` only, it derives the slice from `github.head_ref` and fails the
   PR unless both `.agents/code-reviews/<slice>.md` and
   `.agents/execution-reports/<slice>.md` exist.
3. **`tests/test_ci_runs_the_gates.py` gains two tests** — one asserting the job
   exists and is gated on `pull_request`, one asserting this repository satisfies
   the pairing the job demands.
4. **`.claude/post-execute.json`'s `checks` gains `"slice artifacts"`**, so the
   ship pipeline waits on three checks rather than merging on two of three.
5. **Corrected PR #7's state** in the audit report and the rubric — it was OPEN
   when they were written and merged at 16:45 the same day.

## The new check caught this slice, before CI ever saw it

`test_this_repository_has_the_artifacts_the_ci_job_demands` failed on the first
full-gate run of this branch:

```
AssertionError: these slices have a code review or an execution report but not
both: ['slice-artifacts-are-enforced']
```

The code review had been written and **this file had not**. The guard's first
catch was the slice that added it, from a genuine half-finished state rather than
a contrived one. Fixed by writing this report.

## Design decisions, with reasons

**The grandfather list grandfathers by name, never by predicate.**
`PRE_RULE = {"pr-1-review", "ci-hardware-free-lanes", "ams-feed-bisect-tooling"}`.
There is no "slices before date X" rule to satisfy, so a new unpaired slice is
simply not in the set and fails. Removing a name can only make the check
stricter — the failure mode of a stale entry is a check weaker than it could be,
never one that passes something it should catch.

**The list was not emptied by backfilling.** Writing a retrospective code review
for #6 and #7 would produce documents asserting a review happened when it did not.
That is the same class of false record the audit exists to catch, and an empty
grandfather list bought with a fabricated artifact is worse than a three-name one.
`pr-1-review` is not a lapse at all — it is PR #1's PHASE 6 diff review, which has
no execution-report counterpart by design, and the comment says so, so it is not
"tidied up" later by someone reading the set as a to-do list.

**The `pull_request` gate is load-bearing, and there are two defences.**
`github.head_ref` is empty on a `push`, which would make every path
`.agents/code-reviews/.md`. The job is gated on the event, *and* the step refuses
explicitly on an empty `HEAD_REF` rather than proceeding. A test asserts the gate
string is present, because deleting it looks exactly like simplifying a condition.

## Validation — all measured 2026-08-28 at this tree

```
ruff check .                              All checks passed!
ruff format --check .                     76 files already formatted
interpreter + root-import gate            OK 3.13.15
pytest -m "not printer"                   481 passed,  12 deselected, 0 skipped
pytest -m slicer                            7 passed, 486 deselected, 0 skipped
pytest -m "not printer and not slicer"    474 passed,  19 deselected, 0 skipped
run_mutations.py                          caught 20/20  missed 0  false-positives 0
                                          harness-errors 0   VERDICT: PASS
                                          (30 mutations across 6 benchmarks)
```

Zero skips in every lane. `-m printer` was **not run** — it needs the P1S powered
on, and this slice touches nothing on that path.

**The hardware-free lane moves 472 → 474, and the arithmetic is worth writing
down** because the first version of this paragraph got it wrong. It claimed
471 → 474 as "three new tests", which does not add up and was not checked.
Measured by diffing `--collect-only` against master: **master is 472**, this
branch is 474, and the only file that changed is `test_ci_runs_the_gates.py`
(7 → 9). Exactly **+2**, both added here.

The stale 471 came from the previous slice, which measured it on a branch cut
before PR #7 merged; #7 then added `test_diagnostics_in_tools_still_go_through_
the_one_send_path` to the same lane, so master went to 472 and 471 was never true
of it. `verify.yml` and `test_ci_runs_the_gates.py` both carried that number in
prose and are corrected here. Neither *asserts* a count — `verify.yml` asserts
`deselected > 0` and `skipped == 0` — so nothing was broken, but a documented
measurement that is wrong is a defect in a repository whose first rule is to
report numbers rather than impressions.

**An earlier run of this same gate reported `1 failed, 473 passed`** and is
reported here rather than replaced, because the failure was the new guard doing
its job. The numbers above are the re-run after this file existed.

## Not done, and not claimed

- **The `slice-artifacts` job has never run in CI.** It is asserted locally by two
  tests and its YAML parses, but this PR is its first live exercise. If the shell
  quoting is wrong on a real runner, that is where it shows.
- **The job cannot see a slice that reaches master without a PR.** PHASE 0a
  forbids that path; nothing mechanical enforces it, so the two rules lean on each
  other.
- **The trajectory review still has not run.** It was skipped on PR #8 by workflow
  validation, which is lifted now that `trajectory-review.yml` is on master. This
  PR is the first genuine test of it, and of whether the Claude GitHub App is
  installed at all.
- **Neither #6 nor #7 gained artifacts.** They stay grandfathered by name. The
  audit's Violation 1 is closed going forward, not retroactively.

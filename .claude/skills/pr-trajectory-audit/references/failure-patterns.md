# AI-layer compliance findings

**This is not a rubric of "good PR" patterns. It's a rubric of specific, documented
rules from this repo's own AI layer, checked against real evidence of whether they
were actually followed.** The unit being evaluated isn't "is this fix correct" —
it's "did the agent's process, as evidenced by this PR's trajectory, actually
follow the workflow we defined for it." A PR that fixes the right bug through a
process that skipped a required step is still a finding here; a PR whose process
was clean is not, regardless of how the fix reads on its own.

Every finding below cites the **actual documented step** it checks against. For
this repo (`seanrobertwright/3d-skills`) the AI layer is four files, and they
layer on top of each other rather than instead of each other:

| File | What it governs |
|---|---|
| `CLAUDE.md` | engineering invariants, validation commands, phase boundaries, measured environment gotchas |
| `.claude/post-execute.json` | the ship pipeline's per-repo profile — base branch, gate commands, artifact paths, required checks, merge strategy |
| `.claude/PRINT-GATE.md` | the printer approval gate and why it is committed |
| `.github/workflows/verify.yml` | the three hardware-free CI lanes and the deselected-not-skipped assertion |

`.claude/post-execute.json` parameterizes the `ship:post-execute` pipeline, whose
phase definitions are the procedure this repo's PRs are expected to follow. Note
that pipeline is installed at **user level, outside this repo** — see Gap 1, which
is about exactly that.

Two kinds of finding, and they get different fixes:

- **Rule violations** — the AI layer already documents a step, and the trajectory
  shows it wasn't followed. Fix: tighten enforcement.
- **Coverage gaps** — a pattern recurs across multiple trajectories, and no
  existing rule covers it at all. Fix: add a new rule/skill/hook.

Both feed the same place: **system evolution.** A finding here is never the end of
the story — it's the input to the outer loop, and it isn't closed until an actual
file in the AI layer changes.

Audited 2026-08-28 against all 5 PRs in the repo's history (#1, #2, #3, #6, #7).

---

## Rule violations

### Violation 1 — the review half of the ship pipeline was dropped for every non-phase slice

**The documented step.** `.claude/post-execute.json` declares the artifact paths:

```json
"paths": {
  "plans": ".agents/plans",
  "codeReviews": ".agents/code-reviews",
  "executionReports": ".agents/execution-reports"
}
```

The pipeline it configures requires, at PHASE 2: *"Run **both**, in this order: 1.
`commands.codeReview` → writes `<paths.codeReviews>/<slice>.md`  2.
`commands.executionReport` → writes `<paths.executionReports>/<slice>.md`"*; at
PHASE 4, a PR body carrying a `## Review` section citing both files; at PHASE 6, a
deep PR review against the diff; and at PHASE 7, *"post the results as a PR
comment — the durable record a future reader sees."* Its NOTES add: *"Never report
a phase as done that was skipped."*

**The evidence.** Compliance splits perfectly along one line — phase slices vs.
everything else:

| PR | State | Slice | `.agents/code-reviews/` | `.agents/execution-reports/` | `## Review` in body | Phase 7 comment |
|---|---|---|---|---|---|---|
| #1 | MERGED 2026-07-31 | `phase-1-verification-loop` | yes | yes | yes | yes |
| #2 | MERGED 2026-08-02 | `phase-2-printability-and-preparation` | yes | yes | yes | yes |
| #3 | MERGED 2026-08-05 | `phase-3-printer-and-calibration` | yes | yes | yes | yes |
| #6 | MERGED 2026-08-06 | `ci-hardware-free-lanes` | **no** | **no** | **no** | **no** |
| #7 | **OPEN** | `ams-feed-bisect-tooling` | **no** | **no** | **no** | **no** |

`ls .agents/code-reviews/` returns only the three phase files plus
`pr-1-review.md` (PR #1's PHASE 6 diff review). `gh pr view 6 --json comments`
and `gh pr view 7 --json comments` both return **zero** comments; the single
`review` object on each is `copilot-pull-request-reviewer [COMMENTED]`, a bot,
which satisfies nothing in the documented pipeline.
`git log --all --diff-filter=D -- .agents/code-reviews .agents/execution-reports`
returns nothing, so the artifacts were never written and later removed — they
were never written.

**Why this is a violation and not a judgment call.** The omission is also
undisclosed. Both #6 and #7 replace the mandated `## Review` and `## Validation`
headings with their own (`## Measured after the fixes`, `## Gates`), so a reader
of either PR body gets no signal that a pipeline phase was skipped — which is the
specific thing the NOTES rule forbids. #6 is the weaker case (it *introduced*
`.claude/post-execute.json`, though `.agents/code-reviews/` already existed and
the pipeline's auto-detection would have resolved it anyway). #7 is unambiguous:
the profile was committed and in the tree a full day before the branch was cut.

**Mitigating, and worth stating.** Neither PR is thin on evidence. #6 documents
two real CI-found defects with runner output; #7 has a `## Not verified` section
stating plainly that neither script has been run against the printer. The gap is
in the *process artifacts and the second review lens*, not in candour — the
PHASE 6 pass exists specifically to read the diff *without* memory of the
implementation's reasoning, and that lens is what was lost.

**System-evolution fix — tighten enforcement.** The requirement currently lives
only in a config file and in a skill installed outside the repo; nothing
mechanical checks it (`grep -rl "code-reviews\|execution-reports" tests/ .github/`
→ no matches). This repo already has the idiom for fixing that:
`tests/test_ci_runs_the_gates.py` and `tests/test_printer_path_is_narrow.py` exist
precisely because *"a guardrail that lives only in config is one edit from being
gone."* Add the third: a test asserting every merged slice has both artifacts, or
a CI step failing a PR whose body has no `## Review` section. See also Gap 1 —
enforcement alone won't fix an agent that was never told.

---

## Coverage gaps

### Gap 1 — `CLAUDE.md` never mentions the review or report artifacts at all

**No existing rule covers this.** `CLAUDE.md` is this repo's primary AI-layer
document and the file an agent reads first. It is ~300 lines, exhaustive about
measurement discipline, and names `.agents/plans/` three times (lines 25–27). It
mentions `.agents/code-reviews/` **zero** times and `.agents/execution-reports/`
**zero** times:

```
$ grep -no "\.agents/[a-z-]*" CLAUDE.md | sort -u
25:.agents/plans
26:.agents/plans
27:.agents/plans
```

It also never mentions `.claude/post-execute.json` or the ship pipeline. So the
complete chain of custody for "this slice owes a code review and an execution
report" is: a JSON config file that names paths but no obligation → a skill
installed at **user level, outside the repository**. An agent that reads
`CLAUDE.md` cover to cover — the documented right thing to do here — cannot learn
the requirement exists.

**Recurrence: 2 of 2.** Every non-phase PR in this repo's history (#6, #7) dropped
the artifacts. Every phase PR (#1, #2, #3) produced them. That is not a discipline
gradient: the three phase PRs each had `.agents/plans/phase-N-*.md` naming their
own slice, so the convention was discoverable from inside the repo. #6 and #7 had
no such anchor and no rule to fall back on. One occurrence is an anecdote — this
is 100% of the cases where the in-repo signal was absent.

**Why it matters more here than in most repos.** The three named artifact
directories are how this project records *why* something was done, and `CLAUDE.md`
already treats undocumented process as a defect class. The repo's own stated
principle — a guardrail that lives only in config is one edit from being gone —
applies with full force to a guardrail that lives only in config *belonging to
another machine's plugin directory*.

**System-evolution fix — add a rule.** Add a short "Shipping a slice" section to
`CLAUDE.md` stating that every slice, phase or not, writes
`.agents/code-reviews/<slice>.md` and `.agents/execution-reports/<slice>.md`, that
the PR body carries `## Review` citing both and `## Validation` naming the gate
run, and that a deliberately skipped phase is *stated in the PR body* rather than
silently omitted. Pair it with Violation 1's mechanical check — the rule tells the
agent, the test catches the lapse.

---

## How to extend this file

Run Workflow A against your repo. For every candidate, first identify **which
documented rule or workflow step it actually tests** — read your own AI layer
(`CLAUDE.md`, `.claude/post-execute.json`, `.claude/PRINT-GATE.md`,
`.github/workflows/verify.yml`, or a skill's own precondition) and quote the
specific line. If no existing rule covers the pattern, that's a **coverage gap**,
not a violation — say so, and count how many times it recurred before treating it
as worth encoding (one occurrence is an anecdote, not a finding). Never invent a
rule to match a pattern — if you can't point to the actual documented text, the
finding doesn't belong here yet.

**Before writing any finding, check the PR's actual `state`/`mergedAt`
(`gh pr view <n> --json state,mergedAt,createdAt`) and, for a duplicate-cluster
candidate, each member's `headRefName`.** On this repo both checks were
load-bearing on the first pass: PR #7 is **open, not merged**, and the #1/#2/#3
duplicate cluster is a pure title-prefix artifact that the branch names disprove
outright. A finding built from inference about what "probably" happened is not the
same as one built from what the PR record actually shows.

# Judging rubric -- rendering a Tier 2 verdict

Used by both workflows: Workflow A (deciding whether an audit candidate is a real
finding worth adding to `failure-patterns.md`) and Workflow B (judging a live PR
against that rubric). The mechanics below are the same either way -- only what
happens with the verdict differs (see "Where the verdict goes" at the end).

## Why this is Tier 2, not Tier 1

Tier 1 (CI status, scope blast-radius, duplicate-vs-recent) is pure code -- API
calls and file-path checks, zero judgment, zero LLM tokens, and it runs in
milliseconds against hundreds of PRs at once. It exists to cheaply narrow a large
PR history down to a short candidate list, and to surface *evidence* — CI ran or
didn't, file paths look suspicious or don't. **What Tier 1 structurally can't do
is confirm what a specific documented rule actually requires, or read the content
Tier 1 can only gesture at.** CI green proves the suite didn't fail; it does not
prove the diff's content matches its claim, or that a documented investigate-first
step was genuinely followed rather than skipped. That's Tier 2's job: read the
actual content against the actual rule text, not a pattern match. Escalate to it
only for candidates Tier 1 already flagged, or that Workflow A's mining surfaced
as worth a look — reading every diff in a 1,000-PR history by hand defeats the
point of triaging cheap-first.

## The rubric — every verdict names the specific rule it's checking

There is no generic "is this PR good" question here. Every Tier 2 judgment is
against ONE specific entry in `failure-patterns.md` — a rule violation (a
documented step, checked against real evidence of compliance) or a coverage gap
(a recurring pattern, checked against how often it's shown up). Two concrete
shapes, matching the file's own two categories:

- **Rule-violation check:** does this PR's trajectory show the SPECIFIC documented
  step being followed or skipped? Example (Violation 1 in `failure-patterns.md`):
  `ci_status` PASS is necessary but not sufficient — also read whether the diff's
  actual content matches the claim, since CI passing and "the claim is true" are
  different questions Tier 1 alone can't distinguish. FAIL means "this specific
  rule wasn't followed, here's the evidence"; PASS means "checked against this
  rule, followed."
- **Coverage-gap check:** does this PR match a pattern already logged as
  recurring (e.g. Gap 1's duplicate-work pattern)? This isn't pass/fail against a
  rule that exists yet — it's "does this instance add to the count," which is
  itself useful signal for whether the gap is worth closing.

**Read the actual content, not just Tier 1's signal.** A scope-check FAIL or a CI
PASS is a prompt to look, not a verdict on its own — the harder case is a diff
where every touched file *sounds* plausible but the actual change doesn't do what
the claim says, or where CI is green but never tested what's being claimed.

**Always check and state the PR's actual `state`/`mergedAt`, never infer it from
how the PR body reads.** "Reads as complete" and "actually merged" are different
facts, and conflating them is a real mistake this skill made against itself
during testing: a PR that was blocked in review and never merged got written up
as though it had shipped and the problem resurfaced later — a meaningfully
different, and weaker, finding than what was claimed. `gh pr view <n> --json
state,mergedAt,createdAt` is one cheap call — run it before writing any finding
that describes a PR as having "shipped," "closed the issue," or "landed." The
same discipline applies to a claim of validation: **an agent's self-report
("tests pass," "verified," "comprehensive testing completed") is only
trustworthy if it's falsifiable** — it names the exact command and shows the
actual result, not a summary asserting success. If the PR body asserts something
a Tier 1 check or a `gh` call can directly verify, verify it before citing the
assertion as if it were the fact.

**State the verdict with a one-sentence, evidence-cited reason that names the
specific rule.** "Checked against Violation 1 (validation claimed, no evidence it
ran) — CI passed but the diff only modifies X, unrelated to the claimed Y" is
checkable by the reader; "looks wrong" is not. This matters more here than almost
anywhere else, because the whole point of grounding the rubric in real documented
rules is that a reader can go verify the rule text themselves.

## Where the verdict goes -- the two workflows differ here

**Workflow A (audit, optional report):** if writing the optional human-readable
summary (`assets/report-template.md`), present each finding as a small exercise --
the PR body first, on its own, with a "would you have approved this?" prompt,
*then* the evidence and verdict. That ordering reproduces, on the page, the actual
experience of "this looked fine until I checked," which is the whole reason the
audit matters. This is presentational, for a document meant to be read end to end
-- it's not part of Workflow A's real deliverable (the rubric file itself doesn't
need this framing, see `failure-patterns.md`'s own shape).

**Workflow B (live review, the actual eval):** post the verdict directly and
plainly, as a normal PR review comment -- no quiz framing, no delayed reveal. A CI
comment isn't read end to end the way a report is; the author and reviewers need
the finding immediately, with the evidence that backs it, so they can act on it as
part of the review they're already doing. State what was checked, cite the
specific evidence (file paths, PR numbers, diff excerpts), and say plainly if
nothing in the rubric applied rather than staying silent -- a silent pass and "the
check never ran" look identical from the outside.

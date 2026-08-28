# PR Trajectory Audit -- <owner/repo>

Mined <total_prs> PRs (<date range>) against this repo's own documented AI layer
(<path to the rules/workflow docs actually read, e.g. `.archon/commands/defaults/`
or `CLAUDE.md`>). Full methodology: `references/mining-methodology.md`.

## Summary

| Signal | Count |
|---|---|
| Documented AI-layer rules/steps identified and checked against | <n> |
| PRs referenced 2+ times by a later PR's body (useful for spotting a repeated violation) | <n> |
| Duplicate-title clusters found (candidate coverage gaps) | <n> |
| Candidates deep-dived for this report | <n> |
| Rule violations confirmed | <n> |
| Coverage gaps confirmed (recurred enough to be worth encoding) | <n> |

<One or two sentences on what the pass surfaced overall -- not a finding, just the
shape of what's here. E.g. "Two violations of documented validation/investigate
steps, and one coverage gap with no existing rule at all."</One>

---

## Finding 1 -- Rule violation: <name the documented step, e.g. "validation claimed without evidence it ran">

**The documented rule.** Quote the actual rule text you read, and cite the file.

> `<path to the rule file>` -- *"<verbatim quote of the specific requirement>"*

**The claim.** Show the PR body verbatim, exactly as a reviewer would have seen it
-- title, problem statement, what changed. No verdict yet.

> [PR #<n>](<url>) -- "<title>"
>
> <body excerpt, verbatim>

**The evidence.** Tier 1 findings (`ci_status`, scope check) plus what reading the
actual diff/comments showed. Cite specifics -- CI check names and results, file
paths, quoted diff or comment text -- not a summary.

**Verdict:** `<PASS|FAIL>` against this specific rule -- <one sentence, naming
exactly which evidence supports it>.

**System-evolution fix.** What would actually close this gap -- tighten the rule
into a hook/required check, not just "read the diff more carefully" (see
`references/failure-patterns.md`'s own fix language for the shape this should
take).

---

## Finding 2 -- Rule violation: <second documented step>

<Same shape as Finding 1 -- documented rule quoted, claim shown, evidence cited,
verdict, system-evolution fix.>

---

## Finding 3 -- Coverage gap: <name the recurring pattern>

**No existing rule covers this.** State plainly that this isn't a violation of
something documented -- it's a pattern recurring with nothing in the AI layer
addressing it.

List every PR in the cluster, oldest first, noting which one (if any) merged:

- [PR #<n>](<url>) -- "<title>" -- <state>
- [PR #<n>](<url>) -- "<title>" -- <state>
- ...

**Why this is worth encoding.** How many times it recurred, and why that count
(not just one occurrence) justifies adding a new rule/hook rather than treating
it as a one-off.

**System-evolution fix.** The specific new rule/skill/hook this should become.

---

<!-- Add additional findings in the same shape as needed -- rule violations first,
coverage gaps after. Keep every finding self-contained and readable by someone who
has never seen the underlying PRs or read the AI layer themselves -- cite the rule
text, cite numbers, quote real text, don't summarize from memory. -->

## What this audit does not check

State plainly what was out of scope for this pass -- e.g. "only the
`.archon/commands/defaults/` files were read, not every skill's own internal
preconditions," "candidates beyond the top <n> most-referenced weren't
deep-dived," "this pass didn't re-run against PRs opened after <date>." Silent
under-coverage reads as completeness; say what's uncovered instead.

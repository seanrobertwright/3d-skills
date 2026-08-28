---
slice: pr-trajectory-audit
title: "chore(agents): install the PR trajectory audit and its live review"
author: "seanrobertwright"
reviewed: 2026-08-28
recommendation: approve with one accepted risk
---

# Code review — `pr-trajectory-audit`

Working-tree review, run before the PR was opened. Scope: everything this slice
adds, plus the one existing file it edits.

| File | Change | Provenance |
|---|---|---|
| `.claude/skills/pr-trajectory-audit/**` (7 files) | added | **vendored verbatim** from `dynamous-community/workshops@main`, except `references/failure-patterns.md` |
| `.claude/skills/pr-trajectory-audit/references/failure-patterns.md` | rewritten | authored here; upstream copy was Archon's |
| `.github/workflows/trajectory-review.yml` | added | vendored verbatim from the skill's `assets/` |
| `.agents/audits/pr-trajectory-audit-2026-08-28.md` | added | authored here |
| `pyproject.toml` | 1 line + 6 comment lines | authored here |

## Findings

### 1 — MEDIUM · vendored code is excluded from lint, and that exclusion is load-bearing

`scripts/mine_prs.py` reports **30 E501s** against this repo's 100-column limit
and `ruff format` would rewrite it. Committing it unexcluded turns the CI `lint`
lane red on the first run.

Resolved by adding `.claude/skills/pr-trajectory-audit` to `extend-exclude` in
`pyproject.toml`, alongside the existing `viewer` / `*.md` / `.agents` entries,
with the reason written next to it. Excluded by **specific path**, not by
`.claude/skills`, so a first-party skill script added later is still linted —
the difference matters, because a blanket `.claude/skills` exclusion would
silently un-lint code this repo does own.

**Accepted risk, stated rather than resolved:** this repo now carries ~79 KB of
third-party Python and Markdown that its own gates do not check. `mine_prs.py`
has zero third-party imports (`argparse`, `json`, `re`, `subprocess`, `sys`,
`collections`, `datetime`, `difflib`) and shells out only to `gh`, which bounds
what it can do, but nothing in the suite would catch it changing on an update.

### 2 — MEDIUM · the workflow grants `--allowedTools` including `Bash(gh api:*)`

`trajectory-review.yml:148` grants the review agent:

```
Bash(uv run .claude/skills/pr-trajectory-audit/scripts/mine_prs.py:*),
Bash(gh pr diff:*), Bash(gh pr view:*), Bash(gh pr checks:*),
Bash(gh api:*), Bash(gh issue view:*)
```

`gh api:*` is the broad one — it is the whole GitHub REST surface under the
action's token, not a read-only subset. The job's `permissions:` block
(`contents: read`, `pull-requests: write`, `issues: write`, `id-token: write`,
`actions: read`, `checks: read`) is what actually bounds it, and that is where the
real limit lives.

Kept as-is rather than narrowed: the skill documents `gh api` as the working
fallback when `gh pr checks` fails inside the Action with `Resource not accessible
by integration`, and removing it would reintroduce a failure the upstream authors
measured. **Recorded here so the grant is a decision with a reason attached rather
than something inherited unread.**

### 3 — LOW · `pull_request` trigger will not review PRs from forks

Documented in the skill's own gotchas: GitHub downgrades `GITHUB_TOKEN` to
read-only for `pull_request` runs on fork PRs and may withhold secrets, so the
review silently no-ops. This repo is public, so that case is reachable.

Not fixed. The workflow carries an `issue_comment` trigger, which is the
maintainer-triggered fallback the skill recommends. Left as the mitigation rather
than adding `pull_request_target`, which would run with write access against
untrusted fork code — a materially worse trade.

### 4 — LOW · the audit report went to `.agents/audits/`, a new directory

`.agents/code-reviews/` holds reviews *of a slice*; the audit report is a review
of the repo's PR history and would read as a slice review sitting there — and
would have collided in meaning with this very file. New directory, consistent
with `.agents/diagnostics/` which PR #7 added on the same reasoning.

### 5 — MEDIUM · the slice touches a test file, and it was the repo's guard that forced it

`tests/test_one_ruler.py::test_every_installed_skill_is_covered_by_the_scan`
**failed** on the first full-gate run: it asserts every directory under
`.claude/skills/` appears in the hardcoded `SKILLS` list, and this slice installs
a ninth. That is the guard working — *"a new SKILL.md must not go unscanned"* is
its docstring, and a vendored skill is precisely the case where nobody thinks to
look.

Fixed by **registering** `pr-trajectory-audit` in `SKILLS`, not by exempting it.
The scan the registration subjects it to checks a `SKILL.md` for `lstsq`,
`def fit_circle`, `.ptp(` and `marching_cubes`; this one contains none, so being
scanned costs nothing and the guard keeps its meaning. The alternative — relaxing
the assertion to ignore non-`lril3d-` skills — would have exempted a skill for
being obviously harmless, which is how the next one gets exempted for looking
harmless. The reasoning is in a comment beside the entry.

**Consequence to note:** the hardware-free CI lane moves **470 → 471 passed**,
because `test_skills_contain_no_measurement_logic` is parametrized over `SKILLS`
and gains one case. `CLAUDE.md` and `verify.yml`'s comment both cite 470 as the
measured count. Neither is an assertion — `verify.yml` asserts only
`deselected > 0` and `skipped == 0` — so CI does not break, but the two documented
numbers are now stale by one. Flagged rather than silently left.

### 6 — LOW · nothing yet enforces Violation 1

The audit's own Finding 1 recommends a test asserting every slice carries its two
artifacts. This slice writes its artifacts but does **not** add that test.
Deferred deliberately — the enforcement test and the `CLAUDE.md` rule it pairs
with are a change to the repo's process layer and belong in their own slice,
where they can be reviewed as such rather than riding in on the tooling PR.
**Destination: a follow-up slice, named in the PR body.** Not "deferred" with
nowhere to go.

## What was verified, not assumed

- The 6 unmodified vendored files were **re-fetched from upstream and diffed**,
  not just byte-counted: `SKILL.md`, `assets/report-template.md`,
  `assets/trajectory-review.yml`, `references/judging-rubric.md`,
  `references/mining-methodology.md`, `scripts/mine_prs.py` — all byte-identical
  to `dynamous-community/workshops@main`. `.github/workflows/trajectory-review.yml`
  is byte-identical to the skill's `assets/` copy it was installed from.
  The 7th file, `references/failure-patterns.md`, is intentionally rewritten
  (upstream 12213 bytes of Archon findings, replaced wholesale).
- `trajectory-review.yml` parses as YAML; triggers `pull_request`
  (`opened`, `synchronize`, `ready_for_review`) and `issue_comment`; single job
  `trajectory-review`; includes `astral-sh/setup-uv@v3`, so the runner has `uv`
  for `mine_prs.py`.
- The secret name the workflow reads (`CLAUDE_CODE_OAUTH_TOKEN`, line 105)
  matches the one now set on the repo. An earlier misnamed secret
  (`CLAUDE_CODE_AUTH_TOKEN`) would have failed silently as an empty string.
- `failure-patterns.md` contains **zero** references to `archon` and exactly two
  top-level finding categories, as the skill requires.
- Fast gate after the `pyproject.toml` change: `ruff check` clean,
  `74 files already formatted`.

## Recommendation

**Approve.** Findings 1 and 2 are accepted risks with reasons recorded; 3 is an
upstream constraint with the better of two bad mitigations chosen; 4 is
organisational; 5 has a named destination.

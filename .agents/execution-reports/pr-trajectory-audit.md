---
slice: pr-trajectory-audit
title: "chore(agents): install the PR trajectory audit and its live review"
executed: 2026-08-28
base: master @ 823b3ef
---

# Execution report — `pr-trajectory-audit`

Installs the `pr-trajectory-audit` skill, runs its Workflow A against this repo's
whole PR history, and installs the CI action that runs Workflow B on future PRs.

## What was done

1. **Vendored the skill** from `dynamous-community/workshops` (private; fetched
   through authenticated `gh api`) into `.claude/skills/pr-trajectory-audit/`.
2. **Ran Workflow A** — read this repo's AI layer first, then mined all 5 PRs and
   checked each against it.
3. **Replaced `references/failure-patterns.md`.** The shipped copy was Archon's,
   citing `.archon/commands/defaults/*.md` files that do not exist here. The skill
   documents this trap explicitly; left in place it would have had Workflow B
   judging this repo's PRs against another repo's rules.
4. **Wrote the audit report** to `.agents/audits/`.
5. **Installed `.github/workflows/trajectory-review.yml`.**
6. **Fixed two gate failures the slice caused** — see below.

## Findings the audit produced

- **Violation 1** — the review half of the ship pipeline (PHASE 2 artifacts,
  PHASE 6 diff review, PHASE 7 comment) was dropped for both non-phase PRs (#6
  merged, #7 open) and observed on all three phase PRs.
- **Gap 1** — `CLAUDE.md` never mentions `.agents/code-reviews/` or
  `.agents/execution-reports/`. The requirement exists only in
  `.claude/post-execute.json` and in a skill installed outside the repository.

Full evidence: `.agents/audits/pr-trajectory-audit-2026-08-28.md`.

## Two gate failures, both caused by this slice

**1 — the CI `lint` lane would have gone red.** `scripts/mine_prs.py` reports 30
E501s against this repo's 100-column limit and `ruff format` would rewrite it.
Resolved by excluding `.claude/skills/pr-trajectory-audit` in `pyproject.toml`, by
its specific path so a first-party skill script is still linted.

**2 — `test_one_ruler.py::test_every_installed_skill_is_covered_by_the_scan`
failed.** Installing a ninth skill broke the guard asserting every installed
`SKILL.md` is scanned. Resolved by **registering** the skill in `SKILLS`, not by
exempting it.

> **A process failure of mine, recorded because it is the exact failure this repo
> exists to refuse.** The first full-gate run was
> `uv run pytest … | tail -15 && uv run python benchmarks/run_mutations.py`.
> Piping to `tail` makes the pipeline's exit status `tail`'s, so `&&` proceeded
> past a **failing** pytest, the mutation suite ran, and the chain exited 0 with
> `VERDICT: PASS` at the bottom of the output. A green badge over a failed gate.
> Caught by reading the output rather than the exit code; re-run under
> `set -o pipefail` with explicit exit-code capture. The numbers below come from
> that re-run.

## Validation — all measured 2026-08-28 at this tree

```
ruff check .                              All checks passed!
ruff format --check .                     74 files already formatted
interpreter + root-import gate            OK 3.13.15
pytest -m "not printer"                   478 passed,  12 deselected, 0 skipped
pytest -m slicer                            7 passed, 483 deselected, 0 skipped
pytest -m "not printer and not slicer"    471 passed,  19 deselected, 0 skipped
run_mutations.py                          caught 20/20  missed 0  false-positives 0
                                          harness-errors 0   VERDICT: PASS
                                          (30 mutations across 6 benchmarks)
```

Zero skips in every lane. `-m slicer` ran here against the installed Bambu Studio
rather than skipping, as `CLAUDE.md` requires.

`-m printer` was **not run**: it needs the P1S powered on with Developer Mode, and
this slice touches nothing on that path. Stated rather than omitted.

**The hardware-free lane moved 470 → 471.** `test_skills_contain_no_measurement_
logic` is parametrized over `SKILLS`, so registering the ninth skill adds exactly
one case. Both places documenting 470 as a measured number —
`.github/workflows/verify.yml` and `tests/test_ci_runs_the_gates.py` — were
updated to 471 with the reason and the new date. Neither is an assertion (the
workflow asserts `deselected > 0` and `skipped == 0`), so CI would not have
broken; they were stale documentation, which this repo treats as a defect.

## Files

| File | Change |
|---|---|
| `.claude/skills/pr-trajectory-audit/**` (6 files) | added, byte-identical to upstream (re-fetched and diffed) |
| `.claude/skills/pr-trajectory-audit/references/failure-patterns.md` | added, rewritten for this repo |
| `.github/workflows/trajectory-review.yml` | added |
| `.agents/audits/pr-trajectory-audit-2026-08-28.md` | added |
| `.agents/code-reviews/pr-trajectory-audit.md` | added |
| `.agents/execution-reports/pr-trajectory-audit.md` | added (this file) |
| `pyproject.toml` | ruff `extend-exclude` + 6 comment lines |
| `tests/test_one_ruler.py` | `SKILLS` gains `pr-trajectory-audit` + 4 comment lines |
| `tests/test_ci_runs_the_gates.py` | docstring count 470 → 471 |
| `.github/workflows/verify.yml` | comment count 470 → 471 |

## Not done, and not claimed

- **The live review has never run, and could not have.** Measured on PR #8: the
  `trajectory-review` check reported **pass in 13 s and posted nothing** — zero
  comments, zero reviews, every internal step `outcome=skipped`. The reason is in
  the job log and is by design:

  > `Skipping action due to workflow validation: The workflow file must exist and
  > have identical content to the version on the repository's default branch.`
  > … `your workflow will begin working once you merge your PR.`

  `claude-code-action` refuses to run a workflow file not already on the default
  branch, so a PR cannot rewrite the reviewer that reviews it. **The action is
  therefore untestable on the PR that introduces it** — the first real exercise is
  the next PR after this merges.

  **A green check over a job that did nothing** is this repository's founding
  failure mode, arriving in the tooling built to detect it. It is benign here, and
  it is worth writing down that the badge was green either way.

- **Whether the Claude GitHub App is installed on this repo is still unconfirmed.**
  The run read the OAuth token but skipped before reaching the Claude step, which
  is where a missing App install surfaces. That check is still outstanding.
- **Neither audit finding is fixed.** This slice ships the finding, not the
  remedy. Violation 1's enforcement test and Gap 1's `CLAUDE.md` section are a
  change to the process layer and belong in their own slice — destination named
  in the PR body, not left as an unhomed "deferred".
- **PR #7 remains non-compliant** with Violation 1 and is unaffected by this
  slice. It also will not be reviewed by the new action even after this merges:
  `pull_request` runs the workflow from the PR's head branch, so #7 needs a
  rebase or a push to pick it up.
- **The vendored skill is outside this repo's gates**, by the ruff exclusion
  above. Nothing here would catch it changing on a future update.

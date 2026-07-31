---
pr: 1
title: "feat(threedp): Phase 1 — the verification loop"
author: "seanrobertwright"
reviewed: 2026-07-31
recommendation: approve
---

# PR Review: #1 — Phase 1, the verification loop

**Branch**: `phase-1-verification-loop` → `master`
**Files changed**: 80 (+10,955 / −15)

> **How this review was produced — read this before weighting it.**
> The pipeline's Phase 6 calls for `/ship:prp-review --agents all`, a specialist multi-agent
> fan-out over the PR diff. That path is **unavailable in this install**: the vendored
> `commands/prp-review.md` dispatches to `workflows/agents.md` and `templates/review-report.md`,
> and neither file ships with the plugin (it contains only `commands/`, `examples/` and the
> `post-execute` skill).
>
> This review was therefore done **inline, by the same agent that made the changes**. That is a
> weaker instrument than the fan-out, and for a specific reason: the value of the second pass is
> that it reads the diff *without* memory of the implementation's reasoning, and that is exactly
> the familiarity an inline pass cannot shed. It is reported as what it is.
>
> To spend the effort where it could still be independent, this pass was aimed at the code the
> Phase 2 working-tree review did **not** examine — the three `SKILL.md` files, the viewer client,
> the mutation harness internals — rather than re-reading the library it already covered.

---

## Summary

Phase 1 delivers the verification loop end to end, with the mutation suite — not the benchmark
set — as the gate. The library's invariants are enforced structurally rather than by convention,
which is the property that decides whether this still works in six months. Validation is fully
green. Four Suggestion-level findings, all in the viewer client; none touches the library, the
verification loop, or any gate.

**Recommendation: APPROVE.**

---

## Implementation context

| Artifact | Path |
| --- | --- |
| Plan | `.agents/plans/phase-1-verification-loop.md` (1,332 lines, spike-backed) |
| Working-tree review | `.agents/code-reviews/phase-1-verification-loop.md` (7 findings, 6 fixed) |
| Execution report | `.agents/execution-reports/phase-1-verification-loop.md` |

Documented deviations in the execution report were treated as intentional, not as findings. Four
are recorded; the only one worth restating is that the plan contradicts itself on the public
import surface (7 modules in prose, 8 in its own validation command) and the implementation
follows the executable form. That is the right call.

---

## Validation

| Check | Status | Details |
| --- | --- | --- |
| Lint (`ruff check`) | **PASS** | All checks passed |
| Format (`ruff format --check`) | **PASS** | 45 files |
| Interpreter + root import gate | **PASS** | Python 3.13.14 |
| Tests (`pytest`) | **PASS** | **184 passed**, 0 failed |
| **Mutation suite** | **PASS** | **caught 13/13 · missed 0 · false-positives 0 · harness-errors 0** over 19 mutations |
| Viewer build (`vite build`) | **PASS** | 10 modules, built in 1.53 s |
| Type check | **n/a** | No type checker configured; the plan specifies none |
| CI | **none** | No `.github/workflows/`. Every number above is from a local run |

---

## Issues found

### Critical

None.

### Important

None.

### Suggestions

- **`viewer/src/main.js:97`** — the triangle count is wrong for 3MF files.
  - **Why**: `geometry.attributes.position.count / 3` is correct for an STL, which parses to
    *non-indexed* geometry. A 3MF parses to *indexed* geometry, where `position.count` is the
    vertex count; the displayed triangle count is then simply a wrong number. Renders are a
    channel rather than a gate, but a channel stating a wrong number is still stating one.
  - **Fix**: branch on `geometry.index`. **Applied.**

- **`viewer/src/main.js:135`** — `PROFILE_PATH` was declared below its only use site.
  - **Why**: `loadProfile()` reads it at line 121; the `const` sat at line 135. This works only
    because the call happens at the bottom of the file. Moving that call up would produce a
    temporal-dead-zone `ReferenceError` rather than failing visibly.
  - **Fix**: hoist the declaration above the function. **Applied.**

- **`viewer/src/main.js:148`** — a multi-body 3MF rendered partially and silently.
  - **Why**: the loader traversed to the first mesh and ignored the rest with no indication. A
    viewer that quietly draws part of a model is a worse signal than one that draws nothing —
    the user reads it as the whole part.
  - **Fix**: collect all meshes and state `showing 1 of N bodies` when there is more than one.
    **Applied.**

- **`viewer/src/main.js:129`** — the "printer profile unreadable" warning is transient.
  - **Why**: it is written to the shared status element and overwritten by the next status
    update once a model loads, so a genuine misconfiguration can pass unnoticed and the plate
    silently falls back to 256×256.
  - **Disposition**: **Deferred** by maintainer decision. Destination: the Phase 2 viewer work.

---

## Strengths

- **The mutation harness refuses to score against a broken baseline.** Before any mutation is
  judged, the *unmutated* part must pass its own intent **including** the mutation's injected
  `EXTRA_ASSERTS`. Without that, a bad ruler assertion would make every subsequent verdict
  meaningless while the report still looked populated.
- **Harness errors are a first-class category.** A mutation that crashes is neither caught nor
  missed, and `caught N/M` computes `M` excluding them — so a broken harness cannot inflate the
  score. Zero mutations found exits non-zero.
- **`lril3d-model/SKILL.md` is genuinely thin.** No geometry, no measurement, no numbers it
  derives itself. It makes the halt-for-confirmation step explicitly non-optional "including when
  the user seems to be in a hurry", which is the failure mode that step exists for, and it
  presents cited facts and agent choices in visibly different registers.
- **The BREP↔mesh cross-check is deliberately one-directional**, with the reasoning recorded: a
  Z-scan resolves a closed ring while BREP resolves faces, so a filleted rounded-rectangular
  profile is legitimately one ring and four faces. Making that check symmetric would generate
  false alarms forever.
- **Comments record what was measured, not what was assumed.** Nearly every non-obvious line
  cites a spike number, a trap that was hit, or the failure it prevents.

---

## Pattern compliance

- [x] Follows existing code structure — thin skills, thick library; no geometry in any `SKILL.md`
- [x] One-ruler rule holds; mechanically enforced, and the enforcement test verifies its own
      patterns still match `measure.py`
- [x] Naming conventions followed; mm-by-default with `_deg` suffixes where not
- [x] Tests added for new code (9 added with the review fixes; 175 → 184)
- [x] Documentation updated — `CLAUDE.md`, `README.md`, `PRINT-GATE.md`, plan and reports

---

## Recommendation

**APPROVE.** No Critical or Important findings. All validation green, including the mutation
suite, which is the gate that actually scores the verifier. The three applied viewer fixes are
contained to one file and touch no Python, so the suite result carries over unchanged.

The standing caveat is the one at the top of this document: the deep-review pass was inline
rather than a specialist fan-out, because the fan-out is not installed. If an independent lens on
the library matters before this lands, that is the gap to close.

*Reviewed by Claude — inline, not via the multi-agent fan-out.*

# Execution report — Phase 1: the verification loop

> **Provenance note.** The implementation in commit `c051a03` predates this session — this report
> is reconstructed from the plan, the diff, the committed artifacts and gate runs executed now,
> not from a recollection of writing the code. Sections that would require that recollection
> ("challenges encountered") are stated as *inferred from artifacts* and marked accordingly, and
> anything I could not verify is listed as unverified rather than assumed done.

## Meta information

- **Plan file:** `.agents/plans/phase-1-verification-loop.md` (1,332 lines, spike-backed 2026-07-30)
- **Commit:** `c051a03` on `phase-1-verification-loop`, branched from `db9effb`
- **Files added:** 78 · **modified:** 0 · **deleted:** 0
- **Lines changed:** +10,692 / −0

Added, by area:

| Area | Files | Notable |
| --- | --- | --- |
| `src/threedp/` | 9 | `measure` `features` `intent` `parts` `printability` `compensate` `io` `render` `__init__` |
| `tests/` | 10 | incl. `conftest.py` and `test_one_ruler.py` |
| `benchmarks/` | 40 | 5 parts × (`model.py` `params.json` `intent.json`) + 19 mutations + 2 harnesses |
| `.claude/` | 5 | 3 skills, `settings.json` print gate, `PRINT-GATE.md` |
| `viewer/` | 6 | Vite + three.js + WebSocket watcher |
| root / profiles | 8 | `pyproject.toml` `CLAUDE.md` `README.md` `.gitignore` `.python-version`, 3 profiles |

## Validation results

Every command below was executed in this session against `c051a03`.

- **Syntax & linting:** ✓ `ruff check .` → "All checks passed!"; `ruff format --check .` → 45 files
- **Type checking:** n/a — no type checker is configured. The plan specifies none; `ruff` is the
  only static gate. Not a skipped step, an absent one.
- **Interpreter + root import gate:** ✓ `OK 3.13.14` — confirms the `==3.13.*` pin held and that
  all 8 modules cross-import. (This machine's default is 3.14.6, which `bpy` has no wheel for.)
- **Unit tests:** ✓ **175 passed**, 0 failed at `c051a03`; **184** after the code-review fixes.
  4 `DeprecationWarning`s, all from `vtkmodules` (`numpy_support` shape assignment under
  NumPy 2.5) — third-party, not project code.
- **Integration / mutation suite:** ✓ **caught 13/13 · missed 0 · false-positives 0 ·
  harness-errors 0**, over **19 mutations across 5 benchmarks**. Exit 0.

The mutation count is non-zero, which the plan (§Level 3) and `CLAUDE.md` both call out as the
thing to check: a suite reporting zero mutations is a skipped layer wearing a green badge, not a
pass.

## Acceptance criteria

**Milestone 1A — all met, all verified.**

| Criterion | Evidence |
| --- | --- |
| `measure.py` tested against analytic geometry | `tests/test_measure.py`, no `build123d`/`trimesh` import |
| Duplicate-closing-vertex regression is first-class | `test_measure.py` + `method_keep_dup_vertex` mutation |
| A non-circular section cannot yield a diameter | `CircleFit.diameter` raises; `method_no_circularity` caught |
| Position from OCCT axis, not `face.center()` | `features.py:205-207`; no `.center()` call in the tree |
| Every assertion reports measured value + citation | verified in benchmark report output |
| Absent features FAIL with a reason | `dropped_cbore` caught; `_check_one` converts to FAIL, never skip |
| Tier 2 claims labelled ESTIMATE, excluded from verdict | `AssertionResult.gating`; `Report.passed` |
| Compensation never leaks into CAD output | `resolve(params, None)` applies no arithmetic |
| Bearing-holder mutations: all caught, zero false positives | 7/7 on that part |
| Method mutations detected | all 3 caught |
| Print gate present and committed | `.claude/settings.json`, verified in the diff |

**Milestone 1B — met, with three manual items unverified (below).**

All 5 benchmarks build, export STEP + STL + 3MF, and pass their intent. 19 mutations exceed the
"~15" target. One `cosmetic_*` false-positive detector exists **per benchmark**, which plan §31
required and which is the part most easily skipped. Three skills are under `.claude/skills/`
(correction C1). Ad-hoc measurement is mechanically prohibited.

## What went well

Inferred from the artifacts rather than from writing them:

- **The plan's spike-first structure paid off in a checkable way.** Numeric claims in the plan
  (LSQ −0.0028 mm, square-pocket residual 2.2474 vs 0.0016, overhang 1339.09 mm², min-wall 5.002)
  appear as assertions in the code and tests rather than as prose. Re-running the overhang
  benchmark now reproduces 1339.07 mm² against the spike's 1339.09 — the implementation is
  measurably consistent with the evidence it was planned from.
- **The 1A/1B milestone gate was respected.** The bearing holder carries 7 of the 19 mutations,
  including all 3 method mutations, so the milestone that "proves the thesis" is also the most
  heavily instrumented part. That ordering matches the plan's build order.
- **Invariants are enforced structurally rather than by convention** — `CircleFit.diameter`
  raising, `parts._assert_keys_are_globally_unique()` running at import, `Report.passed` requiring
  at least one gating assertion. These are the mechanisms that survive an agent writing the caller,
  which is the plan's stated design constraint.
- **`test_one_ruler.py` over-delivers on plan Task 32.** It tokenises rather than regexes, so a
  banned token inside a comment, string, docstring or f-string is correctly not flagged; it scans
  `tests/` as well as the required `src/` and `benchmarks/`; and it asserts that `measure.py`
  *does* contain a least-squares fit, so the ban patterns cannot silently rot into matching
  nothing. That last check is the difference between an enforced rule and a decorative one.

## Challenges encountered

Inferred from the code's own comments and defensive structure — each of these reads as a trap that
was hit and then documented in place:

- **Two phantom-feature traps on the mesh path**, both with fixes carrying explanatory comments: a
  Z-scan reporting a cone as a stack of perfectly circular cylinders (fixed by measuring taper
  between two sections), and the crown strip of a bore drilled along Y reading as exactly flat and
  exactly horizontal without being a face (fixed by rejecting facets with shallow-angle neighbours,
  `features.py:492-520`).
- **Coaxial same-radius features being mismatched across sections.** `_measure_axis_and_taper`
  carries a comment about two Ø7 counterbores 54 mm apart pairing with each other and reporting
  their separation as an enormous tilt; the fix restricts candidates to rings near the feature's
  own axis.
- **VTK colouring the feature edges red** regardless of `SetColor`, because `vtkFeatureEdges` tags
  its output with an edge-type scalar that the mapper resolves through a lookup table
  (`render.py:268-270`).
- **Console encoding.** `intent._symbols()` falls back to ASCII marks when stdout cannot encode
  `✅❌⚠` — a verifier that crashes on a Windows console while printing its own verdict reports
  nothing.

## Divergences from plan

**1. Public import surface gained `printability`**

- **Planned:** §Patterns states the public surface is `measure, features, intent, render,
  compensate, parts, io` (7 modules) and to keep it stable.
- **Actual:** 8 modules — `printability` is importable and is exercised by the root gate.
- **Reason:** the plan is internally inconsistent here. Its own Level 1 validation command
  (line 1163) imports all 8 including `printability`. The implementation follows the validation
  command.
- **Type:** Plan assumption wrong (internal contradiction; the later, executable form wins).

**2. `FeatureSet` / `Cylinder` carry more fields than the plan's sketch**

- **Planned:** `Cylinder(radius, axis_point, axis_dir, area)`; `FeatureSet(source, representation,
  cylinders, planes, bbox, volume, watertight)`.
- **Actual:** `Cylinder` adds `z_min`, `z_max`, `fit`; `FeatureSet` adds `noncircular`, `tapered`,
  `mesh`.
- **Reason:** required by ADR-4. Carrying the `CircleFit` is what lets `intent.check` consult
  `is_circular`, and the separate `noncircular`/`tapered` buckets are what turn a refused
  measurement into a FAIL with a reason instead of a silent omission.
- **Type:** Better approach found — the plan's sketch was illustrative, and ADR-4 in the same plan
  requires the richer shape.

**3. `extract()` accepts `.obj` and `.ply`**

- **Planned:** `.step`/`.stp` and `.stl`/`.3mf`.
- **Actual:** the mesh branch also accepts `.obj` and `.ply`.
- **Reason:** trimesh loads them through the same path at no cost.
- **Type:** Other (scope widened slightly). Note the error message was not updated to match — see
  the code review, low-severity finding.

**4. 19 mutations rather than ~15**

- Over-delivery against the plan's target, distributed so that every benchmark has a cosmetic
  false-positive detector. Not a divergence in intent.

**No load-bearing disagreement between plan and implementation was found**, so the pipeline's
stop condition for a planning defect does not apply.

## Skipped items

- **`coupon.py`** — correctly not built. PRD §6's tree lists it but §12 schedules it in Phase 2,
  and the plan resolves that conflict in favour of §12.
- **Slicer and printer paths** — out of Phase 1 scope by design. The print gate ships without them.
- **Type checking** — no checker configured; not called for by the plan.

## Unverified — stated rather than assumed

The plan's **Level 4 manual validation** has five steps. Three cannot be confirmed from artifacts,
and I have not performed them in this session:

1. **Viewer hot reload within ~1 s** with camera preserved — requires `npm run dev`, a browser and
   a live re-export. `viewer/server/watch.mjs` implements debounce plus size-settling, which is the
   right mechanism, but *implemented* is not *observed*.
2. **Contact-sheet legibility** — `tests/test_render.py` asserts the PNG is not a single flat
   colour, is a gradient, and that the part is visible against the background, which covers the
   white-on-white failure specifically. Whether a human finds the sheet legible is not established.
3. **Skill behaviour end-to-end** — that `lril3d-model` actually halts for confirmation before
   writing geometry is a claim about agent behaviour at runtime. The `SKILL.md` text requires it;
   no transcript demonstrates it.

Steps 2 (detection on a hand-edited `POCKET_DEPTH`) and 5 (print gate committed) *are* covered —
by the `shallow_pocket` mutation and by the diff respectively.

`npm install` / `npx vite build` (plan Task 25's validation) was also not run in this session;
`viewer/package-lock.json` is committed, but the build was not re-executed.

## Recommendations

**For `CLAUDE.md`:**

- Record the **units convention for report output**, not just for variable names. The existing rule
  covers identifiers (`angle_deg`) but the report formatter hardcodes `mm` on every value, which is
  how degrees and mm² ended up mislabelled in all five benchmark reports (code review, medium).
- Note that **`_measure_axis_and_taper` has three failure exits with two different safety
  outcomes**, and that the safe one (`inf` taper → refuse Tier 1) is the intended pattern. This is
  the kind of asymmetry that reads as deliberate on a quick pass.

**For the plan command:**

- The plan contradicted itself on the public import surface (7 modules in prose, 8 in the
  validation command). A plan that states an interface in two places should derive one from the
  other, or the executor has to guess which is authoritative.
- Level 4 manual steps had no place to record an outcome. A plan that ends with five manual checks
  and no result slots produces exactly this report's "unverified" section. Give them checkboxes
  with an evidence field.

**For the execute command:**

- Nothing to change on the evidence available. The build order held, the 1A gate was respected, and
  the delivered scope exceeds the plan's mutation target without weakening any guarantee.

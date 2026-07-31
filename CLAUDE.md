# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: Phase 1 implemented

The `threedp` package, three skills, the viewer, 5 benchmarks and a 19-mutation suite are in
place. Phase 1 ships **no slicer and no printer**.

- **`PRD.md` is the source of truth.** Link to its sections; do not copy its text into new docs.
  `PRD.md` is excluded from `ruff format` on purpose — ruff formats fenced Python blocks and
  rewrote its API-specification snippet on first run.
- **`.agents/plans/phase-1-verification-loop.md`** is the current implementation plan, backed by a
  spike run on this machine. It contains measured numbers, four PRD corrections, and five ADRs.
  Read it before implementing anything.

## What this project is

Claude Code skills that take a plain-language description of a physical object to a printable part.
The differentiator is **not** the CAD binding — a dozen OpenSCAD/CadQuery wrappers already exist.
It is the **verification loop**: *understand → confirm → model → measure against intent → iterate*.

The founding observation: an agent that generates confident, plausible, **wrong** geometry is the
default, and bounding boxes, volumes, and renders all fail to detect it. Measurement against
intent recorded *before* the geometry existed is what catches it.

## Architecture

**Thin skills, thick library.** `SKILL.md` files handle intent recognition, user interaction, and
narration. All geometry, measurement, and rendering lives in the `threedp` Python package, which is
testable without an agent. Never put geometry or measurement logic in a `SKILL.md`.

### The artifact relationship (the thing worth understanding first)

```
intent.json      <- WRITTEN FIRST, before any geometry, from parts-DB citations
                    and explicit user confirmation
model.py         <- parametric build123d program
params.json      <- each dimension tagged with a semantic role: hole | outer | neutral
   |
   +-- resolve(nominal)      -> out/*.step   nominal geometry, valid CAD, portable
   +-- resolve(calibration)  -> out/*.stl    compensated for THIS printer + material
```

Three consequences that are easy to get wrong:

- **Nominal geometry is the truth.** The STEP describes the part, never the
  part-plus-this-printer's-error. Compensation must never leak into CAD output.
- **Compensation is applied to *parameters*, not geometry.** Hole and outer deltas have opposite
  signs and need not reconcile into a single offset — that is the whole point.
- **Models are programs.** Changing 40mm to 45mm is an edit, never a regeneration.

### Verification tiers — by feature type, not representation

| Tier | Features | Guarantee |
|---|---|---|
| 1 | Axis-aligned regular features (bores, pockets, planes) | Dimensional, ±0.005mm. Full `intent.json` checking. |
| 2 | Freeform / organic surfaces | Topology + statistics only. Dimensional claims labelled **ESTIMATE**. |

A mesh-derived dimension is Tier 1 only if the circle fit passes the circularity gate **and** the
measured axis is within 1° of Z. Circularity alone is not enough: a Ø22 bore tilted 5° sections as
an ellipse whose residual is 0.042 mm — *inside* the 0.05 mm gate — while its diameter is inflated
by 0.084 mm. `features.py` measures the axis from centre drift between two sections to catch it.

BREP does *not* rescue freeform geometry, and mesh probing *is* Tier 1 for regular features. The
axis of difficulty is the kind of feature, not STEP-vs-STL.

### The mutation suite is the gate, not the benchmarks

Benchmarks passing proves nothing about the verifier if the verifier is only exercised by parts
that happen to be correct. `benchmarks/*/mutations/` inject known defects with declared expected
verdicts, and the verifier is scored on **caught / missed / false-positive**.

Two classes, both required: **geometry mutations** (a dimension is wrong) and **method mutations**
(the *ruler* is wrong). Geometry mutations structurally cannot catch a bad ruler.

## Non-negotiable rules

- **There is exactly one ruler.** All dimensional measurement flows through `src/threedp/measure.py`.
  Ad-hoc measurement elsewhere is prohibited and mechanically enforced by `tests/test_one_ruler.py`.
  Max-radius and bounding-box methods are banned for dimensional assertions — two improvised
  implementations once disagreed by 0.088mm, more than a press-fit tolerance.
- **A circle fit must never yield a diameter without a circularity check.** A square 20×20 pocket
  fits as a confident "24.4949mm circle". `CircleFit.diameter` raises unless `is_circular`.
- **Never touch the printer path.** Enforced at the harness layer in `.claude/settings.json`, not
  by agent discipline.
- **Absent features FAIL with a reason — never skip.** A missing counterbore *is* the defect.
- **Renders are a channel, not a gate.** They never contribute to a pass verdict.
- **All dimensions are millimetres.** Suffix a variable only when it is *not* mm (`angle_deg`).
- **Report numbers, never impressions.** Every claim carries a measured value or an explicit
  ESTIMATE label.

## Environment gotchas (measured on this machine, 2026-07-30)

These each cost real debugging time. All were verified empirically.

- **Pin Python to `==3.13.*`, not `>=3.13`.** This machine's default is **3.14.6**; `bpy` ships
  cp313 wheels only. `>=3.13` lets uv resolve 3.14 and the install fails.
- **PyPI `sdf` is the wrong package** — it is "Scientific Data Format". fogleman's SDF library is
  git-only: `sdf = { git = "https://github.com/fogleman/sdf" }`.
- **Skills must live in `.claude/skills/<name>/SKILL.md`.** A root-level `skills/` directory is
  never discovered. (`PRD.md` §6 shows the wrong path.)
- **`lxml` is required to read 3MF** with trimesh and is not pulled in transitively.
- **`Path3D.to_planar()` is deprecated past its removal date** → use `to_2D()`. Likewise
  `Scene.dump(concatenate=True)` → `Scene.to_geometry()`. A `.3mf` loads as a `Scene`, not a `Trimesh`.
- **Never use `face.center()` for hole position.** It defaults to `CenterOf.GEOMETRY`, which for a
  cylindrical face is a point *on the surface* — wrong by exactly the radius, and wrong plausibly.
  Use the OCCT axis: `BRepAdaptor_Surface(f.wrapped).Cylinder().Axis()`.
- **Shapely closes rings by repeating the first vertex.** Strip it before any centroid. Including
  it inflates a fitted diameter by 0.088mm.
- **Overhang angles are measured from vertical** (0 = vertical wall, 90 = horizontal ceiling).
  Exclude build-plate-contact faces, and give the top histogram bin an inclusive upper bound or
  exactly-horizontal ceilings — the worst case — fall out entirely.
- **`sdf` writes a progress bar to stdout**; do not parse its stdout as data. It does *not* need a
  `__main__` guard despite forking workers. It also emits a **triangle soup** — the raw mesh reads
  as non-watertight until coincident vertices are merged (`merge_vertices`), after which it has
  zero broken faces. Merge, then *verify*; never export the raw output.
- **Least-squares is insensitive to Shapely's duplicate vertex; max-radius is not.** Measured on
  the same 253-point ring: LSQ 29.9973 with and without it, max-radius 30.1387 vs 30.0249. The
  0.088mm bug is specifically *centroid + max-radius*, which is why the duplicate-stripping line
  in `fit_circle` is belt-and-braces rather than load-bearing — and why a mutation asserts exactly
  that.
- **A parts-db citation names a key, not a category.** Heat-set keys are suffixed `-insert`
  (`parts-db:M3-insert.hole_d`) so they cannot collide with `parts-db:M3.clearance`. A shared key
  would resolve to whichever table came first — silently, to a plausible wrong number. Enforced at
  import by `parts._assert_keys_are_globally_unique`.
- **Two mesh-path traps that produce phantom features**, both found on real benchmarks:
  a Z-scan reports a cone as a stack of perfectly circular "cylinders" (fixed by measuring taper
  between two sections), and the crown strip of a bore drilled along Y is exactly flat and exactly
  horizontal without being a face (fixed by rejecting facets with shallow-angle neighbours).

## Commands

```bash
uv sync --extra dev                       # install; resolves on Python 3.13
uv run ruff check . && uv run ruff format --check .
uv run pytest -v                          # full suite
uv run pytest tests/test_measure.py -v    # one file
uv run pytest tests/test_measure.py::test_duplicate_vertex -v   # one test
uv run pytest -k circular -v              # by keyword
```

**Root import + interpreter gate** — the single check that catches a wrong interpreter and any
cross-module import breakage:

```bash
uv run python -c "import sys; assert sys.version_info[:2]==(3,13), sys.version; from threedp import measure, features, intent, render, compensate, parts, io, printability; print('OK', sys.version)"
```

**The real gate** — the mutation suite. A green `pytest` with this skipped is *not* evidence the
verifier works:

```bash
uv run python benchmarks/run_mutations.py                      # all benchmarks
uv run python benchmarks/run_mutations.py --part bearing-holder
uv run python benchmarks/run_mutations.py -v                   # full report on any failure
```

Pass signal: `caught 13/13   missed 0   false-positives 0   harness-errors 0` over 19 mutations.
**If it reports zero mutations found, that is a FAILURE, not a pass** — a skipped layer wearing a
green badge. Mutations run against the **mesh** export: a BREP face query never fits a circle, so a
measurement-method mutation cannot bite there. The harness cross-checks STEP against STL on every
baseline build so the BREP path is not left unexercised.

Not every mutation expects FAIL. `cosmetic_*` mutations expect **PASS** and are the false-positive
detectors — a verifier that fails them cries wolf on every real part, which is a slower route to
the same place as no verifier at all.

Viewer:

```bash
cd viewer && npm install && npm run dev    # Node >=20; v24.18.0 verified present
```

## Phase boundaries

Phase 1 ships **no slicer and no printer**. When in doubt about scope, check `PRD.md` §12.

- **Phase 1** — the verification loop: `measure` → `features` → `intent`, 5 benchmarks, ~15 mutations,
  3 skills, viewer.
- **Phase 2** — `lril3d-dfm`, `lril3d-repair`, `lril3d-slice` (OrcaSlicer), `coupon.py`.
  Note `coupon.py` appears in the PRD §6 directory tree but is scheduled in §12 as Phase 2 — **§12 wins**.
- **Phase 3** — printer comms, and replacing `calibration.json`'s published defaults
  (`"measured": null`) with real measured values.

## Known accepted gaps

Stated plainly rather than papered over — do not "fix" these by weakening a guarantee:

- **Z-only mesh probing**: angled features are invisible. Mitigated by *refusing Tier 1 status*, not
  by guessing.
- **Benchmark 5 (gyroid vase) is Tier 2 and largely unverifiable.** Do not write dimensional
  mutations for it — that scores the verifier against a promise it never made.
- **Imported meshes have no parametrization** and fall back to uniform geometric offset, where the
  hole/outer asymmetry is real and unresolvable. Press fits on imported meshes are unsupported.

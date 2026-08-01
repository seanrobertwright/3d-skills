# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: Phase 2 implemented

The `threedp` package, six skills, the viewer, 6 benchmarks and a 27-mutation suite are in place.
Phase 2 ships a **slicer wrapper but still no printer** — no upload path of any kind.

- **`PRD.md` is the source of truth.** Link to its sections; do not copy its text into new docs.
  `PRD.md` is excluded from `ruff format` on purpose — ruff formats fenced Python blocks and
  rewrote its API-specification snippet on first run.
- **`.agents/plans/phase-1-verification-loop.md`** and
  **`.agents/plans/phase-2-printability-and-preparation.md`** are the implementation plans, each
  backed by a spike run on this machine. They contain measured numbers, PRD corrections, and
  ADRs 1–12. Read the relevant one before implementing anything.
- **The slicer is Bambu Studio, not OrcaSlicer** (Phase 2 correction C1). `PRD.md` §12 and §7 name
  OrcaSlicer; it is not installed on this machine and Bambu Studio is, with the complete BBL
  vendor profile tree. OrcaSlicer is a Bambu Studio fork sharing the CLI surface, so
  `profiles/slicer.json` holds the executable candidates and a second backend stays config rather
  than a rewrite.

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

### The Phase 2 layers, and where each one refuses

```
printability.py   measures  ->  dfm.py       compares against profiles/dfm-rules.json (cited)
repair.py         fixes     ->  verify()     re-measures; a moved dimension is a FAILED repair
slicer.py         runs it   ->  accept_slice ADR-10's four conditions; a 0.00 g result is refused
gcode.py          parses    ->  viewer       a channel, never a gate
```

Three rules that are easy to erode:

- **`dfm.py` performs no measurement and holds no threshold.** New measurements go in
  `printability.py`; thresholds go in `profiles/dfm-rules.json` **with a `source`**. Separated,
  tuning a rule is a JSON edit that cannot touch a measurement.
- **DFM gates only where an `intent.json` asserts `dfm_violation_count`** (ADR-8). DFM is advice
  about a *process*; intent is a claim about a *part*.
- **Only BLOCKER gates.** A WARNING is reported with its number and does not fail a part.

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
- **Never touch the printer path.** Enforced at the harness layer in `.claude/settings.json`, and
  mechanically by `tests/test_no_printer_path.py` — not by agent discipline.
- **Every DFM threshold carries a `source`.** `dfm.load_rules` refuses an uncited one, exactly as
  `parts.get` refuses an unknown key. A threshold in Python or in a `SKILL.md` is a threshold
  outside the config and outside the tests.
- **A repair is not complete until it is re-measured.** `repair()` never returns a mesh alone, and
  "it is watertight now" is not a verdict — a bridged bore is watertight.
- **A slice result is accepted on four independent conditions or not at all.** Each one alone was
  measured being satisfied by a failed run.
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

### Phase 2 additions (measured 2026-07-31 / 2026-08-01)

Bambu Studio CLI — each of these was reproduced on this machine:

- **The CLI writes 0 bytes to stdout on every run.** `result.json` is the machine-readable
  channel and it is written even on failure. Never parse stdout as data.
- **The BBL system presets are not self-contained and the CLI does not walk `inherits`.** The leaf
  `Bambu PLA Basic @BBL P1S 0.4 nozzle.json` has 23 keys and no `filament_density`; the value 1.26
  lives two files up and `fdm_filament_common`'s **0** is what ships. Unflattened, the slice
  *succeeds* and reports `0.00 g`. `slicer.flatten_preset` resolves the chain, root first.
- **Flattening must keep the original preset `name`.** A process preset's `compatible_printers` is
  a list of printer *names*; renaming the machine gives `return_code -17`.
- **`--export-3mf` needs a relative filename with `cwd` set.** An absolute path returns `-13`
  *while still writing a perfectly good `plate_1.gcode`* — so never infer success from a file.
- **`return_code 0, "Success."` on a slice that produced nothing.** `--slice 3` on a single-plate
  model writes a `result.json` with no `sliced_plates` key and no G-code at all. Hence ADR-10's
  four independent acceptance conditions.
- **`total_predication` is not reliably a top-level key.** Slicing a `.3mf` puts it at the top
  level; slicing a `.stl` puts it only inside each `sliced_plates` entry. Read per-plate first,
  then top level, then the G-code header — and refuse rather than report `0s`.
- **The G-code header's volume unit label is wrong**: `; total filament volume [cm^3]` is mm³.
  3580.16 mm × π(1.75/2)² = 8611 mm³ = 8.611 cm³ × 1.26 = 10.85 g, which is the mass in the same
  header. The field is named `volume_mm3`; do not "fix" it back.
- **Bambu's markers are not PrusaSlicer's.** `; FEATURE:`, `; CHANGE_LAYER`, `; Z_HEIGHT:` — with
  a leading space. A parser written to `;TYPE:`/`;LAYER_CHANGE` finds *zero* of each and produces
  an empty preview that looks like an empty part. Bambu also uses **relative E** (`M83`).
- **CLI G-code contains no thumbnail block at all** — one `; thumbnail_size = 50x50` config line
  and nothing else, so the P1S screen preview is blank (PRD correction C2). Not fixable here.

Repair:

- **`trimesh.repair.fill_holes` fills only tris and quads unless `use_fan=True`.** The fan is the
  hazard ADR-9 exists for, and declining it would make repair unable to close any real hole; the
  two passes are separate ops so the report says which one closed the mesh.
- **Fix inversion only *after* filling holes.** Inversion is detected from the sign of the
  enclosed volume, and an open surface does not enclose one — trimesh's own note is that
  `fix_normals` is "really only meaningful on watertight meshes". Run in the intuitive order the
  pipeline returned a **watertight mesh of −23065.76 mm³**: closed, plausible, and inside out,
  with every upward face reading as a 90° overhang to the DFM engine downstream.
- **An inverted mesh passes almost every check.** Watertight, winding-consistent, every bore
  sections as a perfect circle. Only the sign of the volume sees it, which is why
  `benchmarks/imported-mesh/intent.json` asserts `solid_volume: [1.0, null]` — a topology claim,
  open above so it cannot smuggle in a golden volume.

DFM:

- **A flared cone meets its own top face at a knife edge** — measured at 0.006 mm of material —
  which is a real `min_feature` BLOCKER and will mask whatever else you were testing. Give a test
  flare a collar.
- **`min_wall_mm` and `min_feature_mm` share one ray cast**, because a ray cannot tell a thin wall
  from a thin pin. They stay separate rules because the *fix* differs; expect them to fire
  together.

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
uv run python -c "import sys; assert sys.version_info[:2]==(3,13), sys.version; from threedp import measure, features, intent, render, compensate, parts, io, printability, dfm, repair, slicer, gcode, coupon; print('OK', sys.version)"
```

**The slicer layer is a gate, not a formality.** `slicer`-marked tests need Bambu Studio; a green
suite with them skipped is not evidence the wrapper works:

```bash
uv run pytest -m slicer -v        # must RUN here: report the count, expect 0 skipped
uv run pytest -m "not slicer" -q  # green on a machine with no slicer
```

**The real gate** — the mutation suite. A green `pytest` with this skipped is *not* evidence the
verifier works:

```bash
uv run python benchmarks/run_mutations.py                      # all benchmarks
uv run python benchmarks/run_mutations.py --part bearing-holder
uv run python benchmarks/run_mutations.py -v                   # full report on any failure
```

Pass signal: `caught 19/19   missed 0   false-positives 0   harness-errors 0` over 27 mutations
across 6 benchmarks.
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

Phase 2 ships **no printer path** — no FTPS, no MQTT, no socket, no upload. `--export-3mf`
produces a file a human sends by hand, which is PRD Risk 5's documented fallback and the end of
the line for this phase. `.claude/settings.json` and `.claude/PRINT-GATE.md` are unedited; their
`deny` → `ask` conversion arrives *with* `lril3d-print` in Phase 3 (ADR-5), and
`tests/test_no_printer_path.py` makes that mechanical rather than a promise. When in doubt about
scope, check `PRD.md` §12.

- **Phase 1** *(done)* — the verification loop: `measure` → `features` → `intent`, 5 benchmarks,
  19 mutations, 3 skills, viewer.
- **Phase 2** *(done)* — `lril3d-dfm`, `lril3d-repair`, `lril3d-slice` (**Bambu Studio**, not
  OrcaSlicer — correction C1), `coupon.py`, `gcode.py` + viewer preview, the `imported-mesh`
  benchmark, 27 mutations. `coupon.py` appears in the PRD §6 directory tree and is scheduled in
  §12 as Phase 2 — **§12 wins**, and it lives at `src/threedp/coupon.py`.
- **Phase 3** — printer comms, and replacing `calibration.json`'s published defaults
  (`"measured": null`) with real measured values using `coupon.fit_gauge`.
- **Phase 4** — multi-slicer abstraction.

## Known accepted gaps

Stated plainly rather than papered over — do not "fix" these by weakening a guarantee:

- **Z-only mesh probing**: angled features are invisible. Mitigated by *refusing Tier 1 status*, not
  by guessing.
- **Benchmark 5 (gyroid vase) is Tier 2 and largely unverifiable.** Do not write dimensional
  mutations for it — that scores the verifier against a promise it never made.
- **Imported meshes have no parametrization** and fall back to uniform geometric offset, where the
  hole/outer asymmetry is real and unresolvable. Press fits on imported meshes are unsupported.
- **`repair.verify` compares the file it was handed to the file it produced**, so damage that
  arrived *inside* the import is not repair's to catch — that is `intent.json`'s job. A PASS from
  `repair` says the repair changed nothing, never that the file is faithful to its designer.
- **A repair with no Tier 1 feature to compare reports UNVERIFIABLE**, not PASS. Organic geometry
  therefore never gets a green repair verdict, which is correct and is not a bug to fix.
- **Bridge spans are derived from face geometry, not from a slice**, and are labelled ESTIMATE. A
  slicer knows which perimeters actually land over air; this knows which faces point down.

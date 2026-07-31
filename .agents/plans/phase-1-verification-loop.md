# Feature: Phase 1 — The Verification Loop (MVP)

The following plan should be complete, but its important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils types and models. Import from the right files etc.

> **This plan is backed by a PRE-FLIGHT spike run on this machine on 2026-07-30.** Every
> dependency was installed, every core algorithm executed, and every numeric claim below was
> measured — not estimated. Spike artifacts live in the scratchpad
> (`.../scratchpad/spike/`). Where the PRD and the spike disagree, **the spike wins** and the
> discrepancy is called out explicitly under [PRD CORRECTIONS](#prd-corrections).

## Feature Description

`3d-skills` Phase 1 builds the **verification loop** — the differentiator the PRD identifies as
the entire product thesis. A user describes a part in plain language; the agent records
checkable intent *before* writing geometry, authors a parametric `build123d` model, then
**measures the result against that intent** using a single canonical ruler.

Phase 1 deliberately ships **no slicer and no printer**. Its sole job is to prove that the loop
— *understand → confirm → model → measure against intent → iterate* — catches geometry defects
that renders, bounding boxes, and volumes all miss.

The deliverable is: a versioned Python package (`threedp`), three Claude Code skills, a live
browser viewer, 5 benchmark parts, and a **mutation suite that scores the verifier itself** on
caught / missed / false-positive.

## User Story

As a **capable maker with a Bambu P1S**
I want to **describe a part in plain language and have the machine catch its own dimensional
mistakes before I ever slice it**
So that **a plausible-looking, confidently-wrong part never reaches my printer, and I never
have to hand-author parametric CAD for a household bracket.**

## Problem Statement

An agent that generates confident, plausible, **wrong** geometry is the default outcome, and
the usual quality signals do not detect it.

The PRD's v1 spike proved this concretely: a 608 bearing holder passed its bounding-box check,
had a plausible volume, and produced a clean render — while containing three genuine defects (a
pocket 0.5 mm too shallow to retain the bearing, mounting holes that silently weren't
counterbored, and a retaining lip 5× its intended thickness). **None was visible in the render.**

Worse, the verifier itself is a single point of failure. Two improvised implementations of
"measure this bore" disagreed by 0.088 mm — larger than a press-fit tolerance, enough to flip a
±0.05 assertion. A verifier with a subtly wrong ruler is *worse than no verifier*, because it
reports green.

The existing ecosystem does not help: a dozen OpenSCAD/CadQuery MCP servers and skills exist,
and every one is a single-tool wrapper that generates code and hands back a file. **None closes
the verification loop.**

## Solution Statement

Four mechanisms, in strict build order:

1. **One ruler, built first.** `measure.py` is the sole dimensional measurement implementation,
   unit-tested against analytically-known geometry before anything depends on it. Least-squares
   circle fitting is canonical; max-radius and bounding-box methods are prohibited for
   dimensional assertions.
2. **Intent before geometry.** `intent.json` records checkable assertions grounded outside the
   agent's own reasoning — parts-DB citations and explicit user confirmation — and is written
   *before* `model.py` exists.
3. **Feature extraction, not vision.** BREP face queries (STEP) and mesh cross-section probing
   (STL/3MF) both emit one common `FeatureSet` schema, which `intent.check()` scores per
   assertion with measured values.
4. **The verifier is itself scored.** A mutation suite injects known defects with declared
   expected verdicts and scores the verifier on caught / missed / false-positive — including
   *measurement-method* regressions, not just geometry defects.

**The load-bearing new design decision from the spike** (§ADR-1): a least-squares circle fit
returns a confident, plausible diameter even for a section that is not a circle at all. A square
20×20 mm pocket fits as a "24.4949 mm circle". The fit therefore **must** return a residual, and
the API **must make it impossible to consume a diameter without consulting the circularity
verdict**.

## Feature Metadata

**Feature Type**: New Capability (greenfield — repo currently contains only `PRD.md`)
**Estimated Complexity**: **High** — see [SCOPE WARNING](#scope-warning)
**Primary Systems Affected**: all (greenfield)
**Dependencies**: `build123d`, `trimesh`, `shapely`, `rtree`, `networkx`, `manifold3d`, `vtk`,
`numpy`, `lxml`, `bpy`, `sdf` (git), `pytest`, `ruff`; Node ≥20 for the viewer

---

## SCOPE WARNING

**Read this before starting.** Phase 1 as written in PRD §12 is roughly 8 Python modules + 3
skills + a Vite/three.js viewer + 5 benchmark parts + ~15 mutations. That is a large single
increment, and the PRD's own build-order note ("`measure.py` and its unit tests come first")
implies a natural seam.

This plan is delivered **complete and in full**, but the tasks are grouped into two internal
milestones with a hard gate between them:

- **1A — The Ruler and the Verifier** (Tasks 1–20). Ends at: mutation suite green on the bearing
  holder. This is the milestone that *proves the product thesis*. If 1A fails, nothing
  downstream matters.
- **1B — Surface and Coverage** (Tasks 21–33). Skills, viewer, remaining 4 benchmarks.

**Do not begin 1B until the 1A gate passes.** Scaling Phase 1 down is the user's call, not the
executor's — if you run short, complete 1A fully and report exactly what of 1B was left, rather
than half-finishing both.

---

## CONTEXT REFERENCES

### Relevant Codebase Files IMPORTANT: YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

The repository is **greenfield** — at plan time it contains exactly one tracked file. Verified:

```
$ git -C D:/repos/3d-skills log --oneline --all
db9effb Add PRD for 3d-skills: Claude Code skill set for 3D printing
$ git ls-files
PRD.md
```

- `PRD.md` — **the single source of truth.** Read in full before starting. Do not re-derive
  requirements from this plan alone; this plan implements the PRD and defers to it.
  - §2 Core Principles (lines 55–89) — the seven principles; **Principle 6 "There is exactly
    one ruler"** governs the entire module layout
  - §6.1 Intent Before Geometry (lines 247–275) — `intent.json` schema
  - §6.2 Verification Tiers (lines 276–298) — Tier 1 vs Tier 2 by *feature type*, not
    representation
  - §6.3 Measurement Strategy (lines 299–328) — `calibration.json` shape
  - §6.4 Compensation by Re-Parametrization (lines 329–354) — the `role` tag mechanism
  - §6.5 One Ruler (lines 355–373) — origin of `measure.py`
  - §6.6 Render Legibility (lines 374–383) — the mandated render settings
  - §11 Success Criteria (lines 535–599) — the acceptance gate
  - §15 Appendix — Spike Evidence (lines 679–789) — measured numbers this plan builds on

> There are **no existing code patterns to mirror in-repo.** Conventions in this plan are
> therefore *established*, not extracted, and are justified inline. `PRD.md` is the source of
> truth for conventions — do not re-paste its principle text into new docs; link to it.

**There is no `CLAUDE.md` in this repository.** Task 33 creates one.

### New Files to Create

**Project root**
- `pyproject.toml` — uv project, `requires-python = "==3.13.*"`
- `.python-version` — `3.13`
- `.gitignore` — must include `.env`, `.venv`, `out/`, `renders/`, `node_modules/`
- `CLAUDE.md` — conventions + the one-ruler rule (Task 33)

**Harness**
- `.claude/settings.json` — printer-send permission gate (ships before printer code exists)

**Package — `src/threedp/`**
- `__init__.py`
- `measure.py` — **THE canonical ruler.** Circle fitting, ring extraction, plane detection.
- `features.py` — BREP face queries + mesh cross-section probing → common `FeatureSet`
- `intent.py` — `intent.json` schema, checking, reporting
- `parts.py` — standard parts dimension database
- `printability.py` — min-wall sampling + overhang histogram (thin DFM slice)
- `compensate.py` — parameter re-resolution by semantic role
- `io.py` — nominal STEP + compensated STL/3MF export
- `render.py` — VTK offscreen contact sheet

**Profiles**
- `profiles/printer-p1s.json`, `profiles/filaments.json`, `profiles/calibration.json`

**Tests — `tests/`**
- `test_measure.py` — **analytic geometry, written FIRST**
- `test_parts.py`, `test_features.py`, `test_intent.py`, `test_printability.py`,
  `test_compensate.py`, `test_io.py`, `test_render.py`

**Benchmarks — `benchmarks/<part>/`** (`model.py`, `params.json`, `intent.json`, `mutations/`)
- `l-bracket/`, `enclosure/`, `bearing-holder/`, `overhang-test/`, `gyroid-vase/`
- `benchmarks/run_mutations.py` — the scoring harness

**Skills — `.claude/skills/`** (⚠ **not** `skills/` — see [PRD CORRECTIONS](#prd-corrections))
- `.claude/skills/lril3d-model/SKILL.md`
- `.claude/skills/lril3d-inspect/SKILL.md`
- `.claude/skills/lril3d-viewer/SKILL.md`

**Viewer — `viewer/`**
- `package.json`, `vite.config.js`, `index.html`, `src/main.js`, `server/watch.mjs`

### Relevant Documentation YOU SHOULD READ THESE BEFORE IMPLEMENTING!

- [build123d — Direct API Reference](https://build123d.readthedocs.io/en/latest/direct_api_reference.html)
  - Section: `Face` (`geom_type`, `radius`, `area`, `normal_at`, `center(CenterOf)`)
  - Why: the entire Tier 1 BREP extraction path in `features.py`
- [build123d — Import/Export](https://build123d.readthedocs.io/en/latest/import_export.html)
  - Section: `export_step`, `export_stl`, `import_step`, `Mesher`
  - Why: `io.py`; `Mesher` is the 3MF writer
- [build123d — Builders / Cheat Sheet](https://build123d.readthedocs.io/en/latest/cheat_sheet.html)
  - Why: `BuildPart` / `Locations` / `Mode.SUBTRACT` idiom used by every benchmark
- [trimesh — `Trimesh.section`](https://trimesh.org/trimesh.base.html#trimesh.base.Trimesh.section)
  - Why: mesh cross-section probing (Tier 1 on meshes)
- [trimesh — `Path3D.to_2D`](https://trimesh.org/trimesh.path.path.html)
  - Why: ⚠ `to_planar()` is **deprecated with removal dated 1/1/2026 — already past.** Use `to_2D()`.
- [trimesh — ray queries](https://trimesh.org/trimesh.ray.html)
  - Section: `intersects_location`
  - Why: min-wall thickness sampling in `printability.py`
- [Shapely — LinearRing](https://shapely.readthedocs.io/en/stable/reference/shapely.LinearRing.html)
  - Why: **rings repeat the first vertex as the last.** This one fact caused the 0.088 mm error.
- [VTK — offscreen rendering](https://docs.vtk.org/en/latest/api/python/vtkRenderingCore/vtkRenderWindow.html)
  - Why: `render.py`; verified working natively on Windows (no OSMesa/EGL needed)
- [Claude Code — settings & permissions](https://code.claude.com/docs/en/settings)
  - Section: `permissions` (`allow` / `ask` / `deny`)
  - Why: the printer gate. **Verified: `deny` takes precedence over `allow`, and rules *merge*
    across scopes rather than override.**
- [Claude Code — Agent Skills](https://code.claude.com/docs/en/skills)
  - Why: `SKILL.md` frontmatter and the `.claude/skills/` discovery path
- [fogleman/sdf](https://github.com/fogleman/sdf)
  - Why: organic path (benchmark 5). ⚠ **Not on PyPI under `sdf`** — see corrections.

### Patterns to Follow

**Naming conventions** (established here; no in-repo precedent):

- Modules and functions: `snake_case`. Classes/dataclasses: `PascalCase`.
- Public package surface is exactly the PRD §10 import line — keep it stable:
  ```python
  from threedp import measure, features, intent, render, compensate, parts, io
  ```
- Skill directories are kebab-case and prefixed `lril3d-`.
- **All dimensions are millimetres, always.** Never introduce a unit suffix on a variable that
  holds mm; suffix only when a value is *not* mm (`angle_deg`).

**The one-ruler pattern (Principle 6 — non-negotiable):**

```python
# ✅ CORRECT — every dimensional number flows through measure.py
from threedp import measure

fit = measure.fit_circle(ring)
dia = fit.diameter  # raises NotCircularError unless fit.is_circular

# ❌ PROHIBITED — ad-hoc measurement anywhere outside measure.py
dia = 2 * np.sqrt(((ring - ring.mean(axis=0)) ** 2).sum(axis=1)).max()  # max-radius: banned
dia = ring[:, 0].ptp()  # bbox: banned
```

Enforced by Task 32 (a grep-based test that fails if measurement primitives appear outside
`measure.py`).

**Error-handling pattern** — typed exceptions, never silent fallback. A verifier that swallows
an error reports green, which is the exact failure this product exists to prevent:

```python
class MeasurementError(Exception): ...


class NotCircularError(MeasurementError): ...


class FeatureNotFoundError(MeasurementError): ...


# ✅ absent feature => explicit FAIL with reason, never a default value
# ❌ never: `except Exception: return 0.0`
```

**Report pattern** — every verdict carries the measured number and its provenance:

```
✅ bore_diameter   = 21.997 mm   expected 21.95–22.05   [parts-db:608.od]
❌ pocket_depth    =  6.500 mm   expected  6.90– 7.10   [parts-db:608.width]
   └─ the 0.5mm fillet consumed pocket depth; a 7mm 608 will stand proud and won't retain
⚠️ vase_wall       =  1.180 mm   ESTIMATE (Tier 2 — organic surface, not dimensionally verified)
```

Never report an impression ("looks correct"); always report a number or an explicit ESTIMATE label.

> **Spike-snippet fidelity.** Every code snippet below that encodes measured behavior is
> annotated with the spike assertion it must agree with. If your implementation disagrees with a
> stated assertion, **the assertion is right and the snippet transcription is suspect** — stop
> and re-run the spike rather than "fixing" the assertion.

---

## PRD CORRECTIONS

The spike falsified four things stated or implied in `PRD.md`. **Implement the corrected form.**

| # | PRD says | Reality (measured) | Action |
|---|---|---|---|
| C1 | §6 dir structure: `skills/lril3d-model/SKILL.md` at repo root | Claude Code discovers project skills **only** under `.claude/skills/`. Verified against the installed skill tree. | Use `.claude/skills/lril3d-*/SKILL.md`. |
| C2 | §8 stack table lists package `sdf` | PyPI `sdf` is **"Work with Scientific Data Format files"** v0.3.8 — an unrelated library. fogleman's SDF is git-only. | Depend on `sdf @ git+https://github.com/fogleman/sdf` (spike pinned commit `d58a6fc`). |
| C3 | Implies `to_planar()` for sectioning | `to_planar` emits `DeprecationWarning: ... removal 1/1/2026` — **that date has passed.** | Use `Path3D.to_2D()`. Likewise `Scene.dump(concatenate=True)` → `Scene.to_geometry()`. |
| C4 | §15.3 implies mesh probing is sufficient for Tier 1 | True for *diameter*, but a circle fit reports a confident diameter for a **non-circular** ring (square pocket → "24.4949 mm"). | Circularity residual gate is **mandatory** (ADR-1). |

Additionally, PRD §6 lists `coupon.py` in the directory tree, but §12 schedules it in **Phase 2**.
**Phase 2 wins — do not build `coupon.py`.** `printability.py` is added (not in the PRD tree) to
host the §7 "thin DFM slice"; rationale in [ADR-3](#adr-3--printabilitypy-is-its-own-module).

---

## PRE-FLIGHT SPIKE RESULTS

All commands below were **executed on this machine on 2026-07-30**. Reproduce any of them if a
claim looks wrong.

### Environment — verified present

| Component | Measured |
|---|---|
| Python | 3.13.14 at `C:\Python313` (default on PATH is **3.14.6** — must pin) |
| `uv` | 0.8.17 |
| Node / npm | v24.18.0 / 11.16.0 |
| git | 2.55.0.windows.3 |

### Packages — all resolved and imported on Python 3.13

`build123d 0.11.1`, `trimesh 4.12.2`, `vtk 9.6.2`, `shapely 2.1.2`, `rtree 1.4.1`,
`networkx 3.6.1`, `manifold3d 3.5.2`, `numpy 2.5.1`, `bpy 5.2.0`, `lxml 6.1.1`,
`sdf 0.1 (git d58a6fc)`.

### Spike 1 — VTK offscreen rendering on Windows ✅

Wrote a 6461-byte PNG with `SetOffScreenRendering(1)`. **No OSMesa/EGL needed.** PRD §8
justification confirmed.

### Spike 2 — BREP face query is exact ✅

Cylinder OD 30 / bore Ø22 × 7 deep / through-hole Ø10:

```
GeomType.CYLINDER radius=15.0   GeomType.CYLINDER radius=11.0   GeomType.CYLINDER radius=5.0
planar z=+10.0000  planar z=-10.0000  planar z=+3.0000      -> pocket depth 10.0-3.0 = 7.000 exact
STEP roundtrip: cylindrical faces=3, radii={5.0, 11.0, 15.0}   -> exact, no drift
```

### Spike 3 — ⚠ `face.center()` is the WRONG call for hole position

Two Ø8 holes placed at **x = ±21**:

```
face.center()                       -> x = -25.00 , +17.00     ❌ off by exactly the radius
face.center(CenterOf.BOUNDING_BOX)  -> x = -21.00 , +21.00     ✅
BRepAdaptor_Surface(f.wrapped).Cylinder().Axis().Location()
                                    -> x = -21.000, +21.000    ✅ canonical, also yields direction
```

`CenterOf` members verified: `GEOMETRY` (default), `MASS`, `BOUNDING_BOX`.
**Use the OCCT axis for hole position and axis direction.** `center()` defaults to
`CenterOf.GEOMETRY`, which for a cylindrical face is a point *on the surface*.

### Spike 4 — the 0.088 mm finding, reproduced

Section at z=8.0 of a Ø22 bore, 253-point ring:

```
centroid+maxR WITH duplicate closing vertex   center=(-0.0516,-0.0137)  dia=22.0876  err=+0.0876
centroid+maxR WITHOUT duplicate               center=(-0.0138,+0.0077)  dia=22.0047  err=+0.0047
least-squares (canonical)                     center=(-0.0124,+0.0057)  dia=21.9972  err=-0.0028
```

PRD §15.5 claimed +0.0882; **measured +0.0876.** Same mechanism, same magnitude, same conclusion.
Least-squares lands at −0.0028, matching the PRD's ±0.003 claim.
**Assertion for `measure.py`: least-squares fit on analytic geometry must be within ±0.005 mm.**

### Spike 5 — ⚠ ADR-1 evidence: a circle fit lies confidently on non-circular input

```
ADVERSARIAL square 20x20 pocket, fitted as a circle:
  reported dia  = 24.4949 mm      <-- confident, plausible, WRONG
  max|residual| =  2.2474 mm      <-- the tell
CONTROL true round bore dia 20:
  reported dia  = 19.9969 mm
  max|residual| =  0.0016 mm
=> residual separates the two by 1446x
```

**Assertion: `fit_circle` must return `max_residual`, and `diameter` must be unreachable without
consulting `is_circular`.** Gate threshold 0.05 mm cleanly separates (0.0016 ≪ 0.05 ≪ 2.2474).

### Spike 6 — overhang metric validated against known truth

Cone flaring outward, underside at exactly 60° from vertical:

```
expected 60.00 deg   measured (area-weighted) 60.00 deg   max 60.14 deg
45-60 deg from vertical: area = 1078.41 mm2
60-90 deg from vertical: area =  260.69 mm2
UNSUPPORTED (>45 from vertical) = 1339.09 mm2 -> FLAG=True
```

Two traps found while validating:
- **Build-plate contact faces must be excluded** or the flat bottom registers as a 90° overhang.
- **The top bin needs an inclusive upper bound** (`< 90.0001`), else exactly-horizontal ceilings
  — the worst case — fall out of the histogram entirely. My first attempt scored a real overhang
  as all-zeros because of this.

### Spike 7 — min-wall sampling works

Plate 10 thick, Ø8 holes at x=±21 in a 60-wide box → true thinnest wall 5.0 mm.
2000 surface samples, inward ray cast: `min=5.002, p1=5.129, median=10.000`. ✅

### Spike 8 — 3MF export/roundtrip ✅ (with a dependency trap)

`Mesher().add_shape(...).write()` → 1698-byte 3MF. Reading it back with trimesh raised
`ModuleNotFoundError: No module named 'lxml'`. After `uv add lxml`: watertight, volume
1000.0 vs truth 1000.0. **`lxml` is a required dependency for 3MF reading and is not pulled in
transitively.**

### Spike 9 — `sdf` multiprocessing is safe without a `__main__` guard

Concern: `sdf` forks 24 workers; Windows `spawn` normally requires `if __name__ == "__main__":`.
Tested a 27-batch job from a plain script file → completed, exit 0. **No guard needed.**
⚠ But `sdf` writes a progress bar to **stdout**, so skills must not parse its stdout as data.

---

## ARCHITECTURE DECISIONS

### ADR-1 — `fit_circle` returns a residual, and `diameter` is gated on it

**Decision.** `measure.fit_circle()` returns a `CircleFit` dataclass whose `.diameter` property
**raises `NotCircularError`** unless `.is_circular` (i.e. `max_residual <= circularity_tol`,
default 0.05 mm). A `.diameter_unchecked` property exists for diagnostics only.

**Why.** Spike 5. A square pocket fits as a confident "24.4949 mm circle". Returning a bare float
makes the single most dangerous failure mode — plausible-but-wrong — *invisible at the call
site*. Making the unsafe path require a deliberate, differently-named call is the only
enforcement that survives an agent writing the calling code.

**Rejected alternative:** returning `(diameter, residual)` and trusting callers to check. Rejected
because the caller is frequently agent-generated, and the PRD's Risk 1 is precisely that
agent-generated code looks right and isn't.

### ADR-2 — Cylinder position comes from the OCCT axis, never `face.center()`

**Decision.** `features.py` extracts cylindrical-face location via
`BRepAdaptor_Surface(face.wrapped).Cylinder().Axis()`, taking both `Location()` and `Direction()`.

**Why.** Spike 3: `face.center()` reported holes at x = −25/+17 that are actually at x = ∓21 —
wrong by exactly the radius, and *silently plausible*. `CenterOf.BOUNDING_BOX` is correct for a
full cylinder but would break on a partial/trimmed cylindrical face; the OCCT axis is correct in
both cases and additionally supplies the direction needed to reject non-Z-axis holes.

### ADR-3 — `printability.py` is its own module

**Decision.** Min-wall sampling and the overhang histogram live in `printability.py`, not in
`features.py`.

**Why.** `features.py` answers *"what dimensions does this part have?"* (deterministic, exact,
feeds `intent.check`). Printability answers *"will this print?"* (statistical, sampled,
threshold-driven, feeds a human-readable critique). They have different determinism guarantees
and different consumers. PRD §12 also schedules the *full* engine as Phase 2 `lril3d-dfm`, so a
separate module is the clean seam for that later expansion. This is a documented addition to the
PRD §6 tree.

### ADR-4 — Conflict resolution: mesh Tier 1 requires BOTH circularity and axis-alignment

Two PRD statements could conflict at implementation time:

- §6.2: "Tier 1 … BREP face query **or** mesh cross-section + circle fit — Dimensional, ±0.005 mm"
- §6.2 measured limits: "scans along Z only, so **angled features are invisible**"

**Which wins:** the *limit* wins. A mesh-derived dimensional assertion is Tier 1 **only if** the
fit passes the circularity gate **and** the feature axis is within 1° of Z. Otherwise it is
reported as Tier 2 `ESTIMATE`, never as a pass. An angled bore must not silently receive a Tier 1
verdict from a Z-scan that sliced it into an ellipse — an ellipse from a 5°-tilted bore can pass
a loose circularity gate while reporting a diameter inflated by ~0.4%.

Concretely: when the source is a mesh and the assertion targets a diameter, `intent.check` must
consult `fit.is_circular`; a non-circular fit yields **FAIL with reason**, never a silent pass and
never a crash.

### ADR-5 — The print gate uses `deny` in Phase 1, relaxing to `ask` in Phase 3

**Decision.** Ship `deny` rules on printer-send paths now; Phase 3 converts them to `ask` when
`lril3d-print` actually exists.

**Why.** Verified from the settings docs: **`deny` takes precedence over `allow`, and rules merge
across scopes** — so a project `deny` cannot be silently widened by a user-level `allow`. In Phase
1 no send path exists, so `deny` costs exactly nothing and is strictly stronger than `ask`. PRD §9
requires the guardrail to be present *before* the capability arrives; `deny` is the strongest form
of that promise. The `ask` rules ship **alongside** (commented-forward in the same file) so Phase 3
is a one-line edit rather than a redesign.

---

## IMPLEMENTATION PLAN

### Phase 1A-i: Foundation (Tasks 1–4)

Repo scaffold, pinned toolchain, harness permission gate, hardware profiles. Nothing here depends
on geometry, and everything downstream depends on the Python pin being correct.

### Phase 1A-ii: The Ruler (Tasks 5–6)

`measure.py` **and its unit tests, written first.** Everything downstream trusts it. PRD §6.5
documents what happens when it is improvised.

### Phase 1A-iii: Extraction and Checking (Tasks 7–15)

`parts.py` → `features.py` (BREP + mesh) → `intent.py` → `printability.py` → `compensate.py` →
`io.py`. Each with tests against analytically-known geometry.

### Phase 1A-iv: The Real Gate (Tasks 16–20)

The bearing-holder benchmark, its mutations, and the scoring harness. **This is the milestone
that proves the thesis.**

### Phase 1B-i: Rendering and Skills (Tasks 21–26)

`render.py` contact sheet, then the three `SKILL.md` files.

### Phase 1B-ii: Viewer (Tasks 27–29)

Vite + three.js + WebSocket hot reload.

### Phase 1B-iii: Full Benchmark Coverage (Tasks 30–33)

Remaining 4 benchmarks, the full ~15-mutation suite, the one-ruler enforcement test, `CLAUDE.md`.

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order, top to bottom. Each task is atomic and independently
testable.

### Task Format Guidelines

- **CREATE**: New files or components
- **UPDATE**: Modify existing files
- **ADD**: Insert new functionality into existing code
- **MIRROR**: Copy pattern from elsewhere in codebase

---

## MILESTONE 1A — THE RULER AND THE VERIFIER

### 1. CREATE `pyproject.toml`, `.python-version`, `.gitignore`

- **IMPLEMENT**: uv project named `threedp`, `src/` layout, **`requires-python = "==3.13.*"`**.
  Dependencies exactly as spiked.
- **GOTCHA**: The machine's default Python is **3.14.6**. `>=3.13` would let uv resolve 3.14 and
  `bpy` would fail — pin `==3.13.*`, not `>=3.13`. (uv's own `init` emitted `>=3.13`; override it.)
- **GOTCHA**: `sdf` is **not** the PyPI package of that name (correction C2).
- **IMPORTS**:
  ```toml
  [project]
  name = "threedp"
  requires-python = "==3.13.*"
  dependencies = [
    "build123d>=0.11.1", "trimesh>=4.12.2", "shapely>=2.1.2", "rtree>=1.4.1",
    "networkx>=3.6.1", "manifold3d>=3.5.2", "vtk>=9.6.2", "numpy>=2.5.1",
    "lxml>=6.1.1",                                    # REQUIRED to read 3MF (spike 8)
    "bpy>=5.2.0",
    "sdf",
  ]
  [project.optional-dependencies]
  dev = ["pytest>=8", "ruff>=0.6"]

  [tool.uv.sources]
  sdf = { git = "https://github.com/fogleman/sdf" }    # NOT PyPI 'sdf' (spike/C2)

  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"
  ```
- **GOTCHA**: `.gitignore` **must** contain `.env` — PRD §9 requires printer credentials never be
  committed, and the file is created in Phase 3 when this is easy to forget.
- **VALIDATE**: `uv sync --extra dev && uv run python -c "import build123d,trimesh,vtk,sdf,bpy,lxml,sys; assert sys.version_info[:2]==(3,13); print('OK',sys.version)"`

### 2. CREATE `.claude/settings.json` — the printer gate

- **IMPLEMENT**: Per [ADR-5](#adr-5--the-print-gate-uses-deny-in-phase-1-relaxing-to-ask-in-phase-3),
  `deny` on every plausible send path, plus `deny` on credential reads.
- **PATTERN**: Rule syntax verified against the settings docs and the installed user settings.
  ```json
  {
    "permissions": {
      "deny": [
        "Read(.env)", "Read(.env.*)",
        "Bash(uv run lril3d-send*)",
        "Bash(python*send_to_printer*)",
        "Bash(python*lril3d_print*)",
        "Bash(curl*://*/upload*)",
        "Bash(ftp*)", "Bash(lftp*)"
      ]
    }
  }
  ```
- **GOTCHA**: `deny` beats `allow` and rules **merge** across scopes — a user-level `allow`
  cannot widen this. That is exactly why `deny` is used while no send path exists.
- **GOTCHA**: Do **not** put these in `.claude/settings.local.json` — that file is gitignored, and
  PRD §9 requires the guardrail to be committed.
- **VALIDATE**: `uv run python -c "import json;d=json.load(open('.claude/settings.json'));assert any('send' in r for r in d['permissions']['deny']);print('gate present')"`

### 3. CREATE `profiles/printer-p1s.json` and `profiles/filaments.json`

- **IMPLEMENT**: P1S: 0.4 mm hardened nozzle, build volume 256×256×256.
  `filaments.json`: per-slot inventory that **supports a slot type that is not an AMS bay**
  (PRD §15.7 — PC and PA run from the external spool holder).
- **GOTCHA**: Hardware values live in config from day one (PRD §3 secondary persona) — no
  printer constants inline in Python, anywhere.
- **VALIDATE**: `uv run python -c "import json;p=json.load(open('profiles/printer-p1s.json'));f=json.load(open('profiles/filaments.json'));assert p['nozzle_diameter']==0.4;assert any(s['type']!='ams' for s in f['slots']);print('profiles ok')"`

### 4. CREATE `profiles/calibration.json`

- **IMPLEMENT**: Published-literature defaults, exactly the PRD §6.3 shape:
  ```json
  { "PLA_generic": { "hole_delta_mm": 0.18, "outer_delta_mm": -0.05,
                     "first_layer_squish": 0.12, "measured": null,
                     "source": "published-default" } }
  ```
  Include `PETG_generic` and `ABS_generic` with their own defaults.
- **GOTCHA**: `"measured": null` marks an unvalidated literature default. Phase 3 replaces it
  with a date + coupon reference. **Staleness must surface at export** (Task 14).
- **VALIDATE**: `uv run python -c "import json;c=json.load(open('profiles/calibration.json'));assert all('hole_delta_mm' in v and 'measured' in v for v in c.values());print(len(c),'materials')"`

### 5. CREATE `tests/test_measure.py` — **WRITE THIS BEFORE `measure.py`**

- **IMPLEMENT**: Tests against **analytically-known** geometry — no CAD, no meshes, pure
  synthetic point sets where truth is arithmetic:
  1. Perfect circle r=11, 253 pts → `diameter == 22.0 ± 0.005`, `max_residual < 1e-9`
  2. **Duplicate closing vertex** (Shapely ring convention) → identical result to case 1.
     *This is the 0.088 mm regression. It must be a first-class test.*
  3. Circle offset to center (+5, −3) → recovered center within 1e-6
  4. **Square ring 20×20 → `is_circular is False` and `.diameter` raises `NotCircularError`**
     (spike 5)
  5. Ellipse (a=11, b=10.5, ≈ a 5°-tilted bore) → `is_circular is False` at tol=0.05
  6. Noisy circle (σ=0.002) → still circular, diameter within 0.005
  7. Degenerate: <3 points → raises `MeasurementError`, never returns a number
- **GOTCHA**: These tests must **not** import `build123d` or `trimesh`. The ruler is validated
  against arithmetic, not against another library that could share a bug.
- **VALIDATE**: `uv run pytest tests/test_measure.py -v` → **fails** (module absent). That is the
  expected state at end of this task.

### 6. CREATE `src/threedp/measure.py` — THE CANONICAL RULER

- **IMPLEMENT**:
  ```python
  @dataclass(frozen=True)
  class CircleFit:
      cx: float
      cy: float
      radius: float
      max_residual: float
      rms_residual: float
      n_points: int
      circularity_tol: float = 0.05

      @property
      def is_circular(self) -> bool:
          return self.max_residual <= self.circularity_tol

      @property
      def diameter(self) -> float:
          if not self.is_circular:
              raise NotCircularError(
                  f"max_residual={self.max_residual:.4f}mm exceeds tol="
                  f"{self.circularity_tol}mm - section is not a circle"
              )
          return 2.0 * self.radius

      @property
      def diameter_unchecked(self) -> float:
          return 2.0 * self.radius  # diagnostics ONLY
  ```
  Plus: `fit_circle(pts, circularity_tol=0.05) -> CircleFit`,
  `section_rings(mesh, z) -> list[np.ndarray]`, `plane_transitions(mesh, axis="z") -> list[float]`.
- **PATTERN** — algebraic (Kása) least-squares, **exactly as spiked**:
  ```python
  def fit_circle(pts, circularity_tol=0.05):
      pts = np.asarray(pts, dtype=float)
      # Shapely closes rings by repeating the first vertex. Including it shifts the
      # fitted center by 0.037mm and inflates diameter by 0.088mm - MORE than a
      # press-fit tolerance. See PRD 15.5 and spike 4.
      if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
          pts = pts[:-1]
      if len(pts) < 3:
          raise MeasurementError(f"need >=3 points to fit a circle, got {len(pts)}")
      x, y = pts[:, 0], pts[:, 1]
      A = np.c_[2 * x, 2 * y, np.ones(len(x))]
      b = x**2 + y**2
      c, *_ = np.linalg.lstsq(A, b, rcond=None)
      cx, cy = float(c[0]), float(c[1])
      r = float(np.sqrt(c[2] + cx**2 + cy**2))
      resid = np.hypot(x - cx, y - cy) - r
      return CircleFit(
          cx,
          cy,
          r,
          float(np.abs(resid).max()),
          float(np.sqrt((resid**2).mean())),
          len(pts),
          circularity_tol,
      )
  ```
- **SPIKE ASSERTIONS this must satisfy** (measured 2026-07-30 — if you disagree, re-run, don't edit):
  - analytic circle Ø22 → within **±0.005 mm**; on real tessellated mesh → **−0.0028 mm**
  - duplicate-vertex ring → **identical** to de-duplicated ring
  - square 20×20 → `max_residual = 2.2474`; true bore Ø20 → `max_residual = 0.0016` (**1446×** apart)
- **GOTCHA**: Use `to_2D()`, **never** `to_planar()` (correction C3).
- **GOTCHA**: **Do not** add a max-radius or bbox helper "for convenience". They are prohibited
  (PRD §6.5) and Task 32 fails the build if they appear.
- **VALIDATE**: `uv run pytest tests/test_measure.py -v` → **all pass**

### 7. CREATE `src/threedp/parts.py` + `tests/test_parts.py`

- **IMPLEMENT**: `parts.get(category, key) -> dict` with a `source` string on every record.
  Coverage per PRD §11: M2–M8 (clearance, tap, head Ø, socket-head height), heat-set inserts,
  608/623 bearings, common magnets, Pi hole pattern.
- **PATTERN**: every value carries provenance so `intent.json` can cite it:
  ```python
  parts.get("bearing", "608")  # -> {"od":22.0,"id":8.0,"width":7.0,"source":"parts-db:608"}
  parts.get("screw", "M4")  # -> {"clearance":4.5,"tap":3.3,"head_d":7.0,"head_h":4.0, ...}
  ```
- **GOTCHA**: M4 socket head is **4.0 mm tall** — the PRD §15.1 counterbore/plate-thickness
  conflict. A 4 mm counterbore in a 4 mm plate leaves zero material. `parts.py` must expose
  `head_h` so the model skill can catch this *before* geometry.
- **GOTCHA**: Unknown key raises `KeyError` with the list of valid keys — **never** returns a
  guessed default. A fabricated dimension defeats the entire external-truth anchor of §6.1.
- **VALIDATE**: `uv run pytest tests/test_parts.py -v` (assert 608 = 22/8/7, M4 clearance 4.5, unknown raises)

### 8. CREATE `src/threedp/features.py` — BREP path

- **IMPLEMENT**: `extract(path) -> FeatureSet`, dispatching on suffix. This task does `.step`.
  ```python
  @dataclass
  class Cylinder:
      radius: float
      axis_point: tuple
      axis_dir: tuple
      area: float


  @dataclass
  class PlaneFace:
      z: float
      normal_z: float
      area: float


  @dataclass
  class FeatureSet:
      source: str
      representation: str  # "brep" | "mesh"
      cylinders: list
      planes: list
      bbox: tuple
      volume: float
      watertight: bool
  ```
- **PATTERN** — axis extraction per [ADR-2](#adr-2--cylinder-position-comes-from-the-occt-axis-never-facecenter):
  ```python
  from OCP.BRepAdaptor import BRepAdaptor_Surface

  for f in shape.faces():
      if f.geom_type == GeomType.CYLINDER:
          cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
          loc, d = cyl.Axis().Location(), cyl.Axis().Direction()
          cylinders.append(
              Cylinder(cyl.Radius(), (loc.X(), loc.Y(), loc.Z()), (d.X(), d.Y(), d.Z()), f.area)
          )
  ```
- **GOTCHA**: **Never** `face.center()` for position — spike 3 measured it wrong by exactly the
  radius (holes at x=±21 reported as −25/+17), and it is wrong *plausibly*, which is worse.
- **GOTCHA**: `geom_type` compares against the `GeomType` enum (verified members: `PLANE`,
  `CYLINDER`, `CONE`, `SPHERE`, `TORUS`, `BEZIER`, `BSPLINE`, …). Don't string-match.
- **SPIKE ASSERTION**: OD30 / bore Ø22×7 / hole Ø10 → radii exactly `{15.0, 11.0, 5.0}`;
  planes at z = `{+10.0, −10.0, +3.0}` → pocket depth `10.0 − 3.0 = 7.000`.
- **VALIDATE**: `uv run pytest tests/test_features.py -k brep -v`

### 9. ADD mesh path to `src/threedp/features.py`

- **IMPLEMENT**: For `.stl` / `.3mf`: Z-scan sections, `measure.section_rings`, `fit_circle` on
  each ring, plane-transition detection with bisection refinement.
- **PATTERN**: every mesh-derived cylinder carries its `CircleFit` so `intent.check` can consult
  `is_circular` ([ADR-4](#adr-4--conflict-resolution-mesh-tier-1-requires-both-circularity-and-axis-alignment)).
- **GOTCHA**: `Path3D.to_planar()` is deprecated **past its removal date** → `to_2D()`.
- **GOTCHA**: Reading `.3mf` needs **`lxml`** (spike 8) — already a dependency; don't drop it.
- **GOTCHA**: `Scene.dump(concatenate=True)` is deprecated → `Scene.to_geometry()`. A 3MF loads
  as a `Scene`, not a `Trimesh`.
- **GOTCHA**: Z-scan **cannot see angled features** (PRD §6.2). Any cylinder whose axis deviates
  >1° from Z must be flagged Tier 2 ESTIMATE, never given a Tier 1 dimensional verdict.
- **GOTCHA**: Transition detection quantizes to step size — bisect to reach the ±0.005 mm
  guarantee, don't just report the step boundary.
- **SPIKE ASSERTION**: on the same part, mesh probing recovers bore 21.997 (truth 22.000),
  OD 29.997 (truth 30.000) — i.e. **within 0.003 mm**.
- **VALIDATE**: `uv run pytest tests/test_features.py -v` (both paths; assert BREP and mesh agree
  within 0.01 mm on the same part — this is the cross-check that catches a one-sided bug)

### 10. CREATE `src/threedp/intent.py` + `tests/test_intent.py`

- **IMPLEMENT**: schema load/validate for PRD §6.1 `intent.json`; `check(features, path) -> Report`.
- **PATTERN**: PRD §6.1 shape exactly — `{"holds": str, "asserts": [{name: [lo, hi], "source": str}]}`
  where `hi = null` means unbounded (`min_wall: [3.00, null]`).
- **GOTCHA**: golden bbox/volume are a **pure regression guard, demoted** (PRD §6.1). They cannot
  detect first-pass error — only drift. Report them in their own section, clearly labelled
  "drift only", and **never** let them contribute to the pass/fail verdict.
- **GOTCHA**: A missing feature is a **FAIL with reason**, never a skip. PRD §15.2 defect 2 was
  "no 4.5 mm cylinder existed anywhere" — an absent feature *is* the defect. A checker that skips
  absent features would have scored that part green.
- **GOTCHA**: Per ADR-4, a mesh-sourced diameter assertion whose `CircleFit.is_circular` is False
  is a FAIL with reason — not a crash, not a pass.
- **GOTCHA**: Tier 2 dimensional claims must be **labelled ESTIMATE** and excluded from pass/fail.
- **VALIDATE**: `uv run pytest tests/test_intent.py -v`

### 11. CREATE `src/threedp/printability.py` + `tests/test_printability.py`

- **IMPLEMENT**: `min_wall(mesh, samples=2000) -> WallReport`,
  `overhang_histogram(mesh, threshold_deg=45) -> OverhangReport`.
- **PATTERN** — overhang, **exactly as validated in spike 6**:
  ```python
  # angle measured FROM VERTICAL: 0 = vertical wall (fine), 90 = horizontal ceiling (worst)
  ang = np.degrees(np.arcsin(np.clip(-mesh.face_normals[:, 2], -1.0, 1.0)))
  zmin = mesh.bounds[0][2]
  on_plate = (np.abs(mesh.triangles[:, :, 2] - zmin).max(axis=1) < 1e-6) & (
      mesh.face_normals[:, 2] < -0.999
  )
  unsupported_area = mesh.area_faces[(~on_plate) & (ang > threshold_deg)].sum()
  ```
- **GOTCHA**: **Exclude build-plate-contact faces** or the flat bottom scores as a 90° overhang.
- **GOTCHA**: The top bin needs an **inclusive** upper bound (`< 90.0001`). My first spike
  attempt used `< 90` and scored a real overhang as all-zeros — exactly horizontal ceilings, the
  worst case, fell out of the histogram.
- **GOTCHA**: A vertical wall is `ang == 0`. Do not report "0–30° of overhang" as a defect; it's
  the normal case. Label bins from vertical.
- **SPIKE ASSERTIONS**: known 60° cone → area-weighted **60.00°**, unsupported area
  **1339.09 mm²**, FLAG True. Plate 10 thick w/ Ø8 holes at x=±21 in a 60-wide box →
  `min_wall = 5.002` (truth 5.0).
- **VALIDATE**: `uv run pytest tests/test_printability.py -v`

### 12. CREATE `src/threedp/compensate.py` + `tests/test_compensate.py`

- **IMPLEMENT**: `resolve(params, calibration=None) -> dict` applying deltas by semantic `role`.
- **PATTERN**: `params.json` tags each dimension (PRD §6.4):
  ```json
  {"BORE": {"value": 22.0, "role": "hole"},
   "OD":   {"value": 30.0, "role": "outer"},
   "WIDTH":{"value": 7.0,  "role": "neutral"}}
  ```
  `role: hole` → `+hole_delta_mm`; `role: outer` → `+outer_delta_mm`; `role: neutral` → unchanged.
- **GOTCHA**: `resolve(params, None)` must return **nominal, byte-identical** values. PRD §11:
  "STEP dimensions equal nominal — compensation never leaks into CAD output." Test this explicitly.
- **GOTCHA**: Compensation is applied to **parameters, not geometry**. Hole and outer deltas have
  opposite signs and need not reconcile into one offset — that is the whole point of §6.4.
- **SPIKE ASSERTION** (PRD §15.4): `hole_delta +0.18`, `outer_delta −0.05` applied independently
  → bore +0.181, outer −0.064. They do **not** cancel; do not try to unify them.
- **GOTCHA**: If `calibration["<mat>"]["measured"] is None`, `resolve` must return a
  `stale=True` flag so Task 14 can surface the warning.
- **VALIDATE**: `uv run pytest tests/test_compensate.py -v`

### 13. CREATE `src/threedp/io.py` + `tests/test_io.py`

- **IMPLEMENT**: `export(part, stem, nominal=("step",), compensated=("stl","3mf"), calibration=None)`.
- **PATTERN**: verified working API — `export_step`, `export_stl`, and `Mesher` for 3MF:
  ```python
  from build123d import export_step, export_stl, Mesher

  m = Mesher()
  m.add_shape(part, linear_deflection=0.01, angular_deflection=0.1)
  m.write(f"{stem}.3mf")
  ```
- **GOTCHA**: The **nominal** STEP is written from the un-resolved model; the **compensated**
  STL/3MF from the re-resolved one. Two separate model builds — never post-process the STEP.
- **GOTCHA**: `linear_deflection` drives mesh fidelity. PRD §15.5 measured that tessellation
  tolerance had **no effect** on fit accuracy (identical at 0.1 / 0.01 / 0.001) — so pick 0.01 for
  size and do **not** treat tightening it as a fix for a measurement disagreement. The *method*
  dominates, not the mesh.
- **SPIKE ASSERTION**: 3MF roundtrip of a 10 mm cube → watertight, volume **1000.0** vs truth 1000.0.
- **VALIDATE**: `uv run pytest tests/test_io.py -v` (assert STEP radii == nominal exactly; assert
  compensated STL bore ≠ nominal when calibration supplied)

### 14. ADD calibration-staleness warning to `io.py`

- **IMPLEMENT**: On any compensated export where `measured is None`, emit a clear warning naming
  the material and that it is a published default (PRD Risk 7).
- **VALIDATE**: `uv run pytest tests/test_io.py -k stale -v`

### 15. CREATE `benchmarks/bearing-holder/` — the fit case

- **IMPLEMENT**: `intent.json` **first**, then `params.json`, then `model.py`. 608 press-fit
  holder, mirroring PRD §6.1's worked example.
- **PATTERN**: `intent.json` exactly as PRD §6.1 (bore 21.95–22.05 `parts-db:608.od`,
  pocket 6.90–7.10 `parts-db:608.width`, lip 0.80–1.50 `user-confirmed`, min_wall
  `[3.00, null]`, mount hole 4.40–4.60 `parts-db:M4.clearance`).
- **GOTCHA**: This is the part that carried **three real defects** in the PRD spike. The correct
  model must have pocket depth **7.0 (not 6.5)**, lip **1.0 (not 5.0)**, and mount holes that
  **actually are counterbored**. Verify all three against `intent.check` before proceeding.
- **VALIDATE**: `uv run python benchmarks/bearing-holder/model.py && uv run python -c "from threedp import features,intent;f=features.extract('benchmarks/bearing-holder/out/part.step');r=intent.check(f,'benchmarks/bearing-holder/intent.json');print(r);assert r.passed"`

### 16. CREATE the mutation mechanism

- **IMPLEMENT**: Each mutation is a Python module declaring its override and its expected verdict:
  ```python
  EXPECT = "FAIL"  # or "PASS" for cosmetic changes
  REASON = "pocket too shallow to retain a 7mm 608"
  PARAMS_OVERRIDE = {"POCKET_DEPTH": 6.5}


  def patch(builder): ...  # optional, for structural defects (dropped counterbore)
  ```
- **GOTCHA**: `PARAMS_OVERRIDE` covers dimensional defects; `patch()` is required for
  **structural** ones like a dropped counterbore, which no parameter change can express.
  Both must be supported — PRD §15.2 defect 2 was structural.
- **VALIDATE**: `uv run python -c "import importlib.util,sys;spec=importlib.util.spec_from_file_location('m','benchmarks/bearing-holder/mutations/shallow_pocket.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);assert m.EXPECT=='FAIL';print('mutation loads')"`

### 17. CREATE `benchmarks/bearing-holder/mutations/` — the four PRD-named mutations

- **IMPLEMENT**, exactly per PRD §11 (three are **real defects from the spike**):
  | file | change | expected |
  |---|---|---|
  | `shallow_pocket.py` | pocket 7.0 → 6.5 | **MUST FAIL** |
  | `thin_wall.py` | wall 4.0 → 1.1 | **MUST FAIL** |
  | `dropped_cbore.py` | counterbore removed (`patch`) | **MUST FAIL** |
  | `cosmetic_fillet.py` | fillet 0.5 → 0.6 | **MUST PASS** |
- **GOTCHA**: `cosmetic_fillet` is the **false-positive detector**. If it fails, the verifier is
  over-tight and would cry wolf on every real part. It is as important as the three defects.
- **VALIDATE**: (covered by Task 19)

### 18. CREATE measurement-method mutations

- **IMPLEMENT**: Per PRD §6.5, mutations that attack **the ruler**, not the geometry — monkeypatch
  `measure.fit_circle` with a known-bad implementation and assert the suite goes red:
  - `method_maxradius.py` — centroid + max-radius (**the +0.0876 mm bug**) → MUST be detected
  - `method_keep_dup_vertex.py` — don't strip Shapely's duplicate closing vertex → MUST be detected
  - `method_no_circularity.py` — `is_circular` always True → MUST be detected **by the square-pocket
    fixture** (spike 5)
- **GOTCHA**: These are the highest-value tests in the suite. A verifier with a subtly wrong ruler
  reports green forever (PRD Risk 2). Geometry mutations cannot catch this class of bug — only
  method mutations can.
- **VALIDATE**: (covered by Task 19)

### 19. CREATE `benchmarks/run_mutations.py` — the scoring harness

- **IMPLEMENT**: For each mutation: build with override/patch → extract → `intent.check` →
  compare verdict to `EXPECT`. Score **caught / missed / false-positive**. Non-zero exit on any
  miss or false positive.
- **PATTERN**: report format:
  ```
  bearing-holder/shallow_pocket    expect FAIL  got FAIL  ✅ caught
  bearing-holder/cosmetic_fillet   expect PASS  got PASS  ✅ no false positive
  ---
  caught 6/6   missed 0   false-positives 0        VERDICT: PASS
  ```
- **GOTCHA**: A mutation that **errors** during build is neither caught nor missed — it is a
  **harness bug**. Report it as a third, loud category; never silently count a crash as "caught".
- **VALIDATE**: `uv run python benchmarks/run_mutations.py --part bearing-holder` → exit 0,
  `missed 0`, `false-positives 0`

### 20. 🚦 **MILESTONE 1A GATE**

- **VALIDATE**: All must pass before starting 1B:
  ```
  uv run pytest -v
  uv run python benchmarks/run_mutations.py --part bearing-holder
  ```
- **Success signal**: full suite green; mutation report shows **caught 7/7, missed 0,
  false-positives 0**. If this gate fails, **stop and report** — do not start 1B.

---

## MILESTONE 1B — SURFACE AND COVERAGE

### 21. CREATE `src/threedp/render.py` — the contact sheet

- **IMPLEMENT**: `contact_sheet(path, out, views=("iso","top","front","right"),
  projection="parallel", scale_bar=True, plate="p1s")` → one annotated PNG.
- **PATTERN**: PRD §6.6 mandates **all** of: gradient background, Phong-shaded colored material,
  silhouette + feature edges at 20–25°, three-point lighting, **parallel projection on the three
  orthographic views**, mm scale bar, build-plate outline.
- **GOTCHA**: A naive VTK render is **a white part on a white background** — technically
  successful, completely useless. This was confirmed in the PRD spike. The settings above are
  requirements, not styling preferences.
- **GOTCHA**: Set `camera.SetParallelProjection(True)` for ortho views; leave perspective for iso.
- **GOTCHA**: Renders are a **channel, not a gate** (Principle 1). Never let render success
  contribute to a pass verdict.
- **SPIKE ASSERTION**: VTK offscreen works natively on Windows (6461-byte PNG written, VTK 9.6.2).
- **VALIDATE**: `uv run pytest tests/test_render.py -v` (assert PNG exists, >10 KB, and is not
  single-color — decode and assert stddev of pixel values > 10)

### 22. CREATE `.claude/skills/lril3d-model/SKILL.md`

- **IMPLEMENT**: frontmatter `name` + `description`, then the PRD §7 five-step workflow:
  resolve from parts DB w/ citations → **present judgment calls and get confirmation** → write
  `intent.json` → author `model.py` + `params.json` → export.
- **PATTERN**: frontmatter verified against installed skills:
  ```markdown
  ---
  name: lril3d-model
  description: Use when the user describes a physical object to model, print, or fabricate. Captures intent, confirms judgment calls, then authors parametric build123d geometry.
  ---
  ```
- **GOTCHA**: **Location is `.claude/skills/`, not `skills/`** (correction C1). A root-level
  `skills/` directory is never discovered.
- **GOTCHA**: The confirmation step is **before geometry**, and it is the only defense against
  PRD Risk 3 (agent writes a wrong `intent.json` and a matching wrong model that agree). Skill
  text must make halting for confirmation non-optional.
- **GOTCHA**: Thin skill, thick library — **no geometry or measurement logic in `SKILL.md`.**
  It calls `threedp`.
- **VALIDATE**: `uv run python -c "import pathlib,re;t=pathlib.Path('.claude/skills/lril3d-model/SKILL.md').read_text(encoding='utf-8');assert t.startswith('---');assert re.search(r'^name: lril3d-model$',t,re.M);print('frontmatter ok')"`

### 23. CREATE `.claude/skills/lril3d-inspect/SKILL.md`

- **IMPLEMENT**: PRD §7 — extract features, check every assertion, report drift, min-wall +
  overhang, render the contact sheet, write a critique **citing measured numbers**.
- **GOTCHA**: The critique must never contain an impression ("looks good", "seems correct").
  Every claim carries a number or an explicit ESTIMATE label.
- **VALIDATE**: same frontmatter check, `-inspect`

### 24. CREATE `.claude/skills/lril3d-viewer/SKILL.md`

- **IMPLEMENT**: start/stop the viewer dev server, point it at a model dir.
- **VALIDATE**: same frontmatter check, `-viewer`

### 25. CREATE `viewer/` — Vite + three.js scaffold

- **IMPLEMENT**: `package.json` (`three`, `vite`, `chokidar`, `ws`), `vite.config.js`,
  `index.html`, `src/main.js` with `STLLoader` / `3MFLoader`, orbit/pan/zoom, wireframe and
  cross-section toggles, build-plate grid at **P1S 256×256**.
- **GOTCHA**: Read plate dimensions from `profiles/printer-p1s.json` — do not hardcode 256.
- **VALIDATE**: `cd viewer && npm install && npx vite build` → exit 0

### 26. ADD WebSocket hot reload to `viewer/`

- **IMPLEMENT**: `server/watch.mjs` — chokidar watches the model `out/` dir, broadcasts on change;
  the page reloads the mesh in place (preserving camera).
- **GOTCHA**: PRD §11 requires reload **within ~1 s** of a file write.
- **GOTCHA**: Debounce — exporters write STL/3MF in several chunks and will fire multiple events
  for one logical save. Reloading mid-write yields a truncated mesh.
- **VALIDATE**: Manual (Level 4, step 4). Node 24.18.0 verified present.

### 27. CREATE `benchmarks/l-bracket/` (Tier 1)

- **IMPLEMENT**: L-bracket with **counterbored M4 holes**. Exercises constraint solving + hole
  placement.
- **GOTCHA**: The M4 socket head is 4 mm tall. A 4 mm counterbore in a 4 mm plate leaves zero
  material — PRD §15.1 records the agent catching this unprompted. `intent.json` must assert
  remaining material below the counterbore is > 0.
- **VALIDATE**: model runs; `intent.check` passes; **volume within 0.1 % of hand-computed**
  (PRD §15.1 measured 15208.4 mm³ vs 15209 mm³ by hand).

### 28. CREATE `benchmarks/enclosure/` (Tier 1)

- **IMPLEMENT**: enclosure + lid + heat-set boss. Exercises walls and mating tolerance.
- **GOTCHA**: Heat-set boss OD/ID come from `parts.py`, cited in `intent.json` — not invented.
- **VALIDATE**: model runs; `intent.check` passes

### 29. CREATE `benchmarks/overhang-test/` (Tier 1)

- **IMPLEMENT**: deliberate **60° overhang**. Exercises printability detection.
- **SPIKE ASSERTION**: spike 6 built exactly this and measured area-weighted **60.00°** with
  **1339.09 mm²** unsupported. Reuse that geometry approach (outward-flaring cone,
  `run = rise * tan(60°)`).
- **VALIDATE**: `printability.overhang_histogram` flags >45° with non-zero unsupported area

### 30. CREATE `benchmarks/gyroid-vase/` (**Tier 2**)

- **IMPLEMENT**: gyroid vase via `sdf`. Exercises the organic path.
- **GOTCHA**: This part is **Tier 2 and largely unverifiable in v1** — a known, accepted gap
  (PRD §6.2), **not** an oversight. Its `intent.json` gets topology + statistics only
  (watertight, bbox, volume, wall sampling); any dimensional claim is labelled **ESTIMATE**.
- **GOTCHA**: `sdf` writes a progress bar to **stdout** (spike 9) — do not parse its stdout as
  data. It does *not* need a `__main__` guard.
- **GOTCHA**: `sdf` step size drives both runtime and triangle count. The spike produced 73 004
  triangles at `step=0.25` on a 20 mm part; keep the benchmark small enough to stay fast.
- **VALIDATE**: model runs; mesh watertight; report explicitly labels dimensional claims ESTIMATE

### 31. EXTEND mutations to ~15 across all benchmarks

- **IMPLEMENT**: Bring the total to ~15 (PRD §11), each with a declared expected verdict.
  Include **at least one MUST-PASS cosmetic mutation per benchmark** so false positives are
  measurable everywhere, not just on the bearing holder.
- **GOTCHA**: Gyroid-vase mutations may only assert Tier 2 properties (watertightness, volume
  drift). Do **not** write a dimensional mutation for a part the system openly cannot verify —
  that would be scoring the verifier on a promise it never made.
- **VALIDATE**: `uv run python benchmarks/run_mutations.py` → **all** benchmarks, exit 0,
  `missed 0`, `false-positives 0`

### 32. CREATE `tests/test_one_ruler.py` — enforce Principle 6 mechanically

- **IMPLEMENT**: Walk `src/threedp/*.py` (excluding `measure.py`) and `benchmarks/**`; fail if
  any file contains ad-hoc measurement primitives — `np.linalg.lstsq` on a circle system,
  `.ptp(`, `max()` over a radius array, or a locally-defined `fit_circle`.
- **GOTCHA**: PRD §6.5 makes this a hard rule, and a rule with no enforcement decays. Two
  improvised implementations already disagreed by 0.088 mm once.
- **GOTCHA**: Keep the allowlist narrow and explicit — `measure.py` only.
- **VALIDATE**: `uv run pytest tests/test_one_ruler.py -v`

### 33. CREATE `CLAUDE.md`

- **IMPLEMENT**: Point at `PRD.md` as source of truth. State the non-negotiables: one ruler;
  mm everywhere; `.claude/skills/` not `skills/`; thin skills / thick library; nominal geometry
  is truth; never touch the printer path.
- **GOTCHA**: **Link** to `PRD.md` sections; do not re-paste the principles. Duplicated
  conventions drift.
- **VALIDATE**: `uv run python -c "import pathlib;t=pathlib.Path('CLAUDE.md').read_text(encoding='utf-8');assert 'PRD.md' in t and 'measure.py' in t;print('ok')"`

---

## TESTING STRATEGY

Framework: **`pytest`** (no in-repo precedent; chosen as the Python default and the `uv` norm).
Layout: `tests/test_<module>.py` mirroring `src/threedp/<module>.py`.

### Unit Tests

- **`measure.py` is tested against pure arithmetic** — synthetic point sets, no CAD, no meshes.
  It must not be validated against a library that could share its bug.
- Every other module is tested against geometry whose truth is known by construction (a Ø22
  cylinder is 22.000 because we built it that way).
- Fixtures: a shared `conftest.py` builds the canonical OD30 / bore Ø22×7 / hole Ø10 test part
  once per session and exports both `.step` and `.stl`, so BREP and mesh paths are tested against
  **the same** ground truth.

### Integration Tests

- **BREP↔mesh agreement**: both paths measure the same part; assert they agree within 0.01 mm.
  This catches a bug present in only one path — which no single-path test can.
- **Nominal/compensated split**: STEP radii equal nominal exactly; compensated STL differs by the
  calibration delta and in the right direction per role.
- **End-to-end**: `model.py` → export → `features.extract` → `intent.check` → report, for all 5
  benchmarks.

### The Mutation Suite (the real gate)

Not a conventional test tier. It scores **the verifier** on caught / missed / false-positive
across ~15 injected defects. Two classes:

1. **Geometry mutations** — a dimension or feature is wrong (shallow pocket, thin wall, dropped
   counterbore).
2. **Method mutations** — the *ruler* is wrong (max-radius, kept duplicate vertex, disabled
   circularity gate). These catch the class of bug that geometry mutations structurally cannot.

### Edge Cases

- Shapely's duplicate closing vertex (**the 0.088 mm bug**)
- A **non-circular** section fitted as a circle (square pocket → confident "24.4949 mm")
- An **ellipse** from a tilted bore passing a loose circularity gate
- A feature that is **entirely absent** (dropped counterbore) — must FAIL, not skip
- **Exactly horizontal** ceilings at 90° (the histogram's inclusive-upper-bound trap)
- **Build-plate contact faces** miscounted as overhangs
- `resolve(params, None)` leaking compensation into nominal output
- A `.3mf` loading as a `Scene` rather than a `Trimesh`
- Calibration with `"measured": null` — must warn, not silently proceed
- Unknown parts-DB key — must raise, never return a guessed default
- Fewer than 3 points in a ring — must raise, never return a number

---

## VALIDATION COMMANDS

Every command is runnable from the repo root (`D:\repos\3d-skills`) and states its pass signal.

### Level 1: Syntax & Style

```bash
uv run ruff check .                 # pass: exit 0, "All checks passed!"
uv run ruff format --check .        # pass: exit 0
uv sync --extra dev                 # pass: exit 0, resolves on Python 3.13
```

**Root-level import + version gate** — the single check that catches a wrong interpreter and any
cross-module import breakage:

```bash
uv run python -c "import sys; assert sys.version_info[:2]==(3,13), sys.version; from threedp import measure, features, intent, render, compensate, parts, io, printability; print('OK', sys.version)"
```
Pass: prints `OK 3.13.x`. **Fails loudly on 3.14**, which is this machine's default.

### Level 2: Unit Tests

```bash
uv run pytest -v                    # pass: exit 0, 0 failed, 0 errors
uv run pytest tests/test_measure.py -v   # pass: the ruler's own suite, all green
```

### Level 3: Integration — the mutation suite

**This layer must actually execute, not self-skip.** A green `pytest` run with the mutation suite
skipped is **not** evidence the verifier works — it is the exact failure mode PRD §11 was written
to prevent.

```bash
uv run python benchmarks/run_mutations.py
```

Pass signal — the run must report a **non-zero mutation count** and zero of both failure classes:

```
caught 15/15   missed 0   false-positives 0   harness-errors 0    VERDICT: PASS
```

Exit 0 required. **If `caught` is 0 or the suite reports "no mutations found", treat it as a
FAILURE**, not a pass — that is a skipped layer wearing a green badge.

```bash
uv run python benchmarks/run_mutations.py --part bearing-holder   # the 1A gate
```

### Level 4: Manual Validation

1. **Intent-before-geometry**: invoke `lril3d-model` with *"a bracket that holds a 608 bearing
   40 mm off a wall"*. Confirm it presents parts-DB-cited facts **and** halts for confirmation of
   judgment calls **before** any geometry is written.
2. **Detection**: hand-edit `benchmarks/bearing-holder/params.json` to `POCKET_DEPTH: 6.5`,
   re-export, run `lril3d-inspect`. Expect an explicit failure naming the measured 6.50 mm, the
   expected 6.90–7.10, and *why it matters* ("a 7 mm 608 will stand proud and won't retain").
3. **Render legibility**: open a contact sheet. Confirm the part is **not** white-on-white, that
   ortho views are parallel-projected, and that the scale bar and plate outline are present.
4. **Viewer hot reload**: `cd viewer && npm run dev`, open the page, re-export a model, confirm
   reload **within ~1 s** with the camera preserved.
5. **Print gate**: confirm `.claude/settings.json` is committed and its `deny` rules are present.

### Level 5: Additional Validation (Optional)

```bash
uv run python -c "from threedp import features; f=features.extract('benchmarks/bearing-holder/out/part.step'); g=features.extract('benchmarks/bearing-holder/out/part.stl'); print('BREP vs mesh cross-check'); print(sorted(round(c.radius,3) for c in f.cylinders)); print(sorted(round(c.radius,3) for c in g.cylinders))"
```
Pass: the two lists agree within 0.01 mm.

---

## ACCEPTANCE CRITERIA

Traced to PRD §11.

**Milestone 1A**
- [ ] `measure.py` unit tests pass against analytically-known geometry
- [ ] Duplicate-closing-vertex regression is a first-class test and passes
- [ ] A non-circular section **cannot** yield a diameter (`NotCircularError`)
- [ ] Cylinder position comes from the OCCT axis; the `face.center()` trap is not present
- [ ] `intent.check` reports every assertion with its measured value and source citation
- [ ] Absent features FAIL with a reason (never skipped)
- [ ] Tier 2 dimensional claims are labelled **ESTIMATE** and excluded from pass/fail
- [ ] Nominal STEP dimensions equal nominal exactly — compensation never leaks into CAD output
- [ ] Bearing-holder mutation suite: **all defects caught, zero false positives**
- [ ] Measurement-**method** mutations are detected
- [ ] `.claude/settings.json` print gate present, committed, and correct

**Milestone 1B**
- [ ] All 5 benchmarks model successfully, watertight and manifold
- [ ] All 5 export nominal STEP **and** compensated STL/3MF
- [ ] ~15 mutations: **all injected defects caught, zero false positives**
- [ ] Contact sheets legible, parallel projection on orthographic views
- [ ] Viewer hot-reloads within ~1 s of a file write
- [ ] Parts DB resolves M2–M8, heat-set inserts, 608/623 bearings, common magnets
- [ ] Three skills discoverable under `.claude/skills/`
- [ ] Ad-hoc measurement is mechanically prohibited (Task 32)
- [ ] Level 1–3 commands all pass; Level 3 **executed**, not skipped

**Tracked, not gated** (PRD §11): iteration count, target ≤3 rounds to a usable part without the
user editing Python. Deliberately not pass/fail — gating it pressures the loop to *look* efficient
rather than *be* correct.

**Explicitly deferred to Phase 3**: dimensional accuracy against printed parts. Unverifiable
without a printer.

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order
- [ ] Each task validation passed immediately
- [ ] **1A gate (Task 20) passed before 1B was started**
- [ ] All validation commands executed successfully
- [ ] Full test suite passes (unit + integration + mutation)
- [ ] Mutation suite ran with a **non-zero** mutation count
- [ ] No linting or type-checking errors
- [ ] Manual testing confirms intent-before-geometry, detection, legibility, hot reload
- [ ] Acceptance criteria all met
- [ ] Code reviewed for quality and maintainability

---

## NOTES

### What this phase is really proving

Phase 1 is not "build a CAD wrapper" — a dozen of those exist (PRD §15.8) and none closes the
loop. It is proving one claim: **measurement against pre-recorded intent catches defects that
generation confidence, bounding boxes, volumes, and renders all miss.** Every design decision
here serves that claim, which is why the mutation suite — not the benchmark set — is the gate.

### The spike changed one thing about the PRD's own design

The PRD's §6.2 tier table says a mesh cross-section plus circle fit yields a Tier 1 dimensional
guarantee. That is true *for a circle*. Spike 5 showed it is dangerously false otherwise: a square
pocket produces a confident "24.4949 mm diameter" with no error, no warning, and no crash.

This is the same failure shape as the PRD's founding anecdote — plausible, confident, wrong — but
located **inside the verifier**. A verifier that can be fooled this way is worse than none,
because it reports green (Principle 5, Risk 2). Hence ADR-1: the residual is not diagnostic
metadata, it is a **gate**, and the API makes bypassing it require typing a different,
conspicuous name.

### Deliberate trade-offs

- **`deny` over `ask` for the printer gate in Phase 1** (ADR-5). Strictly stronger while no send
  path exists, and costs nothing. Phase 3 relaxes it.
- **Least-squares over geometric (Levenberg–Marquardt) circle fitting.** Algebraic Kása fitting
  measured −0.0028 mm on real tessellated geometry — comfortably inside the ±0.005 mm
  requirement — with no iteration and no convergence failure mode. A verifier that can fail to
  converge is a verifier that can report green on a timeout.
- **`printability.py` split from `features.py`** (ADR-3). Different determinism guarantees,
  different consumers, and the clean seam for Phase 2's `lril3d-dfm`.
- **Benchmark 5 accepted as unverifiable.** Stated plainly rather than papered over. Writing a
  dimensional mutation for the gyroid vase would score the verifier against a promise it never made.

### Known gaps carried into Phase 2+

- **Z-only mesh probing** — angled features are invisible (PRD §6.2, ADR-4). Mitigated by
  refusing Tier 1 status rather than by guessing.
- **Tier 2 is topology + statistics only.**
- **Imported meshes** have no parametrization and fall back to uniform geometric offset, where the
  hole/outer asymmetry is real and unresolvable. **Press fits on imported meshes are not
  supported** (PRD §6.4).
- **`coupon.py` is Phase 2**, despite appearing in the PRD §6 directory tree.

### Confidence Score

**8 / 10** for one-pass success on **Milestone 1A**; **6.5 / 10** for all of Phase 1 in a single
pass — the size, not the difficulty, is the risk. See [SCOPE WARNING](#scope-warning).

---

## Sources

- [build123d documentation](https://build123d.readthedocs.io/)
- [fogleman/sdf](https://github.com/fogleman/sdf)
- [trimesh documentation](https://trimesh.org/)
- [Shapely LinearRing reference](https://shapely.readthedocs.io/en/stable/reference/shapely.LinearRing.html)
- [VTK Python API](https://docs.vtk.org/en/latest/api/python/)
- [Claude Code settings & permissions](https://code.claude.com/docs/en/settings)
- [Claude Code Agent Skills](https://code.claude.com/docs/en/skills)

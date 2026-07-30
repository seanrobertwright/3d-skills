# PRD: `3d-skills` — A Claude Code Skill Set for 3D Printing

**Status:** Draft v2 — revised after an implementation spike
**Date:** 2026-07-30
**Owner:** Sean
**Repository:** `D:\repos\3d-skills`

> **v2 changes.** v1 was stress-tested by building two real parts in `build123d`
> and measuring them. The spike **falsified v1's central risk assumption** and
> exposed three defects in the verification design. Generation quality was never
> the problem; **detection** was. Every change below traces to measured evidence
> in §15, not to speculation.

---

## 1. Executive Summary

`3d-skills` is a set of composable Claude Code skills that take a person from a
plain-language description of a physical object to a printed part, without
requiring them to write CAD code themselves. The user says "I need a bracket that
holds a 608 bearing 40mm off a wall"; Claude confirms its understanding, authors
parametric geometry, **measures the result against assertions written before the
model existed**, checks it for printability, slices it, and — only after explicit
approval — sends it to the printer.

The differentiator is not any single tool binding. A dozen OpenSCAD and CadQuery
MCP servers and skills already exist, and they are all single-tool wrappers that
generate code and hand back a file. What none of them close is the verification
loop.

**The v1 spike established what that loop must actually be.** Two parts were
generated cold and both ran on the first attempt with correct bounding boxes,
plausible volumes, and clean renders. All three signals said "correct." One part
contained three genuine defects — a bearing pocket 0.5mm too shallow to retain the
bearing, mounting holes that silently weren't counterbored, and a retaining lip
five times its intended thickness. **None was visible in the render.** All three
were caught in seconds by geometric feature extraction.

The lesson is the product thesis: an agent that generates confident, plausible,
wrong geometry is the default. What prevents it is not *seeing* — it is
*measuring*, against intent recorded before the geometry was written.

**MVP goal:** prove the loop — *understand → confirm → model → measure against
intent → iterate* — against a fixed benchmark of five parts and ~15 injected
defects, with no slicer and no printer involved.

---

## 2. Mission

> Let a person describe a physical object in their own words and receive a
> correct, printable, editable model — with the machine, not the human, catching
> the geometry mistakes.

### Core Principles

1. **Measurement is the quality mechanism; vision is not.** Every model is
   measured against assertions recorded before it was built. Renders are produced
   for gross-error detection and for the human's understanding — they are a
   channel, not a gate. *(Revised in v2: the spike proved renders miss the defects
   that matter. See §15.)*

2. **Models are programs, not artifacts.** Every design is a versioned Python
   script plus a parameter file. Changing 40mm to 45mm is an edit, never a
   regeneration. This principle is load-bearing beyond convenience: it is what
   makes printer compensation exact (§6.4).

3. **Nominal geometry is the truth.** `model.py` and the exported STEP describe
   the part, never the part-plus-this-printer's-error. Machine-specific
   compensation is applied downstream, at export. A STEP file from this system is
   always valid CAD, portable to any process or shop.

4. **Physics beats syntax.** Code that runs is not a part that prints. Overhangs,
   minimum wall thickness, hole shrinkage, and elephant's foot cause more real
   failures than syntax errors.

5. **Verification must be independently testable.** Passing benchmarks proves
   nothing about the verifier if the verifier is only exercised by parts that
   happen to be correct. The verifier is scored directly, against known defects.
   *(New in v2.)*

6. **There is exactly one ruler.** All dimensional measurement flows through a
   single canonical implementation. Ad-hoc measurement in skill code is
   prohibited. *(New in v2 — two improvised implementations disagreed by 0.088mm,
   more than a press-fit tolerance. See §15.)*

7. **The printer is never touched without permission.** Enforced mechanically at
   the harness layer, not by agent discipline.

---

## 3. Target Users

### Primary Persona — "The Capable Maker" (v1 target: the author)

- Owns a Bambu Lab P1S with AMS; prints regularly and knows print failure modes
  by feel.
- Comfortable in a terminal, reads Python, but does not want to hand-author
  parametric CAD for every household bracket.
- Has used Fusion 360 or OnShape and found the ceremony disproportionate to the
  task for simple functional parts.

**Needs:** speed from idea to printable file; parts that fit real objects on the
first or second try; not having to remember tolerance rules for six materials.

**Pain points:** CAD context-switching cost; AI-generated models that look
plausible and print unusably; discovering a wall is too thin six hours into a
print.

### Secondary Persona — "The Downstream Adopter" (post-v1)

Different printer, different slicer, different OS. Does **not** constrain v1
features, but does constrain v1 *structure*: hardware-specific values live in
configuration from day one, so generalizing later is a refactor rather than a
rewrite.

---

## 4. MVP Scope

### ✅ In Scope — Core Functionality

- ✅ **Intent capture and confirmation** — parts-DB-cited facts plus explicit
      confirmation of judgment calls, *before* geometry is written
- ✅ Parametric modeling of functional/mechanical parts (`build123d`)
- ✅ Code-driven organic modeling (`sdf` — lattices, gyroids, vases, textures)
- ✅ Mesh-level operations: remesh, decimate, boolean cleanup (`bpy`)
- ✅ **Feature extraction and intent verification** — BREP face queries and mesh
      cross-section measurement, both through one canonical implementation
- ✅ Headless multi-view rendering to a single annotated contact sheet (VTK)
- ✅ Printability measurement: minimum wall sampling, overhang histogram
- ✅ **Mutation test suite** scoring the verifier on caught / missed /
      false-positive
- ✅ Live browser viewer with hot-reload on file write (three.js)
- ✅ **Nominal STEP + compensated STL/3MF export** via parameter re-resolution
- ✅ Standard parts dimension database

### ✅ In Scope — Technical

- ✅ Python 3.13, `uv`-managed
- ✅ Skill set + versioned Python package (no MCP server, no daemon)
- ✅ Hardware values isolated in `profiles/*.json`, including `calibration.json`
      seeded with published literature defaults
- ✅ Harness-enforced permission rule on the printer-send path — **written in v1
      even though the send path does not yet exist**

### ❌ Out of Scope for MVP

- ❌ **Measuring** calibration constants — requires a printer, Phase 3. v1 ships
      the architecture on published defaults.
- ❌ Slicing (`lril3d-slice`) — Phase 2
- ❌ Printer communication (`lril3d-print`) — Phase 3
- ❌ Full DFM rules engine (`lril3d-dfm`) — Phase 2; a thin slice ships in
      `lril3d-inspect`
- ❌ Import/repair pipeline (`lril3d-repair`) — Phase 2
- ❌ Local generative 3D — **hardware-blocked**, see §15
- ❌ Multi-printer / multi-slicer abstraction — post-v1
- ❌ Model marketplace integration — post-v1
- ❌ Assemblies, motion, FEA, or simulation
- ❌ Any hosted or paid API

---

## 5. User Stories

1. **As a maker, I want Claude to tell me what it thinks I asked for before it
   builds anything, so that misunderstandings cost seconds instead of prints.**
   *Example:* "Bore 22.00mm [608 OD, parts-db] · Pocket 7.00mm [608 width,
   parts-db] · Retaining lip 1.0mm ← my choice, ok? · Wall 4.0mm ← my choice, ok?"

2. **As a maker, I want to describe a part in plain language and get real
   geometry, so that I don't have to open CAD for a simple bracket.**

3. **As a maker, I want the system to catch its own dimensional errors, so that a
   plausible-looking wrong part doesn't reach my printer.**
   *Example:* "❌ `pocket_depth` = 6.50mm, expected 6.9–7.1. The 0.5mm fillet
   consumed pocket depth; a 7mm-wide 608 will stand proud and won't retain."

4. **As a maker, I want to watch the model change while we iterate, so that I can
   react immediately instead of describing problems in text.**

5. **As a maker, I want to change one dimension without regenerating everything,
   so that iteration is cheap.**

6. **As a maker, I want known hardware dimensions to be automatic, so that I'm not
   measuring an M4 screw.**

7. **As a maker, I want the STEP file to describe the actual part, so that I can
   send it to a machine shop or open it in Fusion years from now.**

8. **As a maker, I want to verify a critical fit before committing to a long
   print, so that I don't waste six hours.**

9. **As a maker, I want to be certain nothing reaches my printer without my
   say-so, so that I can let the agent work unattended.**

### Technical

10. **As the maintainer, I want the verifier tested against known defects, so that
    a broken verifier fails loudly instead of reporting green.**
11. **As the maintainer, I want exactly one measurement implementation, so that
    two parts of the system cannot disagree about the same dimension.**
12. **As the maintainer, I want hardware assumptions in config rather than code.**

---

## 6. Core Architecture & Patterns

Thin skills, thick library. Each `SKILL.md` handles intent recognition, user
interaction, and workflow narration; all geometry, rendering, and measurement work
lives in a versioned Python package independently testable without an agent.

### Directory Structure

```
D:\repos\3d-skills\
├─ .claude/settings.json         # permission rule on the printer-send path
├─ pyproject.toml                # uv, requires-python = "==3.13.*"
├─ skills/
│  ├─ lril3d-model/SKILL.md
│  ├─ lril3d-inspect/SKILL.md
│  └─ lril3d-viewer/SKILL.md
├─ src/threedp/
│  ├─ measure.py                 # THE canonical ruler — see §6.5
│  ├─ features.py                # BREP face queries + mesh section probes
│  ├─ intent.py                  # intent.json schema, checking, reporting
│  ├─ render.py                  # VTK offscreen contact sheet
│  ├─ compensate.py              # parameter re-resolution for export
│  ├─ parts.py                   # standard parts dimension database
│  ├─ coupon.py                  # stepped fit-gauge generator
│  └─ io.py                      # STL / STEP / 3MF export
├─ viewer/                       # vite + three.js, WebSocket hot reload
├─ profiles/
│  ├─ printer-p1s.json
│  ├─ filaments.json             # per-slot; supports non-AMS external spool
│  └─ calibration.json           # published defaults in v1; measured in Phase 3
├─ benchmarks/<part>/
│  ├─ model.py · params.json · intent.json
│  └─ mutations/*.py             # injected defects, each with expected verdict
└─ models/<part-name>/
   ├─ intent.json                # WRITTEN FIRST
   ├─ model.py · params.json
   ├─ out/                       # nominal .step · compensated .stl/.3mf
   └─ renders/
```

### 6.1 Intent Before Geometry

`intent.json` is written **before** `model.py` and records checkable claims
derived from the user's request. Because the same agent writes both, it is only a
real check if grounded outside that agent's own reasoning. Two anchors:

- **Parts-DB citation.** Any dimension traceable to the standard parts database
  carries its source and cannot be fabricated.
- **Explicit user confirmation.** Every judgment call is presented as a short
  numbered list and confirmed before geometry is written.

```json
{
  "holds": "608 bearing (22 OD x 7 W)",
  "asserts": [
    {"bore_diameter": [21.95, 22.05], "source": "parts-db:608.od"},
    {"pocket_depth":  [6.90, 7.10],   "source": "parts-db:608.width"},
    {"retaining_lip": [0.80, 1.50],   "source": "user-confirmed"},
    {"min_wall":      [3.00, null],   "source": "user-confirmed"},
    {"mount_hole_d":  [4.40, 4.60],   "source": "parts-db:M4.clearance"}
  ]
}
```

Golden bounding-box and volume values are still recorded, but **demoted to a pure
regression guard**. They are generated from the model and therefore cannot detect
first-pass error — only drift. v1's success criteria wrongly treated them as
correctness checks.

### 6.2 Verification Tiers — by Feature Type, Not Representation

v1 tiered guarantees by BREP-versus-mesh. **The spike disproved that.** Mesh
cross-sectioning with least-squares circle fitting recovered every dimension to
within 0.003mm and would have caught both real defects. The genuine axis of
difficulty is the *kind of feature*, and BREP does not rescue freeform geometry.

| Tier | Feature type | Method | Guarantee |
|---|---|---|---|
| **1** | Axis-aligned regular features — bores, pockets, planes, prismatic walls | BREP face query *or* mesh cross-section + circle fit | Dimensional, ±0.005mm. Full `intent.json` checking. |
| **2** | Freeform / organic surfaces | Bounding box, volume, watertightness, wall sampling, overhang histogram | Topological and statistical only. **Dimensional claims labelled ESTIMATE.** |

Consequences to state plainly: benchmark 5 (gyroid vase) is **Tier 2 and largely
unverifiable in v1** — this is a known, accepted gap, not an oversight. Tier 1
holds for imported meshes too, which makes the Phase 2 repair pipeline stronger
than v1 assumed.

**Measured limits of mesh probing:** scans along Z only, so angled features are
invisible; transition detection quantizes to step size and needs bisection for
precision; requires `shapely`, `rtree`, `networkx`.

### 6.3 Measurement Strategy — Layered

The "make it fit *this*" problem: the agent has no ground truth about the physical
object. Five mechanisms, descending confidence:

| Order | Mechanism | Confidence | Use when |
|---|---|---|---|
| 1 | Standard parts database | Exact | Known hardware (M-screws, 608/623 bearings, heat-set inserts, magnets, Pi hole patterns) |
| 2 | Calipers interview protocol | High | User can measure; skill names the datum and where |
| 3 | **Calibration profile** | High, empirical | **Always — supplies the printer constant none of the others can** |
| 4 | Test-coupon verification | High, empirical | Unusual or safety-critical fits |
| 5 | Reference-object photos | Low | Rough envelopes only — never press fits |

**Layer 3 is the one v1 missed.** Layers 1, 2, and 5 all answer *"how big is the
object?"* None answers *"how big should I model the hole?"* The gap between them —
FDM bores print undersize by roughly 0.1–0.4mm from arc faceting and flow — is a
property of the **printer and material**, not the part. No amount of measuring the
object recovers it.

v1 framed coupons as per-part, which re-derives the same printer constant every
time and would realistically be abandoned by the third part. Calibration is
therefore **measured once per material** and stored:

```json
{ "PLA_generic": { "hole_delta_mm": 0.18, "outer_delta_mm": -0.05,
                   "first_layer_squish": 0.12, "measured": null,
                   "source": "published-default" } }
```

`"measured": null` marks a literature default; Phase 3 replaces it with a date and
a coupon reference.

### 6.4 Compensation by Re-Parametrization

Compensation is **not** a geometric offset. Because models are programs,
`params.json` tags each dimension's semantic role and export re-runs the model
with resolved values:

```
model.py (nominal)
  BORE=22.00 role=hole · OD=30.00 role=outer · WIDTH=7.00 role=neutral
        │
        ├─ resolve()          → STEP   bore 22.00, outer 30.00   ← valid CAD
        └─ resolve(PLA_cal)   → STL    bore 22.18, outer 29.95   ← P1S + PLA
```

This dissolves the asymmetry problem entirely: hole and outer deltas differ, and
because they are applied to *parameters* rather than to *geometry*, they need not
be reconcilable into a single offset. **Verified in the spike** — bore +0.181,
outer −0.064, independently applied, exact.

`intent.json` asserts **nominal** values and is checked against the nominal model.
Compensation is a separate, independently testable step.

**Tier 2 exception:** imported meshes have no parametrization and fall back to
uniform geometric offset, where the asymmetry is real and unresolvable. Documented
as an approximation; press fits on imported meshes are not supported.

### 6.5 One Ruler

All dimensional measurement flows through `measure.py`. Skills, benchmarks, and
mutation tests call it; none reimplements it.

This is not stylistic. During the spike, two improvised implementations of
"measure this bore" disagreed by **0.088mm** — larger than a press-fit tolerance,
enough to flip pass/fail on a ±0.05 assertion. Root cause: Shapely closes rings by
repeating the first vertex, and including that duplicate in the centroid shifted
the fitted center by 0.037mm.

Consequences:
- Least-squares circle fitting is the canonical method (±0.003mm). Max-radius and
  bounding-box methods are **prohibited** for dimensional assertions.
- `measure.py` carries its own unit tests against analytically-known geometry.
- The mutation suite includes **measurement-method regressions**, not only
  geometry defects. A verifier with a subtly wrong ruler is worse than no
  verifier, because it reports green.

### 6.6 Render Legibility

Renders serve gross-error detection and human understanding. A naive VTK render
produces a white part on a white background — technically successful, completely
useless. The harness therefore mandates: gradient background, Phong-shaded colored
material, silhouette and feature edges at 20–25°, three-point camera lighting,
**parallel projection for orthographic views**, mm scale bar, and build-plate
outline. Four views tile into one annotated PNG so inspection is cheap enough to
run every iteration.

---

## 7. Tools / Features

### `lril3d-model` — Intent Capture and Geometry Authoring

1. Resolve known dimensions from the parts database, with citations
2. Present judgment calls for confirmation — **before writing geometry**
3. Write `intent.json`
4. Author `model.py` + `params.json` (nominal, with semantic role tags)
5. Export nominal STEP and compensated STL/3MF

| Route | Library | Use for |
|---|---|---|
| Functional | `build123d` | Brackets, enclosures, adapters, jigs, fixtures |
| Organic | `sdf` | Lattices, gyroids, vases, surface textures |
| Mesh-level | `bpy` | Remeshing, decimation, boolean cleanup |

### `lril3d-inspect` — Measure, Verify, Critique

- Extract features: BREP face queries and/or mesh cross-section probes
- Check every `intent.json` assertion; report pass/fail with measured values
- Evaluate golden regression values and report drift
- Minimum-wall sampling and overhang histogram (thin DFM slice; full engine
  Phase 2)
- Render the contact sheet
- Produce a written critique citing **measured numbers**, never impressions

### `lril3d-viewer` — Live Browser Viewer

Local vite + three.js; `STLLoader` / `3MFLoader`; WebSocket hot-reload; orbit /
pan / zoom; wireframe and cross-section toggles; build-plate grid at P1S
dimensions. G-code preview in Phase 2.

### Phase 2+ (specified, not built)

| Skill | Purpose |
|---|---|
| `lril3d-dfm` | Full printability engine, per material |
| `lril3d-repair` | Import → diagnose → fix → verify |
| `lril3d-slice` | OrcaSlicer CLI wrapper; AMS mapping; time/filament/purge |
| `lril3d-print` | FTPS + MQTT; telemetry; hard approval gate |

---

## 8. Technology Stack

| Component | Version | Rationale |
|---|---|---|
| Python | **3.13** (pinned) | `bpy` ships **cp313 wheels only**; 3.14 unsatisfiable |
| `uv` | latest | Already installed |
| Node.js | ≥20 | Viewer only |

> The dev machine defaults to Python 3.14. The project must explicitly target 3.13.

| Package | Role |
|---|---|
| `build123d` 0.11.1 | Parametric BREP CAD (OCCT) |
| `sdf` | SDF organic modeling → marching cubes |
| `bpy` | Headless Blender as a library |
| `trimesh` | Mesh loading, sectioning, analysis |
| `shapely`, `rtree`, `networkx` | **Required for cross-section probing** (§6.2) |
| `manifold3d` | Guaranteed-manifold booleans |
| `vtk` | Offscreen rendering |
| `numpy` | Numerics, circle fitting |

All verified installed and working on Python 3.13 on the target machine.

### Justifications

**`build123d` over OpenSCAD.** OpenSCAD dominates existing agent skills but is
CSG-only, has no true fillets, and cannot export STEP — every part a permanent
dead end. `build123d` runs on OCCT and its context-manager API composes with
ordinary Python control flow, which matters for agent-generated code.

**VTK over pyrender.** The OSMesa/EGL burden dominating headless-render docs is a
Linux-server problem. VTK offscreen works natively on Windows — verified.

**Skills + scripts, no MCP.** Matches existing conventions, no daemon, and keeps
the Python package testable in isolation — which §6.5 makes essential.

---

## 9. Security & Configuration

### The Printer Approval Gate

**Nothing reaches the printer without explicit approval.** Two independent layers:

1. **Harness-enforced.** A `.claude/settings.json` permission rule makes the send
   script always require user permission. Enforced by the runtime, not by agent
   behavior. **Ships in v1**, before any printer code exists — writing the
   guardrail before the capability is the only ordering that guarantees it is
   present when the capability arrives.
2. **In-skill.** `lril3d-print` presents a sliced-result render, print time,
   per-slot filament, and AMS purge waste before requesting confirmation.

### Bambu P1S Connectivity (Phase 3)

**Developer Mode is required and has been accepted.** Bambu's control
authorization mechanism (Jan 2025 firmware; X-series first, then P/A) blocks
third-party print starts over plain LAN. Developer Mode (`Settings → WLAN/Network
→ LAN Mode Only → Developer Mode`) is the documented exemption.

**Accepted cost:** permanent disconnection from Bambu Cloud — no Handy app, no
remote monitoring, no MakerWorld one-click send.

**Flow:** FTPS upload (port 990, implicit TLS, user `bblp`, password = access
code) → MQTT publish with `project_file`, `use_ams`, `ams_mapping`.

**Two documented traps:**
- `ams_mapping` is **reverse-indexed** — array *position* = filament index in the
  3MF; array *value* = AMS slot (0–3).
- `use_ams` is **silently ignored** unless `filament_id` is set inside the 3MF.

### Configuration

| File | Contents |
|---|---|
| `profiles/printer-p1s.json` | 0.4mm hardened nozzle, build volume |
| `profiles/filaments.json` | Per-slot inventory; supports non-AMS external spool |
| `profiles/calibration.json` | Per-material deltas; published defaults in v1 |
| `.env` (gitignored) | Printer IP, serial, access code — **never committed** |

**In scope:** credential isolation; harness-level print gate; license provenance
recorded on any imported third-party model (much of Thingiverse is CC-BY-NC or
no-derivatives).
**Out of scope:** multi-user auth, network hardening beyond LAN, remote access.

---

## 10. API Specification

Local skill set, no network service. The internal package surface:

```python
from threedp import measure, features, intent, render, compensate, parts, io

feats  = features.extract("out/holder.step")     # BREP: bores, depths, planes
feats  = features.extract("out/holder.stl")      # mesh: cross-section probing
report = intent.check(feats, "intent.json")      # → per-assertion pass/fail
render.contact_sheet("out/holder.stl", "renders/iter-03.png",
                     views=("iso","top","front","right"),
                     projection="parallel", scale_bar=True, plate="p1s")
parts.get("bearing", "608")                      # → {od:22.0, id:8.0, width:7.0}
io.export(part, "out/holder", nominal=("step",),
          compensated=("stl","3mf"), calibration="PLA_generic")
```

---

## 11. Success Criteria

> **MVP success:** Claude models all five benchmark parts from plain-language
> descriptions with intent confirmed up front, and the verifier catches **every
> injected defect** across ~15 mutations with **zero false positives** — with the
> user never editing Python.

### The Benchmark Set

| # | Part | Exercises | Tier |
|---|---|---|---|
| 1 | L-bracket, counterbored M4 holes | Constraint solving, hole placement | 1 |
| 2 | Enclosure + lid + heat-set boss | Walls, mating tolerance | 1 |
| 3 | 608 bearing press-fit holder | The fit case | 1 |
| 4 | Deliberate 60° overhang | Printability detection | 1 |
| 5 | Gyroid vase | Organic path | **2 — dimensionally unverified** |

### Mutation Suite — The Real Gate

v1 scored only generation. A run could pass all five parts with a completely
broken verifier, purely because generation happened to be right. Each benchmark
therefore carries injected defects with declared expected verdicts:

```
benchmarks/bearing-holder/mutations/
  shallow_pocket.py     pocket 7.0 → 6.5      MUST FAIL
  thin_wall.py          wall  4.0 → 1.1       MUST FAIL
  dropped_cbore.py      counterbore removed   MUST FAIL
  cosmetic_fillet.py    fillet 0.5 → 0.6      MUST PASS
```

Three of the four above are **real defects from the spike**, not invented ones.

Mutations also cover **measurement method** (§6.5): a case that passes under
least-squares fitting and fails under max-radius must be detected as a
measurement-layer regression.

**Verifier scored on: caught / missed / false-positive.**

### Functional Requirements

- ✅ Intent confirmed with the user before geometry, with parts-DB citations
- ✅ Every benchmark models successfully and is watertight and manifold
- ✅ Every benchmark exports **nominal STEP** and **compensated STL/3MF**
- ✅ STEP dimensions equal nominal — compensation never leaks into CAD output
- ✅ All Tier 1 `intent.json` assertions checked and reported with measured values
- ✅ Tier 2 dimensional claims explicitly labelled ESTIMATE
- ✅ **All injected defects caught; zero false positives**
- ✅ `measure.py` unit tests pass against analytically-known geometry
- ✅ Contact sheets legible, with parallel projection on orthographic views
- ✅ Viewer hot-reloads within ~1s of a file write
- ✅ Parts DB resolves M2–M8, heat-set inserts, 608/623 bearings, common magnets
- ✅ `settings.json` print-gate rule present and correct

### Tracked, Not Gated

Iteration count — target ≤3 rounds to a usable part without the user editing
Python. Deliberately not pass/fail: too noisy, and gating it pressures the loop to
*look* efficient rather than *be* correct.

### Deferred to Phase 3

Dimensional accuracy against printed parts (±0.2mm nominal, ±0.1mm on fits) —
unverifiable without a printer. Becomes the gate for `lril3d-slice` and
`lril3d-print`, validated via the calibration workflow.

---

## 12. Implementation Phases

### Phase 1 — The Verification Loop (MVP)

- ✅ Repo scaffold, `uv` pinned to 3.13
- ✅ `.claude/settings.json` print-gate rule
- ✅ `measure.py` — the canonical ruler, with its own unit tests **first**
- ✅ `features.py` — BREP queries + mesh cross-section probing
- ✅ `intent.py` — schema, checking, reporting
- ✅ `parts.py` — standard parts database
- ✅ `compensate.py` + `io.py` — nominal/compensated export split
- ✅ `render.py` — contact sheet
- ✅ `lril3d-model`, `lril3d-inspect`, `lril3d-viewer`
- ✅ `viewer/` — vite + three.js + hot reload
- ✅ 5 benchmarks + ~15 mutations, all passing

**Build order note:** `measure.py` and its unit tests come first. Everything
downstream trusts it, and §6.5 shows what happens when it is improvised.

### Phase 2 — Printability & Preparation

- ✅ `lril3d-dfm` — full rules engine, per material
- ✅ `lril3d-repair` — import, diagnose, fix, verify (Tier 1 probing applies)
- ✅ `lril3d-slice` — OrcaSlicer CLI wrapper (**requires installing OrcaSlicer**)
- ✅ AMS filament mapping and purge-waste estimation
- ✅ `coupon.py` — stepped fit-gauge generator
- ✅ G-code preview in the viewer

**Known issue:** OrcaSlicer's CLI cannot generate thumbnails (requires OpenGL), so
CLI-sliced files show a blank preview on the P1S screen. Cosmetic, but must be
documented or worked around.

### Phase 3 — The Printer & Calibration

- ✅ Enable Developer Mode on the P1S
- ✅ FTPS upload; MQTT job start with `ams_mapping`; telemetry
- ✅ `lril3d-print` approval gate with full pre-send summary
- ✅ **Calibration workflow** — print the calibration part per material, measure,
      populate `calibration.json` with real values
- ✅ Dimensional accuracy validation

### Phase 4 — Generalization

Multi-printer/slicer abstraction; install docs; model library; public release.

---

## 13. Future Considerations

- **Local generative 3D** — needs 24GB+ VRAM; revisit only on capable hardware.
  Output is display-oriented (non-watertight, hollow, arbitrary scale) and would
  require the repair pipeline regardless.
- **Multi-axis mesh probing** — lift the Z-only limitation so angled features
  become measurable.
- **Model repository import** — Thingiverse has an official API; Printables and
  MakerWorld have none. Must carry license provenance.
- **Print history as a learning signal** — feed real failures back into DFM rules.
- **Assembly modeling** — mating constraints, interference checking.
- **Print-farm / queue management.**

---

## 14. Risks & Mitigations

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Plausible-but-wrong geometry passes undetected** — v1 named generation quality as the top risk; the spike showed generation works and *detection* is the real risk. Correct bbox, plausible volume, and a clean render all passed a part with three defects. | **High** | Intent-before-geometry (§6.1), feature extraction (§6.2), mutation-scored verifier (§11). This is now the product's core, not a supporting feature. |
| 2 | **The verifier itself is wrong** — a subtly bad ruler reports green forever. Two improvised implementations disagreed by 0.088mm. | **High** | One canonical `measure.py` (§6.5), built first, unit-tested against analytic geometry, with measurement-method mutations in the suite. |
| 3 | **Comprehension error** — Claude writes a wrong `intent.json` and a matching wrong model, and they agree. | **High** | Parts-DB citation for external truth; explicit user confirmation of every judgment call before geometry. Cannot be fully eliminated. |
| 4 | **Tier 2 geometry is effectively unverified** — organic parts get topology and statistics only. | Medium | Stated explicitly rather than papered over; benchmark 5 accepted as a known gap; dimensional claims labelled ESTIMATE. |
| 5 | **Developer Mode breaks or is restricted** by future firmware. | Medium | Phase 3 only. Fallback intact: emit the sliced 3MF for manual sending. Phases 1–2 unaffected. |
| 6 | **OrcaSlicer CLI brittleness** — profile ordering, string-typed params, relative-extruder errors. | Medium | Phase 2; community cookbook documents fixes; contained in one wrapper module. |
| 7 | **Calibration goes stale** — nozzle swap or filament change silently invalidates the profile. | Medium | `calibration.json` records measurement date and source; `"measured": null` marks unvalidated defaults; staleness surfaced at export. |

---

## 15. Appendix — Spike Evidence

All figures below are measured, not estimated. Spike conducted 2026-07-30.

### 15.1 Generation Quality — Better Than v1 Assumed

Two parts (L-bracket with counterbored M4 holes; 608 pillow-block bearing holder)
written cold in `build123d` with no reference examples. **Both ran on the first
attempt.** L-bracket volume 15208.4mm³ against a hand-computed 15209mm³. The
counterbore/plate-thickness conflict — a real M4 socket head is 4mm tall in a 4mm
plate — was caught unprompted during authoring.

**v1's Risk 2 was misidentified.**

### 15.2 Detection Failure — The Finding That Reshaped This PRD

The bearing holder passed bounding box, volume, and visual render. It contained
three defects:

1. **Pocket 6.5mm deep, not 7.0** — a 0.5mm fillet consumed depth; a 7mm 608 would
   sit proud and fail to retain.
2. **Mounting holes not counterbored** — no 4.5mm cylinder existed anywhere; the
   `CounterBoreHole` call produced plain 8mm bores.
3. **Retaining lip 5mm, not 1mm** — `LIP = 1.0` declared and never used.

None was visible in the render. All three were found in seconds by feature
extraction.

### 15.3 Mesh Probing — Tier 2 Is Stronger Than v1 Claimed

Cross-section + least-squares circle fit, mesh only, no BREP:

| Feature | Truth | Measured | Error |
|---|---|---|---|
| Bearing bore | 22.000 | 21.997 | 0.003 |
| Shaft hole | 10.000 | 9.998 | 0.002 |
| Mount holes | 8.000 @ x=±21 | 7.999 | 0.001 |
| Outer diameter | 30.000 | 29.997 | 0.003 |
| Lip plane | z = 5.0 | z = 5.00 | exact |

Would have caught defects 1 and 2 from the mesh alone. **Limits:** Z-only
scanning; quantized transition detection; requires `shapely` + `rtree` +
`networkx`.

### 15.4 Compensation — Asymmetry Dissolved

Re-parametrization applied `hole_delta +0.18` and `outer_delta −0.05`
independently: bore +0.181, outer −0.064. No single geometric offset needed, so
the asymmetry problem does not arise.

### 15.5 Measurement Method — 0.088mm From One Bad Line

```
centroid WITH duplicate closing vertex   center=(+0.0373,+0.0157)  dia=22.088  err=+0.0882
centroid WITHOUT duplicate               center=(-0.0048,+0.0050)  dia=22.002  err=+0.0016
```

Shapely closes rings by repeating the first vertex; including it shifts the fitted
center by 0.037mm and inflates diameter by 0.088mm — **more than a press-fit
tolerance**, enough to flip a ±0.05 assertion. Tessellation tolerance had no
effect (identical results at 0.1, 0.01, 0.001). **The method, not the mesh
quality, dominates measurement error.** Origin of Principle 6.

### 15.6 Environment — Verified

| Component | Status |
|---|---|
| Python 3.14.6 (default) + 3.13 | ✅ Both present — project targets 3.13 |
| Node.js, `uv`, `git` | ✅ Present |
| `build123d` 0.11.1, `trimesh`, `vtk`, `shapely`, `rtree` | ✅ Working on 3.13 |
| OpenSCAD / OrcaSlicer / Bambu Studio / Blender | ❌ None installed |
| GPU | RTX 4060 Laptop, **8GB VRAM**, driver 592.00, no CUDA toolkit |

> `AppData\Local\Programs\orca` is the Orca agent-browser Electron app, **not**
> OrcaSlicer.

**GPU consequence:** 8GB rules out local generative 3D (needs 24GB+). Confirmed
against an initial belief the machine had a 5090/24GB; `nvidia-smi` reports
otherwise. The organic branch is code-driven for the foreseeable future.

Also verified: VTK offscreen rendering works natively on Windows; a naive render
produces an unusable white-on-white image, confirming §6.6.

### 15.7 Hardware

- **Printer:** Bambu Lab P1S with AMS · **Nozzle:** 0.4mm hardened/steel
- **Materials:** PLA, PETG routinely; ABS, ASA, PC, PA occasionally

> PC and PA are hygroscopic enough that the AMS is a liability — they typically run
> from the external spool holder, so `filaments.json` must support a slot type that
> is not an AMS bay. PA-CF and PC-CF are abrasive, already covered by the hardened
> nozzle.

### 15.8 Prior Art

Existing OpenSCAD skills (`swh/openscad-skill`, `andreahaku/openscad_claude_skill`,
`iancanderson/openscad-agent`), a `build123d` skill on Smithery, and MCP servers
for OpenSCAD, CadQuery, Blender (~20k stars), and Bambu
(`schwarztim/bambu-mcp`). All are single-tool wrappers. **None closes the
verification loop.**

### 15.9 References

- [build123d](https://build123d.readthedocs.io/) ·
  [fogleman/sdf](https://github.com/fogleman/sdf) ·
  [manifold3d](https://github.com/elalish/manifold)
- [OrcaSlicer CLI cookbook](https://github.com/CapitanaIcoachai/orcaslicer-cli-cookbook)
- [Bambu third-party integration](https://wiki.bambulab.com/en/software/third-party-integration) ·
  [bambulabs-api](https://pypi.org/project/bambulabs-api/)
- [3MF Materials Extension](https://github.com/3MFConsortium/spec_materials) ·
  [gcode-preview](https://github.com/xyz-tools/gcode-preview)

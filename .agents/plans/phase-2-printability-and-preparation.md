# Feature: Phase 2 — Printability & Preparation

The following plan should be complete, but its important that you validate documentation and codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils types and models. Import from the right files etc.

> **This plan is backed by a PRE-FLIGHT spike run on this machine on 2026-07-31.** The slicer was
> invoked for real (nine headless runs), meshes were broken and repaired, a fit gauge was built and
> measured, and every numeric claim below was **measured, not estimated**. Spike artifacts live in
> the scratchpad (`.../scratchpad/slice1..6`, `flat2/`, `coupon.*`). Where the PRD and the spike
> disagree, **the spike wins** and the discrepancy is called out under [PRD CORRECTIONS](#prd-corrections).
>
> **Baseline before this plan** (measured, same session): `uv run pytest -q` → **184 passed**;
> `uv run python benchmarks/run_mutations.py` → **caught 13/13, missed 0, false-positives 0,
> harness-errors 0** across 19 mutations, VERDICT PASS.

## Feature Description

Phase 1 proved a part is *correct*. Phase 2 proves it is *printable*, gets it *repaired* when it
arrives broken from outside, and turns it into machine instructions — while never sending anything
to a printer.

Four capabilities, one theme: **every new answer carries a measured number and a source, and every
new layer that can silently succeed is made to fail loudly instead.**

- **`lril3d-dfm`** — the full per-material rules engine that replaces the thin `printability.py`
  slice. Thresholds live in `profiles/dfm-rules.json` with a cited source, exactly as parts
  dimensions live in `parts.py` with a citation.
- **`lril3d-repair`** — import → diagnose → fix → **verify**. Tier 1 probing applies to imported
  meshes (PRD §6.2), so a repair that quietly changes a dimension is a *failed* repair, not a
  successful one.
- **`lril3d-slice`** — a Bambu Studio CLI wrapper producing G-code, print time, per-filament grams,
  AMS mapping and purge waste. The wrapper's hardest job is refusing to report a number the slicer
  did not actually produce.
- **`coupon.py`** — the stepped fit-gauge generator that Phase 3's calibration workflow consumes.

Plus **G-code preview in the viewer**, which is a channel, not a gate — the same rule as renders.

## User Story

As a **capable maker with a Bambu P1S**
I want to **know whether a verified-correct part will actually print, have an imported STL fixed
without silently changing its dimensions, and see real print time and filament cost before I
commit**
So that **the six-hour print I start is one I already know will succeed, and a "repaired" model is
still the model I measured.**

## Problem Statement

Phase 1 answers *"is this part what I asked for?"*. It cannot answer three questions that stand
between a correct part and a good print:

1. **"Will it print?"** `printability.py` ships two measurements — sampled min wall and an overhang
   histogram. It has no per-material thresholds, no bridging check, no small-feature check, no
   footprint/tipping check, and no verdict. A part with a 0.6 mm boss passes Phase 1 completely.

2. **"Can this imported mesh be trusted after repair?"** Repair tooling is the softest place in the
   whole pipeline for the project's founding failure: `fill_holes` returns quietly, the mesh becomes
   watertight, and nothing checks whether a design feature was bridged over in the process. Measured
   this session: an inverted-winding mesh reports **volume −571.14 mm³** — a *negative* number that
   `intent.check`'s `volume` kind will happily compare against a range.

3. **"What will it cost me?"** Print time, grams and purge waste are slicer outputs, and the slicer
   is a black box that **writes nothing to stdout on Windows** and will report `return_code: 0,
   "Success."` for a slice that produced no G-code at all (measured — spike S6). Every one of the
   three ways this wrapper can lie was reproduced on this machine.

## Solution Statement

Five mechanisms, in build order, each one closing a specific way a Phase 2 layer could report green
while being wrong:

1. **DFM thresholds are cited configuration, not code.** `profiles/dfm-rules.json` carries a
   `source` per rule per material, mirroring `parts.py`. An uncited threshold is an invented number
   wearing a lab coat.
2. **DFM findings become measurable assertions.** A new `dfm_violation_count` measure kind lets an
   `intent.json` assert *"zero BLOCKER findings in PLA"*, so the **existing** mutation harness
   scores the DFM engine with no new scoring machinery (ADR-8).
3. **Repair must re-measure, not re-assure.** `repair.verify()` re-extracts a `FeatureSet` after the
   fix and compares every Tier 1 dimension it can measure against the same dimensions before it. A
   drift beyond tolerance is a FAIL with the two numbers printed (ADR-9).
4. **The slice wrapper accepts a result only on four independent conditions**, because each one
   alone was measured to be satisfiable by a failed run (ADR-10).
5. **The mutation suite grows with the verifier.** A new `imported-mesh` benchmark plus DFM
   mutations on the same benchmark — including `cosmetic_*` false-positive detectors — keep the rule
   that *benchmarks passing proves nothing about a verifier scored only on parts that happen to be
   correct*.

## Feature Metadata

**Feature Type**: New Capability (four skills' worth), on top of an unchanged Phase 1 core
**Estimated Complexity**: **High** — 4 new library modules, 3 new skills, 1 new benchmark, ~10 new
mutations, a viewer mode, and one external binary whose failure modes are the main risk
**Primary Systems Affected**: `src/threedp/` (new: `dfm.py`, `repair.py`, `slicer.py`, `gcode.py`,
`coupon.py`; touched: `printability.py`, `intent.py`), `benchmarks/`, `.claude/skills/`, `viewer/`,
`profiles/`
**Dependencies**: **No new Python packages.** Bambu Studio 02.07.01.62 (already installed at
`C:\Program Files\Bambu Studio\bambu-studio.exe`) is an external, discovered-at-runtime tool.

---

## SCOPE WARNING

**Phase 2 ships no printer path.** No FTPS, no MQTT, no socket, no `paho`, no upload. `--export-3mf`
produces a file a human can send by hand — that is PRD Risk 5's documented fallback, and it is the
end of the line for this phase. `.claude/settings.json` and `.claude/PRINT-GATE.md` are **not
edited**; their `deny` → `ask` conversion is a Phase 3 task and doing it early removes a guardrail
in exchange for nothing (`.claude/PRINT-GATE.md`, ADR-5).

Task 28 adds `tests/test_no_printer_path.py` to make that mechanical rather than a promise.

**Not in this phase:** measuring calibration constants (needs a printer — Phase 3), multi-slicer
abstraction (Phase 4), `lril3d-print`.

---

## CONTEXT REFERENCES

### Relevant Codebase Files IMPORTANT: YOU MUST READ THESE FILES BEFORE IMPLEMENTING!

Read `CLAUDE.md` first — it is the source of truth for the conventions this plan assumes and does
not restate. Then `PRD.md` §6.2, §6.3, §7, §9 and §12.

- **`src/threedp/measure.py`** (whole file, 239 lines) — Why: **the one ruler.** No new module may
  fit a circle, take a max radius, or diff a bounding box for a dimensional number. `fit_circle`
  is at :103; the gated `CircleFit.diameter` at :85.
- **`src/threedp/printability.py`** (whole file, 194 lines) — Why: the module `dfm.py` sits on top
  of. `WallReport`/`OverhangReport` at :43-95 are the dataclass-with-`__str__`-and-`flag` shape all
  new reports must mirror. The build-plate exclusion at :105-110 and the inclusive top bin at :40
  are two traps already paid for — do not re-derive them.
- **`src/threedp/intent.py`** :267-425 (measure kinds), :432-445 (`MEASURE_UNITS`), :448-463 (the
  `MEASURE_KINDS` registry), :606-641 (`_check_one`) — Why: Task 6 adds a kind. A kind returns
  `(value, tier, note)` and reports absence by **raising** `MeasurementError`; `_check_one` turns
  that into a FAIL with a reason, never a skip.
- **`src/threedp/features.py`** :160-214 (`select_cylinder` and its three distinct refusals),
  :464-534 (`_measure_axis_and_taper`), :74 (`_UNMEASURABLE_AXIS`) — Why: `repair.py` re-extracts
  through this, and the "refuse rather than report the most flattering answer" pattern at :74 is
  precisely the pattern `slicer.py` must copy for a slice that produced nothing.
- **`src/threedp/io.py`** :70-107 (`_write`), :110-179 (`export`) — Why: `_write` already raises
  when an exporter "reported success but wrote no file" (:88, :106). `slicer.py` needs the same
  reflex, three more times over.
- **`src/threedp/compensate.py`** :127-141 (`_entry` role validation), :144-180 (`resolve`) — Why:
  the coupon is a real part and its `params.json` must carry roles; a fit gauge printed with
  compensation applied measures the compensation, not the printer.
- **`src/threedp/parts.py`** :113-127 (`_SOURCES`, `PARTS`), :130-146
  (`_assert_keys_are_globally_unique`) — Why: `profiles/dfm-rules.json` mirrors this — every value
  carries a source, and an import-time invariant check beats a test that can be skipped.
- **`benchmarks/run_mutations.py`** :95-105 (`apply_overrides`), :117-137 (`build_and_export` —
  already handles a `trimesh.Trimesh` return at :132), :140-163 (`cross_check`), :166-251
  (`run_part`, incl. the baseline-must-pass gate at :208-213) — Why: the new benchmark and
  mutations plug into this **unchanged**. Read :193-237 before writing any mutation.
- **`benchmarks/harness.py`** :25-41 (`export_benchmark`), :44-69 (`run_model_cli`) — Why: the new
  benchmark's `model.py` must expose `load_params()` and `build(params, **options)` and nothing else.
- **`benchmarks/gyroid-vase/model.py`** :1-60 — Why: the only existing **mesh-native** benchmark
  (returns a `trimesh.Trimesh`, exports no STEP). `imported-mesh` follows this shape exactly.
- **`benchmarks/bearing-holder/mutations/README.md`** (whole file) — Why: the mutation protocol
  table (`EXPECT`, `REASON`, `KIND`, `SOURCE`, `PARAMS_OVERRIDE`, `BUILD_OPTIONS`, `patch`,
  `method_patch`, `EXTRA_ASSERTS`). Every new mutation obeys it.
- **`tests/test_one_ruler.py`** :31-52 (`BANNED`), :101-114 (the file walk and the
  skipped-layer guard) — Why: `python_files_under_the_rule()` globs `src/threedp/*.py`, so every new
  module is scanned automatically. Task 9 adds the new names to the :113 assertion so a *missing*
  file is caught too.
- **`tests/conftest.py`** :17-30 (`CANONICAL`, `PLATE`), :33-87 (builders), :174-205
  (`build_interrupted_bore` — the "refuse to measure" case) — Why: reuse these fixtures. Do not
  invent a second canonical part.
- **`.claude/skills/lril3d-inspect/SKILL.md`** (whole file, 86 lines) — Why: the tone, length and
  "banned from a critique" section that the three new SKILL.md files must match. Also the file that
  hands off to `lril3d-dfm`.
- **`viewer/src/main.js`** :121-127 (`fsUrl`), :129-145 (`loadProfile`), :147-172 (`loadModel`),
  :174-196 (WebSocket `connect`) — Why: G-code preview is a second load path alongside `loadModel`.
- **`viewer/server/watch.mjs`** :24-45 (`DEBOUNCE_MS`, `CANDIDATES`, `currentFile`), :66-88
  (`announce`, `schedule`) — Why: `CANDIDATES` must learn about the preview file, and the
  size-settling logic is what stops a half-written file being loaded.
- **`viewer/vite.config.js`** (whole file) — Why: `server.fs.allow` is why files outside `viewer/`
  load at all. A preview JSON written outside the repo root will 403 silently.
- **`profiles/filaments.json`**, **`profiles/printer-p1s.json`**, **`profiles/calibration.json`** —
  Why: AMS slot inventory (note slot 4 is `"type": "external"`, `bay: null` — the mapping code must
  not assume `slot == bay`), plate size, and the per-material `"measured": null` staleness flag.
- **`.claude/PRINT-GATE.md`** (whole file) — Why: states what Phase 2 must *not* touch and why.

### New Files to Create

| Path | Purpose |
|---|---|
| `profiles/dfm-rules.json` | Per-material DFM thresholds, each with a `source` |
| `profiles/slicer.json` | Slicer discovery: executable candidates, preset names, defaults |
| `src/threedp/dfm.py` | Rules engine: `Finding`, `DfmReport`, `evaluate()` |
| `src/threedp/repair.py` | `Diagnosis`, `RepairResult`, `diagnose()`, `repair()`, `verify()` |
| `src/threedp/slicer.py` | Bambu Studio CLI wrapper: discovery, preset flattening, `slice_part()`, `ams_mapping()`, `purge_waste()` |
| `src/threedp/gcode.py` | G-code metadata + toolpath parsing → viewer preview JSON |
| `src/threedp/coupon.py` | Stepped fit-gauge generator (+ its `intent.json`/`params.json`) |
| `tests/test_dfm.py` | Written **before** `dfm.py` |
| `tests/test_repair.py` | Written **before** `repair.py` |
| `tests/test_slicer.py` | Fake-CLI tests + real-CLI tests behind a `slicer` marker |
| `tests/test_gcode.py` | Parser tests against a committed g-code excerpt fixture |
| `tests/test_coupon.py` | Gauge geometry measured through `features`/`measure` |
| `tests/test_no_printer_path.py` | Mechanical proof Phase 2 shipped no send path |
| `tests/fixtures/plate_1_excerpt.gcode` | Small, committed, real Bambu CLI output excerpt |
| `benchmarks/imported-mesh/{model.py,params.json,intent.json}` | The repair benchmark |
| `benchmarks/imported-mesh/mutations/*.py` | 5 repair mutations (incl. 1 `cosmetic_*`) |
| `benchmarks/imported-mesh/mutations/dfm_*.py` | 3 DFM mutations (incl. 1 `cosmetic_*`) — see Task 14 for why they live here and not on `overhang-test` |
| `benchmarks/imported-mesh/mutations/README.md` | What the repair mutations mean |
| `.claude/skills/lril3d-dfm/SKILL.md` | Thin skill |
| `.claude/skills/lril3d-repair/SKILL.md` | Thin skill |
| `.claude/skills/lril3d-slice/SKILL.md` | Thin skill |
| `viewer/src/gcode-preview.js` | Preview rendering module for the viewer |

### Relevant Documentation YOU SHOULD READ THESE BEFORE IMPLEMENTING!

- [BambuStudio Wiki — Command Line Usage](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage)
  - Sections: `--slice`, `--load-settings`, `--load-filaments`, `--outputdir`, `--export-3mf`,
    `--arrange`, `--orient`, `--debug`
  - Why: the flag syntax this wrapper is built on. **Read the note that says the config files
    "should be a full config instead of the one used in `resources/profiles/BBL/machine`"** — spike
    S3 measured exactly what happens when you ignore it (silent `0.00 g`).
- [Printago — Bambu Studio CLI Reference](https://printago.io/blog/bambu-studio-cli-reference)
  - Section: headless slicing invocation and undocumented flags
  - Why: community notes on `--mstpp` and `--skip-useless-pick`. **Treat as unverified** — neither
    appears in the official wiki and neither was exercised in the spike; use a Python-side
    `subprocess` timeout instead (ADR-10).
- [trimesh.repair API](https://trimesh.org/trimesh.repair.html)
  - Sections: `broken_faces`, `fill_holes`, `fix_normals`, `fix_winding`, `fix_inversion`
  - Why: `fill_holes` "fills boundary holes in-place **using fans, which may result in bad answers
    if the holes are non-convex**" — that sentence is the entire reason `repair.verify()` exists.
- [trimesh.base — Trimesh properties](https://trimesh.org/trimesh.base.html)
  - Sections: `is_watertight`, `is_winding_consistent`, `is_volume`, `euler_number`, `volume`
  - Why: the diagnosis vocabulary. `volume` is signed and goes **negative** on inverted winding.
- [build123d docs](https://build123d.readthedocs.io/en/latest/)
  - Sections: `BuildPart`, `Box`, `Cylinder`, `Locations`, `Mode.SUBTRACT`
  - Why: `coupon.py` geometry. Mirror `benchmarks/bearing-holder/model.py`.
- [three.js — LineSegments / BufferGeometry](https://threejs.org/docs/#api/en/objects/LineSegments)
  - Why: the G-code preview draws ~20k extruding moves as one indexed `LineSegments`, not 20k
    objects.

### Patterns to Follow

**A report is a frozen dataclass that knows how to print itself, and a `flag`/`passed` property that
is separate from its text** — `printability.py`:43-95, `intent.py`:469-532:

```python
@dataclass(frozen=True)
class WallReport:
    min_mm: float
    ...
    @property
    def flag(self) -> bool:
        return self.min_mm < self.threshold_mm
    def __str__(self) -> str:
        return f"min_wall  min {self.min_mm:.3f} ...   ESTIMATE ({self.hits}/{self.samples} rays hit)"
```

**Refusal beats a flattering default** — `features.py`:63-74. Copy this comment's *reasoning* into
`slicer.py`, where the equivalent of "taper 0.0" is "0.00 g":

```python
# Every "cannot measure the axis" exit must use this. Returning taper 0.0 instead would report
# the most favourable possible answer -- perfectly vertical, perfectly straight -- on precisely
# the input where nothing was measured.
_UNMEASURABLE_AXIS = ((0.0, 0.0, 1.0), float("inf"))
```

**An exporter that reports success but wrote nothing is an error** — `io.py`:87-88:

```python
if not path.exists():
    raise ExportError(f"{fmt} export reported success but wrote no file at {path}")
```

**Config values carry a source; unknown keys raise with the valid list** — `parts.py`:158-173:

```python
if key not in table:
    raise KeyError(f"unknown {category} {key!r}; valid keys: {sorted(table)}")
record["source"] = f"{CITATION_PREFIX}{key}"
```

**A measure kind returns `(value, tier, note)` and raises to mean "absent"** — `intent.py`:364-377:

```python
def _k_noncircular_count(fs: FeatureSet, spec: dict[str, Any]):
    if fs.representation != "mesh":
        raise MeasurementError("noncircular_count is a mesh-path measurement; a BREP source ...")
    return float(len(fs.noncircular)), 1, ""
```

**Units are declared, not assumed** — `intent.py`:432-445. Every new kind added in Task 6 **must**
get a `MEASURE_UNITS` entry (`""` for counts, `"mm3"`, `"g"`, `"s"`). This exact omission is what
printed degrees as millimetres on all five benchmarks in Phase 1.

**Naming**: `snake_case` functions, `CapWords` dataclasses, module-level `UPPER_SNAKE` constants,
leading `_` for internals. All lengths are millimetres and unsuffixed; **suffix everything that is
not mm** — this phase introduces `_g` (grams), `_s` (seconds), `_mm3` (volume), `_deg`.

> **Spike-snippet fidelity:** the flattening snippet in Task 21 is transcribed from the spike script
> that produced the 10.85 g result. Its assertions are stated inline. If your implementation
> diverges from it, re-run the spike command in the [S3](#s3) block before assuming the snippet is
> stale.

---

## PRD CORRECTIONS

Four, and the first is a deliberate deviation confirmed by the maintainer this session.

<a id="c1"></a>
**C1 — The slicer is Bambu Studio, not OrcaSlicer.** PRD §12 and §7 name OrcaSlicer and say Phase 2
"requires installing OrcaSlicer". OrcaSlicer is **not installed** on this machine (`winget` offers
`SoftFever.OrcaSlicer 2.4.2`); **Bambu Studio 02.07.01.62 is**, with the complete BBL vendor profile
tree, and it was measured slicing headlessly in **0.92 s**. Maintainer decision, this session: target
Bambu Studio. OrcaSlicer is a Bambu Studio fork and shares the CLI surface and the `; FEATURE:`
G-code markers, so Phase 4's multi-slicer abstraction is not foreclosed — `profiles/slicer.json`
holds the executable candidates precisely so a second backend is config, not a rewrite.

<a id="c2"></a>
**C2 — PRD §12's thumbnail issue is confirmed, and it is not about OpenGL being absent.** Measured:
CLI-produced G-code contains **no thumbnail block at all** — one single `; thumbnail_size = 50x50`
config line and nothing else. So the P1S screen preview is blank, as the PRD says. Document it in
`lril3d-slice/SKILL.md`; do not attempt a workaround in Phase 2.

<a id="c3"></a>
**C3 — `coupon.py` is Phase 2, and it belongs in `src/threedp/`.** PRD §6's directory tree lists it
under `src/threedp/` while §12 schedules it in Phase 2; CLAUDE.md already records that §12 wins on
scheduling. Both are satisfied: build it now, at `src/threedp/coupon.py`.

<a id="c4"></a>
**C4 — PRD §9's `ams_mapping` reverse-index trap is a Phase 2 concern, not Phase 3.** §9 documents
it under "Bambu P1S Connectivity (Phase 3)", but §12 schedules "AMS filament mapping and purge-waste
estimation" in Phase 2. Computing and validating the mapping is Phase 2; *publishing it over MQTT*
is Phase 3. Build `ams_mapping()` now, with the reverse-index semantics tested, so Phase 3 inherits a
tested function rather than a documented trap.

---

## PRE-FLIGHT SPIKE RESULTS

Run on this machine, 2026-07-31. Every number below was observed, not estimated.

### Environment — verified present

| Thing | Version / fact | How verified |
|---|---|---|
| Python | **3.13.14** | root import gate, exit 0 |
| Bambu Studio | **02.07.01.62** at `C:\Program Files\Bambu Studio\bambu-studio.exe` | sliced a real part |
| BBL profile tree | 276 process profiles, P1S machine + PLA filament present | directory listing |
| OrcaSlicer | **absent**; `winget` has `SoftFever.OrcaSlicer 2.4.2` | `winget search` |
| trimesh | 4.12.2 | import |
| manifold3d | present, imports in **0.00 s** | import |
| bpy | **5.2.0 LTS**, imports in **2.1 s** | import — heavy; import lazily |
| shapely / networkx | 2.1.2 / 3.6.1 | import |

### S1 — the CLI slices headlessly, and writes **nothing** to stdout ✅

```
bambu-studio.exe --slice 0 --outputdir OUT part.3mf     → shell exit 0
OUT/plate_1.gcode  759,908 bytes
OUT/result.json      2,198 bytes
redirected stdout        0 bytes      ← every run, without exception
```

No GUI window appeared. **Consequence:** `slicer.py` must never parse stdout. `result.json` is the
machine-readable channel and it is written even on failure (see S6).

### S2 — `result.json` is rich, and is the right source for everything

Keys measured on a successful run: `return_code`, `error_string`, `sliced_plates[]` each with
`filaments[{filament_id, id, main_used_g, total_used_g}]`, `total_predication` (seconds),
`filament_change_times`, `warning_message`, `objects[{bbox, triangle_count}]`, plus
`layer_height`, `sparse_infill_density`, `wall_loops` and a `feature_type_times` breakdown.

<a id="s3"></a>
### S3 — ⚠ **the headline finding**: raw system profiles silently produce `0.00 g`

Passing the BBL system JSONs straight to `--load-settings` / `--load-filaments` **succeeds**
(`return_code 0`, `"Success."`, correct printer, correct process) and yields:

```
; total filament weight [g] : 0.00
; filament_density: 0
filaments: [{"filament_id": "", "main_used_g": 0.0, "total_used_g": 0.0}]
```

Cause, traced: `Bambu PLA Basic @BBL P1S 0.4 nozzle.json` has **23 keys and no
`filament_density`**. The chain is four deep —

```
Bambu PLA Basic @BBL P1S 0.4 nozzle  →  Bambu PLA Basic @base (density 1.26)
                                     →  fdm_filament_pla     (density 1.24)
                                     →  fdm_filament_common  (density 0)   ← what shipped
```

— and the CLI does not resolve it. The official wiki says the file "should be a full config"; this
is what "should" costs. **Fix (measured to work):** flatten the `inherits` chain, root first, child
overriding parent. After flattening:

```
; total filament weight [g] : 10.85      ; filament_density: 1.26     filament_id: GFA00
model printing time: 25m 7s              total_predication: 1528 s
```

`filament_id: GFA00` is not cosmetic — PRD §9 records that `use_ams` is **silently ignored** unless
`filament_id` is set inside the 3MF, so the unflattened path also breaks Phase 3.

### S4 — ⚠ flattening must **keep the original preset `name`**

First flatten attempt renamed presets to `"... (flattened)"` and set `from: "User"`:

```
return_code -17   "The selected printer is not compatible with the process preset in the 3mf."
```

The process preset's `compatible_printers` is a list of **printer names** (4 entries; P1S 0.4 is one
of them). Rename the machine and the match fails. Keep `name` verbatim; drop only `inherits`.

### S5 — ⚠ `--export-3mf` requires a **relative** path

Absolute path → `return_code -13  "Failed exporting 3mf files."` — **while `plate_1.gcode` was
still written**. Relative path, with cwd set to the output directory → `return_code 0` and a
135,810-byte `sliced.3mf`. Two lessons: pass a bare filename and set `cwd`; and never infer success
from the presence of a G-code file.

<a id="s6"></a>
### S6 — ⚠ **`return_code: 0, "Success."` on a slice that produced nothing**

```
--slice 3   on a single-plate model
→ result.json: {"return_code": 0, "error_string": "Success.", "plate_index": 3,
                "layer_height": 0.0, ...}          ← and NO "sliced_plates" key at all
→ output dir: result.json only. No plate_1.gcode.
```

This is the Phase 1 failure mode wearing a slicer's clothes. A wrapper keyed on `return_code == 0`
reports a successful slice of nothing. Compare S5, where a **non-zero** code accompanied a perfectly
good G-code file. Neither signal alone is sound — hence ADR-10's four conditions.

For contrast, a genuinely bad input is reported cleanly: missing input file →
`return_code -3  "The input files to the slicer are not found."`, `result.json` still written.

### S7 — the G-code header's volume unit label is **wrong**

```
; total filament length [mm] : 3580.16
; total filament volume [cm^3] : 8611.30      ← this is mm³, not cm³
; total filament weight [g] : 10.85
```

Arithmetic check: 3580.16 mm × π(1.75/2)² = 8611 **mm³** = 8.611 cm³; × 1.26 g/cm³ = **10.85 g** ✓.
Take grams from `result.json`; if volume is ever needed, compute it from length and diameter rather
than trusting the label.

### S8 — purge/flush data is present in the G-code config block

```
; flush_volumes_matrix = 0,280,280,280,280,0,280,280,280,280,0,280,280,280,280,0    (4×4, mm³)
; flush_volumes_vector = 140,140,140,140,140,140,140,140
; flush_multiplier = 1
result.json: "filament_change_times": 0
```

Purge waste = Σ over changes of `matrix[from][to]` × `flush_multiplier`, in mm³ → grams via density.

### S9 — Bambu's G-code markers are **not** PrusaSlicer's

A parser written to `;TYPE:` and `;LAYER_CHANGE` finds **zero** of each. Bambu emits, with a leading
space: `; FEATURE: Inner wall`, `; CHANGE_LAYER`, `; LAYER_HEIGHT: 0.2`. Measured on the 0.73 MB
l-bracket G-code: 31,270 lines, 20,556 `G0/G1` moves, 15,688 extruding moves, 723 Z moves; full
read + regex scan in Python: **14 ms**.

### S10 — repair restores geometry *exactly*, which is why verification must be real

Baseline l-bracket mesh: watertight, winding consistent, volume 19588.860 mm³, 3060 faces.

| Break | Symptom | Repair | Result |
|---|---|---|---|
| delete 3 faces | not watertight, euler −8, **7 broken faces** | `fill_holes` (**2.2 ms**) | watertight, volume 19588.860 — **delta 0.000000** |
| reverse 200 faces' winding | `is_winding_consistent False`, **volume −571.14** | `fix_winding` + `fix_normals` (**89.9 ms**) | consistent, volume 19588.860 |

Then re-extracted through `features.extract`: largest cylinder **Ø6.9989 before and after, delta
0.000000 mm**; cylinder count 4 both times; volume delta 0.000000. So repair *can* be dimensionally
free — which is exactly why "it looks fine after repair" must be replaced by a measured comparison:
the good case is indistinguishable from the bad one without it.

Note the negative volume: an inverted mesh feeds `intent.check`'s `volume` kind a **negative
number**, and a `[5400, 5700]` range would FAIL — correctly, but for the wrong reason and with a
useless message. `diagnose()` must catch inversion first.

### S11 — the stepped fit gauge is measurable to 0.0016 mm

Built a 5-step gauge (Ø9.8/9.9/10.0/10.1/10.2 bores, 16 mm pitch, 6 mm plate) with build123d in
**11.31 s**, exported in 0.16 s, and measured it back through `features.extract`:

```
measured: [9.7985, 9.8985, 9.9984, 10.0984, 10.1984]     max error vs nominal: 0.0016 mm
```

0.1 mm steps are resolved with ~60× margin. The gauge design is sound before a printer exists.

### S12 — a full slice invocation costs 0.92 s wall clock

l-bracket, 3060 triangles: **924 ms** end to end (slicer-reported: prepare 8 ms, slice 401 ms,
export 0 ms). Cheap enough that real-CLI tests need no `slow` marker — only a `slicer` marker so the
suite still passes on a machine without Bambu Studio.

---

## ARCHITECTURE DECISIONS

Numbering continues from Phase 1 (which ended at ADR-5).

### ADR-6 — The module is `slicer.py`, not `slice.py`

`threedp.slice` shadows the `slice` builtin the moment anyone writes `from threedp import slice`,
and the module wraps *a slicer program* rather than performing *a slicing operation*. The skill
keeps the PRD's name (`lril3d-slice`); the module is `slicer.py`. Same reasoning gives
`profiles/slicer.json`.

### ADR-7 — `dfm.py` is a rules engine over `printability.py`, which stays the measurement layer

CLAUDE.md already names `printability.py` "the clean seam for Phase 2's full `lril3d-dfm` engine".
Keep the seam: **new measurements go into `printability.py`** (sampled, statistical, returning
numbers), **thresholds and verdicts go into `dfm.py`** (configuration-driven, returning findings).

The alternative — one big `dfm.py` doing both — was rejected because it puts a threshold and the
measurement that feeds it in the same place, and the first thing anyone does when a rule cries wolf
is loosen whichever of the two is closer to hand. Separated, tuning a threshold is a JSON edit that
cannot touch a measurement.

Corollary: `dfm.py` performs **no dimensional measurement of its own**. `tests/test_one_ruler.py`
scans it automatically.

### ADR-8 — DFM findings are scored by the *existing* mutation harness, via a measure kind

The alternative was teaching `run_mutations.py` a second verdict channel for DFM. Rejected: a second
scoring path is a second place for the score to be wrong, and the harness's most valuable property —
*the baseline must pass its own intent before any mutation is judged* (`run_mutations.py`:208-213) —
would have to be reimplemented.

Instead, `intent.py` gains `dfm_violation_count`:

```json
{"dfm_blockers": [0, 0], "source": "user-confirmed",
 "measure": {"kind": "dfm_violation_count", "severity": "BLOCKER", "material": "PLA_generic"}}
```

A DFM regression then fails an ordinary assertion, is caught by the ordinary harness, and appears in
an ordinary report with a measured count. **Unit is `""`** (a count) — add it to `MEASURE_UNITS`.

Consequence to accept deliberately: DFM findings gate a verdict only where a benchmark's
`intent.json` asserts on them. That is the correct default — DFM advice is advisory; it becomes a
gate only when someone writes down that it should be.

### ADR-9 — A repair is not complete until it is re-measured; a silent dimension change is a FAIL

`trimesh.repair.fill_holes` documents that it fills holes "using fans, which may result in bad
answers if the holes are non-convex". A non-convex boundary hole is what a *bore breaking the
surface* looks like. So the failure mode is: import a model with a hole through a Ø22 bore wall,
"repair" it, get a watertight mesh whose bore is now partially bridged, and report success.

`repair()` therefore never returns a mesh alone. It returns a `RepairResult` carrying:

- the diagnosis before, the diagnosis after, and the ops applied;
- `volume_delta`, `faces_added`, `holes_filled`;
- a **dimensional comparison**: every cylinder `features.extract` can measure at Tier 1 before,
  matched by axis position to the same cylinder after, with the diameter delta;
- `passed`, which is False if any matched dimension moved more than `tol` (default **0.01 mm**, 2×
  the ±0.005 mm Tier 1 guarantee), or if a Tier 1 cylinder present before is **absent** after.

A feature that disappears during repair is the defect — the same rule as `intent.py`, and for the
same reason.

Where the before-mesh is too broken to measure (sections fail, no rings), `verify()` reports
`UNVERIFIABLE` and `passed` is False. It does not report success on the grounds that it could not
look.

### ADR-10 — A slice result is accepted only on four independent conditions

Measured (S5, S6): `return_code == 0` alone admits a slice that produced nothing; "the G-code exists"
alone admits a run that reported failure; and both together still admit the `0.00 g` case (S3), which
is a *plausible number nobody produced*. So `slicer.slice_part()` accepts only when **all four** hold:

1. `result.json` exists and `return_code == 0` (else raise with `error_string` verbatim);
2. `sliced_plates` is present and non-empty (the S6 trap);
3. the expected `plate_N.gcode` exists and is non-empty;
4. filament weight is `> 0` **and** the G-code header's `filament_density` is `> 0` (the S3 trap).

Condition 4 is the one that will feel excessive until someone ships an unflattened preset. It is not
an assertion that the part weighs something; it is a refusal to report a number the slicer computed
from a density of zero. The exception message names the flattening fix.

Timeouts are enforced Python-side with `subprocess.run(..., timeout=)`, not with the undocumented
`--mstpp` flag, because a flag that is not in the official wiki and was not exercised in the spike is
not a dependency this wrapper should acquire.

### ADR-11 — G-code is parsed in Python, and the viewer renders a preview JSON

The viewer could parse `.gcode` in the browser. Rejected: parsing is the part with the traps (S9's
marker names, the header's wrong unit label), and the browser is the one place in this project with
no tests. `gcode.py` parses and emits a compact preview JSON; `viewer/` renders it. This keeps the
"thin skins, thick library" rule pointed at the viewer as well as at skills, and makes S9 a unit
test instead of a visual inspection.

The preview stays a **channel, not a gate** — the same rule as renders and the live viewer. Nothing
in `gcode.py` returns a pass/fail.

### ADR-12 — The repair benchmark's broken mesh is **generated, not committed**

`out/` is gitignored ("models are programs; outputs are rebuildable"). A committed broken STL would
be an opaque binary whose defect nobody can read in a diff, and it would sit outside that rule.

`benchmarks/imported-mesh/model.py` therefore builds a known part with build123d, breaks it
**deterministically** (a documented face-index list and a documented winding reversal — the exact
breaks measured in S10), repairs it, and returns the repaired mesh. The benchmark is mesh-native and
exports no STEP, following `benchmarks/gyroid-vase/model.py`.

Consequence: the intent asserts both that repair *worked* (watertight) and that repair *did not
change the part* (bore diameters unchanged, at Tier 1). A mutation that skips the repair fails the
first; a mutation that over-repairs fails the second.

---

## IMPLEMENTATION PLAN

Two milestones. **2A has no dependency on the slicer at all** — if Bambu Studio is uninstalled
tomorrow, everything in 2A still builds, tests and scores.

### Milestone 2A — Printability and Repair (Tasks 1–18)

Foundation → measurement → rules → repair → benchmark → skills. The mutation coverage lands
*with* the code it scores, not after it.

**Tasks:**
- Config and test-marker foundation (`dfm-rules.json`, pytest markers)
- New sampled measurements in `printability.py`, each validated against known geometry
- `dfm.py` rules engine; `dfm_violation_count` measure kind
- `repair.py` with the ADR-9 verification contract
- `coupon.py` fit-gauge generator
- `benchmarks/imported-mesh/` + 5 repair mutations + 3 DFM mutations
- `lril3d-dfm` and `lril3d-repair` SKILL.md; `lril3d-inspect` handoff update

### Milestone 2B — Slicing, AMS and Preview (Tasks 19–29)

**Tasks:**
- `profiles/slicer.json` + discovery
- Preset flattening (S3/S4), the ADR-10 acceptance gate, `slice_part()`
- AMS mapping (reverse-index) and purge-waste estimation
- `gcode.py` parsing + preview JSON
- Viewer preview mode, watcher candidate list
- `lril3d-slice` SKILL.md; viewer skill update
- The no-printer-path guard test; docs; full validation

---

## STEP-BY-STEP TASKS

IMPORTANT: Execute every task in order, top to bottom. Each task is atomic and independently testable.

### Task Format Guidelines

Use information-dense keywords for clarity:

- **CREATE**: New files or components
- **UPDATE**: Modify existing files
- **ADD**: Insert new functionality into existing code
- **REMOVE**: Delete deprecated code
- **REFACTOR**: Restructure without changing behavior
- **MIRROR**: Copy pattern from elsewhere in codebase

---

## MILESTONE 2A — PRINTABILITY AND REPAIR

### 1. UPDATE `pyproject.toml` — test markers only, no new dependencies

- **IMPLEMENT**: Add two markers to `[tool.pytest.ini_options].markers`:
  `slicer: requires a slicer executable (Bambu Studio) to be installed` and
  `slow: takes more than a few seconds`. Add **no** packages — every Phase 2 capability was spiked
  on the existing dependency set.
- **PATTERN**: `pyproject.toml`:39-42 (the existing `brep`/`mesh` markers)
- **GOTCHA**: Do not relax `requires-python = "==3.13.*"`. Do not add a slicer package from PyPI —
  the slicer is an external executable discovered at runtime, never a Python dependency.
- **VALIDATE**: `uv run pytest --markers | grep -E "slicer|slow"`

### 2. CREATE `profiles/dfm-rules.json`

- **IMPLEMENT**: Per-material thresholds, each an object with `value`, `unit` and **`source`**.
  Structure: `{"_defaults": {...}, "PLA_generic": {...}, "PETG_generic": {...}, "ABS_generic": {...}}`
  where a material record overrides `_defaults`. Rules to include, all derived from the 0.4 mm
  nozzle in `profiles/printer-p1s.json`:

  | Rule | Default | Suggested source string |
  |---|---|---|
  | `min_wall_mm` | 0.8 | `"two perimeters of a 0.4mm nozzle"` |
  | `min_feature_mm` | 0.8 | `"a feature thinner than one bead does not print"` |
  | `min_hole_d_mm` | 2.0 | `"FDM bores below 2mm close up from arc faceting and flow"` |
  | `max_overhang_deg` | 45.0 | `"conventional FDM support threshold, measured from vertical"` |
  | `max_bridge_mm` | 10.0 | `"unsupported bridge span before sag"` |
  | `min_footprint_mm2` | 100.0 | `"bed adhesion / tipping risk on a tall part"` |
  | `max_aspect_ratio` | 8.0 | `"height divided by the smaller footprint dimension"` |
  | `warn_unsupported_mm2` | 50.0 | `"unsupported area worth reporting"` |

  Per-material overrides: ABS/PETG get a lower `max_overhang_deg` and a lower `max_bridge_mm` than
  PLA; state the reason in a `note`. Include a top-level `"source": "..."` and severity mapping
  (`BLOCKER` vs `WARNING`) per rule.
- **PATTERN**: `profiles/calibration.json` (flat per-material records); `parts.py`:113-119 (`_SOURCES`)
- **GOTCHA**: Numbers here are **suffixed by unit in the key** (`_mm`, `_deg`, `_mm2`) because JSON
  cannot carry the convention that bare numbers are millimetres. Do not write bare `min_wall`.
- **VALIDATE**: `uv run python -c "import json;d=json.load(open('profiles/dfm-rules.json'));assert all('source' in r for m in d.values() for r in m.values() if isinstance(r,dict)), 'uncited rule';print('OK',sorted(d))"`

### 3. CREATE `tests/test_dfm.py` — **WRITE THIS BEFORE `dfm.py`**

- **IMPLEMENT**: Tests that pin behaviour, not implementation:
  - a rules file with an uncited threshold **raises** at load;
  - an unknown material raises `KeyError`-style with the valid list (mirror `parts.get`);
  - `build_overhang_cone()` (conftest:74) at 60° produces a BLOCKER for `max_overhang_deg` in
    PLA — the measured spike-6 truth is 1339.09 mm² unsupported;
  - the same cone at 30° produces **no** BLOCKER (the false-positive direction);
  - `build_plate()` (conftest:49, true min wall 5.0 mm) produces no `min_wall_mm` finding;
  - a deliberately thin part does produce one, and the finding **carries the measured value, the
    threshold and the source string**;
  - `DfmReport.blockers` / `.warnings` partition the findings and `str(report)` contains no bare
    "looks"/"should" language (assert the numbers are present);
  - material override actually overrides (`ABS_generic.max_overhang_deg` ≠ `_defaults`).
- **PATTERN**: `tests/test_printability.py` (fixture use and analytic-truth assertions)
- **GOTCHA**: Use the existing conftest builders. Do not add a second canonical part.
- **VALIDATE**: `uv run pytest tests/test_dfm.py -v` (expected: all fail — `dfm.py` does not exist)

### 4. ADD new measurements to `src/threedp/printability.py`

- **IMPLEMENT**: Three additions, each returning a report dataclass in the existing style:
  - `bridge_spans(mesh) -> BridgeReport` — for each downward-facing near-horizontal face
    (reuse `_face_angles_from_vertical`, exclude `_on_build_plate`), the span of its unsupported
    footprint. Report `max_span_mm`, per-span list, and mark it an **ESTIMATE** (it is derived from
    face geometry, not a slice).
  - `min_feature_size(mesh, samples=2000) -> WallReport`-shaped — reuse the existing `min_wall` ray
    machinery; expose thin *positive* features rather than thin walls by sampling and reporting the
    p1 as well as the min (`min_wall` already returns both — prefer extending it with a docstring
    note over duplicating the ray code).
  - `footprint(mesh) -> FootprintReport` — build-plate contact area (`_on_build_plate` faces summed),
    bounding footprint X/Y, `aspect_ratio` = height / min(footprint x, y).
- **PATTERN**: `printability.py`:97-146 exactly — angles from vertical, plate faces excluded,
  reports frozen with `flag` and `__str__`
- **IMPORTS**: nothing new; `numpy`, `trimesh` are already imported
- **GOTCHA**: **Angles are measured from vertical** (0 = wall, 90 = ceiling) and the top bin needs an
  inclusive bound — both traps are already documented at `printability.py`:1-19 and both silently
  produce a clean bill of health when got wrong. A bridge span computed from a *bounding box* of the
  overhang region is a bounding-box measurement — keep it out of dimensional claims and label the
  report ESTIMATE.
- **VALIDATE**: `uv run pytest tests/test_printability.py -v && uv run pytest tests/test_one_ruler.py -v`

### 5. CREATE `src/threedp/dfm.py`

- **IMPLEMENT**:
  ```python
  BLOCKER, WARNING, NOTE = "BLOCKER", "WARNING", "NOTE"

  @dataclass(frozen=True)
  class Finding:
      rule: str; severity: str; measured: float; threshold: float
      unit: str; source: str; message: str

  @dataclass(frozen=True)
  class DfmReport:
      part: str; material: str; findings: list[Finding]
      @property
      def blockers(self) -> list[Finding]: ...
      @property
      def passed(self) -> bool: return not self.blockers
      def count(self, severity: str | None = None) -> int: ...
      def __str__(self) -> str: ...     # one line per finding, measured vs threshold vs source

  def load_rules(material: str, path: str | Path | None = None) -> dict: ...
  def evaluate(mesh, material: str, rules_path=None, printer=None) -> DfmReport: ...
  ```
  `evaluate` calls `printability` for every number and compares against `load_rules`. It **never**
  measures anything itself.
- **PATTERN**: `parts.py`:158-173 for the unknown-key error; `compensate.py`:92-107 for profile
  loading and `profiles_dir()` resolution — **reuse `compensate.profiles_dir()`**, do not write a
  second profile locator.
- **GOTCHA**: A missing rule key must **raise**, never default. A rules engine that silently skips
  an unknown rule is a rules engine that reports a clean part when the config is typo'd. Mirror
  `parts.get`'s "valid keys: [...]" message.
- **VALIDATE**: `uv run pytest tests/test_dfm.py -v` (expected: green)

### 6. ADD `dfm_violation_count` to `src/threedp/intent.py`

- **IMPLEMENT**: A measure kind following the registry contract:
  ```python
  def _k_dfm_violation_count(fs: FeatureSet, spec: dict[str, Any]):
      from threedp import dfm
      report = dfm.evaluate(_require_mesh(fs), str(spec.get("material", "PLA_generic")))
      severity = spec.get("severity", dfm.BLOCKER)
      return float(report.count(severity)), 1, f"{severity} findings under {report.material}"
  ```
  Register it in `MEASURE_KINDS` and add `"dfm_violation_count": ""` to `MEASURE_UNITS`.
- **PATTERN**: `intent.py`:401-424 (the `printability`-backed kinds, imported lazily inside the
  function) and :448-463 (registry)
- **GOTCHA**: **The `MEASURE_UNITS` entry is not optional.** Omitting it prints a count as
  millimetres — the exact bug fixed in commit `bb283b6`. Tier is 1 because a *count of findings* is
  exact even when the findings themselves are estimates; the finding's own text carries the
  ESTIMATE labelling.
- **VALIDATE**: `uv run pytest tests/test_intent.py -v` plus a new test asserting
  `unit_for("dfm_violation_count") == ""`

### 7. CREATE `tests/test_repair.py` — **WRITE THIS BEFORE `repair.py`**

- **IMPLEMENT**: Reproduce the S10 spike as tests, then push past it:
  - `diagnose` on `plate_mesh` (conftest:134) reports watertight, consistent winding, 0 broken faces;
  - deleting faces `[10, 11, 12]` → `broken_faces` non-empty, `watertight` False;
  - reversing 200 faces' winding → `is_winding_consistent` False **and** `volume < 0`, and
    `diagnose` names *inversion* specifically rather than reporting a volume;
  - `repair()` on each → `RepairResult.passed` True, `volume_delta == 0.0` (S10 measured exactly
    0.000000), and the dimensional comparison shows the Ø8 holes unchanged;
  - **the important one**: a mesh broken by removing faces *inside a bore wall*, where `fill_holes`
    bridges the bore → `RepairResult.passed` **False**, with the before/after diameters in the
    message;
  - a mesh so broken that sectioning fails → `UNVERIFIABLE`, `passed` False, never True;
  - a Tier 1 cylinder present before and absent after → FAIL naming the absent feature.
- **PATTERN**: `tests/test_features.py` for extraction-based assertions
- **GOTCHA**: Build the broken meshes from conftest builders, deterministically (fixed face indices,
  fixed counts) — a randomly broken mesh makes a failing test unreproducible.
- **VALIDATE**: `uv run pytest tests/test_repair.py -v` (expected: all fail)

### 8. CREATE `src/threedp/repair.py`

- **IMPLEMENT**:
  ```python
  @dataclass(frozen=True)
  class Diagnosis:
      watertight: bool; winding_consistent: bool; inverted: bool
      broken_faces: int; euler_number: int; volume: float
      duplicate_faces: int; degenerate_faces: int
      @property
      def healthy(self) -> bool: ...
      def __str__(self) -> str: ...

  @dataclass(frozen=True)
  class DimensionDelta:
      xy: tuple[float, float]; before: float; after: float
      @property
      def delta(self) -> float: ...

  @dataclass(frozen=True)
  class RepairResult:
      before: Diagnosis; after: Diagnosis; ops: list[str]
      volume_delta: float; faces_added: int; holes_filled: int
      dimensions: list[DimensionDelta]; lost_features: list[tuple[float, float]]
      status: str            # "PASS" | "FAIL" | "UNVERIFIABLE"
      @property
      def passed(self) -> bool: return self.status == "PASS"

  DEFAULT_DIM_TOL = 0.01          # 2x the +/-0.005mm Tier 1 guarantee

  def diagnose(mesh) -> Diagnosis: ...
  def repair(mesh, ops=None, tol=DEFAULT_DIM_TOL) -> RepairResult: ...   # returns result.mesh too
  def verify(before_mesh, after_mesh, tol=DEFAULT_DIM_TOL) -> RepairResult: ...
  ```
  Ops, in order, each recorded in `ops`: `merge_vertices` → `fix_inversion`/`fix_winding` →
  `fix_normals` → `fill_holes` → `remove_degenerate_faces`/`remove_duplicate_faces`.
- **PATTERN**: `features.py`:160-198 for error text that names *what is absent and why that is the
  defect*; `benchmarks/gyroid-vase/model.py` docstring for the `merge_vertices`-then-**verify**
  discipline (`sdf` emits a triangle soup — merge, then verify, never export the raw output)
- **IMPORTS**: `trimesh`, `trimesh.repair`, `from threedp import features, measure`
- **GOTCHA**: `fill_holes` fans non-convex holes and can bridge a real feature — that is ADR-9's
  entire reason to exist. Match cylinders before/after **by axis XY position** (`Cylinder.xy`),
  not by list index: repair changes face counts and therefore ordering. Use
  `features.from_mesh(...)`, never a fresh circle fit.
- **VALIDATE**: `uv run pytest tests/test_repair.py tests/test_one_ruler.py -v`

### 9. UPDATE `tests/test_one_ruler.py` — extend the skipped-layer guard

- **IMPLEMENT**: Add `"dfm.py"`, `"repair.py"`, `"slicer.py"`, `"gcode.py"`, `"coupon.py"` to the
  expected-names loop at :113.
- **PATTERN**: `tests/test_one_ruler.py`:108-114
- **GOTCHA**: The walk already picks new modules up automatically; this assertion catches the
  *opposite* failure — a module that was never created, or was created in the wrong directory, while
  the ruler test still reports green.
- **VALIDATE**: `uv run pytest tests/test_one_ruler.py -v` (fails until Tasks 21/23/17 land — that is
  correct; re-run at Task 29)

### 10. CREATE `src/threedp/coupon.py`

- **IMPLEMENT**: `fit_gauge(nominal_d, steps=(-0.2,-0.1,0.0,+0.1,+0.2), kind="hole", pitch=16.0,
  plate_t=6.0) -> (shape, params, intent_dict)`. Bores for `kind="hole"`, pins for `kind="pin"`.
  Emits a `params.json`-shaped dict with **roles** (`hole`/`outer`/`neutral`) and an
  `intent.json`-shaped dict asserting each step's diameter through `cylinder_diameter` at its known
  XY, `source: "user-confirmed"`, plus a `feature_count` assertion so a missing step is caught.
- **PATTERN**: `benchmarks/bearing-holder/model.py`:35-81 (build shape); `intent.py`:17-28 (schema)
- **GOTCHA**: A fit gauge must be exported **nominal** — printing a compensated gauge measures the
  compensation, not the printer, which defeats the Phase 3 workflow it exists for. Say so in the
  docstring and default `calibration=None`.
- **VALIDATE**: `uv run pytest tests/test_coupon.py -v` — asserting the S11 numbers: five bores
  measured within **0.0016 mm** of nominal through `features.extract` + `measure`

### 11. CREATE `benchmarks/imported-mesh/model.py`, `params.json`, `intent.json`

- **IMPLEMENT**: Mesh-native benchmark per ADR-12.
  - `params.json`: `PLATE_X/Y/T`, `HOLE_D` (role `hole`), `HOLE_X` — mirroring conftest's `PLATE`
    (60×40×10, Ø8 at x=±21, true min wall 5.0 mm) — plus `BREAK_FACES` (count) and `FLIP_FACES`
    (count) as `neutral` params so mutations can vary the damage, **plus `PIN_D` (role `outer`,
    default 3.0) and `PIN_H`**: a small pin standing on the plate that `intent.json` deliberately
    makes **no dimensional claim about**. See Task 14 — it is the only feature on any benchmark
    that solely the DFM engine constrains, which is what makes a DFM mutation scoreable.
  - `model.py`: `load_params()` + `build(p, repair_it=True, overhang=False)`. Builds the plate and
    the pin with build123d, tessellates via `features._tessellate`, breaks it deterministically,
    then — when `repair_it=True` — runs `repair.repair()` and returns the repaired
    `trimesh.Trimesh`. `repair_it=False` is a real option and is what the `skipped_repair` mutation
    exercises; `overhang=True` adds an unsupported ledge and is what `dfm_unprintable_overhang`
    exercises.
  - `intent.json`: `watertight == 1`; both Ø8 holes at (±21, 0) via `cylinder_diameter`
    `[7.9, 8.1]`; `feature_count` in the Ø7.9–8.1 band `== 2`; `plate_thickness` via `plane_gap`;
    `bbox_x` 60; and `dfm_blockers == 0` via `dfm_violation_count`.
- **PATTERN**: `benchmarks/gyroid-vase/model.py` (mesh-native, no STEP);
  `benchmarks/harness.py`:44-69
- **GOTCHA**: `build_and_export` (run_mutations.py:132) already routes a `trimesh.Trimesh` to
  mesh-only export — do not add a STEP. Keep the break deterministic (fixed indices), or the
  benchmark's own baseline becomes flaky and `run_part`'s baseline gate (:208-213) will fail
  intermittently, which reads as a harness error.
- **VALIDATE**: `uv run python benchmarks/imported-mesh/model.py --check --source stl`

### 12. CREATE `benchmarks/imported-mesh/mutations/` — 5 mutations

- **IMPLEMENT**:

  | File | Mechanism | `EXPECT` | Why |
  |---|---|---|---|
  | `skipped_repair.py` | `BUILD_OPTIONS = {"repair_it": False}` | **FAIL** | a non-watertight mesh must not pass |
  | `bridged_bore.py` | `patch()` removes faces **inside a bore wall** before repair | **FAIL** | `fill_holes` fans it shut; the Ø8 assertion catches a dimension the repair destroyed |
  | `lost_hole.py` | `patch()` repairs so aggressively a hole vanishes | **FAIL** | `feature_count` = 1, absent feature IS the defect |
  | `inverted_only.py` | `PARAMS_OVERRIDE = {"FLIP_FACES": <all>}`, repair on | **FAIL** if unrepaired inversion survives | guards `fix_winding`/`fix_inversion` ordering |
  | `cosmetic_more_facets.py` | tessellation tolerance tightened (more triangles, same geometry) | **PASS** | **the false-positive detector** — a verifier that fails this cries wolf on every remesh |
- **PATTERN**: `benchmarks/bearing-holder/mutations/dropped_cbore.py` (structural, `BUILD_OPTIONS`)
  and `.../cosmetic_fillet.py` (the PASS case). Protocol table:
  `benchmarks/bearing-holder/mutations/README.md`
- **GOTCHA**: Every mutation needs `EXPECT` **and** `REASON`. `SOURCE` defaults to `"stl"`, which is
  right here — there is no STEP. A mutation whose `PARAMS_OVERRIDE` names an unknown key is a
  harness error by design (`run_mutations.py`:99-104), not a silent no-op.
- **VALIDATE**: `uv run python benchmarks/run_mutations.py --part imported-mesh -v`

### 13. CREATE `benchmarks/imported-mesh/mutations/README.md`

- **IMPLEMENT**: Explain, in the register of the bearing-holder README: why a repair benchmark needs
  a *dimensional* assertion and not just `watertight` (a bridged bore is watertight); why
  `cosmetic_more_facets` expects PASS; and the ADR-12 reason the broken mesh is generated rather
  than committed.
- **PATTERN**: `benchmarks/bearing-holder/mutations/README.md`
- **VALIDATE**: `uv run ruff format --check .` (Markdown is excluded; this just proves nothing else
  broke) plus a human read

### 14. CREATE `benchmarks/imported-mesh/mutations/dfm_*.py` — 3 DFM mutations

- **IMPLEMENT**: With `EXTRA_ASSERTS` carrying the `dfm_violation_count` assertion, so the *part's*
  design intent is not permanently coupled to DFM policy:
  - `dfm_thin_pin.py` — `PARAMS_OVERRIDE = {"PIN_D": 0.5}`, below `min_feature_mm` → **FAIL**
  - `dfm_unprintable_overhang.py` — `BUILD_OPTIONS = {"overhang": True}` adds an unsupported ledge
    past `max_overhang_deg` → **FAIL**
  - `cosmetic_dfm_note.py` — a change producing a NOTE/WARNING but no BLOCKER (e.g. `PIN_D` 3.0 →
    2.6, still above the threshold) → **PASS**, the DFM false-positive detector
- **PATTERN**: `benchmarks/overhang-test/mutations/steep_flare.py` (params override) and
  `.../cosmetic_stem.py` (the PASS case); `EXTRA_ASSERTS` as documented in the mutation README
- **GOTCHA**: **These belong on `imported-mesh`, not on `overhang-test`.** Every dimension of
  `overhang-test` is already asserted by its own `intent.json` (`max_overhang_deg`, `stem_diameter`,
  `flare_width`, `unsupported_area`), so any parameter change there fails a *dimensional* assertion
  and the run tells you nothing about whether the DFM engine works — it would be caught with `dfm.py`
  deleted. `PIN_D` exists precisely because nothing else constrains it. Verify that isolation by
  checking the mutation's report: the failing assertion must be the `dfm_*` one.
  Note also that `overhang-test` has **no `STEM_D` parameter** — its stem is `BOTTOM_R` (radius 2.0).
  Second gotcha: `run_mutations.py`:208-213 requires the **baseline** to pass with the extra
  assertions applied, so confirm the unmutated part reports zero BLOCKERs in PLA before writing them.
- **VALIDATE**: `uv run python benchmarks/run_mutations.py --part imported-mesh -v` — and read the
  report: each `dfm_*` mutation must fail on the `dfm_blockers` line, not on a dimensional one

### 15. CREATE `.claude/skills/lril3d-dfm/SKILL.md`

- **IMPLEMENT**: Frontmatter `name`/`description` in the existing voice. Body: how to call
  `dfm.evaluate`, how to read a `DfmReport`, **the rule that a BLOCKER is a blocker** (do not
  downgrade one in prose), that thresholds come from `profiles/dfm-rules.json` with a source and are
  changed *there* with a reason, and the banned-language list from `lril3d-inspect`.
- **PATTERN**: `.claude/skills/lril3d-inspect/SKILL.md` — same length, same section shape, same
  "Non-negotiable" close
- **GOTCHA**: **No thresholds in this file.** A number in a SKILL.md is a number outside the config
  and outside the tests; it will drift and it cannot be validated.
- **VALIDATE**: `uv run python -c "import pathlib,re;t=pathlib.Path('.claude/skills/lril3d-dfm/SKILL.md').read_text(encoding='utf-8');assert t.startswith('---');assert 'name:' in t and 'description:' in t;print('frontmatter OK',len(t.splitlines()),'lines')"`

### 16. CREATE `.claude/skills/lril3d-repair/SKILL.md`

- **IMPLEMENT**: import → diagnose → fix → **verify**, with the ADR-9 contract stated plainly: a
  repair that changes a Tier 1 dimension is a failed repair; report both numbers. Include the
  license-provenance requirement from PRD §9 ("license provenance recorded on any imported
  third-party model") — an imported model needs its source and license recorded before it is worked
  on.
- **PATTERN**: `.claude/skills/lril3d-inspect/SKILL.md`
- **GOTCHA**: State explicitly that "it is watertight now" is **not** a repair verdict — a bridged
  bore is watertight.
- **VALIDATE**: same frontmatter check as Task 15

### 17. UPDATE `.claude/skills/lril3d-inspect/SKILL.md` — hand off to the new skills

- **IMPLEMENT**: In §3 (Printability), replace the thin-slice framing with a handoff: `printability`
  remains the measurement, `lril3d-dfm` is the verdict. Add a line pointing an imported mesh at
  `lril3d-repair` **before** inspection.
- **PATTERN**: the existing "Then hand off" section in `lril3d-model/SKILL.md`:103-106
- **GOTCHA**: Keep the file thin. Do not move any DFM rule text into it.
- **VALIDATE**: `git diff --stat .claude/skills/` shows only the intended file changed

### 18. RUN the 2A gate

- **IMPLEMENT**: Nothing new — this is a checkpoint.
- **VALIDATE**:
  ```bash
  uv run ruff check . && uv run ruff format --check .
  uv run pytest -q
  uv run python benchmarks/run_mutations.py
  ```
  Expected: **≥ 27 mutations**, `missed 0  false-positives 0  harness-errors 0`. Do not start 2B on
  a red 2A.

---

## MILESTONE 2B — SLICING, AMS AND PREVIEW

### 19. CREATE `profiles/slicer.json`

- **IMPLEMENT**:
  ```json
  {
    "backend": "bambu-studio",
    "executable_candidates": [
      "C:/Program Files/Bambu Studio/bambu-studio.exe",
      "C:/Program Files/OrcaSlicer/orca-slicer.exe"
    ],
    "profile_root": "C:/Program Files/Bambu Studio/resources/profiles/BBL",
    "presets": {
      "machine": "Bambu Lab P1S 0.4 nozzle",
      "process": "0.20mm Standard @BBL X1C",
      "filament": {"PLA": "Bambu PLA Basic @BBL P1S 0.4 nozzle"}
    },
    "timeout_s": 300,
    "source": "measured on this machine 2026-07-31; Bambu Studio 02.07.01.62"
  }
  ```
  Env override `THREEDP_SLICER` (executable) and `THREEDP_SLICER_PROFILES` (profile root) take
  precedence.
- **PATTERN**: `compensate.py`:68-89 (`profiles_dir()` with a `THREEDP_PROFILES` env override that
  **raises** when set to a non-directory rather than silently falling back)
- **GOTCHA**: The process preset really is named `@BBL X1C` for a P1S — the P1S machine profile's
  own `default_print_profile` says so, and `compatible_printers` lists P1S 0.4. Do not "fix" it to
  `@BBL P1S`; that file does not exist and the slice will fail with rc −17.
- **VALIDATE**: `uv run python -c "import json;d=json.load(open('profiles/slicer.json'));print(d['backend'],d['presets']['machine'])"`

### 20. CREATE `tests/test_slicer.py` — **WRITE THIS BEFORE `slicer.py`**

- **IMPLEMENT**: Two layers.
  - **No-slicer-needed tests (always run):** preset flattening produces `filament_density` 1.26 from
    the four-file chain and **keeps the original `name`** (S3/S4); the ADR-10 acceptance gate
    rejects each of four crafted `result.json` fixtures — `return_code 0` with **no `sliced_plates`**
    (S6), `return_code 0` with `total_used_g == 0` (S3), `return_code -13` with a G-code file present
    (S5), and a missing `result.json`; discovery raises `SlicerNotFound` with the candidate list when
    nothing is installed; `ams_mapping` reverse-index semantics; `purge_waste` arithmetic on the S8
    matrix.
  - **`@pytest.mark.slicer` tests:** a real slice of `build_plate()` returns `weight_g > 0`,
    `density > 0`, non-empty `sliced_plates`, and a G-code file, in under the configured timeout.
- **PATTERN**: `tests/test_io.py` (export/roundtrip through tmp paths)
- **GOTCHA**: The fake `result.json` fixtures are the highest-value tests in this file — they encode
  three measured ways the slicer lies. Write them from the spike numbers, not from imagination.
  Skip cleanly (not fail) when no slicer is installed.
- **VALIDATE**: `uv run pytest tests/test_slicer.py -v -m "not slicer"` (expected: all fail — no module yet)

### 21. CREATE `src/threedp/slicer.py`

- **IMPLEMENT**:
  ```python
  class SlicerError(Exception): ...
  class SlicerNotFound(SlicerError): ...
  class SliceRejected(SlicerError): ...      # the ADR-10 gate said no

  @dataclass(frozen=True)
  class SliceResult:
      gcode: Path; result_json: Path; plate: int
      time_s: float; weight_g: float; density: float
      filament_id: str; changes: int
      warnings: str; material: str
      @property
      def time_hm(self) -> str: ...
      def __str__(self) -> str: ...

  def find_slicer(config=None) -> Path: ...
  def flatten_preset(kind: str, name: str, root: Path) -> dict: ...
  def slice_part(path, material="PLA", plate=0, outdir=None, config=None,
                 export_3mf: str | None = None) -> SliceResult: ...
  ```
  Flattening — transcribed from the spike script that produced 10.85 g:
  ```python
  def flatten_preset(kind, name, root):
      """Resolve a Bambu preset's `inherits` chain into one self-contained config.

      Measured 2026-07-31: the CLI does NOT walk `inherits`. The leaf PLA preset carries 23 keys
      and no `filament_density`; the value 1.26 lives two files up and `fdm_filament_common`'s 0
      is what ships. Unflattened => `; total filament weight [g] : 0.00`.
      """
      base, chain, cur = root / kind, [], name
      while cur:
          fp = base / f"{cur}.json"
          if not fp.exists():
              raise SlicerError(f"preset {cur!r} not found under {base}")
          d = json.loads(fp.read_text(encoding="utf-8"))
          chain.append(d)
          cur = d.get("inherits")
      merged = {}
      for d in reversed(chain):        # root first; child overrides parent
          merged.update(d)
      merged.pop("inherits", None)
      merged["name"] = name            # ADR/S4: renaming breaks compatible_printers => rc -17
      return merged
  ```
  Invocation: write the three flattened configs to a temp dir, then
  ```python
  subprocess.run([exe, "--load-settings", f"{machine};{process}",
                  "--load-filaments", str(filament),
                  "--slice", str(plate), "--outputdir", str(outdir), str(path)],
                 cwd=outdir, timeout=config["timeout_s"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
  ```
  then apply the four ADR-10 conditions and raise `SliceRejected` naming which one failed.
- **PATTERN**: `io.py`:87-88 ("reported success but wrote no file"); `features.py`:63-74 (refusal
  over a flattering default)
- **IMPORTS**: `json`, `os`, `subprocess`, `tempfile`, `shutil`, `pathlib`; **no new packages**
- **GOTCHA**: (a) **Never** read stdout — it is empty on every run (S1); (b) `--export-3mf` needs a
  **relative** filename with `cwd` set, or rc −13 (S5); (c) the separator in `--load-settings` is a
  semicolon, and on Windows paths contain colons but not semicolons, so quoting is safe; (d) do not
  reach for `--mstpp` — undocumented and unspiked; use the `subprocess` timeout.
- **VALIDATE**: `uv run pytest tests/test_slicer.py -v` then, on this machine,
  `uv run pytest tests/test_slicer.py -v -m slicer`

### 22. ADD AMS mapping and purge estimation to `src/threedp/slicer.py`

- **IMPLEMENT**:
  ```python
  def ams_mapping(used_filaments, inventory=None) -> list[int]:
      """Bambu's `ams_mapping` is REVERSE-INDEXED (PRD 9): array POSITION is the filament index
      inside the 3MF, array VALUE is the AMS slot 0-3. Getting it backwards prints in the wrong
      colours and looks like a slicing bug.
      """

  def purge_waste(flush_matrix, sequence, multiplier=1.0, density=None) -> tuple[float, float]:
      """(mm3, grams). Measured matrix on this machine: 4x4, all off-diagonal entries 280 mm3."""
  ```
  `inventory` defaults to `profiles/filaments.json`.
- **PATTERN**: `compensate.py`:110-124 (`_as_record` — normalise the several shapes a caller may
  pass, and raise on anything else)
- **GOTCHA**: `profiles/filaments.json` has **five** slots and the fifth is
  `{"type": "external", "bay": null}`. `slot` is not `bay`, and an external spool has no AMS slot at
  all — mapping to it must raise, not emit `null` or coerce to 4. Grams need a density; with none,
  **return `None` for grams rather than 0.0** (S3's lesson, applied to purge).
- **VALIDATE**: `uv run pytest tests/test_slicer.py -k "ams or purge" -v`

### 23. CREATE `src/threedp/gcode.py` + `tests/fixtures/plate_1_excerpt.gcode`

- **IMPLEMENT**:
  ```python
  BAMBU_FEATURE = re.compile(r"^; FEATURE:\s*(.+)$")      # NOT ";TYPE:" - see S9
  BAMBU_LAYER   = re.compile(r"^; CHANGE_LAYER")           # NOT ";LAYER_CHANGE"

  @dataclass(frozen=True)
  class GcodeMeta:
      generator: str; time_s: float; layers: int
      length_mm: float; volume_mm3: float; weight_g: float
      density: float; max_z: float; filaments: int

  def read_meta(path) -> GcodeMeta: ...
  def toolpaths(path, max_segments=200_000) -> dict: ...   # -> preview JSON
  def write_preview(gcode_path, out_path) -> Path: ...
  ```
  Preview JSON: `{"layers": [...z...], "features": [names], "segments": {"positions": [...],
  "layer": [...], "feature": [...]}}` — flat typed arrays, one `LineSegments` in the viewer.
- **PATTERN**: `render.py`'s module docstring style — state the trap the module exists to avoid
- **GOTCHA**: (a) S9's markers, with the leading space; (b) the header's `[cm^3]` label is **wrong**
  — the value is mm³ (S7): name the field `volume_mm3` and note the discrepancy so no one "fixes" it
  back; (c) do not trust `weight_g` from the header when `density == 0` — carry the density and let
  the caller refuse; (d) cap segments and **`log` what was dropped** — a truncated preview that
  looks complete is the viewer's version of a silent partial render (the bug fixed in `df6ed5f`).
- **VALIDATE**: `uv run pytest tests/test_gcode.py -v` — asserting on the committed excerpt: markers
  found, `weight_g == 10.85`, `density == 1.26`, `time_s == 1507` (25m 7s)

### 24. UPDATE `viewer/` — G-code preview mode

- **IMPLEMENT**: `viewer/src/gcode-preview.js` exporting `loadPreview(url)` → a `THREE.LineSegments`
  with per-feature vertex colours and a layer range; wire a "preview" toggle and a layer slider into
  `main.js` alongside the existing section slider. Add `part.preview.json` to `CANDIDATES` in
  `watch.mjs` so a re-slice hot-reloads.
- **PATTERN**: `viewer/src/main.js`:147-172 (`loadModel` — fetch, build, `setPart`, status line)
  and :121-127 (`fsUrl`)
- **GOTCHA**: (a) `vite.config.js`'s `server.fs.allow` is why files outside `viewer/` load; a
  preview written elsewhere 403s silently; (b) `watch.mjs`'s size-settling exists because exporters
  write in chunks — a JSON written by Python has the same problem; (c) state the truncation in the
  status line when segments were dropped, mirroring the `showing 1 of N bodies` fix at
  `main.js`:167; (d) the preview is a **channel, not a gate**.
- **VALIDATE**: `cd viewer && npm install && npx vite build` (exit 0), then manual: slice a benchmark,
  `npm run dev -- --model ../benchmarks/l-bracket/out`, confirm the preview draws and the layer
  slider moves

### 25. CREATE `.claude/skills/lril3d-slice/SKILL.md`

- **IMPLEMENT**: How to slice, how to read a `SliceResult`, and — prominently — **what the wrapper
  refuses and why**: a `0.00 g` result is a rejected slice, not a light part. Document the C2
  thumbnail limitation (CLI G-code has no thumbnail, so the P1S screen preview is blank). State that
  nothing here sends to a printer and that `--export-3mf` output is for **manual** transfer.
- **PATTERN**: `.claude/skills/lril3d-viewer/SKILL.md` (short, operational, with a "when it does not
  work" section)
- **GOTCHA**: Do not put preset names or thresholds in this file — they live in
  `profiles/slicer.json`.
- **VALIDATE**: frontmatter check as in Task 15

### 26. UPDATE `.claude/skills/lril3d-viewer/SKILL.md`

- **IMPLEMENT**: Document the preview toggle, the layer slider, and that the preview reflects the
  **last slice**, not the current model, if the two have diverged.
- **VALIDATE**: `git diff --stat .claude/skills/`

### 27. CREATE `tests/test_no_printer_path.py`

- **IMPLEMENT**: Scan `src/threedp/*.py` (reuse the token-stripping scanner from
  `tests/test_one_ruler.py`:64-98 — import it, do not copy it) and fail on any import of `ftplib`,
  `socket`, `paho`, `requests`, `httpx`, `urllib.request`, or any `subprocess` call whose executable
  is not the discovered slicer. Assert `.claude/settings.json` still carries all six printer-send
  `deny` entries and that `.claude/settings.local.json` is **not** where they live.
- **PATTERN**: `tests/test_one_ruler.py` in full — same "a rule with no enforcement decays" reasoning
- **GOTCHA**: Include the skipped-layer guard: assert the walk found ≥ 8 files, or a broken glob
  passes everything.
- **VALIDATE**: `uv run pytest tests/test_no_printer_path.py -v`

### 28. UPDATE `CLAUDE.md` and `README.md`

- **IMPLEMENT**: In `CLAUDE.md`: move Phase 2 items from "Phase boundaries" into the implemented
  set; add the Phase 2 environment gotchas to that section (S1 empty stdout, S3 flattening, S4 name
  preservation, S5 relative `--export-3mf`, S6 `rc 0` with no plates, S7 the wrong `cm^3` label, S9
  the `; FEATURE:` markers); add `dfm`/`repair`/`slicer`/`gcode`/`coupon` to the public import line;
  update the mutation pass signal to the new counts. In `README.md`: add the slicer prerequisite and
  the `-m "not slicer"` note.
- **PATTERN**: `CLAUDE.md`'s existing "Environment gotchas (measured on this machine)" section —
  each entry states the trap **and** what it costs
- **GOTCHA**: Link to `PRD.md` sections; do not copy PRD text. Do not restate thresholds.
- **VALIDATE**: `uv run python -c "import sys; assert sys.version_info[:2]==(3,13); from threedp import measure, features, intent, render, compensate, parts, io, printability, dfm, repair, slicer, gcode, coupon; print('OK', sys.version)"`

### 29. RUN the full Phase 2 gate

- **VALIDATE**: every command in [VALIDATION COMMANDS](#validation-commands), in order, from the repo
  root.

---

## TESTING STRATEGY

### Unit Tests

`pytest`, files mirroring modules (`tests/test_<module>.py`), fixtures in `tests/conftest.py`, and
assertions against **analytically known geometry** — the existing standard. Reuse
`build_canonical`, `build_plate`, `build_overhang_cone`, `build_square_pocket`,
`build_interrupted_bore`. New shared fixtures go in `conftest.py`, never duplicated per file.

Coverage expectations per module: `dfm.py` — every rule fires and every rule can *not* fire;
`repair.py` — every break type in S10 plus the bridged-bore case; `slicer.py` — every ADR-10
rejection path; `gcode.py` — every marker and the density-zero refusal; `coupon.py` — the S11
numbers.

### Integration Tests

- **BREP ↔ mesh cross-check** stays as it is (`run_mutations.py`:140-163) — unchanged by this phase.
- **`imported-mesh` benchmark end-to-end**: build → break → repair → export → extract → check.
- **Real-slicer tests** behind `@pytest.mark.slicer`: `uv run pytest -m slicer`. These are the layer
  that must actually run on this machine — a green suite with the slicer layer skipped is **not**
  evidence the wrapper works. Task 29 requires reporting how many `slicer`-marked tests executed and
  that **zero were skipped** on this machine.
- **The mutation suite** is the real gate and grows from 19 to ≥ 27.

### Edge Cases

Must be tested explicitly:

1. Slicer not installed → `SlicerNotFound` naming the candidates (and `-m "not slicer"` still green).
2. `return_code 0` with no `sliced_plates` (S6) → `SliceRejected`.
3. `return_code -13` with a valid G-code file present (S5) → `SliceRejected`.
4. Unflattened preset → `density == 0` → `SliceRejected` with the flattening fix named.
5. Renamed preset → rc −17 → error surfaced verbatim, not swallowed.
6. Slice exceeding `timeout_s` → `SlicerError`, temp dir cleaned up.
7. Repair that bridges a bore → `RepairResult.passed` False with both diameters.
8. Repair on a mesh too broken to section → `UNVERIFIABLE`, never PASS.
9. Inverted mesh → negative volume caught by `diagnose` as *inversion*, not reported as a volume.
10. DFM rules file with an uncited threshold → raises at load.
11. Unknown DFM material → raises with the valid list.
12. AMS mapping to an `external` spool slot → raises.
13. Purge with no density → grams is `None`, never `0.0`.
14. G-code with PrusaSlicer-style markers only → parser reports **zero** features and says so rather
    than silently drawing nothing.
15. Preview truncated at `max_segments` → the count dropped is reported.

---

<a id="validation-commands"></a>
## VALIDATION COMMANDS

Every command runs from the repo root. Each states its pass signal.

### Level 1: Syntax & Style

```bash
uv run ruff check .                # pass: "All checks passed!", exit 0
uv run ruff format --check .       # pass: exit 0, no files would be reformatted
```

### Level 2: Root import + interpreter gate

```bash
uv run python -c "import sys; assert sys.version_info[:2]==(3,13), sys.version; from threedp import measure, features, intent, render, compensate, parts, io, printability, dfm, repair, slicer, gcode, coupon; print('OK', sys.version)"
# pass: prints "OK 3.13.x"
```

### Level 3: Unit Tests

```bash
uv run pytest -q                   # pass: 0 failed; expect >= 240 passed (184 baseline + new)
uv run pytest -m slicer -v         # pass: N tests, 0 skipped, 0 failed  <- MUST actually run here
uv run pytest -m "not slicer" -q   # pass: green on a machine with no slicer
```

**The `-m slicer` line is a gate, not a formality.** Report the executed count. A run where those
tests skipped is a run where the slicer wrapper was never exercised.

### Level 4: The real gate — the mutation suite

```bash
uv run python benchmarks/run_mutations.py
# pass: missed 0   false-positives 0   harness-errors 0   VERDICT: PASS
# pass: >= 27 mutations across 6 benchmarks   (baseline was 19 across 5)
# ZERO mutations found is a FAILURE, not a pass.

uv run python benchmarks/run_mutations.py --part imported-mesh -v
# pass: 8 mutations (5 repair + 3 DFM), all caught / no false positive.
# Read the -v report: each dfm_* mutation must fail on its `dfm_blockers` line. A dfm_* mutation
# that fails on a dimensional assertion is not scoring the DFM engine (Task 14).
```

### Level 5: Manual Validation — record the outcome next to each box

Phase 1's execution report ended with three unverified manual steps because the plan gave them
nowhere to record a result. Each box below has an evidence field; fill it in or state plainly that
it was not done.

- [ ] **Real slice of a benchmark part** —
      `uv run python -c "from threedp import slicer; print(slicer.slice_part('benchmarks/l-bracket/out/part.stl', material='PLA'))"`
      Evidence (weight_g / time / gcode path): ______________________
- [ ] **Sliced 3MF export** produces a non-empty `.3mf` (relative-path form).
      Evidence (bytes): ______________________
- [ ] **G-code preview in the viewer** draws, the layer slider works, camera survives a re-slice.
      Evidence: ______________________
- [ ] **`lril3d-dfm` end-to-end**: the skill reports a BLOCKER on a deliberately thin part and does
      **not** downgrade it in prose. Evidence (transcript line): ______________________
- [ ] **`lril3d-repair` end-to-end** on a real third-party STL, with license provenance recorded.
      Evidence: ______________________
- [ ] **Print gate untouched**: `git diff master -- .claude/settings.json` is empty.
      Evidence: ______________________

### Level 6: Additional Validation (Optional)

```bash
cd viewer && npm install && npx vite build     # pass: exit 0, dist/ written
```

---

## ACCEPTANCE CRITERIA

- [ ] `dfm.evaluate` returns findings that each carry a measured value, a threshold, **and** the
      source string from `profiles/dfm-rules.json`
- [ ] Every DFM threshold in the repo lives in `profiles/dfm-rules.json` with a `source`; none in
      Python, none in a `SKILL.md`
- [ ] `repair()` never returns a mesh without a verification verdict; a Tier 1 dimension moving more
      than 0.01 mm is a FAIL naming both values
- [ ] A repair that cannot be verified reports `UNVERIFIABLE`, never PASS
- [ ] `slicer.slice_part` rejects all four measured failure shapes (S3, S5, S6, missing result.json)
- [ ] A `0.00 g` slice result is impossible to obtain from `SliceResult`
- [ ] `ams_mapping` implements the reverse index and is tested against PRD §9's semantics
- [ ] `gcode.read_meta` parses `; FEATURE:` / `; CHANGE_LAYER` and names volume `volume_mm3`
- [ ] The viewer preview loads and states any truncation
- [ ] Mutation suite: **≥ 27 mutations, missed 0, false-positives 0, harness-errors 0**
- [ ] At least one `cosmetic_*` false-positive detector exists for **each** new benchmark area
      (repair, DFM)
- [ ] `tests/test_one_ruler.py` passes with the five new module names asserted
- [ ] `tests/test_no_printer_path.py` passes; `.claude/settings.json` unchanged from `master`
- [ ] `uv run pytest -m slicer` executed on this machine with **0 skipped**
- [ ] Full suite green: `ruff` clean, `pytest` 0 failed, import gate OK
- [ ] `CLAUDE.md` and `README.md` updated; no PRD text copied
- [ ] Three new `SKILL.md` files, each thin — no geometry, no measurement, no thresholds

---

## COMPLETION CHECKLIST

- [ ] All 29 tasks completed in order
- [ ] Each task's `VALIDATE` command run immediately, not batched to the end
- [ ] Milestone 2A gate (Task 18) was green before 2B started
- [ ] All validation commands executed successfully from the repo root
- [ ] Full test suite passes, including `-m slicer` with zero skips
- [ ] Mutation suite green with the new count reported
- [ ] No linting errors
- [ ] Manual validation boxes filled in with evidence — or explicitly marked not done
- [ ] Acceptance criteria all met
- [ ] Code reviewed for quality and maintainability

---

## NOTES

**Why the slicer wrapper gets four acceptance conditions and not one.** Every project accumulates a
function that returns a plausible number when it should have raised. This one was measured doing it
in three different ways within twenty minutes: `return_code 0` on a slice of nothing, `return_code
-13` on a slice that worked, and `0.00 g` on a slice that was entirely correct except for a config
detail nobody would notice. The four conditions are not defensive programming; they are three
observed failures plus the one that would obviously follow.

**Why DFM verdicts route through `intent.json` instead of a new scoring path.** The mutation harness
already refuses to score against a broken baseline (`run_mutations.py`:208-213). That property is
worth more than the convenience of a bespoke DFM scorer, and it is not free to reimplement. Routing
DFM through a measure kind means the DFM engine is scored by the same machinery, in the same report,
with the same false-positive detectors.

**The trade-off accepted in ADR-8.** DFM findings only gate where a benchmark asserts on them, so a
part with no `dfm_violation_count` assertion can carry BLOCKERs and still PASS its intent. That is
deliberate: DFM is advice about a *process*, intent is a claim about a *part*, and collapsing the two
would mean a part that is dimensionally perfect fails its intent because the user chose to print it
without supports.

**What this phase does not fix.** Z-only mesh probing still means angled features refuse Tier 1, and
the repair pipeline inherits that limitation — a repaired angled bore is unverifiable, and
`RepairResult` will say so rather than guess. Imported meshes still have no parametrization, so
compensation for them remains a uniform geometric offset and press fits on them remain unsupported
(`CLAUDE.md`, "Known accepted gaps"). Neither is weakened here.

**Bambu Studio version pinning.** `profiles/slicer.json` records the measured version in its
`source` field. The CLI surface is stable across the 2.x line but the *profile tree* moves — a
Bambu Studio update can rename a process preset. Task 21's `flatten_preset` raises with the
searched path when a preset is missing, which turns that into a clear error instead of a mystery
rc −17.

**Runtime.** `run_mutations.py` currently takes ~20 minutes, dominated by the gyroid vase's SDF
rebuilds. The new benchmark is mesh-native and cheap; a full slice is 0.92 s. Expect the suite to
stay in the same ballpark.

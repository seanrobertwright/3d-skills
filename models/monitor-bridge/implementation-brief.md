Everything needed is in hand; the probe settled the last open question with measured numbers. Here is the brief.

# Implementation brief: `models/monitor-bridge/`

Target: `models/monitor-bridge/{intent.json, params.json, model.py}` for a two-monitor connector — a mostly planar bridge/clip with slots, pockets and bores — then inspect, DFM and render it. Written against the working tree of `D:\repos\3d-skills` on 2026-09-10 (branch `slice-artifacts-are-enforced`, build123d 0.11.1, trimesh 4.12.2, Python 3.13.15). Every signature below is quoted verbatim from the source.

## 0. State of the tree you will be working in (read before anything else)

- `git status` shows **uncommitted** edits to `src/threedp/measure.py`, `printability.py`, `dfm.py` and four test files, and `models/` is entirely **untracked** (`models/wrx-badge/` included). Those library edits are the three ruler fixes the wrx-badge forced and this part depends on all three:
  1. `measure.plane_transitions` now bisects on section **ring count** as well as area — without it a small blind hole (0.2 % of a plate's section area) is invisible on the mesh path.
  2. `printability.min_wall` discards **grazing exits** (`GRAZING_EXIT_COS = 0.5`) — without it a corner between a tilted top and a side wall reads as a 0.003 mm wall and fires two BLOCKERs.
  3. `printability.overhang_histogram(..., bridging_span_mm=...)` and `dfm.evaluate` exclude ceilings narrower than the material's `max_bridge_mm` from the overhang rule — without it any hole ceiling is a 90° BLOCKER in every material.
  Do not revert them; do not assume they are on `master`. If you branch, branch from this tree or land them first.
- **First `uv run python -c "import build123d"` in this session exceeded the 120 s tool timeout** (cold import of OCP). Run every `uv run` command with a timeout of at least 300 000 ms, or in the background.
- The PR rule from CLAUDE.md "Shipping a slice" applies to this slice: `.agents/code-reviews/<branch>.md` and `.agents/execution-reports/<branch>.md` must exist before the PR opens; CI's `slice artifacts` job fails without them.

## 1. Exact API: signatures and import lines

### Parts database (citations)

```python
from threedp import parts
def get(category: str, key: str) -> dict[str, Any]:            # raises KeyError; never guesses
def citation(key: str, field: str) -> str:                     # -> "parts-db:<key>.<field>"
def resolve_citation(source: str) -> float:
```

What exists, verbatim from `src/threedp/parts.py`:

- `screw`: `M2 M2.5 M3 M4 M5 M6 M8`, fields `clearance tap head_d head_h nut_af nut_h`. `M4 = {"clearance": 4.5, "tap": 3.3, "head_d": 7.0, "head_h": 4.0, "nut_af": 7.0, "nut_h": 3.2}`, `M3 = {"clearance": 3.4, "tap": 2.5, "head_d": 5.5, "head_h": 3.0, "nut_af": 5.5, "nut_h": 2.4}`.
- `heatset`: `M2-insert M3-insert M4-insert M5-insert`, fields `od length hole_d min_boss_od` (`M4-insert.hole_d = 5.0`, `min_boss_od = 9.0`).
- `bearing`, `magnet`, `pattern` (`raspberry-pi-4`, `raspberry-pi-zero`, `nema17`, `fan-80`, `fan-40`).
- **There is no VESA entry** (no `vesa-75`, `vesa-100`). A monitor mount's hole spacing is therefore either `user-confirmed` (ask, and record the number the user gives) or a new `_PATTERNS` entry in `parts.py` with a `source` and a test — never a number typed from memory into `intent.json` with a `parts-db:` prefix, because `intent._check_citation` resolves every `parts-db:` source and an unknown key prints an `unresolvable citation` line.

### Parameters and compensation

```python
from threedp.compensate import Resolved, resolve
def resolve(params: dict[str, Any], calibration: Any = None) -> Resolved:
```

`params` is the raw `params.json` mapping, every entry shaped `{"value": <number>, "role": "hole"|"outer"|"neutral", ...}` (extra keys such as `"note"` are ignored; `wrx-badge/params.json` carries one on every line). A bare number, a missing `value`, or a role outside `ROLES = ("hole", "outer", "neutral")` raises `CompensationError`. `resolve(params, None)` returns the values byte-identical; `resolve(params, "PLA_generic")` adds `hole_delta_mm` to every `hole` and `outer_delta_mm` to every `outer` (`profiles/calibration.json`: PLA `+0.18 / -0.05`, PETG `+0.25 / -0.08`, ABS `+0.22 / -0.10`; all three `"measured": null`, so every compensated export warns). **`Resolved` is a `dict[str, float]`** — `build(p)` receives floats, not the tagged records, so `build(load_params())` is wrong; it is `build(resolve(load_params(), None))`.

### Export

```python
from threedp import io
def export(
    part: Any | Callable[[dict[str, float]], Any],
    stem: str | Path,
    nominal: Sequence[str] = ("step",),
    compensated: Sequence[str] = ("stl", "3mf"),
    calibration: Any = None,
    params: dict[str, Any] | None = None,
) -> ExportResult:
```

Pass the **builder** (`build`) plus `params`; `export` calls `part(resolve(params, None))` for the STEP and `part(resolve(params, calibration))` for the meshes — two builds, never an offset. `calibration=None` makes the meshes nominal too (that is what you check `intent.json` against). Files land at `stem.with_suffix(".step"/".stl"/".3mf")`, so `stem` must have no dot in its last component. `ExportResult.__str__` prints the paths and the staleness warning; the warning is also raised as `CalibrationStaleWarning`.

### Feature extraction

```python
from threedp import features
def extract(path: str | Path) -> FeatureSet:              # .step/.stp -> BREP; .stl/.3mf/.obj/.ply -> mesh
def from_shape(shape, source: str = "<shape>") -> FeatureSet:   # straight from a build123d shape, no disk
```

`FeatureSet` fields: `source, representation ("brep"|"mesh"), cylinders, planes, bbox, volume, watertight, noncircular, tapered, mesh` and selection helpers `cylinders_at(x, y, tol=0.5)` (largest radius first), `select_cylinder(x, y, rank="largest", tol=0.5)`, `horizontal_planes()`, `bbox_size`. `fs.mesh` is populated on **both** paths (BREP is tessellated at 0.01), so `printability`/`dfm` run on either.

### Intent

```python
from threedp import intent
def load(path: str | Path | dict[str, Any]) -> Intent:
def check(features: FeatureSet, intent: str | Path | dict[str, Any] | Intent) -> Report:
```

`Report.passed` is `not self.failures and any(r.gating for r in self.results)` — a file with only Tier 2 assertions can never pass. `print(report)` is the deliverable; do not paraphrase it.

### Printability (numbers only)

```python
from threedp import printability
def min_wall(mesh: trimesh.Trimesh, samples: int = 2000, threshold_mm: float = DEFAULT_MIN_WALL_MM, seed: int = 20260730) -> WallReport:
def min_feature_size(mesh: trimesh.Trimesh, samples: int = DEFAULT_FEATURE_SAMPLES, threshold_mm: float = DEFAULT_MIN_WALL_MM) -> WallReport:   # same ray cast, 6000 samples
def overhang_histogram(mesh: trimesh.Trimesh, threshold_deg: float = DEFAULT_OVERHANG_THRESHOLD_DEG, bridging_span_mm: float | None = None) -> OverhangReport:
def bridge_spans(mesh: trimesh.Trimesh, threshold_mm: float = DEFAULT_MAX_BRIDGE_MM, angle_deg: float = BRIDGE_ANGLE_DEG) -> BridgeReport:
def footprint(mesh: trimesh.Trimesh, min_area_mm2: float = DEFAULT_MIN_FOOTPRINT_MM2, max_aspect_ratio: float = DEFAULT_MAX_ASPECT_RATIO) -> FootprintReport:
def bore_diameters(mesh: trimesh.Trimesh, threshold_mm: float = DEFAULT_MIN_BORE_D_MM) -> BoreReport:
```

### DFM (verdict)

```python
from threedp import dfm
def load_rules(material: str, path: str | Path | None = None) -> dict[str, dict[str, Any]]:
def evaluate(mesh: trimesh.Trimesh, material: str, rules_path: str | Path | None = None, part: str = "<mesh>") -> DfmReport:
```

Materials are `PLA_generic`, `PETG_generic`, `ABS_generic`. `DfmReport.passed` = no BLOCKER; `.count(severity)`, `.blockers`, `.warnings`, `.skipped`. Thresholds (`profiles/dfm-rules.json`): `min_wall_mm 0.8 BLOCKER`, `min_feature_mm 0.8 BLOCKER`, `min_hole_d_mm 2.0 BLOCKER`, `max_overhang_deg 45 BLOCKER` (PETG/ABS **40**), `max_bridge_mm 10 WARNING` (PETG **5**, ABS **6**), `min_footprint_mm2 100 WARNING` (ABS 400), `max_aspect_ratio 8 WARNING`, `warn_unsupported_mm2 50 WARNING at 30°`.

### Render (channel, never a gate)

```python
from threedp import render
def contact_sheet(
    path: str | Path,
    out: str | Path,
    views: tuple[str, ...] = VIEWS,          # VIEWS = ("iso", "top", "front", "right")
    projection: str = "parallel",
    scale_bar: bool = True,
    plate: str | None = "p1s",
    size: int = 640,
) -> ContactSheet:
```

`path` goes through `features.load_mesh` (trimesh), so pass the **STL/3MF**, not the STEP.

## 2. How `wrx-badge/model.py` is structured, and how it exports two parts

Contrast with the benchmark shape first. `benchmarks/bearing-holder/model.py` is **builder mode**: `with BuildPart() as part:` → `Box(..., align=bottom)`, `fillet(part.edges().filter_by(Axis.Z), radius=...)`, `Cylinder(radius, height, align=top, mode=Mode.SUBTRACT)` inside `with Locations(...)`, returns `part.part`; `build(p, counterbore: bool = True)` takes a keyword for a *structural* option a parameter cannot express; its `__main__` delegates to `benchmarks/harness.run_model_cli(HERE, build, load_params, __doc__)`, which needs the `sys.path` hack to `benchmarks/` — **do not import the harness from `models/`**; copy wrx-badge's `main()` instead.

`models/wrx-badge/model.py` is **algebra mode** and is the template for a `models/` part:

- `load_params()` returns `json.loads((HERE / "params.json").read_text(encoding="utf-8"))` — the raw tagged dict.
- `build(p)` imports build123d **inside the function** (`from build123d import Align, Cylinder, Ellipse, Location, Polygon, extrude`), reads `p["BADGE_X"]` etc. as floats, composes with operators: `body = extrude(Ellipse(a, b), amount=column) & _dome(...)`, `part = body + rim`, `part = part - Cylinder(d / 2, depth, align=bottom).move(Location((x, 0, 0)))`, returns the `Part`. Constants that are not dimensions of the part (`UPSAMPLE`, `SIMPLIFY_MM`, `POINT_TIP_R`) live in the module, not in `params.json`, with a comment saying why.
- Second part = **second builder in the same module, same `params.json`, own intent file**: `build_pin(p)` and `intent-pin.json`. `main()` does:

```python
params = load_params()
parts = {"part": (build, "intent.json"), "pin": (build_pin, "intent-pin.json")}
for stem, (builder, _) in parts.items():
    print(io.export(builder, HERE / "out" / stem, nominal=("step",), compensated=("stl", "3mf"),
                    calibration=args.calibration, params=params))
if not args.check: return 0
ok = True
for stem, (_, intent_file) in parts.items():
    for fmt in ("step", "stl"):
        report = intent.check(features.extract(HERE / "out" / f"{stem}.{fmt}"), HERE / intent_file)
        print(); print(report); ok &= report.passed
return 0 if ok else 1
```

  `--calibration` defaults to `None`, so `--check` compares **nominal** meshes against nominal ranges. A compensated STL (`--calibration PLA_generic`) has every `hole` +0.18 and every `outer` −0.05 and will FAIL ±0.05 hole assertions — that is expected and is not a defect; do not check the compensated file against `intent.json`.

If the monitor bridge is two mating halves, do exactly this: `build_left`/`build_right` (or `build`/`build_clip`), one `params.json`, `intent.json` + `intent-<other>.json`, exported to `out/<stem>.*`. If it is one part, drop the dict to one entry.

How wrx-badge asserted the hard things (`models/wrx-badge/intent.json`, `intent-pin.json`):

- **Freeform claims are stated in `holds`, not asserted**: "The dome rise and the relief are freeform claims the ruler cannot verify and are stated here, not asserted."
- **A single `bbox_z` that separates four failure modes**: `overall_height [7.9, 8.05]` with the note "A flat face reads 5.0, a dome with no relief 7.0, relief stacked twice 9.0".
- **A `volume` floor computed analytically, open above**: `solid_volume [35700.0, null]` = slab 25335 + cap 9529 + rim 442 + half the letters, so "a badge whose graphic did not trace, or whose dome is missing (−9529), measures below it".
- **Ceilings asserted by area, not angle**: `unsupported_area [0.0, 14.0]` at `threshold_deg 45` — "the only downward faces past 45 degrees are the two Ø2.9 hole ceilings, 2 × 6.61 = 13.2 mm²". `max_overhang_deg` would read 90 for any ceiling.
- **Sampled wall forced to Tier 2**: `thinnest_feature [1.4, null]`, `"tier": 2`, `samples 3000`, note explaining that the font's hairlines read thinner and are not a defect.
- **Holes by position and rank**: `cylinder_diameter at [-50, 0] rank "smallest"` for each hole, `cylinder_depth at [50, 0]`, and `feature_count diameter [2.5, 3.5] = [2, 2]`.
- **The pin's cone is never asserted as a cylinder**: the taper is caught by `bbox_z` (analytic: `5.0 + 2.0 + (1.2 − 0.05)/tan 35° = 8.642`), and `max_overhang [0, 40]` because "standing on the shaft face … nothing faces down".
- `golden` bbox/volume are recorded after the build and are drift only.

## 3. Measure kinds usable for a planar bridge, and how `at` / `rank` / `between` select

All from `src/threedp/intent.py`, `MEASURE_KINDS`. Every assert is `{"<unique_name>": [lo, hi], "source": "...", "measure": {"kind": ..., ...}, optional "tier": 2, "note", "unit"}`; exactly one non-reserved key; `null` on one side only; duplicate names refused; `source` must be present (any string, but only `parts-db:...` is machine-checked).

| kind | spec keys | what it measures on a plate | tier |
|---|---|---|---|
| `cylinder_diameter` | `at [x,y]`, `rank` (`"largest"` default, `"smallest"`, or int index into the radius-descending list at that XY, negatives allowed), `tol_xy` (0.5) | a round through-hole, a counterbore, a boss | 1 on BREP; on mesh 1 only if tilt ≤ 1°, else ESTIMATE with `diameter_unchecked` |
| `cylinder_depth` | same | axial extent of that cylindrical face: plate thickness for a through-hole, `t − cbore_depth` for the clearance run under a counterbore (the bearing-holder's `material_under_counterbore` trick), the depth of a round pocket | as above |
| `coaxial_step_radial` | `at`, `between [i, j]` (indices into the radius-descending list at that XY) | `(d_i − d_j)/2`: counterbore-to-clearance step, boss wall around an insert | as above |
| `feature_count` | `diameter [lo, hi]` | how many `fs.cylinders` (circular, untapered, **holes and bosses alike**, anywhere on the part) have `diameter_unchecked` in the band | 1 |
| `plane_gap` | `between [i, j]` (indices into `sorted({round(z, 4)})` of `horizontal_planes()`; negatives allowed) | plate thickness `[0, -1]`, material under a rectangular pocket `[0, 1]`, pocket depth `[1, 2]` — the **only** Tier 1 kind for a rectangular pocket | 1 |
| `bbox_x/y/z` | none | outer envelope of the plate (`fs.bbox_size[axis]`) | 1 |
| `volume` | none | `fs.volume` in mm³ — the way to assert that slots/pockets removed material (see §4) | 1 |
| `watertight` | none | 1.0/0.0 | 1 |
| `unsupported_area` | `threshold_deg` (45) | mm² of faces steeper than the threshold from vertical, plate contact excluded, **ceilings included** (no bridge exclusion on this kind) | 1 |
| `max_overhang_deg` | `threshold_deg` | max angle from vertical; **any ceiling → 90** | 1 |
| `sampled_min_wall` | `samples` (2000) | `printability.min_wall(...).min_mm` | always 2 (ESTIMATE) |
| `dfm_violation_count` | `material` (PLA_generic), `severity` (BLOCKER) | `dfm.evaluate(fs.mesh, material).count(severity)` — this one **does** get the bridge exclusion | 1 |
| `noncircular_count` | none | mesh only; **raises `MeasurementError` → FAIL on the STEP path** | 1 |
| `ams_mismatch_count` | `live`, `inventory`, `materials` | printer inventory; not for this part | — |

Selection mechanics that matter for a plate:

- `at` is absolute XY of the feature **axis**, matched within `tol_xy = 0.5`. Compute it from `params.json` (design intent), never by reading it off the shape. Build the part at a known origin with its bottom on z = 0 (`align=(Align.CENTER, Align.CENTER, Align.MIN)`), as both example models do.
- `rank` orders the coaxial cylinders at that XY largest-first, so `"largest"` at a counterbored hole is the counterbore and `"smallest"` is the clearance; an **absent counterbore makes `"largest"` return the clearance diameter, which is the FAIL** (bearing-holder note: "an absent counterbore reads as the clearance hole's own diameter, which is the defect").
- Absence is never a skip: `FeatureNotFoundError`, `NotCircularError` (section not a circle) and `MeasurementError` (tapered / axis unmeasurable) all become a FAIL line with the reason.
- `plane_gap` indexes the **set of unique Z values**, up- and down-facing merged. On the probe below a 60×30×4 plate with one 2 mm pocket had planes `z = 0.0, 2.0, 4.0` on both paths, so `[0, 1]` = 2.0 (floor), `[1, 2]` = 2.0 (depth), `[0, -1]` = 4.0 (thickness). Every extra shoulder/ceiling/floor adds a Z and shifts the indices — write the note with the full sorted Z list.

## 4. Pitfalls that apply to a planar bridging part

From CLAUDE.md, the skills, the module docstrings, and one scratch probe run today (`60×30×4 plate, vertical-edge fillet r 3, Ø4.5 through-hole at (−20,0), 4.5×12 slot at (15,0), 8×6×2 top pocket at (0,8)`, extracted on both paths — numbers quoted where they come from that run):

1. **Overhang is measured from vertical** (0 = wall, 90 = ceiling); build-plate faces are excluded; the top bin is inclusive. Do not report low bins as defects.
2. **The `max_overhang_deg` intent kind passes no `bridging_span_mm`**, so a single hole/slot ceiling makes it read 90.000. Design the print orientation with every pocket, counterbore and slot opening **upward** (ceiling-free), then `max_overhang_deg [0, 45]` and `unsupported_area [0, 0]` are both assertable. If a ceiling is unavoidable (a clip channel, a counterbore from below), assert `unsupported_area` with an analytic budget like wrx-badge, and let `dfm_violation_count` carry the material-aware verdict — `dfm.evaluate` excludes ceilings ≤ `max_bridge_mm` (10 PLA / **5 PETG** / 6 ABS) from the overhang BLOCKER, then reports them under `max_bridge_mm` as a WARNING.
3. **Bridge span = the shorter footprint extent of a downward patch**, an ESTIMATE from face geometry, not a slice. A slot cut from below bridges its *width*; a channel bridges its *width*. PETG is loaded (green) and the user prints PETG, so a 6 mm ceiling is fine in PLA and a BLOCKER-by-overhang in PETG. Run `dfm.evaluate` for both `PLA_generic` and `PETG_generic` and assert `dfm_violation_count` for the material it will actually print in (two assertions with different names are fine).
4. **`min_wall_mm` and `min_feature_mm` share one ray cast** and fire together; the number is `min_feature_size` at 6000 samples, an ESTIMATE, with `p1_mm` alongside. A clip arm, a rib or a slot wall under 0.8 is a BLOCKER. The grazing-exit filter (uncommitted, §0) is what stops a chamfered/tilted top edge over a thin wall reading 0.003 mm; keep the tree.
5. **Fillets on vertical edges and the rounded ends of slots are cylindrical faces, and the BREP path reports them as `Cylinder`s.** Measured on the probe: STEP listed **7** cylinders — four `r 3.000` at the corners `(±27, ±12)`, the real hole `r 2.250 at (−20, 0)`, and the slot's two ends `r 2.250 at (11.25, 0)` and `(18.75, 0)`; STL listed **1** (the hole) and put the slot at `(15, 0)`, the pocket at `(0, 8)`, and the outline into `noncircular`. Consequences: `feature_count` with a band overlapping `2 × fillet_r` or the slot width **disagrees between STEP and STL** (3 vs 1 in `[4.4, 4.6]` here); `cylinder_diameter` at a slot end passes on STEP and FAILs on STL (`no cylindrical feature at (11.25, 0)`); `cylinder_diameter` at the slot centre FAILs on STL as `NotCircularError` and on STEP as absent. So: keep `feature_count` bands away from fillet and slot diameters (or fillet only top edges — but a horizontal-axis fillet is *also* a cylinder on the BREP path, at 90° tilt, and is still graded Tier 1 there because `_mesh_tier` only demotes on the mesh path; simplest is no fillets, or a fillet radius whose doubled value collides with nothing).
6. **A slot's width has no Tier 1 kind that agrees on both paths.** Assert slots by `volume`: band computed analytically as plate − holes − slots − pockets with the note showing the arithmetic, and tight enough that one missing slot (`(w·(l−w) + π(w/2)²)·t` mm³) falls outside it. `golden.volume` at `tol_pct 1.0` cannot do this job — one Ø4.5 hole in a 4 mm plate is 63.6 mm³, 0.4 % of a 100×40×4 plate. Put the slot's width/length in `holds` and in `params.json` notes.
7. **`noncircular_count` is mesh-only and fragile.** On the probe the rectangular outline split into **two** runs (fit centres `(0.038, −0.012)` and `(−0.038, 0.012)`, 0.076 apart > the 0.05 merge tolerance), so the count was 4 where 3 was expected; and on the STEP path the kind raises. Do not assert it on a part checked on both paths.
8. **Two coaxial equal-diameter holes with a gap between them** (a hole through two stacked flanges) merge into one run whose 25 %/75 % probes land in the gap; the axis is unmeasurable and `select_cylinder` refuses with "the axis of the feature … could not be established". Give stacked holes different diameters or avoid the gap.
9. **A square pocket fits as a confident circle** (20×20 → "24.4949") — the circularity gate (`max_residual ≤ 0.05`) catches it and it lands in `noncircular`; never assert a rectangular pocket with a cylinder kind — use `plane_gap` for its depth and `volume` for its footprint.
10. **`face.center()` is wrong by exactly the radius for a cylindrical face** — you are not measuring anything yourself, but the same trap applies to computing `at` from geometry: compute from parameters.
11. **Counterbore depth vs head height**: `M4.head_h = 4.0`; a 4 mm counterbore in a 4 mm plate leaves nothing. Assert `cylinder_depth at <hole> rank "smallest"` ≥ 1.0 like bearing-holder's `material_under_counterbore`, and check `head_h` in step 1 of `lril3d-model` before writing geometry.
12. **`min_hole_d_mm` is skipped, not passed, on a non-watertight mesh** and on off-axis bores; the report's `skipped` lines are not clean bills of health.
13. **Sketch objects need a `BuildSketch`**: `SlotCenterPoint(...)` directly inside `with BuildPart()` raises `RuntimeError: BuildPart doesn't have a SlotCenterPoint object or operation (SlotCenterPoint applies to ['BuildSketch'])` (hit today). Use `with BuildSketch(): SlotCenterPoint(...)` then `extrude(amount=..., mode=Mode.SUBTRACT)`, or algebra mode.
14. **build123d's STL deflection is relative**; never non-uniformly `scale` a surface that ships as a mesh (0.49 mm sag on the badge). A planar part with cylinders is safe at the library's 0.01.
15. **A `.3mf` loads as a `Scene`**; `features.load_mesh` handles it. `render.contact_sheet` cannot take a STEP.
16. **Windows console**: `Report.__str__` falls back to `[OK] [!!] [~ ]` marks when the encoding cannot carry the emoji; it is the same report.
17. **`ruff check .` lints `models/`** (`extend-exclude` is only `viewer, *.md, .agents, .claude/skills/pr-trajectory-audit`; line length 100). `model.py` must pass `ruff check` and `ruff format --check`. `tests/test_one_ruler.py` does not walk `models/` (it scans `src/threedp`, `benchmarks`, `tests`), but the bans (`lstsq`, `.ptp(`, `def fit_circle`, `hypot(...).max()`) hold as discipline: the model measures nothing.

## 5. Command lines

Give `main()` the wrx-badge flags (`--calibration`, `--check`) and add `--dfm` and `--render` so the whole loop is one file; the one-liners below are the fallback. Run from the repo root (`profiles_dir()` also falls back to the package's own root, so cwd is not load-bearing). Timeouts ≥ 300 000 ms.

```powershell
# 1. nominal export (step + stl + 3mf) and both-path intent check
uv run python models/monitor-bridge/model.py --check

# 2. compensated meshes for printing (warns: PLA_generic is a published default) - do NOT intent-check these
uv run python models/monitor-bridge/model.py --calibration PLA_generic

# 3. printability numbers + DFM verdict in both loaded materials
uv run python -c "from threedp import features, printability, dfm; f = features.extract('models/monitor-bridge/out/part.stl'); print(printability.min_wall(f.mesh, samples=2000)); print(printability.min_feature_size(f.mesh)); print(printability.overhang_histogram(f.mesh, threshold_deg=45)); print(printability.bridge_spans(f.mesh)); print(printability.footprint(f.mesh)); print(printability.bore_diameters(f.mesh)); print(dfm.evaluate(f.mesh, 'PLA_generic', part='monitor-bridge')); print(dfm.evaluate(f.mesh, 'PETG_generic', part='monitor-bridge'))"

# 4. contact sheet (channel, not a gate) - STL in, PNG out, numbered per iteration
uv run python -c "from threedp import render; print(render.contact_sheet('models/monitor-bridge/out/part.stl', 'models/monitor-bridge/renders/iter-01.png', views=('iso', 'top', 'front', 'right'), projection='parallel', scale_bar=True, plate='p1s'))"

# 5. lint the model like library code
uv run ruff check models/monitor-bridge; uv run ruff format --check models/monitor-bridge

# 6. the library gates the part depends on (uncommitted ruler fixes) still hold
uv run pytest tests/test_features.py tests/test_printability.py tests/test_dfm.py tests/test_intent.py -q
```

Report step 1's two reports verbatim, step 3's DFM lines with their `[source]`, and step 4 as "here is what it looks like" — never as evidence.

## 6. Repo rules that will refuse the part

- **Uncited dimension**: an assert without `"source"` → `IntentError: … carries no source`; a `parts-db:` source that does not resolve → visible `unresolvable citation` line; a `parts-db` value outside its own range → `the citation does not bracket the range` (advisory, but it means the intent is wrong). Everything not in `parts.py` is `user-confirmed`, and `lril3d-model` step 2 says to **HALT and ask** before writing `intent.json` — monitor hole spacing, plate thickness, slot lengths, clip gap, and material are judgment calls or user facts, not numbers to invent.
- **Untagged parameter**: a bare number or a role outside `hole|outer|neutral` → `CompensationError` at the first `resolve`, i.e. at export. Roles for this part: through-holes, slot widths, insert holes, a clip gap that grips something → `hole`; outer plate length/width, a tongue that enters something → `outer`; thicknesses, positions, spacings, depths, angles (`_DEG` suffix) → `neutral`. Keep every `hole`/`outer` parameter as a **diameter or full width**, never a radius — the delta is added whole.
- **`"measured": true`** in a calibration record is refused (`compensate._check_measured`); leave `profiles/calibration.json` alone.
- **`intent.json` with no Tier 1 assertion** can never pass; one with an empty `asserts` list, a duplicate name, two names in one entry, `lo > hi`, or `[null, null]` fails to load.
- **A FAIL is a FAIL**: do not widen a range, and do not narrate a BLOCKER down. If you believe the assertion is wrong, say so and ask.
- **Unknown DFM material** (`ASA` has no profile; ABS is the stand-in per the user's memory) or an uncited threshold → `DfmError`; do not add thresholds in Python or in prose.
- **Do not write to `out/` and call it verified**, and do not tell the user the part is correct before `intent.check` has printed PASS on both `part.step` and `part.stl`.
- **A print needs a human yes in the conversation**; nothing in this brief reaches `printer.py`.

## 7. Skeleton to follow (placeholders, not values)

```
models/monitor-bridge/
  params.json      {"PLATE_L": {"value": <user>, "role": "outer", "note": "..."},
                    "PLATE_T": {"value": <user>, "role": "neutral", ...},
                    "MOUNT_HOLE_D": {"value": 4.5, "role": "hole", "note": "parts-db:M4.clearance"},
                    "MOUNT_PITCH": {"value": <user-confirmed VESA pitch>, "role": "neutral", ...},
                    "SLOT_W": {"value": ..., "role": "hole"}, "SLOT_L": {..., "role": "neutral"}, ...}
  intent.json      holds: full plain description incl. what is NOT asserted and why
                   asserts: bbox_x/y/z; volume [analytic_lo, analytic_hi] with the arithmetic in the note;
                            watertight [1,1]; per hole: cylinder_diameter at [x,y] rank "smallest";
                            per counterbore: cylinder_diameter rank "largest" + cylinder_depth rank "smallest" >= 1.0;
                            feature_count on a band that excludes fillet/slot diameters;
                            plane_gap for pocket depth and material under pocket (list the sorted Z in the note);
                            unsupported_area [0, budget] (0 if ceiling-free); max_overhang_deg [0, 45] only if ceiling-free;
                            sampled_min_wall [design_min - margin, null] "tier": 2;
                            dfm_violation_count severity BLOCKER for PLA_generic and for PETG_generic
                   golden: bbox + volume recorded from the first passing build, tol_pct 1.0
  model.py         load_params(); build(p) [and build_<other>(p)]; main() copied from wrx-badge with --dfm/--render added
  out/, renders/   written by main()
```
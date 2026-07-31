# Code review — Phase 1 verification loop

**Slice:** `phase-1-verification-loop`
**Commit:** `c051a03`
**Reviewed against:** `db9effb` (PRD-only baseline)
**Date:** 2026-07-31

## Stats

- Files Modified: 0
- Files Added: 78
- Files Deleted: 0
- New lines: 10,692
- Deleted lines: 0

Core library reviewed in full (`src/threedp/*.py`, 2,240 lines across 9 modules), plus
`benchmarks/harness.py`, `benchmarks/run_mutations.py`, the five `intent.json` files and
`viewer/server/watch.mjs`.

## Gate results

| Gate | Result |
| --- | --- |
| `ruff check .` | PASS |
| `ruff format --check .` | PASS — 45 files |
| Root import + interpreter gate | PASS — Python 3.13.14 |
| `pytest` | PASS — **175 tests** at `c051a03`; **184** after the fixes below |
| **Mutation suite** | **PASS — caught 13/13, missed 0, false-positives 0, harness-errors 0, over 19 mutations / 5 benchmarks** (unchanged by the fixes) |
| Credential scan | Clean — no secrets; `.gitignore` covers `.env*` |

The mutation suite reported 19 mutations, not zero, so this is not the skipped-layer-wearing-a-
green-badge case `CLAUDE.md` warns about. All 6 `cosmetic_*` false-positive detectors passed,
and all 3 method mutations (the ones that check the ruler rather than the geometry) were caught.

## General assessment

The architecture holds up under reading. The non-negotiable rules are enforced *structurally*
rather than by convention, which is the part that usually rots first and here does not:

- `CircleFit.diameter` raising unless `is_circular` makes the unsafe path require typing a
  conspicuously different name (`diameter_unchecked`). That survives an agent writing the caller.
- `parts._assert_keys_are_globally_unique()` runs at **import**, not only in a test.
- `Report.passed` requires `any(r.gating for r in self.results)`, so an all-ESTIMATE intent
  cannot produce a green verdict — a subtle and correct guard.
- `_check_one` turns both `NotCircularError` and `MeasurementError` into `FAIL` **with a reason**,
  never a skip, matching "an absent feature IS the defect".
- `forced_tier` is applied as `max(tier, forced_tier)`, so intent can demote to Tier 2 but never
  promote to Tier 1. The safe direction.

Findings below are one correctness issue, one reporting-accuracy issue, and five low-severity
cleanups. No critical or high findings.

---

## Findings

```
severity: medium
file: src/threedp/intent.py
line: 453
issue: The report hardcodes " mm" on every assertion value, mislabelling degrees, areas and booleans.
detail: `lines.append(f"{mark} {r.name:<{width}} = {value} mm   {tail} ...")` applies a millimetre
  suffix unconditionally, but 5 of the 14 entries in MEASURE_KINDS are not millimetres:
  max_overhang_deg (degrees), unsupported_area (mm2), volume (mm3), watertight (boolean) and
  feature_count (a count). Verified by running the overhang-test benchmark:

      [OK] max_overhang_deg =    60.175 mm   expected 59.50-60.50
      [OK] unsupported_area =  1339.070 mm   expected 1300.00-1380.00
      [OK] watertight       =     1.000 mm   expected 1.00-1.00

  All five benchmarks assert on at least one non-mm kind, so every benchmark report carries this.
  It does not change any verdict, but it is wrong in the primary human-facing output — the text a
  user reads to decide whether to commit a part to a 6-hour print — and it directly contradicts two
  stated project rules: "All dimensions are millimetres. Suffix a variable only when it is not mm"
  and "Report numbers, never impressions."
suggestion: Give each measure kind a unit and print that instead of a literal. The kind functions
  already return a 3-tuple (value, tier, note); extend MEASURE_KINDS to carry a unit string
  ("mm", "deg", "mm2", "mm3", "", "count") and format with it, defaulting to "mm". Assert on the
  rendered line in tests/test_intent.py so it cannot regress silently.
```

```
severity: medium
file: src/threedp/features.py
line: 464
issue: A failed axis/taper probe returns "perfectly axis-aligned, zero taper" — the most
  favourable possible answer — instead of routing the feature to an unverifiable bucket.
detail: `_measure_axis_and_taper` has three failure exits with two different safety outcomes:

    line 451  height < _MIN_PROBE_HEIGHT  -> return (0,0,1), float("inf")   # routes to `tapered`
    line 464  section_rings raised        -> return (0,0,1), 0.0            # routes to `circular`
    line 477  no matching ring found      -> return (0,0,1), 0.0            # routes to `circular`

  Line 451 is deliberate and documented: an unprobeable sliver is reported as infinite taper so it
  cannot be presented as a cylinder with a diameter. Lines 464 and 477 describe the same condition
  — "the axis could not be established" — but return taper 0.0 and axis exactly +Z, which makes
  `_scan_cylinders` classify the feature as `circular`, and `_mesh_tier` then grades it Tier 1
  because `is_axis_aligned` is trivially true for the fabricated (0,0,1).

  Reachable: runs are merged across slabs on matching radius and centre (lines 386-398), so two
  coaxial same-diameter bores separated by solid material collapse into one run spanning both.
  The 25%/75% probe heights then land in the solid gap, where no ring matches the target radius,
  `best` stays None, and line 477 fires. The result is a Tier 1 dimensional claim on a feature
  whose axis was never actually measured — the precise failure mode ADR-4 exists to prevent.

  No current mutation exercises this path, which is why the suite is green.
suggestion: Make lines 464 and 477 return `float("inf")` taper, matching line 451, so an
  unmeasurable axis routes to `tapered` and refuses Tier 1 rather than defaulting to the
  flattering answer. Add a mutation with two coaxial equal-diameter bores separated by a gap to
  lock the behaviour in — this is a ruler mutation, which is the class that geometry mutations
  structurally cannot catch.
```

```
severity: low
file: src/threedp/features.py
line: 230
issue: Dead code — a value is computed and immediately deleted.
detail: `n = pln.Axis().Direction()` on line 230 is never read; line 232 is `del n`. The comment
  explains correctly why `f.normal_at()` is used instead of the OCCT plane axis, but the
  superseded call was left in with a `del` to silence the unused-variable lint.
suggestion: Delete lines 230 and 232 and keep the comment, which is the valuable part.
```

```
severity: low
file: src/threedp/features.py
line: 412
issue: `Cylinder.area` means two different things depending on representation.
detail: The BREP path sets `area=float(f.area)` — the true measured face area, which for a
  partial cylindrical face is less than a full revolution. The mesh path computes
  `2.0 * np.pi * fit.radius * (z_max - z_min)`, the idealised full-cylinder lateral area, which
  overstates any feature that is not a complete bore (a slot end, a scalloped relief). Nothing
  currently asserts on `.area`, so this is latent rather than active.
suggestion: Either compute the mesh-path area from the summed facet areas of the run, or rename
  the mesh-path value to make the difference visible at the call site.
```

```
severity: low
file: src/threedp/features.py
line: 554
issue: The unsupported-format error omits two formats the function accepts.
detail: Line 552 accepts `.stl`, `.3mf`, `.obj` and `.ply`, but the error names only
  "expected .step/.stp (BREP) or .stl/.3mf (mesh)". A user passing `.OBJ` in the wrong case, or
  debugging a typo, is told the format is unsupported when in fact it is.
suggestion: Build the message from the accepted-suffix tuples so it cannot drift again.
```

```
severity: low
file: src/threedp/intent.py
line: 533
issue: The `golden` block is unvalidated, so a malformed one crashes with IndexError rather than
  a clean IntentError.
detail: `load()` validates the `asserts` list carefully — reserved keys, pair shape, lo<=hi,
  duplicate names, unknown measure kinds — but passes `golden` straight through as a dict. A
  `"golden": {"bbox": [30.0, 30.0]}` (two entries instead of three) then raises IndexError from
  `float(golden["bbox"][axis])` inside `check()`, and a non-numeric entry raises ValueError.
  Both surface as an unhandled traceback rather than the "the intent file itself is malformed"
  error IntentError exists to carry.
suggestion: Validate `golden` in `load()` alongside `asserts`: `bbox` must be 3 numbers if
  present, `volume` and `tol_pct` must be numbers.
```

```
severity: low
file: viewer/server/watch.mjs
line: 41
issue: The watch WebSocket binds every interface and broadcasts absolute filesystem paths.
detail: `new WebSocketServer({ port: PORT })` with no `host` listens on 0.0.0.0, so anyone on the
  same network can connect and receive `{type: 'hello', dir: modelDir, file: currentFile()}` —
  absolute paths disclosing the developer's directory layout. It serves no file contents, so the
  impact is limited to path disclosure on a dev-only tool.
suggestion: Pass `host: '127.0.0.1'`. The viewer is documented as a localhost dev workflow, so
  this costs nothing.
```

---

---

## Resolution

Dispositions were chosen by the maintainer at the triage gate: fix 1–6, defer 7.

| # | Severity | Issue | File | Disposition | What was done | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | medium | `" mm"` hardcoded on every reported value | `src/threedp/intent.py:453` | Fix | Added `MEASURE_UNITS` + `unit_for(kind)`; formatter now prints `deg`, `mm2`, `mm3`, `mm`, or nothing for booleans and counts. Applied to the drift section too. | **Fixed** |
| 2 | medium | Failed axis probe returned "axis-aligned, zero taper" | `src/threedp/features.py:464,477` | Fix | All three unmeasurable-axis exits now return a shared `_UNMEASURABLE_AXIS` sentinel (infinite taper), routing the feature to `tapered` so it refuses Tier 1. | **Fixed** |
| 2b | medium | *(found while fixing #2)* the refusal message was itself wrong | `src/threedp/features.py:149` | Fix | `tapered` holds two distinct facts; the message claimed "its radius changes with height" for features whose radius was never measured. `Cylinder` now carries `taper_per_mm` and the message branches on it. | **Fixed** |
| 3 | low | Dead code: `n = pln.Axis().Direction()` then `del n` | `src/threedp/features.py:230` | Fix | Both lines removed; the explanatory comment kept. | **Fixed** |
| 4 | low | Format error omitted `.obj`/`.ply` | `src/threedp/features.py:554` | Fix | Added `BREP_SUFFIXES` / `MESH_SUFFIXES`; the message is built from them so it cannot drift. | **Fixed** |
| 5 | low | `golden` block unvalidated → `IndexError` not `IntentError` | `src/threedp/intent.py:533` | Fix | `_validate_golden()` called from `load()`; rejects short/non-numeric `bbox` and non-numeric `volume`/`tol_pct`, including `bool`. | **Fixed** |
| 6 | low | Watch server bound all interfaces | `viewer/server/watch.mjs:41` | Fix | Binds `127.0.0.1` (matching Vite's default), overridable via `THREEDP_WATCH_HOST`. | **Fixed — not browser-verified** |
| 7 | low | `Cylinder.area` means two things by representation | `src/threedp/features.py:412` | **Defer** | Not changed. Destination: Phase 2 `lril3d-dfm`, which is the work that will actually consume face areas. | Deferred |

### Evidence that #2 was a real defect, not a theoretical one

The fix was verified in both directions on a purpose-built part (two coaxial Ø10 bores separated
by 30 mm of solid, which coalesce into one run so the 25%/75% probes land in the gap):

```
pre-fix sentinel  ->  ACCEPTED  diameter=9.9984  tilt=0.00deg  Tier1=True
post-fix sentinel ->  REFUSED   "the axis of the feature at (0, 0) could not be established"
```

That is a confident Tier 1 dimensional verdict derived from a measurement that never happened —
the exact failure mode ADR-4 exists to prevent, reached through a path no mutation covered.

### Tests added (9; 175 → 184)

- `test_unmeasurable_axis_refuses_rather_than_reporting_zero_taper` — asserts the feature is
  absent from `cylinders`, present in `tapered` with **infinite** taper (a finite value would be
  indistinguishable from a genuine cone), and that the refusal message names the axis.
- `test_report_labels_each_value_with_its_own_unit` — asserts `deg` / `mm3` / bare / `mm` on the
  rendered lines, so the units cannot silently revert.
- `test_a_malformed_golden_block_is_an_intent_error_not_a_crash` — 6 parametrised malformed
  blocks, plus `test_a_well_formed_golden_block_still_loads` as the negative control.

New fixture `build_interrupted_bore()` / `interrupted_bore_stl` in `tests/conftest.py`.

### Post-fix gate re-run

`ruff check` PASS · `ruff format --check` PASS (45 files) · root import gate PASS (3.13.14) ·
`pytest` **184 passed** · mutation suite **caught 13/13, missed 0, false-positives 0,
harness-errors 0** over 19 mutations — unchanged, so no fix introduced a false positive.

---

## Checked and clean

- **Security:** no SQL, no HTML injection surface, no network I/O beyond the localhost dev
  WebSocket. Credential scan over all 78 files returned only `tokenize`/`asttokens` matches.
  `profiles/printer-p1s.json` carries vendor spec only — no serial, no LAN access code.
- **The printer gate:** `.claude/settings.json` denies every send path, committed before any send
  capability exists. Matches `.claude/PRINT-GATE.md` and ADR-5.
- **One-ruler rule:** `tests/test_one_ruler.py` tokenises rather than regexing, so a banned token
  in a comment, string, docstring or f-string is correctly not flagged — and is tested both ways.
- **The 0.088mm duplicate-vertex bug:** `fit_circle` strips the repeated closing vertex, and
  `method_keep_dup_vertex` asserts the least-squares path is insensitive to it while
  `method_maxradius` asserts the banned method is not. Both behave as `CLAUDE.md` documents.
- **`parts.resolve_citation`** splits the field from the right, so `parts-db:M2.5.clearance`
  resolves correctly. Covered by tests.
- **`compensate.resolve(params, None)`** applies no arithmetic at all on the nominal path, so
  compensation cannot leak into CAD output.
- **`io.export`** refuses to derive a compensated mesh from a nominal shape and refuses to write a
  STEP from a mesh, both with errors that explain the reasoning rather than just failing.

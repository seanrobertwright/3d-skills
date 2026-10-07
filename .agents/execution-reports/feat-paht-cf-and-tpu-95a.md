# Execution report — `feat-paht-cf-and-tpu-95a`

Add Bambu PAHT-CF and Bambu TPU 95A, the fpv frame's two materials, to every profile that keys
on material, so the frame's parts can be checked for printability, exported and sliced in the
material they will be printed in. Originating spec: seanrobertwright/fpv#5 and the "Tooling
prerequisites" section of that repo's `SPEC.md`.

## Meta information

- **Plan file:** none; a small slice, not a phase. The issue's six acceptance criteria are the plan.
- **Commits:** `0aa3ee6` (the change) and the follow-up carrying the review fixes and these artifacts,
  on `feat/paht-cf-and-tpu-95a`, branched from `370459b` (master).
- **Files modified:** 11 · **added:** 2 (this pair). No files deleted.

| Area | Files | What |
|---|---|---|
| `profiles/` | 4 | two DFM material records, two calibration records, two filament presets and a per-material process override table, one inventory note |
| `src/threedp/` | 2 | `slicer._write_presets` merges `material_process_overrides`; `compensate` gains `NO_PUBLISHED_DEFAULT`, `Resolved.source` and a warning that says "uncompensated" when it is |
| `tests/` | 4 | 10 new tests; two shipped-profile tests accept the second unmeasured shape |
| root | 1 | `CLAUDE.md` status line |

## What was done, by criterion

| fpv#5 criterion | Outcome |
|---|---|
| Library runs from the fpv repo's environment | From `C:\repos\fpv`: `uv run --project C:\repos\3d-skills python -c "from threedp import dfm"` imports, `profiles_dir()` resolves to this checkout, both materials listed. Nothing changed in the fpv repo. |
| Both materials in printability rules, slicer presets, calibration records; every threshold sourced | Done. Sources: Bambu PAHT-CF TDS V3.0 (overhang ~70°, bridging ~40 mm, fan 0–40%), Bambu TPU 95A TDS V2.0 (overhang ~70°, bridging 20 mm, fan 100%), Bambu's wiki filament guide and PAHT-CF page (warping, enclosure, AMS compatibility), Bambu's public filament profiles (preset names, `compatible_printers`, `filament_type`, densities). |
| New calibration records start unmeasured, nothing copied | Done. `measured: null`, `hole_delta_mm: 0.0`, `outer_delta_mm: 0.0`, `first_layer_squish: null`, `source: no-published-default`. |
| Structural parts slice modelled-solid as solid; arm solid layers along the arm | Configured, not sliced. `material_process_overrides.PA-CF`: `sparse_infill_density 100%`, `sparse_infill_pattern alignedrectilinear`, `infill_direction 0`. Behaviour read from BambuStudio source (`FillBase::_layer_angle` alternates 90° per layer; `FillAlignedRectilinear` overrides it to 0). Applies to every PA-CF part; shells still alternate. |
| Benchmark slices in each material with non-zero mass and time | **Not done.** No Bambu Studio on this machine: `SlicerNotFound: no slicer executable found. Tried: ['C:\Program Files\Bambu Studio\bambu-studio.exe', 'C:\Program Files\OrcaSlicer\orca-slicer.exe']`. |
| Nozzle type read from the printer and recorded | **Not done.** `PrinterNotConfigured: missing printer credentials: ['PRINTER_IP', 'PRINTER_SERIAL', 'PRINTER_ACCESS_CODE']`. `profiles/printer-p1s.json` unchanged; its 2026-08-02 reading says stainless steel. |

## Validation results

Every command below was executed on this machine on 2026-10-07, against the second commit.

- **Lint and format:** ✓ `uv run ruff check src tests` → "All checks passed!"; `ruff format --check` → 36 files already formatted.
- **Interpreter and root import gate:** ✓ `OK 3.13.x`, all fifteen modules cross-import.
- **Unit tests, hardware-free lane:** ✓ `uv run pytest -m "not printer and not slicer"` → 493 passed, 19 deselected.
- **Full suite:** the six `slicer`-marked tests fail (no slicer installed) and `tests/test_printer_live.py` errors (no credentials). Both lanes fail identically on `master` on this machine; see the PR.
- **Mutation suite:** ✓ `uv run python benchmarks/run_mutations.py` → caught 20/20, missed 0, false-positives 0, harness-errors 0 (30 mutations, 6 benchmarks). VERDICT: PASS.
- **Compensated export check:** ✓ `io.export(bearing-holder, calibration="PAHT-CF_bambu")` wrote the STEP and STL and warned: *"calibration for 'PAHT-CF_bambu' has no published default: its deltas are zero, so this export is uncompensated and has never been verified on this printer."* `result.stale == True`.

## Unverified, stated

- The `PA-CF` and `TPU` tray_type spellings come from Bambu's filament profiles (`filament_type`), not from a loaded spool read over telemetry.
- The `@BBL X1C` presets' P1S compatibility was read from `compatible_printers` on GitHub, not flattened on this machine.
- The aligned-rectilinear behaviour was read from source, not from G-code.
- Whether this printer's nozzle is hardened steel. PAHT-CF is not printed until a reading says so.

## Challenges

- Bambu Studio, present when the slicer wrapper was built (`profiles/slicer.json` source, 2026-07-31), is no longer installed here, and no `.env` exists. Both findings were reported on fpv#5 rather than worked around; the issue stays open.
- Bambu's TPU 95A TDS is hosted only on Bambu's Shopify CDN (and reseller mirrors); the plain TPU 95A store page returns 404. The CDN URL is cited.
- Bambu's TDS figures for overhang and bridging exceed the conventional defaults. They were not used to loosen a gate; they are cited, and the defaults held.

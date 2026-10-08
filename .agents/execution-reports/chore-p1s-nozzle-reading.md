---
slice: chore-p1s-nozzle-reading
title: "chore(profiles): record the P1S nozzle reading of 2026-10-07"
executed: 2026-10-07
base: master @ c4f2507
---

# Execution report — `chore-p1s-nozzle-reading`

The last two criteria of seanrobertwright/fpv #5: slice the bearing-holder benchmark in PA-CF and
TPU, and read the nozzle type from the printer and record it with the date.

## What was done

1. **Nozzle read from the printer.** `PrinterLink` with `wait_for_full_push`, 2026-10-07 20:32 UTC,
   printer IDLE. `nozzle_type` is `stainless_steel`, `nozzle_diameter` is `0.4`. Recorded in
   `profiles/printer-p1s.json` as `nozzle_reading`, with a test that the reading is dated and agrees
   with `nozzle_material`.
2. **Printer address.** The address in `.env` no longer answered. The printer's own UDP 2021
   announcement gave its current address, and its serial matched `.env`. The read and the live
   tests used `PRINTER_IP` exported for the process; `.env` was not edited.
3. **Benchmark slices.** `benchmarks/bearing-holder` rebuilt and sliced. Outputs are gitignored.

| Material | Filament | Mass | Time | Warnings |
|---|---|---|---|---|
| PA-CF | GFN04 | 15.03 g | 37m 31s | none |
| TPU | GFU01 | 9.09 g | 38m 17s | none |

4. **Infill direction from the G-code.** PA-CF G-code carries `sparse_infill_density = 100%`,
   `sparse_infill_pattern = alignedrectilinear`, `infill_direction = 0`. Across 62 layers of
   sparse infill, 90.0% of extruded length runs along plate X and no layer has more than 2.5%
   along Y. Consecutive layers 20 and 21 were plotted and both run along X. TPU on the default
   settings fills diagonally. The thin "Internal solid infill" layers next to the skins alternate
   X and Y, about half each.

## Validation

- Full suite, slicer and printer markers included: 522 passed, 1 failed, 2 skipped. The two skips
  are the real-print tests gated behind `THREEDP_APPROVE_A_REAL_PRINT`. The failure is the AMS
  fixture check: slots 2 and 3 were physically swapped since capture.
- `ruff check` and `ruff format --check` with the locked ruff 0.16.0: pass.
- From `D:\repos\fpv`: `uv run --project D:\repos\3d-skills python -c "from threedp import dfm"`
  imports.

## Not done

- PAHT-CF is not printable on this machine: the nozzle is stainless steel.
- The AMS fixture was not re-captured.

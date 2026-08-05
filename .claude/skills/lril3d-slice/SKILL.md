---
name: lril3d-slice
description: Use when a verified part needs turning into machine instructions — print time, filament grams, AMS slot mapping, purge waste, or a G-code preview. Also when the user asks how long a print will take or what it will cost.
---

# lril3d-slice — G-code, time, and grams

Thin skill, thick library. **No preset names or thresholds belong in this file** — they live in
`profiles/slicer.json`. Read `PRD.md` §12 and §9.

**This skill does not send anything to a printer.** `--export-3mf` produces a file; putting it on
the printer is `lril3d-print`'s job, behind its approval gate. Hand off to that skill rather than
uploading anything here, and never as an unprompted next step — sending is a decision the user
makes, not a convenience you add.

## Slice

```python
from threedp import slicer
result = slicer.slice_part("models/<name>/out/part.stl", material="PLA")
print(result)
```

Materials are the keys under `presets.filament` in `profiles/slicer.json`. `outdir` defaults to a
`slice/` directory beside the input. `export_3mf="sliced.3mf"` takes a **bare filename**.

## What the wrapper refuses, and why that matters more than what it returns

`slice_part` raises `SliceRejected` rather than returning a number the slicer did not produce.
When it does, **report the refusal**. Do not retry with different settings hoping for a number,
and do not present a rejected slice as a small part.

- **`0.00 g` is a rejected slice, not a light part.** The vendor presets are not self-contained
  and the CLI does not resolve their `inherits` chain, so an unflattened preset slices
  successfully at a filament density of zero. The wrapper flattens; if you ever see a zero, the
  flattening broke.
- **`return_code 0` is not success.** Asking for a plate that does not exist returns `0` and
  `"Success."` and slices nothing at all.
- **A non-zero return code does not mean nothing was produced**, either. Both signals are
  unsound alone, which is why four conditions are checked.
- **A print time of zero is refused** for the same reason a mass of zero is.

## Read the result

```
slice    plate 0   25m 08s (1528 s)   10.85 g of PLA (density 1.26 g/cm3, filament_id GFA00)
```

`filament_id` is not cosmetic: `use_ams` is silently ignored unless it is set, which prints
successfully from whatever happens to be loaded. `printer.assert_3mf_is_dispatchable` checks it on
the actual file before any send.

## AMS mapping and purge

```python
slicer.ams_mapping(["PETG", "PLA"])          # -> [2, 0]
slicer.purge_waste(matrix, [0, 1, 0], multiplier=1.0, density=1.26)   # -> (mm3, grams)
```

The mapping is **forward-indexed** (correction C5): array *position* is the filament index inside
the 3MF, array *value* is the AMS slot. Backwards, it prints in the wrong colours and looks like a
slicing bug. Values are not capped at 0–3 — a second AMS unit occupies 4–7 — and the external
spool is 254.

**`ams_mapping` maps the inventory faithfully, including when the inventory is wrong.** It knows
nothing about the printer, on purpose. Before a print goes anywhere near the machine,
`lril3d-print` reconciles `profiles/filaments.json` against live telemetry and refuses on a
mismatch; if you are reporting a slot to a user outside that flow, say it is what the inventory
claims, not what is loaded.

An external spool has no AMS slot and mapping to one raises — it is fed by hand, and it is not
"slot 4". Purge with no density returns grams of `None`, never `0.0`; report the volume and say
the mass is unknown.

## Preview it

```python
from threedp import gcode
gcode.write_preview(result.gcode, "models/<name>/out/part.preview.json")
```

The viewer picks that file up and hot-reloads it. **The preview is a channel, not a gate** — the
same rule as renders. If it says TRUNCATED, say so; a preview that was cut short is not the whole
toolpath.

## When it does not work

1. **`SlicerNotFound`** — Bambu Studio is not installed at any configured path. The error lists
   what it tried. Set `THREEDP_SLICER` to the executable rather than editing code.
2. **`return_code -17`, "not compatible with the process preset"** — the machine or process
   preset was renamed. A process preset's `compatible_printers` is a list of printer *names*.
3. **`preset ... not found`** — a Bambu Studio update renamed something in the profile tree. The
   error names the path it looked in; fix `profiles/slicer.json`.
4. **A blank preview on the P1S screen means the G-code was sent, not the 3MF.** The CLI's
   *G-code* carries no thumbnail block at all — one `thumbnail_size` config line and nothing else,
   which is what Phase 2 measured. The **3MF** does: `Metadata/plate_1.png` at 512×512, a real
   render (correction C7). `lril3d-print` sends the 3MF, so the screen preview works. If it is
   blank, the wrong artefact went across.
5. **Timeout** — a comparable part slices in about a second on this machine, so a timeout is a
   hang rather than a slow model. Do not raise `timeout_s` to make it pass.

## Non-negotiable

Report the measured numbers from the `SliceResult` and nothing else. Banned: "roughly", "about
10 grams", "should take around". The result carries exact values; use them. If the slice was
rejected, the sentence is "the slicer refused this result because ...", never a softened estimate.

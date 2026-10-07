---
slice: feat-paht-cf-and-tpu-95a
title: "feat: add PAHT-CF and TPU 95A materials for the fpv frame"
author: "seanrobertwright"
reviewed: 2026-10-07
recommendation: approve, with the two hardware criteria still open on the originating issue
---

# Code review — `feat-paht-cf-and-tpu-95a`

Two-axis review (standards, spec) run as parallel sub-agents against `master...HEAD` after the
first commit (`0aa3ee6`), with the fixes folded into the second commit. Originating spec:
seanrobertwright/fpv#5 and the "Tooling prerequisites" section of that repo's `SPEC.md`.

| File | Change |
|---|---|
| `profiles/dfm-rules.json` | `PAHT-CF_bambu`, `TPU-95A_bambu`; every threshold cites Bambu's TDS or wiki |
| `profiles/calibration.json` | both records, `measured: null`, zero deltas, `source: no-published-default` |
| `profiles/slicer.json` | `PA-CF` and `TPU` filament presets; `material_process_overrides.PA-CF` |
| `profiles/filaments.json` | note: neither material is loaded; TPU cannot be dispatched (external spool) |
| `src/threedp/slicer.py` | `_write_presets` merges the per-material process layer |
| `src/threedp/compensate.py` | `NO_PUBLISHED_DEFAULT`; `Resolved.source`; honest staleness warning |
| `tests/` | 10 new tests; two shipped-profile tests accept the second unmeasured shape |
| `CLAUDE.md` | status line: five unmeasured records, not three |

## Standards findings

### 1 — HARD · slice artifacts were missing from the first commit

`CLAUDE.md` "Shipping a slice" requires this file and the execution report before the PR opens.
The PR was opened without them. **Fixed** in the second commit; the PR body gains `## Review` and
`## Validation`.

### 2 — judgement, leaning hard · `TPU-95A_bambu.max_bridge_mm` cites a figure it does not use

The source cites the TDS's 20 mm; the value is 5.0, from the ratio of the two TDS bridging
figures (TPU 20 mm against PAHT-CF ~40 mm) applied to the 10 mm default. **Kept, with the
derivation stated in the source string.** It is the same shape as `PETG_generic.max_bridge_mm`
("halved for PETG"); the alternative, loosening a WARNING to a data-sheet best case, is the thing
the `_note` argues against.

### 3 — judgement · "nothing borrowed" in `calibration.json` vs "as for ABS" in `dfm-rules.json`

Two files, two policies, one material. The calibration claim is about **deltas**, which were not
borrowed; the footprint threshold reuses ABS's 400 mm² because the reason (warping) is the same
and is sourced to Bambu's own pages for PAHT-CF. **Accepted as written.**

### 4 — judgement · `compensated=True` on a zero-delta record

`resolve()` reports `compensated=True` for a `no-published-default` record while the warning says
"uncompensated". `compensated` means "resolved against a calibration record", and `io.export`
keys its output on it; changing the flag would change export behaviour outside this slice.
**Accepted;** the warning text is where the honesty lives, and it now says so.

### 5 — minor · `CLAUDE.md` status drift ("all three records"). **Fixed.**

### Baseline smells

- **Primitive Obsession** — `"no-published-default"` as a bare string at six sites. **Fixed:**
  `compensate.NO_PUBLISHED_DEFAULT`, used by the module and both test files.
- **Mysterious Name** — `test_the_shipped_config_slices_...` asserted JSON, not a slice.
  **Fixed:** renamed to `..._asks_for_solid_pa_cf_and_leaves_tpu_alone`, docstring says so.
  The `'name'` refusal named only `preset_overrides`. **Fixed:** names both tables.
- **Divergent Change** — `-0.10` → `-0.1` reformat churn in `calibration.json`. **Fixed.**
- **Duplicated Code** — two identical `note` strings in `calibration.json`; the set-difference-
  then-raise shape twice in `_write_presets`. **Accepted:** JSON has no references, and the two
  raises carry different messages for different mistakes.

## Spec findings

### 1 — missing · nozzle type read and recorded

Needs a printer; no `.env` exists on this machine. **Open on fpv#5.** The reviewer notes that a
PA-CF gate on `PrinterState.nozzle_type` could be coded and fixture-tested without hardware; that
is a follow-up, not configuration, and is not in this slice.

### 2 — missing · benchmark sliced in each material

No Bambu Studio on this machine (`SlicerNotFound`). **Open on fpv#5.**

### 3 — partial · "runs from this repo's environment"

The fpv repo has no Python project; the spec says the tooling changes land here, not there. The
evidence offered is `uv run --project C:\repos\3d-skills` from the fpv directory, which resolves
`profiles/` to this checkout. **Accepted as the intended reading; stated on the issue.**

### 4 — partial · arm solid layers along the arm

`infill_direction 0` + `alignedrectilinear` lays internal solid lines along plate X on every
layer (read from BambuStudio's `FillAlignedRectilinear::_layer_angle`), but only when the arm is
placed along X, and top/bottom shells still alternate. **Stated in the override's note;**
verification is on G-code when a slicer is installed.

### 5 — scope · the override applies to every PA-CF part, not only arms

True: tray, deck and side plates get X-aligned internal fill too. **Stated in the note** as a
known limitation; a per-part override is a follow-up if a body part wants alternating layers.

### 6 — wrong · `first_layer_squish: 0.0` in the new records

The tooling's convention (`calibrate.build_record`) writes `null` when no gauge measured a
squish; `0.0` is a value no gauge produced. **Fixed:** `null`, asserted in the new test.

### 7 — stated · TPU cannot be dispatched

`ams_mapping` raises for an external spool by design, so a TPU part slices but cannot be mapped
and sent. **Stated in `slicer.json` and `filaments.json` notes.**

## Not flagged

`measured` is `null`, never a boolean; every new DFM rule has a `source`; no thresholds in Python
or skill files; nominal/compensated export split untouched; PLA, PETG and ABS behaviour unchanged.

---
name: lril3d-calibrate
description: Use when press fits come out wrong, when a hole prints undersize or a peg prints too fat, when the user asks to calibrate the printer or a material, or when an export warns that the calibration has never been measured. Turns caliper readings from a printed fit gauge into a measured calibration record.
---

# lril3d-calibrate — from a printed coupon to a measured compensation constant

Thin skill, thick library. **No deltas, no tolerances, no step sizes belong in this file** — the
numbers live in `profiles/calibration.json` beside the date they were measured. Read `PRD.md` §6.4
and §15.7.

The whole of this workflow exists to replace three published literature defaults with numbers
measured on *this* printer, with *this* material, on *this* nozzle. Until that happens every
compensated export warns, and it is right to.

## The gauge is exported nominal. Always.

`coupon.write_gauge` refuses a calibration outright, and the reason is worth quoting rather than
paraphrasing:

> a fit gauge is exported nominal and cannot be compensated. Printing a compensated gauge
> measures the compensation rather than the printer: the correction is baked into the geometry and
> then measured back out, and the answer always says the printer is perfect.

Never pass one. If the user asks for a "calibrated coupon", explain that the resulting number
would say the printer has no error no matter how much error it has.

## Both kinds, every time

```python
from threedp import coupon
coupon.write_gauge("out/gauge-hole", kind="hole", nominal_d=10.0)
coupon.write_gauge("out/gauge-pin",  kind="pin",  nominal_d=10.0)
```

**One gauge cannot measure an asymmetry.** A printed bore comes out undersize and a printed stud
comes out oversize; the two errors differ in sign *and* magnitude, and compensation applies them
to separate parameters precisely so they never have to reconcile. Fitting one and inheriting the
other produces a record that looks complete and is half invented.

## Then slice, and print through `lril3d-print`

Slice each gauge with `lril3d-slice` in the material being calibrated, and send it with
`lril3d-print` — including its approval gate and its AMS reconciliation. A gauge printed from the
wrong slot calibrates the wrong material and nothing downstream can tell.

## Measure

Caliper **every step**, and record the reading against the step's nominal diameter — the
`intent.json` the gauge wrote lists them in order.

- **Measure each bore in two orientations.** A bore that is out of round reads correctly on one
  axis and wrong on the other, which is exactly what the circularity gate exists to refuse in the
  digital path. Do the same by hand.
- If two readings of the same step disagree, say so and re-measure. Do not average away a
  disagreement you have not explained.

## Fit and write

```python
from threedp import calibrate
hole  = calibrate.fit_deltas([(9.8, 9.62), (9.9, 9.72), ...], "hole")
outer = calibrate.fit_deltas([(9.8, 9.85), (9.9, 9.95), ...], "outer")
record = calibrate.build_record(hole, outer, "PLA_generic",
                                gauge="coupon:hole-10mm-5step + coupon:pin-10mm-5step",
                                nozzle="<from the printer's own telemetry>",
                                date="<today, ISO>")
calibrate.write_record("PLA_generic", record)
```

`fit_deltas` **raises** when the per-step deltas span more than one gauge step. That is not a
tolerance to loosen: it means the printer's error changes with diameter, so no single offset
describes it, and reporting the mean would be a confident, plausible, wrong constant computed
from real measurements. Re-measure first — a single mis-read step produces exactly this — and if
the spread is real, say that this material needs a fit tested at its own diameter rather than a
profile.

## Confirm it took

```python
from threedp import compensate
resolved = compensate.resolve({"D": {"value": 10.0, "role": "hole"}}, "PLA_generic")
assert not resolved.stale
```

Re-export the part that started the conversation and confirm the staleness warning is gone. If it
is still there, the record did not land.

## Never invent the record you did not print

`"measured"` is an **ISO date**, never `true`. A boolean satisfies the staleness check while
discarding when it was measured, on what nozzle and with which gauge — which is the entire content
of the claim — and `compensate.load_calibration` refuses it.

A material with no spool loaded **stays at its published default with `"measured": null`**. Do not
fill it in from another material, from a blog post, or by scaling. A calibration file that looks
complete and is partly invented is worse than one that is honestly half empty, because only one of
the two gets questioned.

## Non-negotiable

- The gauge is nominal. No exceptions, no flags.
- Both kinds or no record.
- Report the caliper readings; the record stores them so the fit can be recomputed by anyone who
  disagrees with it.
- Never overwrite a measured record with a default. If the user wants to start over, print another
  coupon.

---
name: lril3d-dfm
description: Use when a part needs checking for printability rather than correctness — before committing to a print, after a design change, or when the user asks whether something will print, needs supports, or is too thin.
---

# lril3d-dfm — will it print?

Thin skill, thick library. **No thresholds belong in this file.** Every number lives in
`profiles/dfm-rules.json` next to the `source` that justifies it. Read `PRD.md` §7 for where this
sits in the loop.

`lril3d-inspect` answers *"is this the part I asked for?"*. This answers *"will that part come off
the plate?"*. They are independent: a dimensionally perfect part can be unprintable, and a
printable part can be the wrong part.

## Run it

```python
from threedp import dfm
report = dfm.evaluate(feats.mesh, "PLA_generic", part="bearing-holder")
print(report)
```

Materials are the keys of `profiles/dfm-rules.json` — the same names as `profiles/calibration.json`.
An unknown one raises and names the valid list; do not guess one.

## Read the report

Every line carries the measured value, the threshold it was compared against, and the source
string. Report those, not an impression.

```
BLOCKER max_overhang_deg  measured 75.099 deg  threshold 45.000 deg  above the 45.000 deg
        maximum - past this angle from vertical the underside droops without support
        [conventional FDM support threshold, measured from vertical]
```

- **A BLOCKER is a blocker.** Do not downgrade one in prose. If you believe the threshold is wrong
  rather than the part, say that explicitly and ask — a rule quietly narrated away is a rule that
  is not there.
- **A WARNING is not a gate**, and saying so is not the same as ignoring it. Report it with its
  number and let the user decide.
- **`skipped` lines are not clean bills of health.** "No bore was small" and "no bore was
  measurable" are different facts and the report distinguishes them. Pass the distinction on.
- Overhang angles are **measured from vertical**: 0 is a vertical wall and perfectly fine, 90 is a
  horizontal ceiling and the worst case.
- Wall, feature and bridge numbers are **sampled or derived from face geometry**, and every one of
  them says ESTIMATE. Never present one as a dimension.

## Changing a threshold

Edit `profiles/dfm-rules.json`, and change the `source` in the same edit. A threshold with no
traceable source will not load — `dfm.load_rules` refuses it — and that refusal is deliberate:
an uncited number cannot be argued with by anyone who was not in the room.

Per-material overrides sit under the material key and inherit `_defaults` for everything they do
not mention. ABS and PETG are stricter on overhangs and bridges than PLA, and the reason is in
the `note` on each rule.

## Making DFM gate a verdict

By default it does not, and that is correct: DFM is advice about a *process*, `intent.json` is a
claim about a *part*. To make it gate for a specific part, assert on it:

```json
{"dfm_blockers": [0, 0], "source": "user-confirmed",
 "measure": {"kind": "dfm_violation_count", "severity": "BLOCKER", "material": "PLA_generic"}}
```

Now a DFM regression fails an ordinary assertion, in the ordinary report, with a measured count.

## Non-negotiable

Banned from a critique: "looks printable", "seems fine", "should be OK", "appears thin". Every
claim carries a measured number and the rule it was measured against, or an explicit **ESTIMATE**
label. State the verdict plainly at the top — blockers or none — then the numbers, then what to
change and by how much.

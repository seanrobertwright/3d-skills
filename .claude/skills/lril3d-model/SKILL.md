---
name: lril3d-model
description: Use when the user describes a physical object to model, print, or fabricate. Captures intent, confirms judgment calls, then authors parametric build123d geometry.
---

# lril3d-model — intent capture and geometry authoring

Thin skill, thick library. **No geometry or measurement logic belongs in this file.** Everything
numeric goes through the `threedp` package, which is tested without an agent.

Read `PRD.md` §7 for the workflow's purpose and §6.1 for why intent comes first.

## The five steps, in order

### 1. Resolve known dimensions from the parts database, with citations

```python
from threedp import parts
parts.get("bearing", "608")   # -> {"od": 22.0, "id": 8.0, "width": 7.0, "source": "parts-db:608", ...}
parts.get("screw", "M4")      # -> {"clearance": 4.5, "tap": 3.3, "head_d": 7.0, "head_h": 4.0, ...}
```

An unknown key **raises** with the list of valid keys. Never invent a dimension to keep moving —
a fabricated number is indistinguishable from a cited one downstream, and that is exactly what
the citation mechanism exists to prevent. If the part isn't in the database, say so and ask.

Check `head_h` whenever you counterbore. A real M4 socket head is **4 mm tall**; a 4 mm
counterbore in a 4 mm plate leaves zero material. Catch that here, before geometry.

### 2. Present judgment calls and HALT for confirmation — before writing geometry

This step is **not optional and must not be skipped**, including when the user seems to be in a
hurry. It is the only defense against the failure where you write a wrong `intent.json` and a
matching wrong model, and the two agree with each other (PRD Risk 3). Confirmation is what
grounds the intent outside your own reasoning.

Present cited facts and your own choices in visibly different registers:

```
Bore          22.00mm   [608 OD, parts-db]
Pocket depth   7.00mm   [608 width, parts-db]
Retaining lip  1.00mm   <- my choice. Enough to retain the outer race without fouling the inner. OK?
Wall           4.00mm   <- my choice. Carries the press-fit hoop stress. OK?
Mount holes    4.50mm   [M4 clearance, parts-db]
```

Then stop and wait. Do not write `intent.json` until the judgment calls come back confirmed or
corrected.

### 3. Write `intent.json` — before `model.py` exists

Schema and the available `measure` kinds are documented in `src/threedp/intent.py`. Every
assertion needs a range, a `source`, and a `measure` block:

```json
{"bore_diameter": [21.95, 22.05], "source": "parts-db:608.od",
 "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": 1}}
```

- `source` is either a `parts-db:<key>.<field>` citation or `user-confirmed`. Nothing else is
  grounded in anything.
- Describe features **structurally** — "the second-largest cylinder at (0,0)", "the radial gap
  between the outermost and the bore" — not by the number you are about to build. An assertion
  that just restates the parameter checks nothing.
- `hi: null` means unbounded (`"min_wall": [3.00, null]`).
- Golden bbox/volume go in `golden`, never in `asserts`. They are drift guards and cannot detect
  first-pass error.
- If a claim cannot be dimensionally verified — an organic surface, an angled feature — mark it
  `"tier": 2`. It will be reported as **ESTIMATE** and excluded from the verdict. That is the
  honest outcome, not a failure.

### 4. Author `model.py` + `params.json`

`params.json` tags every dimension with a semantic role, because compensation is applied to
parameters rather than to geometry:

```json
{"BORE": {"value": 22.0, "role": "hole"},
 "OD":   {"value": 30.0, "role": "outer"},
 "WIDTH":{"value": 7.0,  "role": "neutral"}}
```

`hole` gets the hole delta, `outer` gets the outer delta, `neutral` is untouched. An untagged
dimension is refused — it would silently escape compensation.

`model.py` exposes `load_params()` and `build(params, **options) -> shape`. Models are programs:
changing 40 mm to 45 mm is an edit to `params.json`, never a regeneration.

Follow `benchmarks/bearing-holder/model.py` for the shape of one.

### 5. Export

```python
from threedp import io
io.export(build, "models/<name>/out/part", nominal=("step",), compensated=("stl", "3mf"),
          calibration="PLA_generic", params=params)
```

Two separate builds: the STEP from nominal parameters, the meshes from resolved ones. If the
calibration says `"measured": null`, a warning naming the material is emitted — pass it on to
the user rather than swallowing it.

## Then hand off

Run `lril3d-inspect` and report what it measured. Do not tell the user the part is correct
before it has been measured.

## Non-negotiable

- All dimensions are millimetres. Suffix a variable only when it is *not* mm (`angle_deg`).
- Never measure anything yourself. Every dimensional number comes from `threedp.measure`.
- Never write to `out/` and call it verified.

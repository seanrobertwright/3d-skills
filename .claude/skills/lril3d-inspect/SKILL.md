---
name: lril3d-inspect
description: Use when a modelled part needs verifying, measuring, or critiquing — after generating geometry, after editing a parameter, or when the user asks whether a part is correct, will fit, or will print.
---

# lril3d-inspect — measure, verify, critique

Thin skill, thick library. **No measurement logic belongs in this file.** Read `PRD.md` §7 and
§6.2 for the tier rules.

## Before you start: where did this file come from?

If the geometry was **imported** rather than modelled here — a downloaded STL, a scan, a file from
another tool — hand off to `lril3d-repair` first. Inspecting a broken mesh measures the breakage
as much as the part, and a repair applied afterwards can move the very dimension you just
reported. Repair, verify the repair, *then* inspect.

## The workflow

### 1. Extract features

```python
from threedp import features
feats = features.extract("models/<name>/out/part.step")   # BREP face queries
feats = features.extract("models/<name>/out/part.stl")    # mesh cross-section probing
```

Check both when both exist. They measure the same part by different routes, so a disagreement
means one of them has a bug — report it rather than picking the answer you prefer.

### 2. Check every assertion

```python
from threedp import intent
report = intent.check(feats, "models/<name>/intent.json")
print(report)
```

Read the report, do not paraphrase it. Every line already carries a measured value, the expected
range, and the source citation.

- **A FAIL is a FAIL.** Do not relax a range to make it pass, and do not describe a failure as a
  "minor deviation". If you believe the assertion is wrong rather than the part, say that
  explicitly and ask — changing intent to match geometry silently defeats the entire loop.
- **An absent feature is a FAIL**, and it is usually the most important one. A missing
  counterbore is the defect, not a gap in coverage.
- **ESTIMATE lines are not passes.** Report them as unverified, with the reason (Tier 2 surface,
  axis off Z, sampled rather than measured).
- The golden bbox/volume section is **drift only**. Never present it as evidence of correctness.

### 3. Printability — measurement here, verdict in `lril3d-dfm`

`printability` measures; it reaches no conclusion.

```python
from threedp import printability
printability.min_wall(feats.mesh, samples=2000)          # ray-sampled, an ESTIMATE
printability.overhang_histogram(feats.mesh, threshold_deg=45)
```

Overhang angles are **measured from vertical**: 0 is a vertical wall and perfectly fine, 90 is a
horizontal ceiling and the worst case. Do not report low-angle bins as defects.

**Then hand off to `lril3d-dfm` for the verdict.** It compares these numbers against per-material
thresholds that each carry a cited source, and returns findings graded BLOCKER / WARNING / NOTE.
Do not compare a number against a threshold of your own here — a threshold in a transcript is a
threshold outside the config and outside the tests.

### 4. Render the contact sheet

```python
from threedp import render
render.contact_sheet("models/<name>/out/part.stl", "models/<name>/renders/iter-03.png",
                     views=("iso", "top", "front", "right"),
                     projection="parallel", scale_bar=True, plate="p1s")
```

**A render is a channel, not a gate.** It never contributes to a pass verdict. The founding case
for this project is a part with three real defects that rendered cleanly. Offer the sheet so the
user can see the part; never offer it as evidence the part is right.

### 5. Write the critique

Cite measured numbers. Never an impression.

```
❌ pocket_depth = 6.500 mm   expected 6.90–7.10   [parts-db:608.width]
   └─ the 0.5mm fillet consumed pocket depth; a 7mm 608 will stand proud and won't retain
```

Banned from a critique: "looks correct", "seems fine", "should work", "appears to be". If you
cannot attach a number or an explicit **ESTIMATE** label to a claim, do not make the claim.

State the verdict plainly at the top — passed or failed — then the numbers, then what to change.

## When something fails

Name the parameter to change and by how much, and say what physically goes wrong if it is not
changed. Then hand back to `lril3d-model` for the edit. One dimension changing is an edit to
`params.json`, not a regeneration.

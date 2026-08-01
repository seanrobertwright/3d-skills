---
name: lril3d-repair
description: Use when a mesh arrives from outside — a downloaded STL, a scan, a file from another tool — and is broken, non-manifold, inverted, or fails to load or slice. Also when the user asks to fix, heal, or clean up a model.
---

# lril3d-repair — import, diagnose, fix, **verify**

Thin skill, thick library. **No geometry or measurement logic belongs in this file.** Read
`PRD.md` §6.2 and §9.

The fourth step is the one that matters. A repair that changes a dimension is a *failed* repair,
and it is indistinguishable from a good one by inspection.

## 0. Record where it came from — before touching it

An imported third-party model needs its **source and licence recorded** before it is worked on
(PRD §9). Write them next to the file, in the model's own directory:

```json
{"source_url": "...", "author": "...", "licence": "CC-BY-4.0", "downloaded": "2026-08-01"}
```

If the user cannot say where a file came from or under what terms, say so plainly and ask. A
model with unknown provenance is a model you cannot tell them it is safe to publish or sell.

## 1. Diagnose

```python
from threedp import features, repair
mesh = features.load_mesh("imported/thing.stl")
print(repair.diagnose(mesh))
```

Report the diagnosis as it comes: watertight, winding consistency, broken faces, euler number,
duplicates, degenerates.

**Inversion is named, never reported as a volume.** An inside-out mesh encloses a *negative*
volume — measured at −571.14 mm³ on a real part — and a checker comparing that against a range
fails correctly for entirely the wrong reason. `diagnose` says INVERTED.

## 2. Repair, and read the verdict

```python
result = repair.repair(mesh)
print(result)
```

`repair()` never returns a mesh alone. It returns a result with a status:

- **PASS** — closed, and every Tier 1 dimension it could compare held to within 0.01 mm.
- **FAIL** — still open or still inverted, a dimension moved, or a feature present before is
  **absent** after. A feature the repair consumed is the defect.
- **UNVERIFIABLE** — nothing Tier 1 could be compared, because the mesh could not be probed or
  because the part carries no such feature. This is **not** a pass. Say "the repair could not be
  verified", never "the repair succeeded".

**"It is watertight now" is not a repair verdict.** `fill_holes` fans a non-convex boundary shut,
and a bore breaking a surface is exactly a non-convex boundary — so a bridged bore is watertight,
plausible, and wrong. Report the measured before/after numbers the result carries.

Only `result.mesh` is safe to export, and only when you have reported the status alongside it.

## 3. Hand off

A repaired mesh is a *mesh*: no parametrisation, so a press fit on it is unsupported
(`CLAUDE.md`, "Known accepted gaps") and compensation falls back to a uniform geometric offset
where the hole/outer asymmetry is real and unresolvable. Say that before anyone asks for a fit.

Then: `lril3d-inspect` to check it against an `intent.json`, and `lril3d-dfm` to check whether it
prints. A Z-only scan cannot see angled features, so a repaired angled bore is unverifiable and
the result says so rather than guessing.

## Non-negotiable

Report the status verbatim and both numbers on any dimension that moved. Banned: "cleaned up
nicely", "should be fine now", "looks watertight". If the status is UNVERIFIABLE, the sentence is
"I could not verify this", not a softer version of PASS.

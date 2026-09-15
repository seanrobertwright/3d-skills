## Monitor seam connector — judgment calls (step 2, awaiting your confirmation)

### 1. What the monitors are

"B30"/"P30" are EDID names, not Sceptre part numbers. Best match: **B30 = C305W-2560UN1** (100 Hz, blue LED strips, rear OSD buttons) — https://www.sceptre.com/C305W-2560UN1-product1363.html. **P30 = C305B-200UN family** (200 Hz, red V LEDs, OSD under the chin; suffix only on the rear label) — https://www.sceptre.com/support/574/C305B-200UN. Decisive check: max refresh in Windows (100 vs 200 Hz).

| Fact (both) | Value | Unit | Source |
|---|---|---|---|
| Curvature | 1800R | mm | Sceptre pages, both |
| Resolution / pitch | 2560x1080 / 0.2697 | px / mm | Sceptre spec |
| Active area (EDID) | 690 x 291 | mm | linuxhw/EDID SPT0BC2, SPT0BCC |
| Housing W x H (no stand) | 706.6 x 321.1 (B30); 706.1 x 320.0 (P30) | mm | Sceptre pages |
| Housing depth (no stand) | 93.7 (B30); 81.3 / 93.7 / 109.2 (P30, by suffix) | mm | Sceptre, self-contradicting |
| VESA | 75 x 75 via shipped X-plate, M4x10 | mm | Sceptre manual |
| Weight (no stand) | 4.99 / 5.00 | kg | Sceptre |

**Unknown / refuted (not published anywhere):** edge thickness at the side (render ESTIMATE 20–25), bezel widths (derived ~8.1/side, reviewer ~6.4), rim height above glass, rear-cover taper and facet at the ends, OSD button and boss positions, tilt range (four different published values), whether 706 mm is chord or arc.

**Seam geometry (derived):** active arc 690.4 → each monitor subtends 2 x 10.99° = **22.0°** of the circle (22.6° on the 706.6 housing chord); front tangent planes meet at ~157.4°. Front sagitta 33.0 (active) / 35.0 (housing) — so ~35 of the published "depth" is curve, not housing. Rear surface at R≈1821: falls **0.99 mm** across the 120 mm spine, **0.79 mm** between a pad's inner (16) and outer (56) edge, **0.11 mm** within one 40 mm pad.

### 2. Recommended concept

**Arc-seam rear bridge**: one flat 120x120x6 PETG spine with two ribs, bolted to two VHB-bonded shoes on the plain rear cover 16–56 mm inboard of each inner edge, at mid-height. All unknowns live in the two shoes as a thickness step DT = T_EDGE_R − T_EDGE_L plus a 0.79 mm wedge each, so the front glasses stay on one 1800R circle. All three judges chose it: stands stay on, no hardware to buy, three flat prints with zero overhang, and the only concept whose fit-critical geometry — including the wedge's *sign* — is Tier 1 in-repo (witness pockets sharing one floor). Grafts adopted: **(a)** inserts become Ø4.0 through-holes opening on the spine face (the original cut them under the tape — unreachable); **(b)** shoes printed and dry-fitted first, VHB last; **(c)** look-down-the-seam check before any caliper; **(d)** one side-ID witness hole per shoe so a swapped/mirrored shoe fails "absent"; **(e)** spot-faced hole mouths on the incline so the ruler reads local height; **(f)** optional full-height seam-cover strip later, once borders are measured; **(g)** `ams_mismatch_count` asserted at dispatch. Not adopted: toe-in — geometrically the alternative to a shared arc is a flat butt joint (R→∞, same parts).

### 3. Judgment calls

| Name | Value (mm) | Basis |
|---|---|---|
| R_FRONT | 1800 | [user-stated; matches Sceptre both models] |
| **T_EDGE_L / T_EDGE_R** | 20 / 22 | **<- MUST MEASURE**: placeholders from renders |
| **TAPER_L / TAPER_R** | 0 / 0 | **<- MUST MEASURE**: rear-cover rise 16→56 mm |
| **FACET** | 12 | **<- MUST MEASURE**: end chamfer width; PAD_INSET ≥ FACET+3 |
| DT | 2.0 | derived: T_EDGE_R − T_EDGE_L; sign from calipers only |
| ARC_RISE | 0.79 | derived: (56²−16²)/(2x1821) |
| SEAM_GAP | 2.0 | <- my choice. Keeps two imperfect end faces from rubbing; hides ±0.3 flush error. Touching or wider? OK? |
| PAD_INSET | 15 | <- my choice. Clears the rear end facet seen in renders. OK? |
| PAD_W x PAD_H | 40 x 120 | <- my choice. Peel resistance vs 0.11 in-pad arc residual; shrinks to 30 if the plain slab is <56. OK? |
| BRIDGE_Y_FROM_BOTTOM | 160 | <- my choice. Mid-height; raised if B30 rear OSD cluster is inside 100–220. OK? |
| SHOE_T_MIN | 9.0 | <- my choice. Thinnest shoe end; ≥ insert length + floor. OK? |
| SHOE_L / SHOE_R thickness | 11.00→11.79 / 9.00→9.79 | derived from placeholders; recomputed after measuring |
| INSERT_HOLE_D | 4.0 | [parts-db:M3-insert.hole_d] through-hole, from spine face |
| SPINE_HOLE_D | 3.4 | [parts-db:M3.clearance] x4 at (±36, ±40) |
| Screw head | 5.5 x 3.0 | [parts-db:M3 head_d/head_h]; no counterbore in a 6 mm plate |
| SPINE_X x Y x T | 120 x 120 x 6 | derived / my choice. Spans pads + 4 mm margin. OK? |
| RIB_H x RIB_W | 8 x 4 | <- my choice. Torsional stiffness (ESTIMATE ~0.2°/N·m). OK? |
| WITNESS_D / X / FLOOR_Z | 3.0 / ±17 / 2.0 | <- my choice. Shared floor makes wedge sign Tier 1. OK? |
| ID witness (per shoe) | Ø3.0 blind, side-specific position | <- my choice. Swapped shoe fails "absent". OK? |
| VHB_T | 1.1 | <- my choice. 3M 5952; not in parts-db; ±0.3 compliance budget. OK? |
| Material | Bambu PETG (green, AMS) | <- my choice. Creep margin beside a warm housing; PETG_generic calibration is `measured: null` — export will warn. PLA fallback. OK? |
| Parts | 3 (spine + 2 shoes, one shoe program, two param sets) | <- my choice. OK? |
| Orientation | all three flat on bed, spine/shoe interface down | <- my choice. Zero downward faces, no supports; shoe incline faces up. OK? |
| Arrangement | continuous 1800R arc | <- my choice pending your look-down-the-seam check. OK? |

### 4. What we cannot know from the web

1. **Look down the seam from above** (no caliper): even gap front-to-back = one arc, proceed; wedge = stop, report front and rear gap.
2. **T_EDGE_L, T_EDGE_R**: outside jaws over the inner edge, from the front *glass* (not the rim) to the rear cover, at 100, 160 and 220 mm up; jaws ≤16 mm in; to 0.05.
3. **TAPER_L, TAPER_R**: steel rule on edge along the rear cover from the inner edge inward at 160 mm; gap under the rule at 16 and 56 mm in.
4. **FACET**: distance from inner edge to where the rear becomes plain flat, both monitors.
5. **Keep-out survey**: pad zone 16–56 in, 100–220 up — plain? B30: height and inset of the rear OSD cluster at its lower-right corner. Both: distance to the nearest raised wing.
6. **Levelness**: rule across both top edges, butted at 2 mm, same tilt — offset in mm.
7. (For the optional cover strip) **BORDER** edge-to-first-lit-pixel and **RIM** height above glass, both inner edges.

### 5. Verification plan

Tier 1 (intent.json): spine `bbox_x/y/z` [120,120,14]; `plane_gap` [0,1]=6.0 and [1,2]=8.0; `cylinder_diameter` at the four (±36,±40) rank smallest [3.35,3.45] source parts-db:M3.clearance, `cylinder_depth` 6.0, `feature_count` band [3,4]=4; `watertight`; `volume` window that drops a missing rib; `unsupported_area` [0,1] at 40°; `dfm_violation_count` BLOCKER PETG_generic 0. Shoes: `bbox_z` per side (reads DT); `cylinder_depth` at the two witness pockets rank smallest (outer deeper by 0.85x(ARC_RISE−TAPER) — the one read of the wedge's **sign**); `cylinder_depth` at (0,±40) through-holes = T(0); `cylinder_diameter` [3.95,4.05] source parts-db:M3-insert.hole_d; `cylinder_diameter` at the ID witness with tol_xy 0.5; `plane_gap` [0,1]=2.0; `watertight`, `volume`, `unsupported_area`, `dfm_violation_count`. At dispatch: `ams_mismatch_count` 0 for PETG. Golden bbox/volume in `golden` only.

Tier 2 / ESTIMATE, stated not asserted: the shoe incline as an angle; in-pad 0.11 arc residual; spine torsional stiffness; every placeholder until calipers replace it. **Not verifiable by the repository at all:** that the assembled fronts are flush and the arc continuous — you check with a rule across the glass at three heights after fitting; the seam cover strip's pixel coverage.

Halting here. Confirm or correct each row before intent.json is written.
---

## Measurement sheet (2026-09-10, supersedes section 4 above)

The caliper instructions were drawn up as an illustrated page, `measure-guide.html` (published as the
artifact "B30–P30 Seam Survey"; the record sheet it writes is the artifact db document
`sheets/monitor-bridge`, version 2). A five-lens adversarial review of the first draft (55 confirmed
findings, `research/`) changed the method in four places, so the sheet's fields differ from section 4:

- **Thickness is read with the fixed jaw on a shim lying on the glass, never on the rim.** A jaw
  pivoting on a proud rim has no angular reference and the reading moves about 0.17 mm per degree.
  `T_glass = display − SHIM`; the shim is measured with the same caliper and recorded.
- **Tips at pencil marks 16 mm and 36 mm in, not "about 10 mm".** 10 mm is inside the expected facet
  (placeholder 12 mm), so the first-draft `T10` readings were taken on the chamfer. `T_EDGE` is
  defined at 16 mm, where the pad starts; the slope is `T36 − T16` and TAPER over 16→56 is
  extrapolated as `2 × (T36 − T16)` — an **ESTIMATE**, stated as such.
- **The arc check is a rule flat on the glass across the seam**, comparing the mid-gap with the same
  rule on one monitor (1.56 mm for a 150 mm rule on 1800R). The end-face gap test only works for
  radial end faces; end faces square to the chord open an 8 mm wedge at 20 mm depth on a *correct*
  shared arc. Both end-face gaps are still recorded, defined at the glass and at 15 mm depth.
- **The rear field is read as numbers**: `FACET` from the rear corner, and the gap under a 60 mm span
  of rule pressed at 36 mm in, at 16 and at 56 (0.1–0.3 at the ends is the housing's own 1821 mm
  curve). The first draft's 0.5 mm yes/no test would have passed a 0.4 mm ridge, above the VHB budget.

Station order was changed so the seam is opened once (2–5) and closed once (6–7), which is also the
assembly order. Added fields the design needs and the first draft lacked: `LEFT_IS` (which physical
screen Windows calls B30), `BORDER` (for the optional cover strip), `SHIM`, a repeat reading at
160 mm, `END_FACE`, `PORT_IN`, `MODEL_LABEL`, `GAP_STOP`, `ARRANGEMENT`, `SEAM_GAP_WANTED`.

### First-draft readings, saved 2026-09-10 19:49 UTC (kept as `sheets/monitor-bridge-v1`)

| Reading | B30 | P30 | Note |
|---|---|---|---|
| Max refresh offered | 100 | 190 | consistent with B30 = C305W-2560UN1, P30 = C305B-200UN family |
| Rim above glass | 1 | 1 | the "P30 edgeless" research claim looks wrong |
| Jaw on rim, tips ~10 mm in, 100/160/220 up | 15.0 | 15.0 | on the chamfer; superseded |
| Jaw on rim, jaws fully in (40 / 39.5 mm) | 20.9 | 20.9 | strong anchor for T at ~40 mm |
| Gap front / back as butted | 6 / 6 | | end faces parallel; stands probably touching |
| Level offset | 0 | | neither lower |
| Pad zone plain | yes | yes | |
| B30 buttons: top above bottom edge / in from edge | 10 / 80 | — | clear of the pad zone (100–220 up, 16–56 in) |

Identical numbers on both monitors suggest a shared chassis; the reworked sheet's repeat readings will
say whether that is real. `T10 = 15.0` versus `TDEEP = 20.9` is a 5.9 mm rise over 30 mm — a chamfer,
not a taper — which is exactly why the shallow reading moved to 16 mm.

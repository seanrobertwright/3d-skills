# Mutation protocol — imported mesh

The protocol table (`EXPECT`, `REASON`, `KIND`, `SOURCE`, `PARAMS_OVERRIDE`, `BUILD_OPTIONS`,
`patch`, `method_patch`, `EXTRA_ASSERTS`) is documented once, in
[`../../bearing-holder/mutations/README.md`](../../bearing-holder/mutations/README.md). Every
mutation here obeys it. `SOURCE` defaults to `"stl"`, which is right for this benchmark: it is
mesh-native and there is no STEP.

This file covers what is different about *this* benchmark.

## Why the broken mesh is generated rather than committed

`out/` is gitignored, because models are programs and outputs are rebuildable. A committed broken
STL would be an opaque binary whose defect nobody can read in a diff, and it would sit outside
that rule — you would have to load it into something to find out what was wrong with it, and a
reviewer would have to take the filename's word for it.

So the damage is code (ADR-12). `model.py` builds a known plate, deletes `BREAK_FACES` faces from
its top surface and reverses `FLIP_FACES` windings — the two breaks the spike measured — and then
repairs it. The break is chosen **geometrically**, not by raw face index: a mutation that changes
the pin or the tessellation renumbers every face, and a break keyed on `faces[10:13]` would
silently move somewhere else. A benchmark whose own baseline is flaky reads as a harness error
rather than as the design fault it is.

## Why "watertight" is not enough, and the assertion that carries the weight

A repair benchmark that asserted only `watertight` would score a bridged bore green. That is the
failure mode `trimesh.repair.fill_holes` documents on itself — it fills boundary holes "using
fans, which may result in bad answers if the holes are non-convex" — and a bore breaking a
surface is exactly a non-convex boundary. `bridged_bore` reproduces it: the mesh comes back
watertight and the section at (21, 0) comes back at `max_residual = 0.954 mm`, nineteen times the
circularity gate.

So the intent asserts both halves of a repair:

| The repair *worked* | The repair *changed nothing* |
|---|---|
| `watertight` | `left_bore_d`, `right_bore_d` |
| `solid_volume` | `bore_count`, `plate_thickness`, `plate_width` |

`solid_volume` is worth its own paragraph. It is asserted as `[1.0, null]` — a lower bound only,
which makes it a claim about **topology, not size**, and keeps it from smuggling in a golden
volume through the front door. An inside-out mesh is watertight, its winding is consistent, and
every bore on it sections as a perfect circle and measures Ø7.999. The sign of the enclosed
volume is the only thing that sees it, and the spike measured exactly that: **−571.14 mm³**, a
negative number `intent.check`'s `volume` kind would compare against a range without comment.
Delete this one assertion and `inverted_only` goes from caught to missed while every other line
of the report stays green.

## Why the DFM mutations live here

`dfm_thin_pin`, `dfm_unprintable_overhang` and `cosmetic_dfm_note` score `dfm.py` through the
ordinary `dfm_violation_count` measure kind and the ordinary harness (ADR-8). No second scoring
path, and the baseline-must-pass gate comes for free.

They are on **this** benchmark and not on `overhang-test`, and the reason is the point. Every
dimension of `overhang-test` is already asserted by its own `intent.json` — `max_overhang_deg`,
`unsupported_area`, `stem_diameter`, `flare_width` — so any parameter change there fails a
*dimensional* assertion, and the run tells you nothing about whether the DFM engine works. Such a
mutation would be caught with `dfm.py` deleted from the repository.

`PIN_D` exists precisely because nothing else constrains it. It is the only dimension on any
benchmark whose sole guardian is a printability rule, and that is what makes a DFM mutation
scoreable. **When reading a `-v` report, check that each `dfm_*` mutation failed on its
`dfm_blockers` line.** A `dfm_*` mutation failing on a dimensional line has stopped testing the
DFM engine.

## Why two `cosmetic_*` mutations and not one

Because there are two engines here and they fail false in different ways.

`cosmetic_more_facets` re-tessellates the same geometry five times finer. Every triangle, every
face index, the faces the break lands on and the boundary the repair fills are all different, and
the part is the part. A verifier that fails this cries wolf on every remesh, every re-export and
every file that came out of a different CAD package.

`cosmetic_dfm_note` adds a 40° flare — inside PLA's 45° threshold. It produces a real finding
(197.63 mm² past the 30° reporting angle, against a 50 mm² threshold) and that finding is a
**WARNING**. A WARNING is not a gate. If this flips to FAIL, either every severity has quietly
become a blocker or somebody tightened `max_overhang_deg` past what PLA needs, and the engine now
refuses parts that print. Advice and refusal are different acts; severity is what separates them.

## `inverted_only` expects FAIL for an unusual reason

It is the only mutation here that skips the repair on a mesh that is **already watertight**.
Nothing is deleted; every face is simply wound backwards. It exists to score one assertion
(`solid_volume`, above) and to guard the repair op ordering, which was measured getting this
wrong: fixing inversion *before* filling holes asks for the sign of the enclosed volume of an
open surface, which does not have one. Run in that order the pipeline returned a watertight mesh
of **−23065.76 mm³** — closed, plausible, and inside out, with every upward face reading as a 90°
overhang to the DFM engine downstream.

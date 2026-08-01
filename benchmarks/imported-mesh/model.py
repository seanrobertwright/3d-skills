"""Benchmark 6 -- imported mesh (**Tier 1**). The repair path.

A part arrives from outside as a broken mesh, gets repaired, and must still be the part it was.
This benchmark builds that whole situation deterministically: build a known plate, break it in
the two ways the spike measured (S10), repair it, and hand the repaired mesh to the verifier.

**The broken mesh is generated, not committed** (ADR-12). ``out/`` is gitignored because models
are programs and outputs are rebuildable; a committed broken STL would be an opaque binary whose
defect nobody can read in a diff, and it would sit outside that rule. So the damage is code:

* ``BREAK_FACES`` faces are deleted from the plate's top surface -- chosen *geometrically*, not
  by raw index, so the break stays in the same place when a mutation changes the tessellation or
  the pin. S10: 3 deleted faces -> 7 broken faces, euler -8, not watertight.
* ``FLIP_FACES`` faces have their winding reversed. S10: 200 reversed -> winding inconsistent and
  volume **-934.24 mm3**, a negative number ``intent.check``'s ``volume`` kind would happily
  compare against a range.

Mesh-native, following ``benchmarks/gyroid-vase/model.py``: there is no STEP, because the thing
under test is a *mesh* that arrived from outside and has no BREP behind it.

The intent asserts both halves of a repair, which is the point of the benchmark:

* that repair **worked** -- the mesh is watertight;
* that repair **changed nothing** -- both Ø8 bores are still Ø8, there are still two of them, the
  plate is still 10mm thick and 60mm wide.

A mutation that skips the repair fails the first. A mutation that over-repairs fails the second.
"Watertight" alone is not a repair verdict: a bridged bore is watertight.

``PIN_D`` is the one dimension on this part that **no** assertion in ``intent.json`` constrains.
That is deliberate and it is what makes a DFM mutation scoreable -- see ``mutations/README.md``.

All dimensions are millimetres.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from harness import load_json  # noqa: E402

# Overhang variants the DFM mutations use. `steep` is past the 45 deg support threshold and is a
# BLOCKER; `mild` is inside it and produces a WARNING only, which is what proves a WARNING does
# not gate a verdict.
#
# `cap` is not decoration. A bare flared cone meets its own top face at a knife edge -- thousandths
# of a millimetre of material at the rim -- which is a real and correct min_feature BLOCKER, and it
# would fire on *both* variants and make the mild one unable to isolate the overhang rule. The
# collar gives the rim a printable wall so each mutation tests the one thing it names. No figure is
# quoted because the geometry that produced one is not the geometry that ships.
OVERHANGS = {
    "steep": {"angle_deg": 75.0, "rise": 4.0, "cap": 2.5},
    "mild": {"angle_deg": 40.0, "rise": 6.0, "cap": 2.5},
}


def load_params():
    return load_json(HERE / "params.json")


def _shape(p, overhang):
    import math

    from build123d import Align, Box, BuildPart, Cone, Cylinder, Locations, Mode

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    plate_t, pin_h = p["PLATE_T"], p["PIN_H"]
    pin_r = p["PIN_D"] / 2.0

    with BuildPart() as part:
        Box(p["PLATE_X"], p["PLATE_Y"], plate_t, align=bottom)
        with Locations((-p["HOLE_X"], 0, 0), (p["HOLE_X"], 0, 0)):
            Cylinder(radius=p["HOLE_D"] / 2.0, height=plate_t * 3.0, mode=Mode.SUBTRACT)
        with Locations((0, 0, plate_t)):
            Cylinder(radius=pin_r, height=pin_h, align=bottom)
        if overhang:
            spec = OVERHANGS[overhang]
            run = spec["rise"] * math.tan(math.radians(spec["angle_deg"]))
            flare_r = pin_r + run
            with Locations((0, 0, plate_t + pin_h)):
                Cone(
                    bottom_radius=pin_r,
                    top_radius=flare_r,
                    height=spec["rise"],
                    align=bottom,
                )
            with Locations((0, 0, plate_t + pin_h + spec["rise"])):
                Cylinder(radius=flare_r, height=spec["cap"], align=bottom)
    return part.part


def top_face_indices(mesh, z_top: float) -> np.ndarray:
    """Faces lying in the plate's top plane, in index order.

    Geometric rather than by raw face index: a mutation that changes the pin or the tessellation
    renumbers every face, and a break keyed on ``faces[10:13]`` would silently move somewhere
    else -- which makes the benchmark's own baseline flaky, and a flaky baseline reads as a
    harness error rather than as the design fault it is.
    """
    tri = mesh.triangles
    flat_at_top = (np.abs(tri[:, :, 2] - z_top) < 1e-6).all(axis=1)
    upward = mesh.face_normals[:, 2] > 0.999
    return np.flatnonzero(flat_at_top & upward)


def bore_wall_faces(mesh, cx: float, cy: float, radius: float, z_lo=None, z_hi=None) -> np.ndarray:
    """Faces lying on the wall of the bore at ``(cx, cy)``, optionally within a Z band.

    Lives here rather than in each mutation so that "which faces are the bore" is defined once.
    A mutation that re-derived it would be free to drift away from the geometry it is damaging.
    """
    tri = mesh.triangles
    offset = np.hypot(tri[:, :, 0] - cx, tri[:, :, 1] - cy)
    on_wall = (np.abs(offset - radius) <= 0.05).all(axis=1)
    if z_lo is not None:
        on_wall &= (tri[:, :, 2] >= z_lo).all(axis=1)
    if z_hi is not None:
        on_wall &= (tri[:, :, 2] <= z_hi).all(axis=1)
    return np.flatnonzero(on_wall)


def drop_faces(mesh, indices):
    keep = np.ones(len(mesh.faces), dtype=bool)
    keep[np.asarray(indices, dtype=np.int64)] = False
    out = mesh.copy()
    out.update_faces(keep)
    return out


def tessellated(p, overhang=False, tess_tol: float = 0.01):
    """The undamaged mesh, before any break. The entry point a ``patch()`` mutation starts from."""
    from threedp.features import _tessellate

    return _tessellate(_shape(p, overhang), tolerance=tess_tol)


def break_mesh(mesh, delete: int, flip: int):
    """Damage a mesh the two ways the spike measured. Deterministic, and it says what it did."""
    import trimesh

    working = mesh.copy()
    if delete > 0:
        candidates = top_face_indices(working, float(working.bounds[1][2]))
        if len(candidates) == 0:
            candidates = np.arange(len(working.faces))
        victims = candidates[: min(delete, max(len(candidates) - 1, 0))]
        keep = np.ones(len(working.faces), dtype=bool)
        keep[victims] = False
        working.update_faces(keep)

    if flip > 0:
        faces = np.array(working.faces)
        n = min(flip, len(faces))
        faces[:n] = faces[:n][:, ::-1]
        working = trimesh.Trimesh(vertices=working.vertices, faces=faces, process=False)
    return working


def build(p, repair_it: bool = True, overhang=False, tess_tol: float = 0.01):
    """Build the plate, break it, and -- unless told otherwise -- repair it.

    ``repair_it=False`` is a real option, not a hack: it is what an imported mesh looks like
    before anyone touches it, and it is what the ``skipped_repair`` mutation exercises.
    ``overhang`` adds an unsupported flare (``"steep"``/True, or ``"mild"``), which is what the
    DFM mutations exercise. ``tess_tol`` re-tessellates the same geometry finer, which changes
    every triangle and must change no verdict.
    """
    from threedp import repair
    from threedp.features import _tessellate

    if overhang is True:
        overhang = "steep"
    if overhang and overhang not in OVERHANGS:
        raise ValueError(f"unknown overhang {overhang!r}; valid: {sorted(OVERHANGS)}")

    mesh = _tessellate(_shape(p, overhang), tolerance=tess_tol)
    broken = break_mesh(mesh, int(p["BREAK_FACES"]), int(p["FLIP_FACES"]))
    if not repair_it:
        return broken

    result = repair.repair(broken)
    # The result is *not* consulted for a verdict here. intent.check is the verdict, and letting
    # the model refuse to emit geometry would hide a bad repair from the very harness whose job
    # is to score whether that bad repair gets caught.
    return result.mesh


def main() -> int:
    import argparse

    from threedp import features, intent
    from threedp.compensate import resolve
    from threedp.io import export

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--source", default="stl", choices=("stl", "3mf"))
    ap.add_argument("--no-repair", action="store_true", help="export the broken mesh as imported")
    args = ap.parse_args()

    mesh = build(resolve(load_params(), None), repair_it=not args.no_repair)
    # No "step" in nominal: this benchmark is a mesh that arrived from outside, and there is no
    # BREP to write one from.
    print(export(mesh, HERE / "out" / "part", nominal=(), compensated=("stl", "3mf")))

    if not args.check:
        return 0
    report = intent.check(
        features.extract(HERE / "out" / f"part.{args.source}"), HERE / "intent.json"
    )
    print()
    print(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

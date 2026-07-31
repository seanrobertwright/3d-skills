"""Benchmark 1 -- L-bracket with counterbored M4 holes (Tier 1). Constraint solving, hole placement.

The counterbore/plate-thickness conflict is the point of this part. A real M4 socket head is
**4.0mm tall** (parts-db:M4.head_h); counterboring 4mm into a 4mm plate leaves *zero* material
and the bracket tears out around the screw. The spike caught this unprompted while authoring
(PRD 15.1), so the plate is 6mm and ``intent.json`` asserts the material remaining below the
counterbore -- turning a lucky catch into a mechanical one.

All dimensions are millimetres.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from harness import load_json, run_model_cli  # noqa: E402


def load_params():
    return load_json(HERE / "params.json")


def build(p, counterbore: bool = True):
    from build123d import Align, Box, BuildPart, Cylinder, Locations, Mode, Plane

    corner = (Align.CENTER, Align.MIN, Align.MIN)
    top = (Align.CENTER, Align.CENTER, Align.MAX)

    with BuildPart() as part:
        # the two legs of the L, sharing the origin corner
        Box(p["WIDTH"], p["THICK"], p["LEG_UP"], align=corner)
        Box(p["WIDTH"], p["LEG_OUT"], p["THICK"], align=corner)

        # base holes: axis along Z, counterbored from the top face
        base_holes = [(-p["HOLE_X"], p["BASE_HOLE_Y"], 0), (p["HOLE_X"], p["BASE_HOLE_Y"], 0)]
        with Locations(*base_holes):
            Cylinder(radius=p["HOLE_D"] / 2, height=p["THICK"] * 4, mode=Mode.SUBTRACT)
        if counterbore:
            with Locations(*[(x, y, p["THICK"]) for x, y, _ in base_holes]):
                Cylinder(
                    radius=p["CBORE_D"] / 2,
                    height=p["CBORE_DEPTH"],
                    align=top,
                    mode=Mode.SUBTRACT,
                )

        # wall holes: axis along Y, plain clearance. Deliberately not asserted dimensionally --
        # a Z-scan cannot see a Y-axis bore, and claiming Tier 1 for it would be a lie (ADR-4).
        with Locations(
            Plane.XZ * Plane(origin=(-p["HOLE_X"], p["WALL_HOLE_Z"], 0)),
            Plane.XZ * Plane(origin=(p["HOLE_X"], p["WALL_HOLE_Z"], 0)),
        ):
            Cylinder(radius=p["HOLE_D"] / 2, height=p["THICK"] * 4, mode=Mode.SUBTRACT)

    return part.part


if __name__ == "__main__":
    raise SystemExit(run_model_cli(HERE, build, load_params, __doc__))

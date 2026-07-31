"""Benchmark 3 -- 608 bearing press-fit holder (Tier 1). The fit case.

This is the part that carried three genuine defects in the PRD spike, all of which passed a
bounding-box check, had a plausible volume, and rendered cleanly (PRD 15.2):

1. pocket 6.5mm deep instead of 7.0 -- a fillet had eaten the depth
2. mounting holes silently not counterbored
3. a retaining lip 5x its intended thickness

The correct model below has ``POCKET_DEPTH = 7.0``, ``LIP = 1.0``, and mount holes that really
are counterbored. Those three defects are re-injected as mutations and must be caught.

Geometry: a rectangular base with a cylindrical boss. The bearing drops into a pocket in the top
of the boss and seats on an annular lip; a clearance hole below the lip passes the shaft.

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
    """Build the holder.

    ``counterbore=False`` is a real design option (plain through-holes for a pan-head screw) and
    is what the ``dropped_cbore`` mutation exercises -- a *structural* defect that no parameter
    value can express.
    """
    from build123d import Align, Axis, Box, BuildPart, Cylinder, Locations, Mode, fillet

    base_t = p["BASE_T"]
    boss_h = p["BOSS_H"]
    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    top = (Align.CENTER, Align.CENTER, Align.MAX)

    with BuildPart() as part:
        Box(p["BASE_X"], p["BASE_Y"], base_t, align=bottom)
        if p["FILLET"] > 0:
            fillet(part.edges().filter_by(Axis.Z), radius=p["FILLET"])

        Cylinder(radius=p["BODY_OD"] / 2, height=boss_h, align=bottom)

        # bearing pocket, opening at the top of the boss
        with Locations((0, 0, boss_h)):
            Cylinder(
                radius=p["BORE"] / 2,
                height=p["POCKET_DEPTH"],
                align=top,
                mode=Mode.SUBTRACT,
            )

        # shaft clearance below the pocket; what is left of the floor is the retaining lip
        Cylinder(radius=p["BORE"] / 2 - p["LIP"], height=boss_h * 3, mode=Mode.SUBTRACT)

        mounts = [(-p["MOUNT_X"], 0, 0), (p["MOUNT_X"], 0, 0)]
        with Locations(*mounts):
            Cylinder(radius=p["MOUNT_HOLE_D"] / 2, height=base_t * 3, mode=Mode.SUBTRACT)

        if counterbore:
            with Locations(*[(x, y, base_t) for x, y, _ in mounts]):
                Cylinder(
                    radius=p["CBORE_D"] / 2,
                    height=p["CBORE_DEPTH"],
                    align=top,
                    mode=Mode.SUBTRACT,
                )

    return part.part


if __name__ == "__main__":
    raise SystemExit(run_model_cli(HERE, build, load_params, __doc__))

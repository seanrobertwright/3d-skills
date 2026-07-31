"""Benchmark 4 -- deliberate 60 deg overhang (Tier 1). Printability detection.

An outward-flaring cone whose underside sits at exactly ``ANGLE_DEG`` from vertical, with
``run = rise * tan(angle)``. This is the spike-6 geometry, which measured an area-weighted
**60.00 deg** and **1339.09 mm2** of unsupported area against an analytic lateral surface of
1339.6 mm2.

Two traps this part exists to keep caught:

* the flat bottom rests on the build plate and is **not** a 90 deg overhang;
* the vertical stem is 0 deg from vertical, which is the normal case and not a defect.

Angles are measured **from vertical**: 0 is a vertical wall, 90 a horizontal ceiling.

All dimensions are millimetres.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from harness import load_json, run_model_cli  # noqa: E402


def load_params():
    return load_json(HERE / "params.json")


def build(p):
    from build123d import Align, BuildPart, Cone, Cylinder, Locations

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    run = p["RISE"] * math.tan(math.radians(p["ANGLE_DEG"]))

    with BuildPart() as part:
        Cylinder(radius=p["BOTTOM_R"], height=p["STEM_H"], align=bottom)
        with Locations((0, 0, p["STEM_H"])):
            Cone(
                bottom_radius=p["BOTTOM_R"],
                top_radius=p["BOTTOM_R"] + run,
                height=p["RISE"],
                align=bottom,
            )
    return part.part


if __name__ == "__main__":
    raise SystemExit(run_model_cli(HERE, build, load_params, __doc__))

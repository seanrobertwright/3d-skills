"""Benchmark 2 -- enclosure + lid with heat-set bosses (Tier 1). Walls and mating tolerance.

Both bodies are built into one file, laid out side by side exactly as they would be printed. The
mating interface is the boss system, and every dimension in it is cited rather than invented:

* the insert hole is ``parts-db:M3-insert.hole_d`` -- too large and the insert spins under
  torque, too small and it splits the boss going in;
* the boss OD is ``parts-db:M3-insert.min_boss_od``, which is what keeps 2mm of wall around the
  insert;
* the lid's screw holes are ``parts-db:M3.clearance``.

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


def build(p, bosses: bool = True):
    from build123d import Align, Box, BuildPart, Cylinder, Locations, Mode

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    top = (Align.CENTER, Align.CENTER, Align.MAX)
    boss_xy = [(sx * p["BOSS_X"], sy * p["BOSS_Y"]) for sx in (-1, 1) for sy in (-1, 1)]

    with BuildPart() as part:
        # --- enclosure body ---------------------------------------------------------------
        Box(p["OUTER_X"], p["OUTER_Y"], p["HEIGHT"], align=bottom)
        with Locations((0, 0, p["FLOOR"])):
            Box(
                p["OUTER_X"] - 2 * p["WALL"],
                p["OUTER_Y"] - 2 * p["WALL"],
                p["HEIGHT"],
                align=bottom,
                mode=Mode.SUBTRACT,
            )

        if bosses:
            with Locations(*[(x, y, 0) for x, y in boss_xy]):
                Cylinder(radius=p["BOSS_OD"] / 2, height=p["BOSS_H"], align=bottom)
            with Locations(*[(x, y, p["BOSS_H"]) for x, y in boss_xy]):
                Cylinder(
                    radius=p["INSERT_HOLE_D"] / 2,
                    height=p["INSERT_DEPTH"],
                    align=top,
                    mode=Mode.SUBTRACT,
                )

        # --- lid, laid beside the body ----------------------------------------------------
        with Locations((0, p["LID_OFFSET_Y"], 0)):
            Box(p["OUTER_X"], p["OUTER_Y"], p["LID_THICK"], align=bottom)
        with Locations(*[(x, y + p["LID_OFFSET_Y"], 0) for x, y in boss_xy]):
            Cylinder(radius=p["LID_HOLE_D"] / 2, height=p["LID_THICK"] * 4, mode=Mode.SUBTRACT)

    return part.part


if __name__ == "__main__":
    raise SystemExit(run_model_cli(HERE, build, load_params, __doc__))

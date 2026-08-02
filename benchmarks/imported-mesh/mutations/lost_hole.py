"""The whole wall of the left-hand bore is missing, and the repair plugs the hole.

Where ``bridged_bore`` leaves a bore that is no longer round, this one removes the bore's entire
cylindrical surface. The two circular boundaries left behind -- one where the wall met the top
face, one where it met the bottom -- are fanned shut, and the result is a solid plate with one
hole in it instead of two.

**An absent feature is the defect**, the same rule as ``intent.py`` and PRD 15.2 defect 2. A
checker that skipped features it could not find would score this green: there is nothing wrong
with the bore it *can* measure.

Two assertions must catch it, and they catch it differently: ``left_bore_d`` because the feature
it names is not there, and ``bore_count`` because two became one. Either alone would be enough;
both is the point, since a Ø8 bore that moved somewhere else entirely would satisfy the count.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPECT = "FAIL"
REASON = "the repair consumed one of the two bores; a plate with one hole is not this part"
KIND = "geometry"


def patch(model, params):
    from threedp import repair

    mesh = model.tessellated(params)
    mesh = model.break_mesh(mesh, int(params["BREAK_FACES"]), int(params["FLIP_FACES"]))

    wall = model.bore_wall_faces(mesh, -params["HOLE_X"], 0.0, params["HOLE_D"] / 2.0)
    if len(wall) == 0:
        raise AssertionError("no bore-wall faces selected; this mutation is damaging nothing")
    return repair.repair(model.drop_faces(mesh, wall)).mesh

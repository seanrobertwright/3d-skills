"""A quadrant of the right-hand bore's wall is missing, and ``fill_holes`` fans it shut.

This is ADR-9's entire reason to exist, reproduced. ``trimesh.repair.fill_holes`` documents that
it fills boundary holes "using fans, which may result in bad answers if the holes are
non-convex", and a bore breaking a surface is exactly a non-convex boundary. The fan throws a
flat patch across the mouth of the damage, chord-wise through the bore.

The result is **watertight**, which is what a naive repair reports as success. Measured on the
quadrant this mutation actually removes: the section at (21, 0) comes back with
``max_residual = 0.9019mm``, eighteen times the circularity gate, so the ruler refuses to report a
diameter for it at all -- and refusing is the correct answer, because the shape at (21, 0) is no
longer a circle and no single diameter describes it.

The verifier must catch this on ``right_bore_d`` and ``bore_count``: *dimensional* assertions.
A run where this fails on ``watertight`` instead would mean the fan never happened and the
mutation is no longer testing what it claims to test.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPECT = "FAIL"
REASON = "a watertight mesh whose bore the repair bridged is not a repaired part"
KIND = "geometry"


def patch(model, params):
    """Break the mesh the usual way, then damage one bore wall as well, then repair."""
    from threedp import repair

    mesh = model.tessellated(params)
    mesh = model.break_mesh(mesh, int(params["BREAK_FACES"]), int(params["FLIP_FACES"]))

    x = params["HOLE_X"]
    wall = model.bore_wall_faces(mesh, x, 0.0, params["HOLE_D"] / 2.0)
    corner = mesh.triangles[wall]
    # One quadrant, not one half: half the wall leaves a sliver the DFM engine flags as a thin
    # feature, and this mutation must fail on a dimension so that it is scoring the ruler.
    quadrant = wall[((corner[:, :, 0] >= x) & (corner[:, :, 1] >= 0.0)).all(axis=1)]
    if len(quadrant) == 0:
        raise AssertionError("no bore-wall faces selected; this mutation is damaging nothing")
    return repair.repair(model.drop_faces(mesh, quadrant)).mesh

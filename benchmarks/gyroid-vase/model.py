"""Benchmark 5 -- gyroid vase (**Tier 2**). The organic path.

**This part is deliberately, openly unverifiable in dimensional terms.** It is a known and
accepted gap (PRD 6.2), not an oversight. A gyroid has no bores, no pockets and no prismatic
walls -- nothing a circle fit or a plane query can get hold of -- so ``intent.json`` claims only
topology and statistics, and every dimensional number it reports is labelled **ESTIMATE**.

There is no STEP. A marching-cubes surface has no BREP behind it, and writing 260k triangles
into a STEP file would produce something technically CAD-shaped that describes nothing. The
organic path exports meshes only, and says so.

Two things learned the hard way:

* ``sdf`` writes a **progress bar to stdout**. Never parse its stdout as data.
* ``sdf`` emits a triangle **soup** -- vertices are not shared between triangles, so the raw
  mesh reads as non-watertight. Merging coincident vertices makes it watertight with zero broken
  edges; this is verified here rather than assumed.

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


def load_params():
    return load_json(HERE / "params.json")


def _gyroid(period: float, thickness: float):
    """The gyroid triply-periodic minimal surface, thickened into a solid band."""
    from sdf import sdf3

    k = 2.0 * np.pi / period

    @sdf3
    def surface():
        def f(p):
            x, y, z = p[:, 0] * k, p[:, 1] * k, p[:, 2] * k
            g = np.cos(x) * np.sin(y) + np.cos(y) * np.sin(z) + np.cos(z) * np.sin(x)
            return (np.abs(g) - thickness).reshape((-1, 1))

        return f

    return surface()


def build(p):
    """Generate the vase and return a watertight ``trimesh.Trimesh``."""
    import tempfile

    import trimesh
    from sdf import cylinder, slab

    r, h, wall = p["RADIUS"], p["HEIGHT"], p["WALL"]
    band = (cylinder(r) - cylinder(r - wall)) & slab(z0=p["BASE"], z1=h)
    base = cylinder(r) & slab(z0=0, z1=p["BASE"])
    rim = (cylinder(r) - cylinder(r - wall)) & slab(z0=h - p["RIM"], z1=h)
    vase = (_gyroid(p["PERIOD"], p["GYROID_T"]) & band) | base | rim

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.stl"
        vase.save(
            str(raw),
            step=p["STEP"],
            bounds=((-r - 1, -r - 1, -1), (r + 1, r + 1, h + 1)),
        )
        mesh = trimesh.load_mesh(str(raw))

    # Stitch the triangle soup. Without this the mesh is non-watertight purely because no two
    # triangles share a vertex -- a repair, not a fudge, and it is verified immediately.
    mesh.merge_vertices(digits_vertex=5)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    if not mesh.is_watertight:
        broken = len(trimesh.repair.broken_faces(mesh))
        raise RuntimeError(
            f"the generated vase is not watertight after merging ({broken} broken faces). "
            f"Try a smaller STEP or a larger GYROID_T; do not export it as-is."
        )
    return mesh


def main() -> int:
    import argparse

    from threedp import features, intent
    from threedp.io import export

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    from threedp.compensate import resolve

    params = load_params()
    mesh = build(resolve(params, None))
    # Note: no "step" in nominal -- there is no BREP to write one from.
    result = export(mesh, HERE / "out" / "part", nominal=(), compensated=("stl", "3mf"))
    print(result)

    if not args.check:
        return 0
    report = intent.check(features.extract(HERE / "out" / "part.stl"), HERE / "intent.json")
    print()
    print(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

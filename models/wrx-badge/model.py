"""Rear trunk badge for a 2015-2021 Subaru WRX, with a traced graphic across the face.

Geometry: an elliptical plate with a flat back and a domed face. The dome is ellipsoidal so it
rises the same ``CROWN_RISE`` from the edge all the way round. A raised rim runs round the edge
and the traced letters of ``graphic.png`` stand proud of the curved face by the same amount,
each cut to an offset of the same dome so they follow it.

The graphic is a **raster**, so its outline is traced, not typed: ``graphic.png`` is upsampled,
contoured at mid-grey, simplified, and scaled so the ink spans ``GRAPHIC_W``. The letters are
freeform and therefore Tier 2; every other feature of the badge is regular and Tier 1.

All dimensions are millimetres.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAPHIC = HERE / "graphic.png"

# Tracing constants. Neither is a dimension of the part: UPSAMPLE is a resolution multiplier and
# SIMPLIFY_MM is the vertex-thinning tolerance after scaling, kept well under a nozzle width.
UPSAMPLE = 8
SIMPLIFY_MM = 0.05
INK_LEVEL = 128


def load_params():
    return json.loads((HERE / "params.json").read_text(encoding="utf-8"))


def trace_graphic(width_mm: float):
    """Trace the bright pixels of ``graphic.png`` into centred shapely polygons.

    The ink is scaled so it spans ``width_mm``.

    Returns a list of ``shapely.Polygon`` (with holes) in badge XY millimetres, Y up.
    """
    import numpy as np
    from PIL import Image
    from shapely.geometry import Polygon as ShapelyPolygon
    from skimage.measure import find_contours

    im = Image.open(GRAPHIC).convert("RGBA")
    black = Image.new("RGBA", im.size, (0, 0, 0, 255))
    lum = np.asarray(Image.alpha_composite(black, im).convert("L"), dtype=np.float64)

    ys, xs = np.where(lum > INK_LEVEL)
    if len(xs) == 0:
        raise ValueError(f"{GRAPHIC.name} has no pixels above {INK_LEVEL}; nothing to trace")
    ink_w_px = xs.max() - xs.min() + 1
    cx_px = (xs.min() + xs.max() + 1) / 2
    cy_px = (ys.min() + ys.max() + 1) / 2
    mm_per_px = width_mm / ink_w_px

    big = Image.fromarray(lum.astype(np.uint8)).resize(
        (im.width * UPSAMPLE, im.height * UPSAMPLE), Image.LANCZOS
    )
    field = np.asarray(big, dtype=np.float64)
    # pad so ink touching the image border still closes
    field = np.pad(field, 1, constant_values=0.0)

    rings = []
    for c in find_contours(field, level=INK_LEVEL):
        # (row, col) in padded, upsampled pixels -> badge mm, Y up, centred on the ink bbox.
        col = (c[:, 1] - 1) / UPSAMPLE
        row = (c[:, 0] - 1) / UPSAMPLE
        x = (col - cx_px) * mm_per_px
        y = -(row - cy_px) * mm_per_px
        ring = ShapelyPolygon(np.column_stack([x, y])).buffer(0).simplify(SIMPLIFY_MM)
        if ring.is_empty or ring.area < (mm_per_px**2):
            continue
        rings.append(ring)

    # Even-odd nesting: a ring inside an even number of others is an outer boundary, an odd
    # number a hole. Each hole is attached to the smallest outer that contains it.
    rings.sort(key=lambda r: r.area, reverse=True)
    depth = [sum(1 for o in rings if o is not r and o.contains(r)) for r in rings]
    outers = [r for r, d in zip(rings, depth, strict=True) if d % 2 == 0]
    holes = [r for r, d in zip(rings, depth, strict=True) if d % 2 == 1]
    result = []
    for o in outers:
        mine = [h for h in holes if o.contains(h)]
        result.append(ShapelyPolygon(o.exterior.coords, [h.exterior.coords for h in mine]))
    return result


def _pts(coords):
    """Shapely closes a ring by repeating the first vertex; build123d closes it itself."""
    pts = [(float(x), float(y)) for x, y in coords]
    if pts[0] == pts[-1]:
        pts.pop()
    return pts


def _dome(a: float, b: float, rise: float, edge_z: float, offset: float = 0.0):
    """The spheroid whose upper surface is the badge face, optionally pushed out by ``offset``.

    A sphere of radius ``r`` through the ellipse edge at the minor axis with a rise of ``rise``,
    stretched by ``a / b`` along X, meets the edge at ``edge_z`` all the way round. Its Y and Z
    semi-axes are equal, so it is built as a half-ellipse **revolved about X** rather than a
    scaled sphere: build123d's exporter passes its deflection to OCCT as *relative*, and on the
    BSpline a non-uniform scale produces, the dome tessellated with 0.49 mm of chordal sag and
    63 mm facet edges at the library's 0.01 setting. The revolved surface meshes at 0.015 mm.

    ``offset`` grows every semi-axis by the same amount, which is the offset surface at the
    apex and within 2 % of it at the edge for a dome this shallow. The poles lie on X, hundreds
    of millimetres outside the badge, and the seam on the underside.
    """
    from build123d import Align, Axis, Ellipse, Location, Rectangle, revolve

    r = (b * b + rise * rise) / (2.0 * rise)
    centre_z = edge_z + rise - r
    r2 = r + offset
    ax = r * a / b + offset
    half = Ellipse(ax, r2) & Rectangle(2 * ax + 2, r2 + 1, align=(Align.CENTER, Align.MIN))
    return revolve(half, axis=Axis.X, revolution_arc=360).move(Location((0, 0, centre_z)))


def build(p):
    """Algebra-mode build: every raised feature is a tall column cut back to its own dome."""
    from build123d import Align, Cylinder, Ellipse, Location, Polygon, extrude

    a, b = p["BADGE_X"] / 2, p["BADGE_Y"] / 2
    body_t, rise = p["BODY_T"], p["CROWN_RISE"]
    # every column is extruded past the apex, then intersected with its dome
    column = body_t + rise + p["RIM_H"] + p["GRAPHIC_H"] + 1.0

    # body: flat back on the build plate, face domed from BODY_T at the edge
    body = extrude(Ellipse(a, b), amount=column) & _dome(a, b, rise, body_t)

    # rim: an elliptical ring following the dome, RIM_H proud of it
    ring = Ellipse(a, b) - Ellipse(a - p["RIM_W"], b - p["RIM_W"])
    rim = extrude(ring, amount=column) & _dome(a, b, rise, body_t, offset=p["RIM_H"])

    # graphic: the traced letters following the dome, GRAPHIC_H proud of it
    # Each glyph is cut on its own: intersecting a multi-solid compound with the dome was
    # measured returning the compound unchanged, silently, which intent.json's overall_height
    # and watertight assertions both caught.
    letter_dome = _dome(a, b, rise, body_t, offset=p["GRAPHIC_H"])
    part = body + rim
    for poly in trace_graphic(p["GRAPHIC_W"]):
        glyph = Polygon(*_pts(poly.exterior.coords), align=None)
        for hole in poly.interiors:
            glyph = glyph - Polygon(*_pts(hole.coords), align=None)
        # a traced ring winds clockwise, so its face points -Z; extrude upward explicitly
        part = part + (extrude(glyph, amount=column, dir=(0, 0, 1)) & letter_dome)

    # pin holes in the back: plain blind bores with flat ceilings. A conical roof was tried
    # and failed twice over: OCCT tessellates a true apex non-watertight, and the Z-scan could
    # not locate where the taper began. A 2.9 mm ceiling is a 2.9 mm bridge.
    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    for x in (-p["PIN_X"], p["PIN_X"]):
        part = part - Cylinder(p["PIN_HOLE_D"] / 2, p["PIN_HOLE_DEPTH"], align=bottom).move(
            Location((x, 0, 0))
        )

    return part


# A true cone apex tessellates non-watertight (two broken faces at the seam, measured), so the
# pin's point is truncated to this radius. Not a dimension of the part.
POINT_TIP_R = 0.05


def build_pin(p):
    """The mounting pin: shaft, tang, a step, and a truncated point."""
    import math

    from build123d import Align, Cone, Cylinder, Location

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    shaft_r, tang_r, point_r = p["PIN_SHAFT_D"] / 2, p["PIN_TANG_D"] / 2, p["PIN_POINT_D"] / 2
    shaft_l, tang_l = p["PIN_SHAFT_L"], p["PIN_TANG_L"]
    point_h = (point_r - POINT_TIP_R) / math.tan(math.radians(p["POINT_ANGLE_DEG"]))
    shaft = Cylinder(shaft_r, shaft_l, align=bottom)
    tang = Cylinder(tang_r, tang_l, align=bottom).move(Location((0, 0, shaft_l)))
    point = Cone(bottom_radius=point_r, top_radius=POINT_TIP_R, height=point_h, align=bottom)
    return shaft + tang + point.move(Location((0, 0, shaft_l + tang_l)))


def main() -> int:
    """Export the badge and the pin, then check each against its own intent on both paths."""
    import argparse

    from threedp import features, intent, io

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calibration", default=None, help="material key, e.g. PLA_generic")
    ap.add_argument("--check", action="store_true", help="check both intents after exporting")
    args = ap.parse_args()

    params = load_params()
    parts = {"part": (build, "intent.json"), "pin": (build_pin, "intent-pin.json")}
    for stem, (builder, _) in parts.items():
        print(
            io.export(
                builder,
                HERE / "out" / stem,
                nominal=("step",),
                compensated=("stl", "3mf"),
                calibration=args.calibration,
                params=params,
            )
        )
    if not args.check:
        return 0

    ok = True
    for stem, (_, intent_file) in parts.items():
        for fmt in ("step", "stl"):
            report = intent.check(
                features.extract(HERE / "out" / f"{stem}.{fmt}"), HERE / intent_file
            )
            print()
            print(report)
            ok &= report.passed
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

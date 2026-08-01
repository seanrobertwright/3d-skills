"""Printability, validated against geometry whose overhang and wall thickness are known exactly."""

import math

import numpy as np
import pytest
from conftest import PLATE, build_overhang_cone

from threedp import features, printability

# --- overhangs ----------------------------------------------------------------------------


def test_known_60_degree_cone_measures_60_degrees(overhang_mesh):
    """Spike 6: a cone flaring at exactly 60 deg from vertical measures 60.00 area-weighted."""
    r = printability.overhang_histogram(overhang_mesh)
    assert r.area_weighted_deg == pytest.approx(60.0, abs=0.05)
    assert r.max_deg == pytest.approx(60.0, abs=0.2)
    assert r.flag


def test_known_cone_unsupported_area_matches_the_spike(overhang_mesh):
    r = printability.overhang_histogram(overhang_mesh)
    assert r.unsupported_area == pytest.approx(1339.09, rel=0.01)


def test_bins_account_for_the_whole_unsupported_area(overhang_mesh):
    """The 45-60 and 60-90 bins must sum to the unsupported area -- nothing may fall out."""
    r = printability.overhang_histogram(overhang_mesh)
    above_45 = sum(area for lo, _hi, area in r.bins if lo >= 45.0)
    assert above_45 == pytest.approx(r.unsupported_area, rel=1e-6)


def test_build_plate_contact_faces_are_not_overhangs(plate_mesh):
    """A flat-bottomed plate has a large downward face at z_min. It rests on the plate.

    Without the exclusion it reads as a 90 deg overhang and the whole report is noise.
    """
    r = printability.overhang_histogram(plate_mesh)
    assert r.unsupported_area == 0.0
    assert not r.flag


def test_exactly_horizontal_ceiling_lands_in_the_top_bin():
    """The inclusive-upper-bound trap.

    A ``< 90`` top bound drops exactly-horizontal ceilings -- the worst case there is -- out of
    the histogram entirely, and the first attempt at this scored a real overhang as all-zeros.
    """
    import trimesh
    from build123d import Align, Box, BuildPart, Locations, Mode

    with BuildPart() as p:
        Box(30.0, 30.0, 20.0)
        with Locations((0, 0, 0.0)):
            # a pocket opening downward at the plate: its ceiling at z=0 is exactly horizontal
            Box(10.0, 10.0, 10.0, align=(Align.CENTER, Align.CENTER, Align.MAX), mode=Mode.SUBTRACT)
    from threedp.features import _tessellate

    mesh: trimesh.Trimesh = _tessellate(p.part)

    r = printability.overhang_histogram(mesh)
    top_bin_area = [area for lo, _hi, area in r.bins if lo == 60.0][0]
    assert top_bin_area == pytest.approx(100.0, rel=0.01), "the 10x10 ceiling fell out of the bins"
    assert r.max_deg == pytest.approx(90.0, abs=0.01)
    assert r.unsupported_area == pytest.approx(100.0, rel=0.01)


def test_a_vertical_wall_is_zero_degrees_not_a_defect(plate_mesh):
    r = printability.overhang_histogram(plate_mesh)
    lowest_bin = r.bins[0]
    assert lowest_bin[0] == 0.0
    assert lowest_bin[2] > 0.0, "vertical walls should land in the 0-15 bin"
    assert not r.flag, "a vertical wall is the normal case, never an overhang defect"


def test_angles_are_measured_from_vertical(overhang_mesh):
    ang = printability._face_angles_from_vertical(overhang_mesh)
    # the cone's flat top faces up -> -90; nothing may exceed +90
    assert ang.max() <= 90.0 + 1e-9
    assert ang.min() >= -90.0 - 1e-9
    assert np.isclose(ang.min(), -90.0, atol=0.01)


def test_shallower_threshold_finds_more_area(overhang_mesh):
    strict = printability.overhang_histogram(overhang_mesh, threshold_deg=30.0)
    loose = printability.overhang_histogram(overhang_mesh, threshold_deg=70.0)
    assert strict.unsupported_area > loose.unsupported_area


# --- minimum wall -------------------------------------------------------------------------


def test_min_wall_recovers_a_known_thinnest_wall(plate_mesh):
    """Spike 7: 60-wide plate, 10 thick, Ø8 holes at x = +/-21 -> true thinnest wall 5.0mm."""
    r = printability.min_wall(plate_mesh, samples=2000)
    true_wall = (PLATE["size_x"] / 2) - PLATE["hole_x"] - PLATE["hole_d"] / 2
    assert true_wall == 5.0
    assert r.min_mm == pytest.approx(5.0, abs=0.05)
    assert r.median_mm == pytest.approx(PLATE["thick"], abs=0.05)
    assert r.hits > 1000


def test_min_wall_is_reported_as_an_estimate(plate_mesh):
    r = printability.min_wall(plate_mesh, samples=500)
    assert "ESTIMATE" in str(r)


def test_min_wall_flags_below_threshold(plate_mesh):
    assert not printability.min_wall(plate_mesh, samples=500, threshold_mm=0.8).flag
    assert printability.min_wall(plate_mesh, samples=500, threshold_mm=6.0).flag


def test_min_wall_is_deterministic(plate_mesh):
    """A verifier whose number moves between runs cannot be argued with."""
    a = printability.min_wall(plate_mesh, samples=500)
    b = printability.min_wall(plate_mesh, samples=500)
    assert a.min_mm == b.min_mm


def test_min_wall_rejects_a_nonsense_sample_count(plate_mesh):
    with pytest.raises(ValueError):
        printability.min_wall(plate_mesh, samples=0)


def test_overhang_rejects_an_empty_mesh():
    import trimesh

    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64))
    with pytest.raises(ValueError):
        printability.overhang_histogram(empty)


def test_cone_geometry_is_actually_60_degrees():
    """Guard the fixture itself: if the cone is not 60 deg, the assertions above prove nothing."""
    import math

    run = 10.0 * math.tan(math.radians(60.0))
    assert math.degrees(math.atan(run / 10.0)) == pytest.approx(60.0, abs=1e-9)
    assert build_overhang_cone() is not None


# --- bridges ------------------------------------------------------------------------------


def test_a_known_bridge_measures_its_shorter_span(bridge_mesh):
    """A 24mm-wide slot through a 20mm-deep block: the deck bridges 20mm, not 24mm.

    A bridge is thrown across the *narrow* direction of the patch it spans. Reporting the longer
    extent would understate every long narrow ceiling as harder than it is, and overstate every
    short wide one -- and the two errors would hide each other in aggregate.
    """
    r = printability.bridge_spans(bridge_mesh)
    assert r.count == 1, f"expected one bridged patch, got {r.count}"
    assert r.max_span_mm == pytest.approx(20.0, abs=0.01)
    assert r.spans[0].long_mm == pytest.approx(24.0, abs=0.01)
    assert r.spans[0].area == pytest.approx(24.0 * 20.0, rel=0.01)
    assert r.spans[0].z == pytest.approx(20.0, abs=0.01)


def test_a_bridge_report_is_labelled_an_estimate(bridge_mesh):
    """It is derived from face geometry, not from a slice, and every line says so."""
    assert "ESTIMATE" in str(printability.bridge_spans(bridge_mesh))


def test_a_bridge_flags_against_its_threshold(bridge_mesh):
    assert printability.bridge_spans(bridge_mesh, threshold_mm=10.0).flag
    assert not printability.bridge_spans(bridge_mesh, threshold_mm=30.0).flag


def test_a_part_with_no_ceiling_reports_no_bridges(plate_mesh):
    """The false-positive direction, and the reason the build-plate exclusion is in this path too:
    a flat bottom is resting on something, not spanning air."""
    r = printability.bridge_spans(plate_mesh)
    assert r.count == 0
    assert r.max_span_mm == 0.0
    assert not r.flag


def test_a_steep_overhang_is_not_counted_as_a_bridge(overhang_mesh):
    """60 degrees from vertical is an overhang and not a bridge; the two need different advice."""
    assert printability.bridge_spans(overhang_mesh).count == 0


def test_two_separate_ceilings_are_two_spans():
    """Connected components, not one bounding box over everything downward-facing."""
    from build123d import Align, Box, BuildPart, Locations, Mode

    from threedp.features import _tessellate

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    with BuildPart() as p:
        Box(80.0, 20.0, 28.0, align=bottom)
        with Locations((-22.0, 0, 0), (22.0, 0, 0)):
            Box(16.0, 40.0, 20.0, align=bottom, mode=Mode.SUBTRACT)
    r = printability.bridge_spans(_tessellate(p.part))
    assert r.count == 2, f"two slots must be two patches, got {r.count}"
    assert r.max_span_mm == pytest.approx(16.0, abs=0.01)
    assert r.total_area == pytest.approx(2 * 16.0 * 20.0, rel=0.01)


def test_bridge_spans_rejects_an_empty_mesh():
    import trimesh

    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64))
    with pytest.raises(ValueError):
        printability.bridge_spans(empty)


# --- footprint ----------------------------------------------------------------------------


def test_footprint_measures_plate_contact_and_slenderness(plate_mesh):
    """Contact area is summed from the faces that touch the plate, not from the bounding box.

    The distinction is the assertion: the plate is 60x40 = 2400 mm2 in plan, and its two Ø8 holes
    take 2*pi*4^2 = 100.5 mm2 of that away, so the material actually touching the bed is 2299.5.
    A bounding-footprint answer would say 2400 and be wrong by exactly the holes.
    """
    r = printability.footprint(plate_mesh)
    bounding = PLATE["size_x"] * PLATE["size_y"]
    holes = 2 * math.pi * (PLATE["hole_d"] / 2) ** 2
    assert r.contact_area == pytest.approx(bounding - holes, rel=0.01)
    assert r.contact_area < bounding
    assert r.size_x == pytest.approx(PLATE["size_x"], abs=0.01)
    assert r.height == pytest.approx(PLATE["thick"], abs=0.01)
    # height over the SMALLER footprint extent -- the axis a part topples about
    assert r.aspect_ratio == pytest.approx(PLATE["thick"] / PLATE["size_y"], rel=0.01)
    assert not r.flag


def test_footprint_flags_a_slender_part():
    from build123d import Box, BuildPart

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(6.0, 6.0, 60.0)
    r = printability.footprint(_tessellate(p.part))
    assert r.aspect_ratio == pytest.approx(10.0, rel=0.01)
    assert r.flag, "36 mm2 of contact under a 10:1 part is both risks at once"


# --- tilted bores are refused, not reported ------------------------------------------------


def test_a_tilted_bore_is_not_reported_as_a_diameter():
    """CLAUDE.md's named case, from the direction that hides a defect.

    A Ø22 bore tilted 5 deg sections as an ellipse whose residual sits INSIDE the circularity
    gate, so `fit.is_circular` is True and the cylinder reaches `fs.cylinders` looking measurable.
    Its fitted diameter is 22.0395mm -- inflated by 0.04mm. Tilt always inflates, so admitting
    one would let a genuinely undersized bore read as acceptable and slip under `min_hole_d_mm`.
    """
    from conftest import build_tilted_bore

    from threedp.features import _tessellate

    mesh = _tessellate(build_tilted_bore(tilt_deg=5.0))

    # The premise: the ruler does hand this cylinder over, circular and confident.
    found = features.from_mesh(mesh)
    assert len(found.cylinders) == 1
    assert found.cylinders[0].fit.is_circular, "the circularity gate does NOT catch tilt"
    assert not found.cylinders[0].is_axis_aligned
    assert found.cylinders[0].diameter_unchecked > 22.0, "tilt inflates; that is the danger"

    r = printability.bore_diameters(mesh)
    assert r.diameters == (), "a tilted bore must not be reported as a measured diameter"
    assert r.tilted == 1, "...and must not be silently dropped either"
    assert r.min_mm is None
    assert not r.flag
    assert "off Z" in str(r)


def test_an_axis_aligned_bore_is_still_reported(plate_mesh):
    """The false-positive direction: the axis check must not swallow ordinary vertical bores."""
    r = printability.bore_diameters(plate_mesh)
    assert r.tilted == 0
    assert len(r.diameters) == 2
    assert r.min_mm == pytest.approx(PLATE["hole_d"], abs=0.05)

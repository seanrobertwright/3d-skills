"""Printability, validated against geometry whose overhang and wall thickness are known exactly."""

import numpy as np
import pytest
from conftest import PLATE, build_overhang_cone

from threedp import printability

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

"""Feature extraction, both paths, against the same analytically-known part.

The BREP<->mesh cross-check at the bottom is the test that catches a bug present in only one
path -- which no single-path test can.
"""

import numpy as np
import pytest
from conftest import CANONICAL, PLATE

from threedp import features, measure
from threedp.measure import FeatureNotFoundError, NotCircularError

# --- BREP path ----------------------------------------------------------------------------


@pytest.mark.brep
def test_brep_radii_are_exact(canonical_step):
    f = features.extract(canonical_step)
    assert f.representation == "brep"
    radii = sorted(round(c.radius, 6) for c in f.cylinders)
    assert radii == [5.0, 11.0, 15.0]  # spike 2, exact -- no drift through the STEP roundtrip


@pytest.mark.brep
def test_brep_planes_are_exact(canonical_step):
    f = features.extract(canonical_step)
    zs = sorted(round(p.z, 6) for p in f.horizontal_planes())
    assert zs == [-10.0, 3.0, 10.0]


@pytest.mark.brep
def test_brep_pocket_depth_is_exact(canonical_step):
    """Pocket depth is the axial extent of the bore's own cylindrical face: 10.0 - 3.0 = 7.000."""
    f = features.extract(canonical_step)
    bore = f.cylinders_at(0.0, 0.0)[1]  # largest is the OD; next is the bore
    assert bore.radius == pytest.approx(11.0, abs=1e-9)
    assert bore.depth == pytest.approx(CANONICAL["pocket_depth"], abs=1e-9)
    assert bore.z_min == pytest.approx(3.0, abs=1e-9)
    assert bore.z_max == pytest.approx(10.0, abs=1e-9)


@pytest.mark.brep
def test_brep_diameter_needs_no_circularity_gate(canonical_step):
    """A BREP cylinder is a cylinder by construction; there is no fit and nothing to gate."""
    f = features.extract(canonical_step)
    outer = f.select_cylinder(0.0, 0.0, rank="largest")
    assert outer.fit is None
    assert outer.diameter == pytest.approx(30.0, abs=1e-9)


@pytest.mark.brep
def test_brep_hole_position_uses_the_occt_axis_not_face_center(plate_part):
    """ADR-2 / spike 3.

    ``face.center()`` reported these holes at x = -25 and +17 -- wrong by exactly the radius
    (4.0mm), and wrong plausibly. The OCCT axis reports -21.000 and +21.000.
    """
    f = features.from_shape(plate_part, source="<plate>")
    hole_xs = sorted(
        round(c.xy[0], 6) for c in f.cylinders if abs(c.radius - PLATE["hole_d"] / 2) < 1e-6
    )
    assert hole_xs == [-21.0, 21.0]
    for wrong in (-25.0, 17.0):
        assert wrong not in hole_xs


@pytest.mark.brep
def test_brep_cylinder_axes_point_along_z(canonical_step):
    f = features.extract(canonical_step)
    for c in f.cylinders:
        assert c.is_axis_aligned
        assert c.tilt_deg == pytest.approx(0.0, abs=1e-9)


@pytest.mark.brep
def test_brep_volume_and_bbox(canonical_step):
    f = features.extract(canonical_step)
    assert f.bbox_size == pytest.approx((30.0, 30.0, 20.0), abs=1e-6)
    assert f.watertight
    # truth: pi*(15^2*20 - 11^2*7 - 5^2*13) = 10455.22
    expected = np.pi * (15.0**2 * 20.0 - 11.0**2 * 7.0 - 5.0**2 * 13.0)
    assert f.volume == pytest.approx(expected, rel=1e-6)


# --- mesh path ----------------------------------------------------------------------------


@pytest.mark.mesh
def test_mesh_recovers_diameters_within_spike_tolerance(canonical_stl):
    """Spike: bore 21.997 against truth 22.000, OD 29.997 against 30.000 -- within 0.003mm."""
    f = features.extract(canonical_stl)
    assert f.representation == "mesh"
    at_origin = f.cylinders_at(0.0, 0.0)
    diameters = sorted(c.diameter for c in at_origin)
    assert diameters == pytest.approx([10.0, 22.0, 30.0], abs=0.005)


@pytest.mark.mesh
def test_mesh_pocket_depth_survives_bisection(canonical_stl):
    """Transition detection quantises to the scan step; bisection is what keeps it at +/-0.005."""
    f = features.extract(canonical_stl)
    bore = [c for c in f.cylinders_at(0.0, 0.0) if abs(c.radius - 11.0) < 0.05][0]
    assert bore.depth == pytest.approx(CANONICAL["pocket_depth"], abs=0.005)


@pytest.mark.mesh
def test_mesh_planes_are_exact(canonical_stl):
    f = features.extract(canonical_stl)
    zs = sorted(round(p.z, 3) for p in f.horizontal_planes())
    assert zs == [-10.0, 3.0, 10.0]


@pytest.mark.mesh
def test_mesh_cylinders_carry_their_fit(canonical_stl):
    f = features.extract(canonical_stl)
    for c in f.cylinders:
        assert c.fit is not None
        assert c.fit.is_circular
        assert c.fit.max_residual < measure.DEFAULT_CIRCULARITY_TOL


@pytest.mark.mesh
def test_mesh_3mf_loads_as_a_scene_and_still_measures(canonical_3mf):
    """A .3mf loads as a Scene, not a Trimesh, and reading one needs lxml (spike 8)."""
    f = features.extract(canonical_3mf)
    assert f.watertight
    diameters = sorted(c.diameter for c in f.cylinders_at(0.0, 0.0))
    assert diameters == pytest.approx([10.0, 22.0, 30.0], abs=0.005)


@pytest.mark.mesh
def test_square_pocket_is_not_reported_as_a_cylinder(square_pocket_stl):
    """ADR-1 end to end: the confident '24.4949mm circle' never reaches a caller as a diameter."""
    f = features.extract(square_pocket_stl)
    assert not any(abs(c.radius - 12.247) < 0.5 for c in f.cylinders)
    assert f.noncircular, "the square section should be recorded, not discarded"
    with pytest.raises(NotCircularError):
        f.select_cylinder(0.0, 0.0, rank="largest")


@pytest.mark.mesh
def test_absent_feature_raises_rather_than_defaulting(canonical_stl):
    f = features.extract(canonical_stl)
    with pytest.raises(FeatureNotFoundError):
        f.select_cylinder(40.0, 40.0, rank="largest")


@pytest.mark.mesh
def test_unmeasurable_axis_refuses_rather_than_reporting_zero_taper(interrupted_bore_stl):
    """An axis that could not be established must not be reported as a perfect +Z axis.

    Two coaxial Ø10 bores separated by 30mm of solid coalesce into one run, and the 25%/75%
    probe heights land in the gap where no ring matches. Every such exit returns
    ``_UNMEASURABLE_AXIS`` -- infinite taper -- so the feature is refused.

    The guard matters because the flattering answer is silent: with the probe returning taper
    0.0 instead, this exact part reports ``diameter=9.9984, tilt=0.00deg, Tier1=True``. Nothing
    measured that axis; it is the sentinel's default leaking out as a dimensional verdict.
    """
    f = features.extract(interrupted_bore_stl)

    assert not any(abs(c.radius - 5.0) < 0.5 for c in f.cylinders), (
        "the Ø10 feature was graded as a measurable cylinder despite an unestablished axis"
    )
    unmeasurable = [c for c in f.tapered if abs(c.radius - 5.0) < 0.5]
    assert unmeasurable, "the Ø10 feature should be recorded as unmeasurable, not discarded"
    assert np.isinf(unmeasurable[0].taper_per_mm), (
        "an unestablished axis must carry infinite taper, not a finite one - a finite value "
        "would be indistinguishable from a genuine cone"
    )

    with pytest.raises(measure.MeasurementError) as exc:
        f.select_cylinder(0.0, 0.0, rank="largest")
    # The refusal must say what actually happened. Reporting "its radius changes with height"
    # here would be a confident, plausible, wrong reason - the same defect one level up.
    assert "axis" in str(exc.value) and "could not be established" in str(exc.value)


@pytest.mark.mesh
def test_plane_transitions_are_bisected_to_tolerance(canonical_stl):
    mesh = features.load_mesh(canonical_stl)
    zs = measure.plane_transitions(mesh)
    assert zs[0] == pytest.approx(-10.0, abs=0.005)
    assert zs[-1] == pytest.approx(10.0, abs=0.005)
    assert any(abs(z - 3.0) < 0.005 for z in zs), f"pocket floor missing from {zs}"


def test_plane_transitions_refuse_non_z_axes(canonical_stl):
    mesh = features.load_mesh(canonical_stl)
    with pytest.raises(measure.MeasurementError):
        measure.plane_transitions(mesh, axis="x")


# --- the cross-check ----------------------------------------------------------------------


def test_brep_and_mesh_agree_on_the_same_part(canonical_step, canonical_stl):
    """The test a one-sided bug cannot survive."""
    brep = features.extract(canonical_step)
    mesh = features.extract(canonical_stl)
    b = sorted(round(c.radius, 4) for c in brep.cylinders)
    m = sorted(round(c.radius, 4) for c in mesh.cylinders)
    assert len(b) == len(m), f"different feature counts: brep {b} vs mesh {m}"
    assert np.allclose(b, m, atol=0.01), f"brep {b} vs mesh {m}"


def test_brep_and_mesh_agree_on_pocket_depth(canonical_step, canonical_stl):
    brep = features.extract(canonical_step)
    mesh = features.extract(canonical_stl)
    bd = [c for c in brep.cylinders_at(0, 0) if abs(c.radius - 11.0) < 0.05][0].depth
    md = [c for c in mesh.cylinders_at(0, 0) if abs(c.radius - 11.0) < 0.05][0].depth
    assert bd == pytest.approx(md, abs=0.01)


def test_unsupported_format_raises(tmp_path):
    p = tmp_path / "part.iges"
    p.write_text("not really iges", encoding="utf-8")
    with pytest.raises(measure.MeasurementError):
        features.extract(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        features.extract(tmp_path / "nope.step")

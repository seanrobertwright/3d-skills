"""Export: the nominal/compensated split, and the staleness warning."""

import pytest

from threedp import features, io
from threedp.io import CalibrationStaleWarning, ExportError

PARAMS = {
    "BORE": {"value": 22.0, "role": "hole"},
    "OD": {"value": 30.0, "role": "outer"},
    "HEIGHT": {"value": 20.0, "role": "neutral"},
}

PLA = {"hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "measured": None, "material": "PLA_generic"}
MEASURED = dict(PLA, measured="2026-09-01")


def build(p):
    """A parametric ring: OD outside, BORE through the middle."""
    from build123d import BuildPart, Cylinder, Mode

    with BuildPart() as part:
        Cylinder(radius=p["OD"] / 2, height=p["HEIGHT"])
        Cylinder(radius=p["BORE"] / 2, height=p["HEIGHT"] * 2, mode=Mode.SUBTRACT)
    return part.part


def radii(path):
    return sorted(round(c.radius, 4) for c in features.extract(path).cylinders)


def test_nominal_step_equals_nominal_exactly(tmp_path):
    """PRD 11: compensation never leaks into CAD output."""
    with pytest.warns(CalibrationStaleWarning):
        r = io.export(build, tmp_path / "ring", calibration=PLA, params=PARAMS)
    assert radii(r.nominal["step"]) == [11.0, 15.0]


def test_compensated_mesh_differs_from_nominal_in_the_right_direction(tmp_path):
    with pytest.warns(CalibrationStaleWarning):
        r = io.export(build, tmp_path / "ring", calibration=PLA, params=PARAMS)
    got = radii(r.compensated["stl"])
    # bore grows by +0.18/2 in radius; outer shrinks by -0.05/2
    assert got[0] == pytest.approx(11.09, abs=0.01)
    assert got[1] == pytest.approx(14.975, abs=0.01)


def test_the_two_files_disagree_which_is_the_entire_point(tmp_path):
    with pytest.warns(CalibrationStaleWarning):
        r = io.export(build, tmp_path / "ring", calibration=PLA, params=PARAMS)
    assert radii(r.nominal["step"]) != radii(r.compensated["stl"])


def test_without_calibration_the_mesh_is_nominal_too(tmp_path):
    r = io.export(build, tmp_path / "ring", params=PARAMS)
    assert radii(r.nominal["step"]) == pytest.approx(radii(r.compensated["stl"]), abs=0.005)
    assert r.material is None
    assert not r.stale


def test_3mf_roundtrip_is_watertight_with_correct_volume(tmp_path):
    """Spike 8: a 10mm cube roundtrips to volume 1000.0 against truth 1000.0."""
    from build123d import Box, BuildPart

    with BuildPart() as p:
        Box(10.0, 10.0, 10.0)
    r = io.export(p.part, tmp_path / "cube", nominal=("step",), compensated=("3mf",))
    f = features.extract(r.compensated["3mf"])
    assert f.watertight
    assert f.volume == pytest.approx(1000.0, abs=0.001)


def test_all_three_formats_are_written(tmp_path):
    r = io.export(build, tmp_path / "ring", params=PARAMS)
    assert r.nominal["step"].exists()
    assert r.compensated["stl"].exists()
    assert r.compensated["3mf"].exists()
    assert len(r.paths) == 3


def test_export_accepts_a_finished_shape_when_no_compensation_is_asked_for(tmp_path):
    r = io.export(build({"OD": 30.0, "BORE": 22.0, "HEIGHT": 20.0}), tmp_path / "ring")
    assert radii(r.nominal["step"]) == [11.0, 15.0]


def test_creates_missing_output_directories(tmp_path):
    r = io.export(build, tmp_path / "deep" / "nested" / "ring", params=PARAMS)
    assert r.nominal["step"].exists()


# --- staleness (Task 14) ------------------------------------------------------------------


def test_stale_calibration_warns_and_names_the_material(tmp_path):
    with pytest.warns(CalibrationStaleWarning, match="PLA_generic"):
        r = io.export(build, tmp_path / "ring", calibration=PLA, params=PARAMS)
    assert r.stale
    assert "published literature default" in str(r)


def test_measured_calibration_does_not_warn(tmp_path, recwarn):
    r = io.export(build, tmp_path / "ring", calibration=MEASURED, params=PARAMS)
    assert not r.stale
    assert not [w for w in recwarn if issubclass(w.category, CalibrationStaleWarning)]


def test_nominal_only_export_never_warns(tmp_path, recwarn):
    io.export(build, tmp_path / "ring", compensated=(), params=PARAMS)
    assert not [w for w in recwarn if issubclass(w.category, CalibrationStaleWarning)]


def test_stale_export_still_writes_the_files(tmp_path):
    """Refusing to export would be worse than warning. The warning must not become a block."""
    with pytest.warns(CalibrationStaleWarning):
        r = io.export(build, tmp_path / "ring", calibration=PLA, params=PARAMS)
    assert r.compensated["stl"].exists()


# --- refusals -----------------------------------------------------------------------------


def test_compensating_a_finished_shape_is_refused(tmp_path):
    """An imported mesh has no parametrization; a uniform offset would be a silent lie."""
    shape = build({"OD": 30.0, "BORE": 22.0, "HEIGHT": 20.0})
    with pytest.raises(ExportError, match="press fits on imported meshes"):
        io.export(shape, tmp_path / "ring", calibration=PLA, params=PARAMS)


def test_builder_without_params_is_refused(tmp_path):
    with pytest.raises(ExportError, match="params"):
        io.export(build, tmp_path / "ring")


def test_unsupported_format_is_refused(tmp_path):
    with pytest.raises(ExportError, match="unsupported"):
        io.export(build, tmp_path / "ring", nominal=("iges",), compensated=(), params=PARAMS)

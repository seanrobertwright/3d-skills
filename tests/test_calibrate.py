"""Caliper readings to a calibration record: the arithmetic, and what it refuses.

Pure functions, no printer, no CAD. The numbers below are the ones a stepped Ø10 gauge would
produce on a machine with the shipped published defaults -- holes 0.18 mm undersize, outers
0.05 mm oversize -- so the fits land where ``profiles/calibration.json`` claims and a sign
inversion is visible immediately rather than as a plausible number of the wrong sign.

The two things worth reading here are both refusals:

* **hole and outer deltas are never pooled.** They come out with opposite signs from one formula,
  and a test asserts the pair rather than each alone -- averaging them is the mistake that
  compensating parameters instead of geometry exists to make impossible;
* **a delta that changes with diameter is not a delta.** If the per-step deltas span more than one
  gauge step, no single offset describes the printer, and reporting the mean would be a confident,
  plausible, wrong constant computed from perfectly real measurements.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from threedp import calibrate, compensate

# A Ø10 five-step gauge, measured. Holes come out ~0.18 undersize, studs ~0.05 oversize.
HOLE = [(9.8, 9.62), (9.9, 9.72), (10.0, 9.82), (10.1, 9.92), (10.2, 10.02)]
OUTER = [(9.8, 9.85), (9.9, 9.95), (10.0, 10.05), (10.1, 10.15), (10.2, 10.25)]

GAUGE = "coupon:hole-10mm-5step + coupon:pin-10mm-5step"
NOZZLE = "stainless_steel 0.4"
DATE = "2026-08-09"


# --- one step ------------------------------------------------------------------------------


def test_a_hole_that_prints_undersize_gets_a_positive_delta():
    assert calibrate.fit_delta(10.0, 9.82, "hole") == pytest.approx(0.18)


def test_an_outer_that_prints_oversize_gets_a_negative_delta():
    assert calibrate.fit_delta(10.0, 10.05, "outer") == pytest.approx(-0.05)


def test_the_two_roles_have_opposite_signs_and_must_never_be_averaged():
    """CLAUDE.md's central compensation rule, asserted on the pair rather than on either alone."""
    hole = calibrate.fit_delta(10.0, 9.82, "hole")
    outer = calibrate.fit_delta(10.0, 10.05, "outer")
    assert hole > 0 > outer
    pooled = (hole + outer) / 2.0
    # The single offset a naive implementation would produce is wrong for both roles at once:
    # it under-corrects the bore and over-corrects the stud, and no fit comes out right.
    assert abs(pooled - hole) > 0.1
    assert abs(pooled - outer) > 0.1


def test_a_neutral_dimension_has_no_delta_and_asking_is_an_error():
    with pytest.raises(calibrate.CalibrationError, match="neutral"):
        calibrate.fit_delta(10.0, 10.0, "neutral")


def test_a_nonsense_diameter_is_refused():
    with pytest.raises(calibrate.CalibrationError, match="positive"):
        calibrate.fit_delta(10.0, 0.0, "hole")


# --- across a gauge ------------------------------------------------------------------------


def test_a_fit_averages_the_steps_and_reports_its_spread():
    fit = calibrate.fit_deltas(HOLE, "hole")
    assert fit.delta_mm == pytest.approx(0.18, abs=1e-9)
    assert fit.spread_mm == pytest.approx(0.0, abs=1e-9)
    assert fit.n == 5
    assert "hole" in str(fit)


def test_one_step_is_not_a_gauge():
    with pytest.raises(calibrate.CalibrationError, match="at least two"):
        calibrate.fit_deltas([(10.0, 9.82)], "hole")


def test_a_delta_that_grows_with_diameter_is_refused_rather_than_averaged():
    """No single offset describes this printer, and the mean would look entirely reasonable."""
    drifting = [(9.8, 9.78), (9.9, 9.85), (10.0, 9.90), (10.1, 9.93), (10.2, 9.95)]
    with pytest.raises(calibrate.CalibrationError) as exc:
        calibrate.fit_deltas(drifting, "hole")
    message = str(exc.value)
    assert "one 0.10 mm step" in message
    assert "confident, plausible, wrong" in message
    # The mean it declined to report is named, so the refusal can be argued with.
    assert "+0.1180" in message


def test_measurement_noise_inside_one_step_is_accepted():
    noisy = [(9.8, 9.63), (9.9, 9.72), (10.0, 9.81), (10.1, 9.93), (10.2, 10.01)]
    fit = calibrate.fit_deltas(noisy, "hole")
    assert fit.spread_mm == pytest.approx(0.02, abs=1e-9)
    assert fit.delta_mm == pytest.approx(0.18, abs=0.02)


# --- the record (ADR-18) -------------------------------------------------------------------


def test_a_record_carries_a_date_a_source_a_nozzle_and_the_raw_readings():
    record = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE)
    assert record["measured"] == DATE
    assert record["nozzle"] == NOZZLE
    assert GAUGE in record["source"]
    assert "caliper" in record["source"]
    assert record["readings"]["hole"][0] == [9.8, 9.62]
    assert len(record["readings"]["outer"]) == 5
    assert record["hole_delta_mm"] > 0 > record["outer_delta_mm"]


def test_a_record_will_not_say_measured_true():
    """The shape someone reaches for when cutting the corner, refused at the source (ADR-18)."""
    with pytest.raises(calibrate.CalibrationError, match="ISO date"):
        calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, True)
    with pytest.raises(calibrate.CalibrationError, match="ISO date"):
        calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, "yesterday")


def test_a_record_must_name_its_gauge_and_its_nozzle():
    with pytest.raises(calibrate.CalibrationError, match="gauge"):
        calibrate.build_record(HOLE, OUTER, "PLA_generic", "", NOZZLE, DATE)
    with pytest.raises(calibrate.CalibrationError, match="nozzle"):
        calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, "", DATE)


def test_swapping_the_hole_and_outer_fits_is_caught():
    hole = calibrate.fit_deltas(HOLE, "hole")
    outer = calibrate.fit_deltas(OUTER, "outer")
    with pytest.raises(calibrate.CalibrationError, match="twice the error"):
        calibrate.build_record(outer, hole, "PLA_generic", GAUGE, NOZZLE, DATE)


def test_first_layer_squish_is_null_unless_it_was_measured():
    """The fit gauge does not measure it, and carrying the old default forward would launder it."""
    record = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE)
    assert record["first_layer_squish"] is None
    with_squish = calibrate.build_record(
        HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE, first_layer_squish=0.12
    )
    assert with_squish["first_layer_squish"] == 0.12


# --- writing it back (3B-3) ----------------------------------------------------------------


@pytest.fixture
def calibration_file(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {
                "PLA_generic": {
                    "hole_delta_mm": 0.18,
                    "outer_delta_mm": -0.05,
                    "first_layer_squish": 0.12,
                    "measured": None,
                    "source": "published-default",
                },
                "ABS_generic": {
                    "hole_delta_mm": 0.22,
                    "outer_delta_mm": -0.10,
                    "first_layer_squish": 0.14,
                    "measured": None,
                    "source": "published-default",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_writing_one_material_leaves_every_other_untouched(calibration_file):
    before = json.loads(calibration_file.read_text(encoding="utf-8"))["ABS_generic"]
    record = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE)
    result = calibrate.write_record("PLA_generic", record, calibration_file)

    after = json.loads(calibration_file.read_text(encoding="utf-8"))
    assert after["ABS_generic"] == before
    assert after["PLA_generic"]["measured"] == DATE
    assert result.untouched == ("ABS_generic",)
    assert "PLA_generic" in str(result)


def test_a_written_record_stops_the_material_being_stale(calibration_file):
    record = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE)
    calibrate.write_record("PLA_generic", record, calibration_file)
    resolved = compensate.resolve(
        {"D": {"value": 10.0, "role": "hole"}},
        compensate.load_calibration("PLA_generic", calibration_file),
    )
    assert not resolved.stale
    assert resolved["D"] == pytest.approx(10.18)


def test_writing_refuses_a_record_with_no_date(calibration_file):
    with pytest.raises(calibrate.CalibrationError, match="ISO date"):
        calibrate.write_record(
            "PLA_generic",
            {
                "hole_delta_mm": 0.1,
                "outer_delta_mm": -0.1,
                "measured": None,
                "source": "published-default",
            },
            calibration_file,
        )
    # ...and the file is unchanged, so a refused write is not a partial write.
    unchanged = json.loads(calibration_file.read_text(encoding="utf-8"))
    assert unchanged["PLA_generic"]["measured"] is None


def test_writing_refuses_an_incomplete_record(calibration_file):
    with pytest.raises(calibrate.CalibrationError, match="outer_delta_mm"):
        calibrate.write_record(
            "PLA_generic", {"hole_delta_mm": 0.1, "measured": DATE, "source": "x"}, calibration_file
        )


def test_a_measured_record_is_reported_when_it_is_replaced(calibration_file):
    record = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE)
    calibrate.write_record("PLA_generic", record, calibration_file)
    again = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, "2026-09-01")
    result = calibrate.write_record("PLA_generic", again, calibration_file)
    assert result.replaced is not None
    assert result.replaced["measured"] == DATE


def test_stale_materials_lists_what_phase_3b_still_owes(calibration_file):
    assert calibrate.stale_materials(calibration_file) == ["ABS_generic", "PLA_generic"]
    record = calibrate.build_record(HOLE, OUTER, "PLA_generic", GAUGE, NOZZLE, DATE)
    calibrate.write_record("PLA_generic", record, calibration_file)
    assert calibrate.stale_materials(calibration_file) == ["ABS_generic"]


# --- the shipped file ----------------------------------------------------------------------------

REPO = Path(__file__).resolve().parents[1]


def test_the_shipped_calibration_says_which_records_are_unvalidated():
    stale = calibrate.stale_materials()
    data = compensate.load_calibration()
    for material in stale:
        assert data[material]["measured"] is None
        assert data[material]["source"] == "published-default"


def test_abs_is_not_fabricated_while_no_abs_is_loaded():
    """A phase that invented the third record to look complete reintroduces the problem.

    ABS is not in the AMS -- slot 3 holds PETG -- so ``ABS_generic`` stays a published default
    with ``"measured": null`` and the export keeps warning about it. That is the honest state and
    it is asserted so nobody "finishes" it later without printing a coupon.
    """
    record = compensate.load_calibration("ABS_generic")
    assert record["measured"] is None
    assert record["source"] == "published-default"


# --- compensate's half of ADR-18 (3B-2) ----------------------------------------------------


def test_a_boolean_measured_is_refused_by_the_loader(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text(
        json.dumps(
            {"PLA_generic": {"hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "measured": True}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(compensate.CompensationError, match="ISO date"):
        compensate.load_calibration("PLA_generic", path)
    with pytest.raises(compensate.CompensationError, match="ISO date"):
        compensate.load_calibration(None, path)


def test_a_boolean_measured_is_refused_when_a_record_is_passed_straight_to_resolve():
    """The loader is not the only door. A hand-built record never passes through it."""
    record = {"hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "measured": True}
    with pytest.raises(compensate.CompensationError, match="ISO date"):
        compensate.resolve({"D": {"value": 10.0, "role": "hole"}}, record)


def test_a_null_measured_is_still_a_valid_unvalidated_record():
    record = {"hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "measured": None}
    assert compensate.resolve({"D": {"value": 10.0, "role": "hole"}}, record).stale


def test_an_iso_date_resolves_as_measured():
    record = {"hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "measured": "2026-08-09"}
    assert not compensate.resolve({"D": {"value": 10.0, "role": "hole"}}, record).stale


# --- the calibrate skill (3B-4) ------------------------------------------------------------------

SKILL = REPO / ".claude" / "skills" / "lril3d-calibrate" / "SKILL.md"


def test_the_calibrate_skill_exists_and_quotes_the_gauge_refusal():
    """`write_gauge` refuses a calibration; the skill quotes the reason rather than paraphrasing."""
    from threedp import coupon

    assert SKILL.is_file()
    text = SKILL.read_text(encoding="utf-8")
    assert "name: lril3d-calibrate" in text
    quoted = "measures the compensation rather than the printer"
    assert quoted in coupon.write_gauge.__doc__ or quoted in _refusal_text()
    assert quoted in text, "the skill paraphrases the refusal instead of quoting it"


def _refusal_text() -> str:
    from threedp import coupon

    try:
        coupon.write_gauge("/dev/null", calibration="PLA_generic")
    except coupon.CouponError as exc:
        return str(exc)
    raise AssertionError("write_gauge accepted a calibration")

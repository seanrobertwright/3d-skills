"""Compensation by re-parametrization, and the rule that nominal output stays nominal."""

import pytest

from threedp import compensate
from threedp.compensate import CompensationError, resolve

PARAMS = {
    "BORE": {"value": 22.0, "role": "hole"},
    "OD": {"value": 30.0, "role": "outer"},
    "WIDTH": {"value": 7.0, "role": "neutral"},
}

PLA = {"hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "measured": None}


def test_no_calibration_returns_nominal_unchanged():
    """PRD 11: STEP dimensions equal nominal -- compensation never leaks into CAD output."""
    r = resolve(PARAMS, None)
    assert r == {"BORE": 22.0, "OD": 30.0, "WIDTH": 7.0}
    assert not r.compensated
    assert r.deltas == {}


def test_nominal_values_are_bit_identical_to_the_input():
    r = resolve(PARAMS, None)
    for name, entry in PARAMS.items():
        assert r[name] == entry["value"]
        assert r[name].hex() == float(entry["value"]).hex()


def test_hole_and_outer_move_in_opposite_directions():
    r = resolve(PARAMS, PLA)
    assert r["BORE"] == pytest.approx(22.18, abs=1e-12)
    assert r["OD"] == pytest.approx(29.95, abs=1e-12)
    assert r["WIDTH"] == 7.0
    assert r.compensated


def test_the_two_deltas_do_not_reconcile_into_one_offset():
    """PRD 15.4 / 6.4: the asymmetry is real. Trying to unify it is the bug, not the fix."""
    r = resolve(PARAMS, PLA)
    bore_shift = r["BORE"] - PARAMS["BORE"]["value"]
    outer_shift = r["OD"] - PARAMS["OD"]["value"]
    assert bore_shift > 0 > outer_shift
    assert bore_shift != pytest.approx(-outer_shift), "the deltas are independent, not mirrored"


def test_neutral_dimensions_are_never_touched():
    r = resolve(PARAMS, PLA)
    assert r["WIDTH"] == PARAMS["WIDTH"]["value"]


def test_published_default_is_flagged_stale():
    """Risk 7: a literature default silently standing in for a measurement."""
    r = resolve(PARAMS, PLA)
    assert r.stale
    assert "never been verified" in r.staleness_warning


def test_a_measured_calibration_is_not_stale():
    measured = dict(PLA, measured="2026-09-01", source="coupon-2026-09-01")
    assert not resolve(PARAMS, measured).stale


def test_nominal_resolution_is_never_stale():
    assert not resolve(PARAMS, None).stale


# --- refusal to guess ---------------------------------------------------------------------


def test_untagged_parameter_is_rejected():
    """A bare number would silently escape compensation -- a hole that never gets its delta."""
    with pytest.raises(CompensationError, match="semantic role"):
        resolve({"BORE": 22.0}, PLA)


def test_unknown_role_is_rejected_and_lists_valid_roles():
    with pytest.raises(CompensationError) as exc:
        resolve({"BORE": {"value": 22.0, "role": "bore"}}, PLA)
    assert "hole" in str(exc.value)


def test_missing_value_is_rejected():
    with pytest.raises(CompensationError, match="no 'value'"):
        resolve({"BORE": {"role": "hole"}}, PLA)


def test_empty_params_is_rejected():
    with pytest.raises(CompensationError):
        resolve({}, None)


def test_calibration_record_missing_a_delta_is_rejected():
    with pytest.raises(CompensationError, match="missing"):
        resolve(PARAMS, {"hole_delta_mm": 0.18})


def test_passing_the_whole_profile_instead_of_one_record_is_rejected():
    whole = {"PLA_generic": PLA}
    with pytest.raises(CompensationError, match="one material record"):
        resolve(PARAMS, whole)


def test_nonsense_calibration_type_is_rejected():
    with pytest.raises(CompensationError):
        resolve(PARAMS, 0.18)


# --- the shipped profile ------------------------------------------------------------------


def test_shipped_profile_loads_and_is_all_unmeasured():
    data = compensate.load_calibration()
    assert "PLA_generic" in data
    for name, record in data.items():
        assert record["measured"] is None, f"{name} claims a measurement Phase 1 cannot have made"
        assert record["source"] == "published-default"


def test_material_lookup_by_name():
    pla = compensate.load_calibration("PLA_generic")
    assert pla["hole_delta_mm"] == 0.18
    assert pla["outer_delta_mm"] == -0.05


def test_unknown_material_raises_and_lists_available():
    with pytest.raises(CompensationError) as exc:
        compensate.load_calibration("PLA_unicorn")
    assert "PLA_generic" in str(exc.value)


def test_resolve_accepts_a_material_name(monkeypatch):
    r = resolve(PARAMS, "PLA_generic")
    assert r.material == "PLA_generic"
    assert r["BORE"] == pytest.approx(22.18)
    assert r.stale

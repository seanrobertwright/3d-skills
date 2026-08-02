"""The fit gauge, measured back through the one ruler.

Spike S11 built a five-step Ø9.8-10.2 gauge and probed it back through ``features``/``measure``
at ``[9.7985, 9.8985, 9.9984, 10.0984, 10.1984]`` -- a maximum error of 0.0016 mm against
nominal, against a 0.1 mm step. Those are the numbers asserted here. A gauge whose own geometry
cannot be recovered to well inside one step is a gauge that cannot measure a printer.
"""

from __future__ import annotations

import pytest

from threedp import coupon, features, intent

# --- the record the gauge carries ------------------------------------------------------------


def test_a_five_step_gauge_has_five_steps_around_the_nominal():
    g = coupon.fit_gauge(10.0)
    assert g.diameters == pytest.approx((9.8, 9.9, 10.0, 10.1, 10.2))
    assert len(g.positions) == 5
    assert g.positions[2] == pytest.approx(0.0)


def test_every_parameter_declares_a_role():
    from threedp import compensate

    g = coupon.fit_gauge(10.0)
    resolved = compensate.resolve(g.params, None)
    assert set(resolved) == set(g.params)
    for name, entry in g.params.items():
        assert entry["role"] in compensate.ROLES, name


def test_bore_steps_are_tagged_hole_and_pin_steps_are_tagged_outer():
    """The two roles take opposite-signed deltas; a gauge that mislabels them measures nothing."""
    holes = coupon.fit_gauge(10.0, kind="hole")
    pins = coupon.fit_gauge(10.0, kind="pin")
    assert holes.params["STEP_0_D"]["role"] == "hole"
    assert pins.params["STEP_0_D"]["role"] == "outer"


def test_the_intent_it_emits_is_a_valid_intent():
    g = coupon.fit_gauge(10.0)
    spec = intent.load(g.intent)
    assert len(spec.asserts) == 6  # five diameters plus the count
    assert all(a.source for a in spec.asserts)


def test_adjacent_assertion_bands_do_not_overlap():
    """Two steps satisfying one assertion would make a passing gauge unable to name a step."""
    spec = intent.load(coupon.fit_gauge(10.0).intent)
    bands = sorted((a.lo, a.hi) for a in spec.asserts if a.name.endswith("_diameter"))
    for (_lo_a, hi_a), (lo_b, _hi_b) in zip(bands, bands[1:], strict=False):
        assert hi_a < lo_b, f"bands {bands} overlap"


# --- the geometry ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gauge_mesh():
    from threedp.features import _tessellate

    g = coupon.fit_gauge(10.0)
    return g, _tessellate(g.shape)


def test_measured_bores_land_within_the_spike_error(gauge_mesh):
    """S11: max error 0.0016 mm. Asserted at the Tier 1 guarantee, which is 3x looser."""
    g, mesh = gauge_mesh
    found = features.from_mesh(mesh, source="coupon")
    measured = sorted(c.diameter for c in found.cylinders)
    assert len(measured) == 5, f"expected five bores, measured {measured}"
    errors = [abs(m - d) for m, d in zip(measured, sorted(g.diameters), strict=True)]
    assert max(errors) < 0.005, f"measured {measured}, errors {errors}"


def test_the_steps_are_resolved_apart_by_far_more_than_the_measurement_error(gauge_mesh):
    """0.1 mm steps against a ~0.0016 mm ruler error: the margin is what makes the gauge usable."""
    g, mesh = gauge_mesh
    measured = sorted(c.diameter for c in features.from_mesh(mesh).cylinders)
    errors = [abs(m - d) for m, d in zip(measured, sorted(g.diameters), strict=True)]
    step = 0.1
    assert max(errors) * 20 < step, f"only {step / max(errors):.0f}x margin"


def test_the_gauge_passes_its_own_intent(gauge_mesh):
    g, mesh = gauge_mesh
    report = intent.check(features.from_mesh(mesh, source="coupon"), g.intent)
    assert report.passed, str(report)


def test_a_pin_gauge_builds_and_measures(gauge_mesh):
    from threedp.features import _tessellate

    g = coupon.fit_gauge(10.0, kind="pin")
    found = features.from_mesh(_tessellate(g.shape), source="coupon-pin")
    measured = sorted(c.diameter for c in found.cylinders)
    assert len(measured) == 5
    errors = [abs(m - d) for m, d in zip(measured, sorted(g.diameters), strict=True)]
    assert max(errors) < 0.005, f"measured {measured}"


def test_a_missing_step_fails_the_count_assertion(gauge_mesh):
    """A gauge short one step reads the wrong number confidently -- absence IS the defect."""
    g, _mesh = gauge_mesh
    short = coupon.fit_gauge(10.0, steps=(-0.2, -0.1, 0.0, 0.1))
    from threedp.features import _tessellate

    report = intent.check(features.from_mesh(_tessellate(short.shape)), g.intent)
    assert not report.passed
    failed = {r.name for r in report.failures}
    assert "step_count" in failed or "step_4_diameter" in failed


# --- the refusals ----------------------------------------------------------------------------


def test_a_compensated_gauge_is_refused(tmp_path):
    """Printing a compensated gauge measures the compensation, not the printer."""
    with pytest.raises(coupon.CouponError) as exc:
        coupon.write_gauge(tmp_path, calibration="PLA_generic")
    assert "measures the compensation" in str(exc.value)


def test_an_unknown_kind_is_refused_with_the_valid_list():
    with pytest.raises(coupon.CouponError) as exc:
        coupon.fit_gauge(10.0, kind="thread")
    assert "hole" in str(exc.value) and "pin" in str(exc.value)


def test_steps_closer_than_the_assertion_band_are_refused():
    """Bands that overlap make the gauge unable to say which step it measured."""
    with pytest.raises(coupon.CouponError) as exc:
        coupon.fit_gauge(10.0, steps=(-0.05, 0.0, 0.05))
    assert "adjacent" in str(exc.value) or "closer together" in str(exc.value)


def test_a_single_step_is_refused():
    with pytest.raises(coupon.CouponError):
        coupon.fit_gauge(10.0, steps=(0.0,))


def test_a_step_that_removes_the_feature_is_refused():
    with pytest.raises(coupon.CouponError):
        coupon.fit_gauge(0.2, steps=(-0.5, 0.0, 0.5))


# --- writing ----------------------------------------------------------------------------------


def test_write_gauge_writes_nominal_geometry_and_both_records(tmp_path):
    written = coupon.write_gauge(tmp_path, nominal_d=10.0)
    for key in ("params.json", "intent.json", "step", "stl"):
        assert key in written, sorted(written)
        assert written[key].exists() and written[key].stat().st_size > 0
    # The written intent must load, or the files disagree with each other.
    assert intent.load(written["intent.json"]).asserts

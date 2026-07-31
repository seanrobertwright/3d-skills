"""Unit tests for THE canonical ruler.

These tests are deliberately written against **analytically-known** geometry: synthetic point
sets whose truth is arithmetic. They must not import ``build123d`` or ``trimesh`` — the ruler is
validated against arithmetic, not against another library that could share its bug (PRD 6.5).

Written before ``src/threedp/measure.py`` existed (plan Task 5).
"""

import dataclasses

import numpy as np
import pytest

from threedp.measure import CircleFit, MeasurementError, NotCircularError, fit_circle

N_POINTS = 253  # the spike's real bore section had 253 points; keep the same sampling


def circle_points(r, n=N_POINTS, cx=0.0, cy=0.0, closed=False):
    """Points on an exact circle. ``closed`` repeats the first vertex, Shapely-style."""
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    pts = np.c_[cx + r * np.cos(t), cy + r * np.sin(t)]
    if closed:
        pts = np.vstack([pts, pts[0]])
    return pts


def square_ring(side):
    """The spike's adversarial fixture: a square ring at corners + edge midpoints.

    This exact sampling is what produced the measured "24.4949mm circle" with
    max|residual| = 2.2474mm. Reproduced literally so the spike assertions stay checkable.
    """
    h = side / 2.0
    return np.array(
        [
            [-h, -h],
            [0.0, -h],
            [h, -h],
            [h, 0.0],
            [h, h],
            [0.0, h],
            [-h, h],
            [-h, 0.0],
        ]
    )


def square_ring_dense(side, n_per_edge=64):
    """A densely sampled square ring -- what a real mesh section of a square pocket looks like."""
    h = side / 2.0
    t = np.linspace(-h, h, n_per_edge, endpoint=False)
    top = np.c_[t, np.full(n_per_edge, h)]
    right = np.c_[np.full(n_per_edge, h), -t]
    bottom = np.c_[-t, np.full(n_per_edge, -h)]
    left = np.c_[np.full(n_per_edge, -h), t]
    return np.vstack([top, right, bottom, left])


def ellipse_points(a, b, n=N_POINTS):
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.c_[a * np.cos(t), b * np.sin(t)]


# --- 1. perfect circle -------------------------------------------------------------------


def test_perfect_circle_recovers_diameter():
    fit = fit_circle(circle_points(11.0))
    assert fit.n_points == N_POINTS
    assert fit.is_circular
    assert fit.diameter == pytest.approx(22.0, abs=0.005)
    assert fit.max_residual < 1e-9
    assert fit.rms_residual < 1e-9


# --- 2. the 0.088mm regression ----------------------------------------------------------


def test_duplicate_closing_vertex_is_identical_to_open_ring():
    """Shapely closes rings by repeating the first vertex.

    Including that duplicate shifted the fitted centre by 0.037mm and inflated the diameter by
    0.088mm in the spike -- more than a press-fit tolerance, enough to flip a +/-0.05 assertion.
    This is THE regression test for PRD 15.5; it is first-class on purpose.
    """
    open_fit = fit_circle(circle_points(11.0, closed=False))
    closed_fit = fit_circle(circle_points(11.0, closed=True))

    assert closed_fit.n_points == open_fit.n_points  # the duplicate was stripped
    assert closed_fit.cx == pytest.approx(open_fit.cx, abs=1e-12)
    assert closed_fit.cy == pytest.approx(open_fit.cy, abs=1e-12)
    assert closed_fit.diameter == pytest.approx(open_fit.diameter, abs=1e-12)


def test_duplicate_closing_vertex_on_offset_circle():
    """The duplicate only biases a fit when it pulls the centre; check an off-origin ring too."""
    open_fit = fit_circle(circle_points(11.0, cx=5.0, cy=-3.0, closed=False))
    closed_fit = fit_circle(circle_points(11.0, cx=5.0, cy=-3.0, closed=True))
    assert closed_fit.cx == pytest.approx(open_fit.cx, abs=1e-12)
    assert closed_fit.cy == pytest.approx(open_fit.cy, abs=1e-12)


# --- 3. centre recovery ------------------------------------------------------------------


def test_offset_circle_recovers_centre():
    fit = fit_circle(circle_points(7.5, cx=5.0, cy=-3.0))
    assert fit.cx == pytest.approx(5.0, abs=1e-6)
    assert fit.cy == pytest.approx(-3.0, abs=1e-6)
    assert fit.diameter == pytest.approx(15.0, abs=0.005)


# --- 4. ADR-1: a square is not a circle --------------------------------------------------


def test_square_ring_is_not_circular_and_diameter_raises():
    """The spike's adversarial case: a 20x20 pocket fits as a confident 24.4949mm circle."""
    fit = fit_circle(square_ring(20.0))
    assert not fit.is_circular
    assert fit.max_residual == pytest.approx(2.2474, abs=0.001)  # spike 5, measured
    with pytest.raises(NotCircularError):
        _ = fit.diameter
    # the unsafe path exists for diagnostics, and is deliberately named differently
    assert fit.diameter_unchecked == pytest.approx(24.4949, abs=0.001)


def test_densely_sampled_square_is_also_rejected():
    """A real mesh section of a square pocket has many vertices per edge, not eight."""
    fit = fit_circle(square_ring_dense(20.0))
    assert not fit.is_circular
    assert fit.max_residual > 1.0
    with pytest.raises(NotCircularError):
        _ = fit.diameter


def test_true_bore_and_square_pocket_are_separated_by_the_residual():
    """Spike 5: the residual separates the two cases by ~1446x. 0.05mm sits cleanly between."""
    bore = fit_circle(circle_points(10.0))
    pocket = fit_circle(square_ring(20.0))
    assert bore.max_residual < 0.05 < pocket.max_residual


# --- 5. an ellipse from a tilted bore ----------------------------------------------------


def test_ellipse_from_tilted_bore_is_not_circular():
    """A ~5deg-tilted bore sections as an ellipse and would report a diameter inflated ~0.4%.

    It must not pass the circularity gate (ADR-4).
    """
    fit = fit_circle(ellipse_points(11.0, 10.5))
    assert not fit.is_circular
    with pytest.raises(NotCircularError):
        _ = fit.diameter


# --- 6. tolerable noise ------------------------------------------------------------------


def test_noisy_circle_is_still_circular_and_accurate():
    rng = np.random.default_rng(20260730)
    pts = circle_points(11.0)
    pts = pts + rng.normal(0.0, 0.002, pts.shape)
    fit = fit_circle(pts)
    assert fit.is_circular
    assert fit.diameter == pytest.approx(22.0, abs=0.005)


# --- 7. degenerate input -----------------------------------------------------------------


@pytest.mark.parametrize("n", [0, 1, 2])
def test_too_few_points_raises(n):
    pts = circle_points(11.0)[:n]
    with pytest.raises(MeasurementError):
        fit_circle(pts)


def test_closing_duplicate_leaving_too_few_points_raises():
    """3 points where one is a closing duplicate leaves 2 real points -- must raise, not guess."""
    pts = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    with pytest.raises(MeasurementError):
        fit_circle(pts)


def test_collinear_points_do_not_return_a_silent_number():
    """A degenerate (collinear) section has no circle. Whatever happens, it is not a pass."""
    pts = np.c_[np.linspace(-10, 10, 51), np.zeros(51)]
    try:
        fit = fit_circle(pts)
    except MeasurementError:
        return
    assert not fit.is_circular
    with pytest.raises(NotCircularError):
        _ = fit.diameter


# --- API shape ---------------------------------------------------------------------------


def test_circle_fit_is_immutable():
    """A measurement result that can be edited after the fact is not evidence."""
    fit = fit_circle(circle_points(11.0))
    with pytest.raises(dataclasses.FrozenInstanceError):
        fit.radius = 999.0  # type: ignore[misc]


def test_not_circular_error_is_a_measurement_error():
    assert issubclass(NotCircularError, MeasurementError)


def test_circularity_tol_is_configurable_and_recorded():
    fit = fit_circle(ellipse_points(11.0, 10.5), circularity_tol=1.0)
    assert fit.circularity_tol == 1.0
    assert fit.is_circular  # a deliberately loose gate, explicitly asked for
    assert isinstance(fit, CircleFit)


def test_error_message_names_the_residual_and_the_tolerance():
    fit = fit_circle(square_ring(20.0))
    with pytest.raises(NotCircularError) as exc:
        _ = fit.diameter
    msg = str(exc.value)
    assert "2.2474" in msg or "max_residual" in msg
    assert "0.05" in msg

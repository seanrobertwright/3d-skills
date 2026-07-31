"""Replace the canonical least-squares fit with **centroid + max-radius**.

This is the improvised implementation from the spike, verbatim: take the mean of the ring's
points as the centre and the furthest point as the radius, on the ring exactly as Shapely
delivers it -- closing duplicate and all. It measured a Ø22 bore as **22.088mm**, an error of
+0.088mm: larger than a press-fit tolerance and enough to flip a +/-0.05 assertion.

This is the highest-value class of mutation in the suite. A verifier with a subtly wrong ruler
reports green forever, and **geometry mutations structurally cannot catch it** -- they compare a
measured number to a range, and a wrong measurement that lands inside the range is invisible to
them (PRD 6.5, Risk 2).

The circularity verdict is deliberately left intact (computed from the canonical fit) so the
mutation isolates one variable: the diameter method. Otherwise the off-centre fit would also
trip the circularity gate and the detection could not be attributed.
"""

import contextlib

import numpy as np

EXPECT = "FAIL"
REASON = "centroid + max-radius on the raw Shapely ring reads a Ø22 bore as 22.088mm"
KIND = "method"
SOURCE = "stl"


@contextlib.contextmanager
def method_patch():
    from threedp import measure

    canonical = measure.fit_circle

    def bad_fit_circle(pts, circularity_tol=measure.DEFAULT_CIRCULARITY_TOL):
        good = canonical(pts, circularity_tol)
        pts = np.asarray(pts, dtype=float)[:, :2]  # NOTE: duplicate closing vertex NOT stripped
        if len(pts) < 3:
            raise measure.MeasurementError("need >=3 points")
        cx, cy = pts.mean(axis=0)
        r = float(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).max())
        return measure.CircleFit(
            float(cx),
            float(cy),
            r,
            good.max_residual,
            good.rms_residual,
            good.n_points,
            circularity_tol,
        )

    measure.fit_circle = bad_fit_circle
    try:
        yield
    finally:
        measure.fit_circle = canonical

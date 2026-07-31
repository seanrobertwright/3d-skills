"""Delete the duplicate-stripping line from the canonical least-squares fit.

**Expects PASS, on measured evidence.** Shapely closes rings by repeating the first vertex, and
including that duplicate is what broke the spike's centroid method by 0.088mm. Least-squares was
then measured on the same 253-point ring with and without the duplicate:

    with dup   LSQ dia = 29.9973   MAXR dia = 30.1387
    stripped   LSQ dia = 29.9973   MAXR dia = 30.0249

Identical to four decimal places under least-squares; 0.114mm apart under max-radius. One extra
sample among 253 has no leverage on a least-squares solution, and that immunity is the
load-bearing reason least-squares is the canonical method rather than a stylistic preference.

So this mutation is a **false-positive detector aimed at the ruler**: it must PASS. If it ever
flips to FAIL, the fitter is no longer least-squares -- someone has reintroduced a
centroid-weighted method -- and the strip line has silently become load-bearing again.

(The plan predicted this would be caught. It is not, and asserting otherwise would bake a
permanent miss into the suite. The measurement above is the evidence; re-run it before changing
this verdict.)
"""

import contextlib

import numpy as np

EXPECT = "PASS"
REASON = "least-squares is provably insensitive to the closing duplicate; max-radius is not"
KIND = "method"
SOURCE = "stl"


@contextlib.contextmanager
def method_patch():
    from threedp import measure

    canonical = measure.fit_circle

    def unstripped_fit_circle(pts, circularity_tol=measure.DEFAULT_CIRCULARITY_TOL):
        pts = np.asarray(pts, dtype=float)
        if pts.ndim != 2 or pts.shape[-1] < 2:
            raise measure.MeasurementError(f"expected an Nx2 point array, got shape {pts.shape}")
        pts = pts[:, :2]
        # the strip is deliberately absent here -- that is the mutation
        if len(pts) < 3:
            raise measure.MeasurementError(f"need >=3 points to fit a circle, got {len(pts)}")
        x, y = pts[:, 0], pts[:, 1]
        A = np.c_[2 * x, 2 * y, np.ones(len(x))]
        b = x**2 + y**2
        c, *_ = np.linalg.lstsq(A, b, rcond=None)
        cx, cy = float(c[0]), float(c[1])
        r = float(np.sqrt(c[2] + cx**2 + cy**2))
        resid = np.hypot(x - cx, y - cy) - r
        return measure.CircleFit(
            cx,
            cy,
            r,
            float(np.abs(resid).max()),
            float(np.sqrt((resid**2).mean())),
            len(pts),
            circularity_tol,
        )

    measure.fit_circle = unstripped_fit_circle
    try:
        yield
    finally:
        measure.fit_circle = canonical

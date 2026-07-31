"""THE canonical ruler.

Every dimensional number produced by this project flows through this module. That is not a
style preference: during the spike two improvised implementations of "measure this bore"
disagreed by 0.088mm -- larger than a press-fit tolerance and enough to flip a +/-0.05
assertion (PRD 6.5, 15.5).

Two rules this module exists to enforce:

1. **Least-squares circle fitting is the canonical method.** Max-radius and bounding-box
   methods are prohibited for dimensional assertions. ``tests/test_one_ruler.py`` fails the
   build if either reappears elsewhere in the tree.
2. **A diameter is unreachable without consulting the circularity verdict** (ADR-1). A square
   20x20 pocket fits as a confident "24.4949mm circle"; the residual is the only tell, so it is
   a gate rather than diagnostic metadata.

All dimensions are millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "MeasurementError",
    "NotCircularError",
    "FeatureNotFoundError",
    "CircleFit",
    "fit_circle",
    "section_rings",
    "section_area",
    "plane_transitions",
    "DEFAULT_CIRCULARITY_TOL",
]

# Spike 5: a true bore sections with max|residual| = 0.0016mm; a square pocket with 2.2474mm.
# 0.05 sits cleanly between them, separated by 1446x, and is also a press-fit tolerance.
DEFAULT_CIRCULARITY_TOL = 0.05

# Sections are taken at this Z step before bisection refines each transition.
DEFAULT_SCAN_STEP = 0.5

# Transitions are bisected until the bracket is narrower than this, so a mesh-derived plane
# position meets the same +/-0.005mm guarantee as a BREP one.
DEFAULT_TRANSITION_TOL = 0.002


class MeasurementError(Exception):
    """A measurement could not be made. Never swallowed, never defaulted to a number."""


class NotCircularError(MeasurementError):
    """A circle fit was consulted for a diameter on a section that is not a circle."""


class FeatureNotFoundError(MeasurementError):
    """A feature the caller asked to measure does not exist. An absent feature IS a defect."""


@dataclass(frozen=True)
class CircleFit:
    """The result of a least-squares circle fit.

    ``diameter`` deliberately raises unless the fit is circular. The unsafe path exists as
    ``diameter_unchecked`` and is for diagnostics only -- consuming it requires typing a
    different, conspicuous name, which is the only enforcement that survives an agent writing
    the calling code (ADR-1).
    """

    cx: float
    cy: float
    radius: float
    max_residual: float
    rms_residual: float
    n_points: int
    circularity_tol: float = DEFAULT_CIRCULARITY_TOL

    @property
    def is_circular(self) -> bool:
        return self.max_residual <= self.circularity_tol

    @property
    def diameter(self) -> float:
        if not self.is_circular:
            raise NotCircularError(
                f"max_residual={self.max_residual:.4f}mm exceeds tol="
                f"{self.circularity_tol}mm - section is not a circle"
            )
        return 2.0 * self.radius

    @property
    def diameter_unchecked(self) -> float:
        """Diagnostics ONLY. Never use this for a dimensional assertion."""
        return 2.0 * self.radius

    @property
    def center(self) -> tuple[float, float]:
        return (self.cx, self.cy)


def fit_circle(pts, circularity_tol: float = DEFAULT_CIRCULARITY_TOL) -> CircleFit:
    """Algebraic (Kasa) least-squares circle fit over an Nx2 point set.

    Measured on real tessellated geometry the algebraic fit lands at -0.0028mm on a nominal
    22.000mm bore, comfortably inside the +/-0.005mm requirement, with no iteration and no
    convergence failure mode. A fit that can fail to converge is a verifier that can report
    green on a timeout, so geometric (Levenberg-Marquardt) fitting was rejected.
    """
    pts = np.asarray(pts, dtype=float)
    if pts.ndim != 2 or pts.shape[-1] < 2:
        raise MeasurementError(f"expected an Nx2 point array, got shape {pts.shape}")
    pts = pts[:, :2]

    # Shapely closes rings by repeating the first vertex. Including it shifts the
    # fitted center by 0.037mm and inflates diameter by 0.088mm - MORE than a
    # press-fit tolerance. See PRD 15.5 and spike 4.
    if len(pts) >= 2 and np.allclose(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        raise MeasurementError(f"need >=3 points to fit a circle, got {len(pts)}")

    x, y = pts[:, 0], pts[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    b = x**2 + y**2
    c, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = float(c[0]), float(c[1])
    r2 = c[2] + cx**2 + cy**2
    if not np.isfinite(r2) or r2 <= 0.0:
        raise MeasurementError(
            "circle fit is degenerate (collinear or coincident points); no circle exists"
        )
    r = float(np.sqrt(r2))
    resid = np.hypot(x - cx, y - cy) - r
    return CircleFit(
        cx,
        cy,
        r,
        float(np.abs(resid).max()),
        float(np.sqrt((resid**2).mean())),
        len(pts),
        circularity_tol,
    )


def _section(mesh, z: float):
    """Cross-section a mesh with the plane Z=z. Returns a ``Path3D`` or ``None``."""
    return mesh.section(plane_origin=(0.0, 0.0, float(z)), plane_normal=(0.0, 0.0, 1.0))


def section_rings(mesh, z: float) -> list[np.ndarray]:
    """Closed rings of the mesh cross-section at Z=z, as world-XY Nx2 arrays.

    Coordinates are taken from the 3D section and projected by dropping Z, so ring positions
    stay in world coordinates. ``Path3D.to_2D()`` applies an arbitrary in-plane transform,
    which is harmless for a diameter but wrong for a hole position.

    (``to_planar()`` is deprecated past its removal date and is never used here -- see
    correction C3.)
    """
    sec = _section(mesh, z)
    if sec is None:
        raise FeatureNotFoundError(f"no cross-section exists at z={z:.4f} - plane misses the mesh")
    rings = [np.asarray(d, dtype=float)[:, :2] for d in sec.discrete]
    if not rings:
        raise FeatureNotFoundError(f"cross-section at z={z:.4f} produced no closed rings")
    return rings


def section_area(mesh, z: float) -> float:
    """Enclosed area of the mesh cross-section at Z=z, holes subtracted. 0.0 if the plane misses.

    Uses ``Path3D.to_2D()`` (never ``to_planar()``); the in-plane transform is irrelevant to an
    area, and ``Path2D`` is what knows how to subtract interior rings.
    """
    sec = _section(mesh, z)
    if sec is None:
        return 0.0
    try:
        planar, _to_3d = sec.to_2D()
    except Exception as exc:  # a section that cannot be planarised is not a measurement
        raise MeasurementError(f"could not planarise the section at z={z:.4f}: {exc}") from exc
    return float(planar.area)


def plane_transitions(
    mesh,
    axis: str = "z",
    step: float = DEFAULT_SCAN_STEP,
    tol: float = DEFAULT_TRANSITION_TOL,
    area_rel_tol: float = 0.01,
) -> list[float]:
    """Z heights at which the cross-sectional area changes discontinuously.

    These are the horizontal planes of the part: the build-plate face, the top face, a pocket
    floor, a counterbore shoulder. Detection quantises to ``step``, so every candidate is then
    **bisected** to ``tol`` -- reporting the step boundary would forfeit the +/-0.005mm
    guarantee (PRD 6.2).

    Only Z is supported. A Z-scan cannot see angled features; callers must not promote a
    mesh-derived measurement of one to Tier 1 (ADR-4).
    """
    if axis.lower() != "z":
        raise MeasurementError(f"only the Z axis is supported for mesh probing, got {axis!r}")

    zmin = float(mesh.bounds[0][2])
    zmax = float(mesh.bounds[1][2])
    if not np.isfinite(zmin) or not np.isfinite(zmax) or zmax <= zmin:
        raise MeasurementError(f"mesh has a degenerate Z extent: [{zmin}, {zmax}]")

    inset = min(step, (zmax - zmin)) * 1e-3
    zs = np.arange(zmin + inset, zmax - inset, step)
    if len(zs) < 2:
        return [round(zmin, 6), round(zmax, 6)]
    areas = [section_area(mesh, float(z)) for z in zs]

    transitions: list[float] = [zmin, zmax]
    for i in range(len(zs) - 1):
        a_lo, a_hi = areas[i], areas[i + 1]
        scale = max(abs(a_lo), abs(a_hi), 1e-9)
        if abs(a_hi - a_lo) <= area_rel_tol * scale:
            continue
        lo, hi = float(zs[i]), float(zs[i + 1])
        while hi - lo > tol:
            mid = 0.5 * (lo + hi)
            a_mid = section_area(mesh, mid)
            if abs(a_mid - a_lo) <= abs(a_mid - a_hi):
                lo = mid  # still on the low side of the step
            else:
                hi = mid
        transitions.append(0.5 * (lo + hi))

    transitions.sort()
    merged: list[float] = []
    for z in transitions:
        if not merged or abs(z - merged[-1]) > max(tol, 1e-4):
            merged.append(round(z, 6))
    return merged

"""The thin DFM slice: minimum-wall sampling and the overhang histogram.

Split from ``features.py`` deliberately (ADR-3). ``features`` answers *"what dimensions does
this part have?"* -- deterministic, exact, and it feeds ``intent.check``. This module answers
*"will this print?"* -- statistical, sampled, threshold-driven, and it feeds a human-readable
critique. Different determinism guarantees and different consumers, so a different module; it is
also the clean seam for Phase 2's full ``lril3d-dfm`` engine.

**Overhang angles are measured from vertical**: 0 = a vertical wall (fine), 90 = a horizontal
ceiling (the worst case). Two traps found while validating this against known geometry, both
of which silently produce a clean bill of health:

* **Build-plate contact faces must be excluded**, or a flat bottom registers as a 90 deg overhang.
* **The top bin needs an inclusive upper bound.** A ``< 90`` bound drops exactly-horizontal
  ceilings -- the worst case -- straight out of the histogram, scoring a real overhang as
  all-zeros.

All dimensions are millimetres; angles are degrees and always suffixed ``_deg``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

__all__ = [
    "WallReport",
    "OverhangReport",
    "min_wall",
    "overhang_histogram",
    "DEFAULT_OVERHANG_THRESHOLD_DEG",
    "DEFAULT_MIN_WALL_MM",
]

DEFAULT_OVERHANG_THRESHOLD_DEG = 45.0
DEFAULT_MIN_WALL_MM = 0.8  # two perimeters of a 0.4mm nozzle
_PLATE_TOL = 1e-6
_BIN_EDGES = (0.0, 15.0, 30.0, 45.0, 60.0, 90.0001)  # inclusive top -- see module docstring


@dataclass(frozen=True)
class WallReport:
    """Ray-sampled wall thickness. Sampled, therefore an ESTIMATE -- never a Tier 1 number."""

    min_mm: float
    p1_mm: float
    median_mm: float
    samples: int
    hits: int
    threshold_mm: float = DEFAULT_MIN_WALL_MM

    @property
    def flag(self) -> bool:
        return self.min_mm < self.threshold_mm

    def __str__(self) -> str:
        return (
            f"min_wall  min {self.min_mm:.3f} / p1 {self.p1_mm:.3f} / "
            f"median {self.median_mm:.3f} mm"
            f"   ESTIMATE ({self.hits}/{self.samples} rays hit)"
        )


@dataclass(frozen=True)
class OverhangReport:
    """Overhang distribution, area-weighted, measured from vertical."""

    max_deg: float
    area_weighted_deg: float
    unsupported_area: float
    total_area: float
    threshold_deg: float
    bins: list[tuple[float, float, float]] = field(default_factory=list)

    @property
    def flag(self) -> bool:
        return self.unsupported_area > 0.0

    def __str__(self) -> str:
        rows = [
            f"  {lo:5.1f}-{min(hi, 90.0):5.1f} deg from vertical: area = {area:9.2f} mm2"
            for lo, hi, area in self.bins
        ]
        return "\n".join(
            [
                f"overhang  max {self.max_deg:.2f} deg   "
                f"area-weighted {self.area_weighted_deg:.2f} deg",
                *rows,
                f"  UNSUPPORTED (>{self.threshold_deg:g} from vertical) = "
                f"{self.unsupported_area:.2f} mm2 -> FLAG={self.flag}",
            ]
        )


def _face_angles_from_vertical(mesh: trimesh.Trimesh) -> np.ndarray:
    """Angle of each face from vertical: 0 = vertical wall, 90 = horizontal ceiling.

    Upward-facing surfaces come out negative and are therefore never overhangs.
    """
    return np.degrees(np.arcsin(np.clip(-mesh.face_normals[:, 2], -1.0, 1.0)))


def _on_build_plate(mesh: trimesh.Trimesh) -> np.ndarray:
    """Downward faces lying in the lowest Z plane -- they rest on the plate, not over air."""
    zmin = float(mesh.bounds[0][2])
    return (np.abs(mesh.triangles[:, :, 2] - zmin).max(axis=1) < _PLATE_TOL) & (
        mesh.face_normals[:, 2] < -0.999
    )


def overhang_histogram(
    mesh: trimesh.Trimesh, threshold_deg: float = DEFAULT_OVERHANG_THRESHOLD_DEG
) -> OverhangReport:
    """Area-weighted overhang histogram, binned from vertical."""
    if len(mesh.faces) == 0:
        raise ValueError("cannot measure overhangs on a mesh with no faces")

    ang = _face_angles_from_vertical(mesh)
    areas = mesh.area_faces
    on_plate = _on_build_plate(mesh)
    candidate = ~on_plate

    bins: list[tuple[float, float, float]] = []
    for lo, hi in zip(_BIN_EDGES[:-1], _BIN_EDGES[1:], strict=True):
        sel = candidate & (ang >= lo) & (ang < hi)
        bins.append((lo, min(hi, 90.0), float(areas[sel].sum())))

    unsupported = candidate & (ang > threshold_deg)
    unsupported_area = float(areas[unsupported].sum())
    if unsupported_area > 0:
        weighted = float((ang[unsupported] * areas[unsupported]).sum() / unsupported_area)
        max_deg = float(ang[unsupported].max())
    else:
        weighted = 0.0
        max_deg = float(ang[candidate].max()) if candidate.any() else 0.0

    return OverhangReport(
        max_deg=max_deg,
        area_weighted_deg=weighted,
        unsupported_area=unsupported_area,
        total_area=float(areas.sum()),
        threshold_deg=float(threshold_deg),
        bins=bins,
    )


def min_wall(
    mesh: trimesh.Trimesh,
    samples: int = 2000,
    threshold_mm: float = DEFAULT_MIN_WALL_MM,
    seed: int = 20260730,
) -> WallReport:
    """Sample the surface and cast each sample inward; the first exit is the local thickness.

    Validated against known truth: a 10mm plate 60 wide with Ø8 holes at x = +/-21 has a true
    thinnest wall of 5.0mm, and 2000 samples measured min 5.002 / p1 5.129 / median 10.000.

    Sampling means this is an estimate and is reported as one. It is deliberately *not* a Tier 1
    measurement: a wall that a ray never happens to cross is a wall this cannot see.
    """
    if len(mesh.faces) == 0:
        raise ValueError("cannot sample walls on a mesh with no faces")
    if samples < 1:
        raise ValueError(f"need at least one sample, got {samples}")

    rng = np.random.default_rng(seed)
    points, face_idx = trimesh.sample.sample_surface(mesh, samples, seed=int(rng.integers(1 << 31)))
    normals = mesh.face_normals[face_idx]

    eps = max(float(mesh.scale) * 1e-6, 1e-6)
    origins = points - normals * eps
    directions = -normals

    locations, index_ray, _tri = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=directions, multiple_hits=False
    )
    if len(index_ray) == 0:
        raise ValueError("no inward ray hit anything; the mesh is probably not closed")

    distances = np.linalg.norm(locations - origins[index_ray], axis=1)
    distances = distances[distances > eps * 10]
    if len(distances) == 0:
        raise ValueError("every inward ray hit its own origin; the mesh is degenerate")

    return WallReport(
        min_mm=float(distances.min()),
        p1_mm=float(np.percentile(distances, 1)),
        median_mm=float(np.median(distances)),
        samples=int(samples),
        hits=int(len(distances)),
        threshold_mm=float(threshold_mm),
    )

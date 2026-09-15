"""The measurement half of DFM: wall sampling, overhangs, bridges, footprint and bores.

Split from ``features.py`` deliberately (ADR-3). ``features`` answers *"what dimensions does
this part have?"* -- deterministic, exact, and it feeds ``intent.check``. This module answers
*"will this print?"* -- statistical, sampled, threshold-driven, and it feeds a human-readable
critique. Different determinism guarantees and different consumers, so a different module.

**The seam with** ``dfm.py`` **(ADR-7).** Everything here returns a *number*; every *threshold*
and every *verdict* lives in ``profiles/dfm-rules.json`` and ``dfm.py``. The default thresholds
carried on the report dataclasses below exist only so a report can print its own ``flag`` when
used directly; they are not the rules engine's thresholds and ``dfm.evaluate`` never reads them.
Keeping the two apart means tuning a rule is a JSON edit that cannot reach a measurement -- and
loosening a measurement to quiet a rule requires doing so somewhere conspicuous.

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
    "BridgeSpan",
    "BridgeReport",
    "FootprintReport",
    "BoreReport",
    "min_wall",
    "min_feature_size",
    "overhang_histogram",
    "bridge_spans",
    "footprint",
    "bore_diameters",
    "DEFAULT_OVERHANG_THRESHOLD_DEG",
    "DEFAULT_MIN_WALL_MM",
    "DEFAULT_MAX_BRIDGE_MM",
    "DEFAULT_MIN_FOOTPRINT_MM2",
    "DEFAULT_MAX_ASPECT_RATIO",
    "DEFAULT_MIN_BORE_D_MM",
    "DEFAULT_FEATURE_SAMPLES",
    "BRIDGE_ANGLE_DEG",
]

DEFAULT_OVERHANG_THRESHOLD_DEG = 45.0
DEFAULT_MIN_WALL_MM = 0.8  # two perimeters of a 0.4mm nozzle
DEFAULT_MAX_BRIDGE_MM = 10.0
DEFAULT_MIN_FOOTPRINT_MM2 = 100.0
DEFAULT_MAX_ASPECT_RATIO = 8.0
DEFAULT_MIN_BORE_D_MM = 2.0
# A thin positive feature is a small fraction of a part's surface, so it is a small fraction of
# the samples. The plate-with-a-0.5mm-pin case puts ~0.2% of the surface on the pin; at 2000
# samples that is ~4 expected hits and a real chance of seeing none at all, which would report a
# thin pin as absent rather than as thin. 6000 makes the miss probability negligible.
DEFAULT_FEATURE_SAMPLES = 6000
# An inward ray's first exit is only a thickness if it leaves through a face that *faces* the
# ray. Measured on a domed badge (models/wrx-badge): samples on a 1.5mm rim whose top tilts 10
# degrees exited through the adjacent 1mm inner wall at 80 degrees to the ray and reported 0.003mm
# on a part whose thinnest wall is 1.5mm -- eleven such samples in 3000, every one of them a
# corner, and two DFM BLOCKERs on a part that prints. The exit face's normal must be within 60
# degrees of the ray: cos(60) = 0.5. A wedge of interior angle t exits at cos(t), so a 45-degree
# knife-edge flare (0.71) is still a thin feature and a 90-degree corner (0.0) is not.
GRAZING_EXIT_COS = 0.5
# Downward faces within this many degrees of horizontal are bridging rather than sloping.
BRIDGE_ANGLE_DEG = 80.0
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
    grazing: int = 0  # exits discarded for leaving through a face the ray only grazed

    @property
    def flag(self) -> bool:
        return self.min_mm < self.threshold_mm

    def __str__(self) -> str:
        return (
            f"min_wall  min {self.min_mm:.3f} / p1 {self.p1_mm:.3f} / "
            f"median {self.median_mm:.3f} mm"
            f"   ESTIMATE ({self.hits}/{self.samples} rays hit, {self.grazing} grazing discarded)"
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


@dataclass(frozen=True)
class BridgeSpan:
    """One connected patch of near-horizontal downward surface, and how far it has to bridge.

    ``span_mm`` is the *shorter* footprint extent of the patch, because that is the direction a
    bridge is actually thrown across: a long narrow ceiling bridges its width, not its length.
    """

    span_mm: float
    long_mm: float
    area: float
    z: float


@dataclass(frozen=True)
class BridgeReport:
    """Unsupported near-horizontal spans. Derived from face geometry, so an ESTIMATE.

    This is not a slice. A slicer knows which perimeters actually land over air on the previous
    layer; this knows only which faces point downward and how wide their footprint is. The number
    is useful and it is not a dimensional claim, which is why every line says so.
    """

    spans: list[BridgeSpan] = field(default_factory=list)
    threshold_mm: float = DEFAULT_MAX_BRIDGE_MM
    angle_deg: float = BRIDGE_ANGLE_DEG

    @property
    def max_span_mm(self) -> float:
        return max((s.span_mm for s in self.spans), default=0.0)

    @property
    def total_area(self) -> float:
        return float(sum(s.area for s in self.spans))

    @property
    def count(self) -> int:
        return len(self.spans)

    @property
    def flag(self) -> bool:
        return self.max_span_mm > self.threshold_mm

    def __str__(self) -> str:
        head = (
            f"bridges   {self.count} span(s) within {self.angle_deg:g} deg of horizontal, "
            f"max {self.max_span_mm:.3f} mm   ESTIMATE (face geometry, not a slice)"
        )
        rows = [
            f"  span {s.span_mm:8.3f} x {s.long_mm:8.3f} mm  area {s.area:9.2f} mm2  z {s.z:.3f}"
            for s in self.spans
        ]
        return "\n".join([head, *rows])


@dataclass(frozen=True)
class FootprintReport:
    """Build-plate contact and slenderness. Contact area is summed from faces, so it is exact;
    the footprint extents are a bounding box and are therefore an ESTIMATE, never a dimension.
    """

    contact_area: float
    size_x: float
    size_y: float
    height: float
    min_area_mm2: float = DEFAULT_MIN_FOOTPRINT_MM2
    max_aspect_ratio: float = DEFAULT_MAX_ASPECT_RATIO

    @property
    def aspect_ratio(self) -> float:
        """Height over the *smaller* footprint extent -- the axis a part topples about."""
        base = min(self.size_x, self.size_y)
        if base <= 0.0:
            return float("inf")
        return self.height / base

    @property
    def flag(self) -> bool:
        return self.contact_area < self.min_area_mm2 or self.aspect_ratio > self.max_aspect_ratio

    def __str__(self) -> str:
        return (
            f"footprint contact {self.contact_area:.2f} mm2   "
            f"bbox {self.size_x:.2f} x {self.size_y:.2f} mm, height {self.height:.2f} mm   "
            f"aspect {self.aspect_ratio:.2f}   ESTIMATE (bounding footprint)"
        )


@dataclass(frozen=True)
class BoreReport:
    """Diameters of the *holes* in a mesh, separated from the bosses.

    Both are cylinders to a Z-scan, and the two need opposite advice: a 0.5mm hole wants
    enlarging, a 0.5mm pin wants thickening or deleting. They are told apart by asking whether
    the axis is inside solid material, which requires a watertight mesh -- when the mesh is not
    watertight the classification is refused rather than guessed, and ``classified`` says so.

    ``tilted`` counts bores a Z-scan cannot measure dimensionally. It is not a curiosity: tilt
    *inflates* a fitted diameter, so a bore that is genuinely too small reads larger than it is
    and slips under a minimum-diameter rule. Counting them separately means "no bore was too
    small" and "some bores could not be measured" stay different answers.

    Every diameter here comes from :mod:`threedp.features`, which is to say from the one ruler.
    """

    diameters: tuple[float, ...] = ()
    threshold_mm: float = DEFAULT_MIN_BORE_D_MM
    classified: bool = True
    reason: str = ""
    tilted: int = 0

    @property
    def min_mm(self) -> float | None:
        return min(self.diameters) if self.diameters else None

    @property
    def flag(self) -> bool:
        return self.min_mm is not None and self.min_mm < self.threshold_mm

    def __str__(self) -> str:
        if not self.classified:
            return f"bores     not classified: {self.reason}"
        tail = f"   ({self.tilted} more off Z, not dimensionally measurable)" if self.tilted else ""
        if not self.diameters:
            return f"bores     none measured on this mesh{tail}"
        listed = ", ".join(f"{d:.3f}" for d in sorted(self.diameters))
        return (
            f"bores     {len(self.diameters)} measured, min {self.min_mm:.3f} mm  [{listed}]{tail}"
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
    mesh: trimesh.Trimesh,
    threshold_deg: float = DEFAULT_OVERHANG_THRESHOLD_DEG,
    bridging_span_mm: float | None = None,
) -> OverhangReport:
    """Area-weighted overhang histogram, binned from vertical.

    With ``bridging_span_mm`` given, a near-horizontal downward patch no wider than it is a
    bridge and is left out: it is :func:`bridge_spans`'s to judge. Without it every ceiling is
    the worst-case overhang, which is what the histogram's inclusive top bin exists to keep.
    """
    if len(mesh.faces) == 0:
        raise ValueError("cannot measure overhangs on a mesh with no faces")

    ang = _face_angles_from_vertical(mesh)
    areas = mesh.area_faces
    on_plate = _on_build_plate(mesh)
    candidate = ~on_plate
    if bridging_span_mm is not None:
        # A near-horizontal ceiling narrow enough to bridge is a bridge, not an overhang: the
        # nozzle throws it across in one move and it is judged by max_bridge. Measured on
        # models/wrx-badge: two Ø2.9 blind pin holes read as a 90-degree overhang BLOCKER in
        # every material while bridge_spans reported 2.9 mm against a 5 mm limit. A ceiling
        # *wider* than the span stays an overhang, which is what it is.
        for faces, span in _bridge_patches(mesh, BRIDGE_ANGLE_DEG):
            if span.span_mm <= bridging_span_mm:
                candidate[faces] = False

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

    An exit is only counted if the ray leaves through a face that faces it (within 60 degrees,
    :data:`GRAZING_EXIT_COS`). Without that, every raised feature whose top is not exactly
    horizontal reports the corner between its top and its side as a wall of a few microns -- see
    the constant's note for the measured case. The knife-edge exception is deliberate: a wedge
    sharper than 60 degrees still exits facing the ray and is still reported thin.

    The same rays measure *positive* features as well as walls -- the inward distance from a pin's
    surface is the pin's own thickness -- so :func:`min_feature_size` is this function at a higher
    sample count rather than a second implementation of the ray cast. ``p1_mm`` is carried
    alongside ``min_mm`` for exactly that reason: on a part with one thin feature the minimum is a
    handful of samples and the 1st percentile says whether the rest of the part agrees.
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

    locations, index_ray, index_tri = mesh.ray.intersects_location(
        ray_origins=origins, ray_directions=directions, multiple_hits=False
    )
    if len(index_ray) == 0:
        raise ValueError("no inward ray hit anything; the mesh is probably not closed")

    distances = np.linalg.norm(locations - origins[index_ray], axis=1)
    real = distances > eps * 10
    # A ray that leaves through a face it only grazes has measured a corner, not a wall: the
    # sample sat within a fraction of a millimetre of a convex edge and the exit face is the
    # *other* side of that edge. Keep exits whose face turns toward the ray (GRAZING_EXIT_COS).
    exit_cos = np.einsum("ij,ij->i", directions[index_ray], mesh.face_normals[index_tri])
    facing = exit_cos >= GRAZING_EXIT_COS
    grazing = int((real & ~facing).sum())
    distances = distances[real & facing]
    if len(distances) == 0:
        raise ValueError("every inward ray hit its own origin; the mesh is degenerate")

    return WallReport(
        min_mm=float(distances.min()),
        p1_mm=float(np.percentile(distances, 1)),
        median_mm=float(np.median(distances)),
        samples=int(samples),
        hits=int(len(distances)),
        threshold_mm=float(threshold_mm),
        grazing=grazing,
    )


def min_feature_size(
    mesh: trimesh.Trimesh,
    samples: int = DEFAULT_FEATURE_SAMPLES,
    threshold_mm: float = DEFAULT_MIN_WALL_MM,
) -> WallReport:
    """Thinnest *anything* -- wall or standing feature -- by the same inward ray cast.

    Deliberately not a second ray implementation. The only difference from :func:`min_wall` is
    the sample count, which is raised because a thin pin is a much smaller share of a part's
    surface than a thin wall is and can otherwise be missed entirely (see
    :data:`DEFAULT_FEATURE_SAMPLES`). Still sampled, still an ESTIMATE.
    """
    return min_wall(mesh, samples=samples, threshold_mm=threshold_mm)


def bridge_spans(
    mesh: trimesh.Trimesh,
    threshold_mm: float = DEFAULT_MAX_BRIDGE_MM,
    angle_deg: float = BRIDGE_ANGLE_DEG,
) -> BridgeReport:
    """Group near-horizontal downward faces into patches and measure how far each has to bridge.

    Build-plate contact faces are excluded for the same reason they are excluded from the
    overhang histogram: a flat bottom is resting on something, not spanning air.

    The span of a patch is the smaller extent of its bounding footprint. That is a bounding-box
    number, which is banned for dimensional assertions and is fine here precisely because this is
    not one -- the report is labelled ESTIMATE and ``dfm`` raises it as a WARNING, never as a
    dimension.
    """
    if len(mesh.faces) == 0:
        raise ValueError("cannot measure bridges on a mesh with no faces")

    spans = [span for _faces, span in _bridge_patches(mesh, angle_deg)]
    spans.sort(key=lambda s: (-s.span_mm, -s.area))
    return BridgeReport(spans=spans, threshold_mm=float(threshold_mm), angle_deg=float(angle_deg))


def _bridge_patches(mesh: trimesh.Trimesh, angle_deg: float) -> list[tuple[np.ndarray, BridgeSpan]]:
    """Connected patches of near-horizontal downward faces, each with its span, as (faces, span).

    Shared by :func:`bridge_spans`, which reports them, and :func:`overhang_histogram`, which
    needs to know which faces they are so a bridge is not also scored as an overhang.
    """
    ang = _face_angles_from_vertical(mesh)
    selected = (ang >= angle_deg) & ~_on_build_plate(mesh)
    index = np.flatnonzero(selected)
    patches: list[tuple[np.ndarray, BridgeSpan]] = []
    if len(index) == 0:
        return patches
    adjacency = mesh.face_adjacency
    if len(adjacency):
        internal = selected[adjacency[:, 0]] & selected[adjacency[:, 1]]
        edges = adjacency[internal]
    else:
        edges = np.zeros((0, 2), dtype=np.int64)
    for group in trimesh.graph.connected_components(edges, nodes=index, min_len=1):
        faces = np.asarray(group, dtype=np.int64)
        tris = mesh.triangles[faces]
        dx = float(tris[:, :, 0].max() - tris[:, :, 0].min())
        dy = float(tris[:, :, 1].max() - tris[:, :, 1].min())
        span = BridgeSpan(
            span_mm=min(dx, dy),
            long_mm=max(dx, dy),
            area=float(mesh.area_faces[faces].sum()),
            z=float(tris[:, :, 2].mean()),
        )
        patches.append((faces, span))
    return patches


def footprint(
    mesh: trimesh.Trimesh,
    min_area_mm2: float = DEFAULT_MIN_FOOTPRINT_MM2,
    max_aspect_ratio: float = DEFAULT_MAX_ASPECT_RATIO,
) -> FootprintReport:
    """Build-plate contact area, footprint extents and slenderness."""
    if len(mesh.faces) == 0:
        raise ValueError("cannot measure a footprint on a mesh with no faces")
    contact = float(mesh.area_faces[_on_build_plate(mesh)].sum())
    low, high = mesh.bounds
    return FootprintReport(
        contact_area=contact,
        size_x=float(high[0] - low[0]),
        size_y=float(high[1] - low[1]),
        height=float(high[2] - low[2]),
        min_area_mm2=float(min_area_mm2),
        max_aspect_ratio=float(max_aspect_ratio),
    )


def bore_diameters(
    mesh: trimesh.Trimesh, threshold_mm: float = DEFAULT_MIN_BORE_D_MM
) -> BoreReport:
    """Diameters of the holes in a mesh, with the bosses filtered out.

    Diameters come from :func:`threedp.features.from_mesh`, which is the one ruler. The only
    thing added here is the hole-versus-boss question, answered by testing whether the cylinder's
    own axis lies inside solid material. That test needs a watertight mesh; on a broken one the
    classification is refused rather than guessed, because calling a pin a hole points the user
    at the opposite fix.

    **A tilted bore is not a measurement.** A mesh-derived dimension is Tier 1 only if the circle
    fit passes the circularity gate *and* the axis is within 1 deg of Z -- circularity alone is
    not enough, because a Z-scan sections a tilted bore into an ellipse that can sit inside the
    gate while its fitted diameter is inflated. Measured on the 5 deg fixture: a nominal Ø22 bore
    reports 22.0395 mm, circular and 0.04 mm too large. Since the inflation runs *upward*, letting
    one through would make a genuinely undersized bore read as acceptable and evade a
    minimum-diameter BLOCKER -- a false pass on precisely the defect class this project exists to
    catch. They are counted in ``tilted`` rather than dropped, so the caller can tell "nothing was
    too small" from "something could not be looked at" (ADR-4).
    """
    from threedp import features
    from threedp.measure import MeasurementError

    if len(mesh.faces) == 0:
        raise ValueError("cannot measure bores on a mesh with no faces")
    if not mesh.is_watertight:
        return BoreReport(
            (),
            float(threshold_mm),
            classified=False,
            reason=(
                "the mesh is not watertight, so a bore cannot be told apart from a boss; "
                "repair it first (lril3d-repair)"
            ),
        )

    found = features.from_mesh(mesh)
    if not found.cylinders:
        return BoreReport((), float(threshold_mm))

    probes = np.array(
        [[c.xy[0], c.xy[1], 0.5 * (c.z_min + c.z_max)] for c in found.cylinders], dtype=float
    )
    solid_on_axis = np.asarray(mesh.contains(probes), dtype=bool)

    diameters: list[float] = []
    tilted = 0
    for cylinder, is_boss in zip(found.cylinders, solid_on_axis, strict=True):
        if is_boss:
            continue  # material on the axis: this is a pin or a boss, not a hole
        if not cylinder.is_axis_aligned:
            # A Z-scan cannot measure this dimensionally, and the error runs upward -- see the
            # docstring. Counted, never silently dropped and never reported as a diameter.
            tilted += 1
            continue
        try:
            diameters.append(float(cylinder.diameter))
        except MeasurementError:
            continue  # the circularity gate refused it; it is not a diameter to report
    return BoreReport(tuple(diameters), float(threshold_mm), tilted=tilted)

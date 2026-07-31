"""Feature extraction: BREP face queries and mesh cross-section probing, one common schema.

``extract(path)`` dispatches on suffix and returns a :class:`FeatureSet` regardless of
representation, so ``intent.check`` never has to know whether it is looking at a STEP or an STL.

Two rules this module exists to enforce:

* **Cylinder position comes from the OCCT axis, never** ``face.center()`` **(ADR-2).** The spike
  measured ``center()`` reporting holes at x = -25/+17 that are actually at x = -/+21 -- wrong by
  exactly the radius, and wrong *plausibly*, which is worse than wrong loudly.
* **Every mesh-derived cylinder carries its** :class:`~threedp.measure.CircleFit`. A Z-scan
  cannot see angled features, and a circle fit reports a confident diameter for a section that
  is not a circle. Both facts are the caller's to act on, so both are carried (ADR-4).

All dimensions are millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

from threedp import measure
from threedp.measure import CircleFit, FeatureNotFoundError, MeasurementError

__all__ = [
    "Cylinder",
    "PlaneFace",
    "FeatureSet",
    "extract",
    "load_mesh",
    "from_shape",
    "MAX_AXIS_TILT_DEG",
    "MAX_TAPER_PER_MM",
]

# A Z-scan slices an angled bore into an ellipse. Beyond this tilt a mesh-derived dimension is
# not a Tier 1 measurement, however circular the fit happens to look (ADR-4).
MAX_AXIS_TILT_DEG = 1.0

_TESSELLATION_TOL = 0.01  # spike: tessellation tolerance had no effect on fit accuracy
_RADIUS_MERGE_TOL = 0.02
_CENTER_MERGE_TOL = 0.05
_PLANE_MERGE_TOL = 1e-4
# Neighbouring facets meeting below this angle describe one curved surface, not two faces.
_CURVATURE_ANGLE_DEG = 10.0
# Below this a run cannot be probed at two distinct heights, so its axis and taper are unknown.
_MIN_PROBE_HEIGHT = 0.05
# A surface whose radius changes faster than this with height is tapered, not cylindrical.
# tan(1 deg), matching MAX_AXIS_TILT_DEG: the same 1 deg of "close enough to axis-aligned".
MAX_TAPER_PER_MM = 0.017455


@dataclass(frozen=True)
class Cylinder:
    """A cylindrical face. ``fit`` is present only on the mesh path."""

    radius: float
    axis_point: tuple[float, float, float]
    axis_dir: tuple[float, float, float]
    area: float
    z_min: float = 0.0
    z_max: float = 0.0
    fit: CircleFit | None = None

    @property
    def diameter(self) -> float:
        """The measured diameter.

        On the mesh path this defers to the fit, so a non-circular section raises
        ``NotCircularError`` here exactly as it would at the ruler.
        """
        if self.fit is not None:
            return self.fit.diameter
        return 2.0 * self.radius

    @property
    def diameter_unchecked(self) -> float:
        return 2.0 * self.radius

    @property
    def depth(self) -> float:
        """Axial extent of the cylindrical face -- a pocket's depth, a hole's length."""
        return self.z_max - self.z_min

    @property
    def xy(self) -> tuple[float, float]:
        return (self.axis_point[0], self.axis_point[1])

    @property
    def tilt_deg(self) -> float:
        """Angle between this cylinder's axis and Z, in degrees."""
        d = np.asarray(self.axis_dir, dtype=float)
        n = np.linalg.norm(d)
        if n == 0:
            return 90.0
        return float(np.degrees(np.arccos(min(1.0, abs(d[2]) / n))))

    @property
    def is_axis_aligned(self) -> bool:
        return self.tilt_deg <= MAX_AXIS_TILT_DEG


@dataclass(frozen=True)
class PlaneFace:
    z: float
    normal_z: float
    area: float


@dataclass
class FeatureSet:
    source: str
    representation: str  # "brep" | "mesh"
    cylinders: list[Cylinder]
    planes: list[PlaneFace]
    bbox: tuple[float, float, float, float, float, float]  # xmin,ymin,zmin,xmax,ymax,zmax
    volume: float
    watertight: bool
    noncircular: list[Cylinder] = field(default_factory=list)
    tapered: list[Cylinder] = field(default_factory=list)
    mesh: trimesh.Trimesh | None = field(default=None, repr=False, compare=False)

    # --- selection ------------------------------------------------------------------------

    def cylinders_at(self, x: float, y: float, tol: float = 0.5) -> list[Cylinder]:
        """Cylinders whose axis passes through (x, y), largest radius first."""
        hits = [c for c in self.cylinders if abs(c.xy[0] - x) <= tol and abs(c.xy[1] - y) <= tol]
        return sorted(hits, key=lambda c: c.radius, reverse=True)

    def noncircular_at(self, x: float, y: float, tol: float = 0.5) -> list[Cylinder]:
        return [c for c in self.noncircular if abs(c.xy[0] - x) <= tol and abs(c.xy[1] - y) <= tol]

    def select_cylinder(
        self, x: float, y: float, rank: str | int = "largest", tol: float = 0.5
    ) -> Cylinder:
        """Select one cylinder at (x, y), by rank or by index into the radius-sorted list.

        Raises :class:`FeatureNotFoundError` when nothing is there. An absent feature **is** the
        defect; it is never silently skipped (PRD 15.2 defect 2).
        """
        hits = self.cylinders_at(x, y, tol)
        if not hits:
            taper = [c for c in self.tapered if abs(c.xy[0] - x) <= tol and abs(c.xy[1] - y) <= tol]
            if taper:
                raise MeasurementError(
                    f"the surface at ({x:g}, {y:g}) is tapered, not cylindrical - its radius "
                    f"changes with height, so no single diameter describes it"
                )
            bad = self.noncircular_at(x, y, tol)
            if bad:
                worst = max(bad, key=lambda c: c.fit.max_residual if c.fit else 0.0)
                resid = worst.fit.max_residual if worst.fit else float("nan")
                raise measure.NotCircularError(
                    f"the section at ({x:g}, {y:g}) is not a circle "
                    f"(max_residual={resid:.4f}mm) - no diameter can be reported"
                )
            raise FeatureNotFoundError(
                f"no cylindrical feature at ({x:g}, {y:g}) within {tol}mm - "
                f"the feature is absent, which is itself the defect"
            )
        if isinstance(rank, bool):
            raise MeasurementError(f"cylinder rank must be a name or an index, got {rank!r}")
        if isinstance(rank, int):
            if not -len(hits) <= rank < len(hits):
                raise FeatureNotFoundError(
                    f"only {len(hits)} coaxial cylinder(s) at ({x:g}, {y:g}); "
                    f"index {rank} names one that is absent"
                )
            return hits[rank]
        if rank == "largest":
            return hits[0]
        if rank == "smallest":
            return hits[-1]
        raise MeasurementError(
            f"unknown cylinder rank {rank!r}; expected 'largest', 'smallest', or an integer index"
        )

    def horizontal_planes(self) -> list[PlaneFace]:
        return sorted((p for p in self.planes if abs(p.normal_z) > 0.999), key=lambda p: p.z)

    @property
    def bbox_size(self) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bbox
        return (x1 - x0, y1 - y0, z1 - z0)


# --- BREP path --------------------------------------------------------------------------------


def from_shape(shape, source: str = "<shape>") -> FeatureSet:
    """Extract features straight from a build123d shape, without a round-trip through disk."""
    from build123d import GeomType
    from OCP.BRepAdaptor import BRepAdaptor_Surface

    cylinders: list[Cylinder] = []
    planes: list[PlaneFace] = []

    for f in shape.faces():
        gt = f.geom_type
        if gt == GeomType.CYLINDER:
            cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
            axis = cyl.Axis()
            loc, d = axis.Location(), axis.Direction()
            pts = np.array([tuple(v) for v in f.vertices()], dtype=float)
            if len(pts):
                z_min, z_max = float(pts[:, 2].min()), float(pts[:, 2].max())
            else:
                bb = f.bounding_box()
                z_min, z_max = float(bb.min.Z), float(bb.max.Z)
            cylinders.append(
                Cylinder(
                    radius=float(cyl.Radius()),
                    axis_point=(float(loc.X()), float(loc.Y()), float(loc.Z())),
                    axis_dir=(float(d.X()), float(d.Y()), float(d.Z())),
                    area=float(f.area),
                    z_min=z_min,
                    z_max=z_max,
                )
            )
        elif gt == GeomType.PLANE:
            pln = BRepAdaptor_Surface(f.wrapped).Plane()
            loc = pln.Axis().Location()
            n = pln.Axis().Direction()
            # OCCT's plane axis is unsigned with respect to the face; take the face's own normal
            # so a build-plate face reads -1 and a top face reads +1.
            fn = f.normal_at()
            planes.append(PlaneFace(z=float(loc.Z()), normal_z=float(fn.Z), area=float(f.area)))
            del n

    cylinders = _merge_cylinders(cylinders)
    planes = _merge_planes(planes)

    mesh = _tessellate(shape)
    bb = shape.bounding_box()
    return FeatureSet(
        source=source,
        representation="brep",
        cylinders=cylinders,
        planes=planes,
        bbox=(
            float(bb.min.X),
            float(bb.min.Y),
            float(bb.min.Z),
            float(bb.max.X),
            float(bb.max.Y),
            float(bb.max.Z),
        ),
        volume=float(shape.volume),
        watertight=bool(mesh.is_watertight),
        mesh=mesh,
    )


def _tessellate(shape) -> trimesh.Trimesh:
    """Tessellate a BREP shape so statistical queries (wall sampling, overhangs) work on it too.

    Tessellation tolerance is fixed: the spike measured identical fit accuracy at 0.1, 0.01 and
    0.001, so tightening it is never the fix for a measurement disagreement -- the method
    dominates, not the mesh (PRD 15.5).
    """
    verts, tris = shape.tessellate(_TESSELLATION_TOL)
    v = np.array([(p.X, p.Y, p.Z) for p in verts], dtype=float)
    return trimesh.Trimesh(vertices=v, faces=np.asarray(tris, dtype=np.int64), process=True)


def _merge_cylinders(cylinders: list[Cylinder]) -> list[Cylinder]:
    """Coalesce cylindrical faces that OCCT split (booleans routinely halve a cylinder).

    Without this, "the largest cylinder at (0,0)" can select one half of a bore and report its
    area and axial extent as the whole feature's.
    """
    merged: list[Cylinder] = []
    for c in cylinders:
        for i, m in enumerate(merged):
            if (
                abs(m.radius - c.radius) <= _RADIUS_MERGE_TOL
                and abs(m.xy[0] - c.xy[0]) <= _CENTER_MERGE_TOL
                and abs(m.xy[1] - c.xy[1]) <= _CENTER_MERGE_TOL
                and abs(abs(float(np.dot(m.axis_dir, c.axis_dir))) - 1.0) < 1e-6
            ):
                merged[i] = Cylinder(
                    radius=m.radius,
                    axis_point=m.axis_point,
                    axis_dir=m.axis_dir,
                    area=m.area + c.area,
                    z_min=min(m.z_min, c.z_min),
                    z_max=max(m.z_max, c.z_max),
                    fit=m.fit or c.fit,
                )
                break
        else:
            merged.append(c)
    return sorted(merged, key=lambda c: (-c.radius, c.xy))


def _merge_planes(planes: list[PlaneFace]) -> list[PlaneFace]:
    merged: list[PlaneFace] = []
    for p in planes:
        for i, m in enumerate(merged):
            if abs(m.z - p.z) <= _PLANE_MERGE_TOL and abs(m.normal_z - p.normal_z) < 1e-3:
                merged[i] = PlaneFace(m.z, m.normal_z, m.area + p.area)
                break
        else:
            merged.append(p)
    return sorted(merged, key=lambda p: p.z)


# --- mesh path --------------------------------------------------------------------------------


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load an STL or 3MF as a single ``Trimesh``.

    A ``.3mf`` loads as a ``Scene``, not a ``Trimesh``, and reading one requires ``lxml`` --
    which is a hard dependency and is not pulled in transitively (spike 8). ``Scene.to_geometry()``
    replaces the deprecated ``Scene.dump(concatenate=True)``.
    """
    path = Path(path)
    loaded = trimesh.load(str(path), force=None)
    if isinstance(loaded, trimesh.Scene):
        loaded = loaded.to_geometry()
    if not isinstance(loaded, trimesh.Trimesh):
        raise MeasurementError(
            f"{path} did not load as a single mesh (got {type(loaded).__name__})"
        )
    return loaded


def from_mesh(mesh: trimesh.Trimesh, source: str = "<mesh>") -> FeatureSet:
    """Probe a mesh by Z-scanning: sections between plane transitions, circle-fitted."""
    transitions = measure.plane_transitions(mesh)
    cylinders, noncircular, tapered = _scan_cylinders(mesh, transitions)
    planes = _mesh_planes(mesh)
    b = mesh.bounds
    return FeatureSet(
        source=source,
        representation="mesh",
        cylinders=cylinders,
        planes=planes,
        bbox=(
            float(b[0][0]),
            float(b[0][1]),
            float(b[0][2]),
            float(b[1][0]),
            float(b[1][1]),
            float(b[1][2]),
        ),
        volume=float(mesh.volume),
        watertight=bool(mesh.is_watertight),
        noncircular=noncircular,
        tapered=tapered,
        mesh=mesh,
    )


def _scan_cylinders(
    mesh: trimesh.Trimesh, transitions: list[float]
) -> tuple[list[Cylinder], list[Cylinder], list[Cylinder]]:
    """Fit every ring in every slab, then coalesce runs of matching fits into cylinders.

    A slab is the gap between two consecutive plane transitions -- within one slab the
    cross-section is constant, so one section per slab is sufficient and its midpoint is the
    furthest point from either end face.
    """
    slabs: list[tuple[float, float, CircleFit]] = []
    for lo, hi in zip(transitions[:-1], transitions[1:], strict=False):
        if hi - lo < 1e-3:
            continue
        z = 0.5 * (lo + hi)
        try:
            rings = measure.section_rings(mesh, z)
        except MeasurementError:
            continue
        for ring in rings:
            try:
                slabs.append((lo, hi, measure.fit_circle(ring)))
            except MeasurementError:
                continue

    runs: list[dict] = []
    for lo, hi, fit in slabs:
        for run in runs:
            head: CircleFit = run["fit"]
            if (
                abs(head.radius - fit.radius) <= _RADIUS_MERGE_TOL
                and abs(head.cx - fit.cx) <= _CENTER_MERGE_TOL
                and abs(head.cy - fit.cy) <= _CENTER_MERGE_TOL
            ):
                run["z_min"] = min(run["z_min"], lo)
                run["z_max"] = max(run["z_max"], hi)
                # keep the least flattering fit: a feature is only as circular as its worst slice
                if fit.max_residual > head.max_residual:
                    run["fit"] = fit
                break
        else:
            runs.append({"z_min": lo, "z_max": hi, "fit": fit})

    circular: list[Cylinder] = []
    noncircular: list[Cylinder] = []
    tapered: list[Cylinder] = []
    for run in runs:
        fit: CircleFit = run["fit"]
        axis_dir, taper = _measure_axis_and_taper(mesh, run)
        cyl = Cylinder(
            radius=fit.radius,
            axis_point=(fit.cx, fit.cy, run["z_min"]),
            axis_dir=axis_dir,
            area=2.0 * np.pi * fit.radius * (run["z_max"] - run["z_min"]),
            z_min=run["z_min"],
            z_max=run["z_max"],
            fit=fit,
        )
        if not fit.is_circular:
            noncircular.append(cyl)
        elif abs(taper) > MAX_TAPER_PER_MM:
            # A cone slices into a stack of perfectly circular sections, each of a different
            # radius. Reporting any one of them as "the diameter" is exactly the confident,
            # plausible, wrong number this project exists to prevent.
            tapered.append(cyl)
        else:
            circular.append(cyl)
    for group in (circular, noncircular, tapered):
        group.sort(key=lambda c: (-c.radius, c.xy))
    return circular, noncircular, tapered


def _measure_axis_and_taper(
    mesh: trimesh.Trimesh, run: dict
) -> tuple[tuple[float, float, float], float]:
    """Measure a mesh feature's axis direction and its taper, from two sections through it.

    Returns ``(axis_dir, dr/dz)``. Both come from the same pair of sections, taken at 25% and 75%
    of the feature's height: the centre drift gives the axis, the radius change gives the taper.

    The circularity gate alone does **not** catch a tilted bore. A Ø22 bore tilted 5deg sections
    as an ellipse whose max residual is 0.042mm -- inside the 0.05mm gate -- while its reported
    diameter is inflated by 0.084mm, more than a press-fit tolerance. Two sections taken at 25%
    and 75% of the feature's height expose the tilt directly: a tilted axis walks its centre by
    ``dz * tan(theta)``, a straight one does not (ADR-4).
    """
    z_min, z_max = run["z_min"], run["z_max"]
    height = z_max - z_min
    if height < _MIN_PROBE_HEIGHT:
        # Too thin to take two distinct sections through, so neither the axis nor the taper can
        # be established. Reported as infinite taper, which routes it to `tapered` rather than
        # letting an unverifiable sliver be presented as a cylinder with a diameter.
        return (0.0, 0.0, 1.0), float("inf")
    target: CircleFit = run["fit"]
    # A part routinely carries several identical features -- two Ø7 counterbores 54mm apart, for
    # instance. Matching on radius alone pairs one with the other across the two sections and
    # reports their separation as an enormous tilt, so candidates are restricted to rings near
    # this feature's own axis first.
    max_drift = max(2.0 * target.radius, 1.0)
    z1, z2 = z_min + 0.25 * height, z_min + 0.75 * height
    fits = []
    for z in (z1, z2):
        try:
            rings = measure.section_rings(mesh, z)
        except MeasurementError:
            return (0.0, 0.0, 1.0), 0.0
        best, best_err = None, float("inf")
        for ring in rings:
            try:
                f = measure.fit_circle(ring)
            except MeasurementError:
                continue
            if np.hypot(f.cx - target.cx, f.cy - target.cy) > max_drift:
                continue
            err = abs(f.radius - target.radius)
            if err < best_err and err < max(0.25 * target.radius, 0.2):
                best, best_err = f, err
        if best is None:
            return (0.0, 0.0, 1.0), 0.0
        fits.append(best)

    dx = fits[1].cx - fits[0].cx
    dy = fits[1].cy - fits[0].cy
    dz = z2 - z1
    taper = (fits[1].radius - fits[0].radius) / dz if dz else 0.0
    v = np.array([dx, dy, dz], dtype=float)
    n = float(np.linalg.norm(v))
    if n == 0:
        return (0.0, 0.0, 1.0), float(taper)
    v = v / n
    return (float(v[0]), float(v[1]), float(v[2])), float(taper)


def _mesh_planes(mesh: trimesh.Trimesh) -> list[PlaneFace]:
    """Horizontal planar faces of a mesh, grouped by Z.

    Taken from face normals rather than from the section scan: a tessellated horizontal face is
    exact, so there is nothing to bisect toward.

    A near-vertical normal is not sufficient, and neither is flatness. A tessellated bore drilled
    along Y is split into strips, and the strip straddling the crown has **both** edges at the
    same height -- it is exactly flat, exactly horizontal, and not a face at all. Left in, it
    inserts phantom planes at the top and bottom of every horizontal bore and shifts every
    ``plane_gap`` index after them.

    What separates the two is what happens at the edges: a plane stays flat until it stops, so
    its neighbours are either coplanar or meet it at a sharp angle. A curved surface's strips
    meet their neighbours at a *shallow but non-zero* angle. That is the test used here, and it
    needs no area threshold.
    """
    nz = mesh.face_normals[:, 2]
    tri_z = mesh.triangles[:, :, 2]
    flat = (tri_z.max(axis=1) - tri_z.min(axis=1)) < 1e-6

    curved = np.zeros(len(mesh.faces), dtype=bool)
    angles = mesh.face_adjacency_angles
    shallow = (angles > 1e-4) & (angles < np.radians(_CURVATURE_ANGLE_DEG))
    if shallow.any():
        pairs = mesh.face_adjacency[shallow]
        curved[pairs[:, 0]] = True
        curved[pairs[:, 1]] = True

    horiz = (np.abs(nz) > 0.999) & flat & ~curved
    if not horiz.any():
        return []
    zs = mesh.triangles[horiz][:, :, 2].mean(axis=1)
    areas = mesh.area_faces[horiz]
    signs = np.sign(nz[horiz])

    planes: list[PlaneFace] = []
    order = np.argsort(zs)
    for idx in order:
        z, a, s = float(zs[idx]), float(areas[idx]), float(signs[idx])
        if planes and abs(planes[-1].z - z) <= 1e-4 and planes[-1].normal_z == s:
            planes[-1] = PlaneFace(planes[-1].z, s, planes[-1].area + a)
        else:
            planes.append(PlaneFace(round(z, 6), s, a))
    return planes


# --- dispatch ---------------------------------------------------------------------------------


def extract(path: str | Path) -> FeatureSet:
    """Extract features from a STEP, STL or 3MF file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such geometry file: {path}")
    suffix = path.suffix.lower()
    if suffix in (".step", ".stp"):
        from build123d import import_step

        return from_shape(import_step(str(path)), source=str(path))
    if suffix in (".stl", ".3mf", ".obj", ".ply"):
        return from_mesh(load_mesh(path), source=str(path))
    raise MeasurementError(
        f"unsupported geometry format {suffix!r}; expected .step/.stp (BREP) or .stl/.3mf (mesh)"
    )

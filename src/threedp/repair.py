"""Import, diagnose, fix -- and then **measure again**, because the fix can be the defect.

``trimesh.repair.fill_holes`` fills boundary holes "using fans, which may result in bad answers
if the holes are non-convex". A non-convex boundary hole is what a *bore breaking the surface*
looks like. So the failure mode this module exists to prevent is concrete: import a model with a
hole through a Ø22 bore wall, "repair" it, get a watertight mesh whose bore is now bridged, and
report success.

The spike measured the good case as **dimensionally free** -- delete three faces, fill them, and
the largest bore comes back at Ø6.9989 before and after, delta 0.000000 mm. That is exactly why
"it is watertight now" cannot be the verdict: a correct repair and a destructive one are
indistinguishable by inspection, and only a re-measurement tells them apart (ADR-9).

So :func:`repair` never returns a mesh alone. It returns a :class:`RepairResult` whose status is

* ``FAIL`` -- the mesh is still open or inverted, a Tier 1 dimension moved more than ``tol``, or
  a Tier 1 feature that existed before is **absent** after. An absent feature is the defect, the
  same rule as ``intent.py`` and for the same reason.
* ``UNVERIFIABLE`` -- nothing Tier 1 could be compared, because the mesh could not be probed or
  because the part carries no such feature. ``passed`` is False. It does not report success on
  the grounds that it could not look.
* ``PASS`` -- the mesh is closed and every dimension that could be compared held.

Every diameter here comes from :mod:`threedp.features`, which is to say from the one ruler. A
Z-only scan still cannot see angled features, so a repaired angled bore is unverifiable and this
says so rather than guessing (``CLAUDE.md``, "Known accepted gaps").

All dimensions are millimetres.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh
import trimesh.repair

from threedp import features
from threedp.measure import MeasurementError

__all__ = [
    "RepairError",
    "Diagnosis",
    "DimensionDelta",
    "RepairResult",
    "diagnose",
    "repair",
    "verify",
    "PASS",
    "FAIL",
    "UNVERIFIABLE",
    "DEFAULT_DIM_TOL",
    "DEFAULT_OPS",
    "MATCH_TOL_XY",
]

PASS, FAIL, UNVERIFIABLE = "PASS", "FAIL", "UNVERIFIABLE"

# 2x the +/-0.005mm Tier 1 guarantee. Stated rather than tuned: at exactly the guarantee a
# repair that changed nothing could fail on measurement noise, and anything looser stops being
# a dimensional check.
DEFAULT_DIM_TOL = 0.01

# Two cylinders are the same feature if their axes land within this of each other in XY. Repair
# changes face counts and therefore ordering, so matching by list index would compare a bore
# against whichever feature happened to sort into its old slot.
MATCH_TOL_XY = 0.5

# Order matters, and getting it wrong is silent.
#
# Winding is made consistent *before* the holes are filled, because fill_holes orients each new
# patch from its neighbours and an inconsistent neighbour fans the patch the wrong way round.
#
# Inversion is fixed *after*, and only after. trimesh's own note on ``fix_normals`` is that it is
# "really only meaningful on watertight meshes", and the reason is arithmetic: inversion is
# detected from the sign of the enclosed volume, and an open surface does not enclose one. Run in
# the intuitive order -- fix everything, then fill -- this pipeline was measured returning a
# watertight mesh whose volume was **-23065.76 mm3**: closed, plausible-looking, and inside out,
# with every upward face reading as a 90 deg overhang to the DFM engine downstream.
#
# Degenerate and duplicate faces go last, once nothing else will create them.
DEFAULT_OPS = (
    "merge_vertices",
    "fix_winding",
    "fill_holes",
    "fill_holes_fan",
    "fix_normals",
    "remove_degenerate_faces",
    "remove_duplicate_faces",
)


class RepairError(Exception):
    """A repair was asked for something it cannot honestly do."""


# --- diagnosis --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Diagnosis:
    """What is wrong with a mesh, in the vocabulary trimesh answers in."""

    watertight: bool
    winding_consistent: bool
    inverted: bool
    broken_faces: int
    euler_number: int
    volume: float
    duplicate_faces: int
    degenerate_faces: int

    @property
    def healthy(self) -> bool:
        return (
            self.watertight
            and self.winding_consistent
            and not self.inverted
            and self.broken_faces == 0
            and self.duplicate_faces == 0
            and self.degenerate_faces == 0
        )

    def __str__(self) -> str:
        lines = [
            f"watertight={self.watertight}  winding_consistent={self.winding_consistent}  "
            f"broken_faces={self.broken_faces}  euler={self.euler_number}  "
            f"duplicate={self.duplicate_faces}  degenerate={self.degenerate_faces}"
        ]
        if self.inverted:
            # Named as a winding fault, never presented as a measurement. A negative volume fed
            # to intent.check's `volume` kind fails a [5400, 5700] range correctly and for
            # entirely the wrong reason, with a message nobody can act on.
            lines.append(
                f"INVERTED: the surface normals point inward, so the enclosed volume computes "
                f"as {self.volume:.3f} mm3. That is a winding fault, not a size."
            )
        else:
            lines.append(f"volume={self.volume:.3f} mm3")
        return "\n".join(lines)


def _count_false(mask) -> int:
    mask = np.asarray(mask, dtype=bool)
    return int(mask.size - mask.sum())


def diagnose(mesh: trimesh.Trimesh) -> Diagnosis:
    """Describe a mesh's health without changing it."""
    if not isinstance(mesh, trimesh.Trimesh):
        raise RepairError(f"expected a trimesh.Trimesh, got {type(mesh).__name__}")
    volume = float(mesh.volume) if len(mesh.faces) else 0.0
    return Diagnosis(
        watertight=bool(mesh.is_watertight),
        winding_consistent=bool(mesh.is_winding_consistent),
        # A negative enclosed volume means the surface is inside out. This is true whether the
        # winding is consistent (every face flipped) or not (some faces flipped), which is why
        # it is tested on the volume rather than on the winding flag.
        inverted=volume < 0.0,
        broken_faces=int(len(trimesh.repair.broken_faces(mesh))) if len(mesh.faces) else 0,
        euler_number=int(mesh.euler_number),
        volume=volume,
        duplicate_faces=_count_false(mesh.unique_faces()) if len(mesh.faces) else 0,
        degenerate_faces=_count_false(mesh.nondegenerate_faces()) if len(mesh.faces) else 0,
    )


def _boundary_loops(mesh: trimesh.Trimesh) -> int:
    """How many open boundary loops the surface has -- i.e. how many holes are there to fill."""
    if len(mesh.faces) == 0:
        return 0
    single = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    if len(single) == 0:
        return 0
    return len(trimesh.graph.connected_components(mesh.edges_sorted[single], min_len=1))


# --- the dimensional comparison ---------------------------------------------------------------


@dataclass(frozen=True)
class DimensionDelta:
    """One Tier 1 cylinder, measured before the repair and again after it."""

    xy: tuple[float, float]
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before

    def __str__(self) -> str:
        return (
            f"  bore at ({self.xy[0]:.3f}, {self.xy[1]:.3f})  "
            f"before {self.before:.4f} mm  after {self.after:.4f} mm  "
            f"delta {self.delta:+.4f} mm"
        )


@dataclass(frozen=True)
class RepairResult:
    before: Diagnosis
    after: Diagnosis
    ops: list[str] = field(default_factory=list)
    volume_delta: float = 0.0
    faces_added: int = 0
    holes_filled: int = 0
    dimensions: list[DimensionDelta] = field(default_factory=list)
    lost_features: list[tuple[float, float]] = field(default_factory=list)
    status: str = UNVERIFIABLE
    tol: float = DEFAULT_DIM_TOL
    reasons: list[str] = field(default_factory=list)
    mesh: trimesh.Trimesh | None = field(default=None, repr=False, compare=False)

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def moved(self) -> list[DimensionDelta]:
        return [d for d in self.dimensions if abs(d.delta) > self.tol]

    def __str__(self) -> str:
        lines = [
            f"repair   {self.status}   ops: {', '.join(self.ops) or '(none)'}",
            f"  before   {str(self.before).replace(chr(10), chr(10) + '           ')}",
            f"  after    {str(self.after).replace(chr(10), chr(10) + '           ')}",
            f"  volume delta {self.volume_delta:+.6f} mm3   faces {self.faces_added:+d}   "
            f"holes filled {self.holes_filled}",
        ]
        if self.dimensions:
            lines.append(f"  Tier 1 dimensions compared (tol {self.tol} mm):")
            lines += [str(d) for d in self.dimensions]
        for x, y in self.lost_features:
            lines.append(
                f"  ABSENT: the Tier 1 feature at ({x:.3f}, {y:.3f}) existed before the repair "
                f"and does not exist after it. A feature the repair consumed is the defect."
            )
        lines += [f"  {reason}" for reason in self.reasons]
        return "\n".join(lines)


def _match(before_list, after_list, tol_xy: float) -> tuple[list[DimensionDelta], list]:
    """Pair cylinders before and after by axis XY, nearest radius first. Never by list index."""
    remaining = list(after_list)
    pairs: list[DimensionDelta] = []
    lost = []
    for b in before_list:
        candidates = [
            c
            for c in remaining
            if abs(c.xy[0] - b.xy[0]) <= tol_xy and abs(c.xy[1] - b.xy[1]) <= tol_xy
        ]
        if not candidates:
            lost.append(b)
            continue
        best = min(candidates, key=lambda c: abs(c.radius - b.radius))
        remaining.remove(best)
        pairs.append(DimensionDelta(xy=b.xy, before=b.diameter, after=best.diameter))
    return pairs, lost


def _tier1_cylinders(mesh: trimesh.Trimesh, label: str):
    """Every cylinder the one ruler can measure at Tier 1, or ``None`` if it could not look."""
    try:
        found = features.from_mesh(mesh, source=label)
    except MeasurementError:
        return None
    usable = []
    for c in found.cylinders:
        if not c.is_axis_aligned:
            continue  # a Z-scan cannot measure a tilted bore dimensionally (ADR-4)
        try:
            # Consults the circularity gate. A refusal here is not a dimension, so the feature
            # is dropped from the comparison rather than compared on an unchecked radius.
            _ = c.diameter
        except MeasurementError:
            continue
        usable.append(c)
    return usable


def verify(
    before_mesh: trimesh.Trimesh,
    after_mesh: trimesh.Trimesh,
    tol: float = DEFAULT_DIM_TOL,
    before: Diagnosis | None = None,
    after: Diagnosis | None = None,
    ops: tuple[str, ...] | list[str] = (),
    holes_filled: int = 0,
) -> RepairResult:
    """Score a repair by re-measuring, not by re-assuring.

    ``before`` / ``after`` diagnoses are accepted so :func:`repair` does not pay for them twice;
    they are computed here when not supplied.
    """
    before = diagnose(before_mesh) if before is None else before
    after = diagnose(after_mesh) if after is None else after

    reasons: list[str] = []
    status = PASS

    if not after.watertight:
        status = FAIL
        reasons.append(
            f"the mesh is still not watertight after the repair "
            f"({after.broken_faces} broken face(s)); it is not a repaired part"
        )
    if after.inverted:
        status = FAIL
        reasons.append("the mesh is still inverted after the repair; its normals point inward")

    old = _tier1_cylinders(before_mesh, "before")
    new = _tier1_cylinders(after_mesh, "after")

    dimensions: list[DimensionDelta] = []
    lost: list[tuple[float, float]] = []
    if old is None or new is None:
        which = "pre-repair" if old is None else "post-repair"
        if status != FAIL:
            status = UNVERIFIABLE
        reasons.append(
            f"the {which} mesh could not be probed, so no dimension could be compared. "
            f"UNVERIFIABLE is not a pass: nothing was measured."
        )
    else:
        pairs, missing = _match(old, new, MATCH_TOL_XY)
        dimensions = pairs
        lost = [c.xy for c in missing]
        if missing:
            status = FAIL
        moved = [d for d in pairs if abs(d.delta) > tol]
        if moved:
            status = FAIL
            for d in moved:
                reasons.append(
                    f"the bore at ({d.xy[0]:.3f}, {d.xy[1]:.3f}) measured {d.before:.4f} mm "
                    f"before the repair and {d.after:.4f} mm after it -- a change of "
                    f"{d.delta:+.4f} mm, beyond the {tol} mm tolerance. A repair that moves a "
                    f"dimension is a failed repair."
                )
        if not pairs and not missing:
            if status != FAIL:
                status = UNVERIFIABLE
            reasons.append(
                "this part carries no Tier 1 feature a Z-scan can compare, so the repair could "
                "not be checked dimensionally. UNVERIFIABLE, not a pass."
            )

    return RepairResult(
        before=before,
        after=after,
        ops=list(ops),
        volume_delta=float(after.volume - before.volume),
        faces_added=int(len(after_mesh.faces) - len(before_mesh.faces)),
        holes_filled=int(holes_filled),
        dimensions=dimensions,
        lost_features=lost,
        status=status,
        tol=float(tol),
        reasons=reasons,
        mesh=after_mesh,
    )


# --- repair -----------------------------------------------------------------------------------


def _op_merge_vertices(mesh: trimesh.Trimesh) -> None:
    mesh.merge_vertices(digits_vertex=5)


def _op_fix_inversion(mesh: trimesh.Trimesh) -> None:
    trimesh.repair.fix_inversion(mesh)


def _op_fix_winding(mesh: trimesh.Trimesh) -> None:
    trimesh.repair.fix_winding(mesh)


def _op_fix_normals(mesh: trimesh.Trimesh) -> None:
    trimesh.repair.fix_normals(mesh)


def _op_fill_holes(mesh: trimesh.Trimesh) -> None:
    """The safe pass: triangle and quad boundaries only, no fans."""
    trimesh.repair.fill_holes(mesh, use_fan=False)


def _op_fill_holes_fan(mesh: trimesh.Trimesh) -> None:
    """The dangerous pass, run deliberately and named separately in ``ops``.

    ``use_fan=True`` triangulates an arbitrary boundary loop as a fan, which trimesh documents
    "may result in bad answers if the holes are non convex" -- and a bore breaking a surface is
    exactly a non-convex boundary. Declining to fan would make repair unable to close any hole
    bigger than a quad, which is not repair; the hazard is answered by :func:`verify` measuring
    afterwards, not by refusing to act. Which pass closed the mesh is visible in ``ops``.
    """
    if not mesh.is_watertight:
        trimesh.repair.fill_holes(mesh, use_fan=True)


def _op_remove_degenerate_faces(mesh: trimesh.Trimesh) -> None:
    mesh.update_faces(mesh.nondegenerate_faces())


def _op_remove_duplicate_faces(mesh: trimesh.Trimesh) -> None:
    mesh.update_faces(mesh.unique_faces())


_OPS = {
    "merge_vertices": _op_merge_vertices,
    "fix_inversion": _op_fix_inversion,
    "fix_winding": _op_fix_winding,
    "fix_normals": _op_fix_normals,
    "fill_holes": _op_fill_holes,
    "fill_holes_fan": _op_fill_holes_fan,
    "remove_degenerate_faces": _op_remove_degenerate_faces,
    "remove_duplicate_faces": _op_remove_duplicate_faces,
}


def repair(
    mesh: trimesh.Trimesh,
    ops: tuple[str, ...] | list[str] | None = None,
    tol: float = DEFAULT_DIM_TOL,
) -> RepairResult:
    """Repair a copy of ``mesh`` and verify the result against the original.

    The input is never mutated: it is the before-state of the comparison, and repairing it in
    place would erase the only evidence the verdict rests on.
    """
    if not isinstance(mesh, trimesh.Trimesh):
        raise RepairError(f"expected a trimesh.Trimesh, got {type(mesh).__name__}")
    names = tuple(DEFAULT_OPS if ops is None else ops)
    unknown = [n for n in names if n not in _OPS]
    if unknown:
        raise RepairError(f"unknown repair op(s) {unknown}; valid ops: {sorted(_OPS)}")

    before = diagnose(mesh)
    holes = _boundary_loops(mesh)

    working = mesh.copy()
    applied: list[str] = []
    for name in names:
        _OPS[name](working)
        applied.append(name)

    filled_any = any(name.startswith("fill_holes") for name in applied)
    holes_filled = holes - _boundary_loops(working) if filled_any else 0
    return verify(
        mesh,
        working,
        tol=tol,
        before=before,
        ops=applied,
        holes_filled=max(holes_filled, 0),
    )

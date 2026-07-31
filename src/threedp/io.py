"""Export: nominal STEP, compensated STL/3MF.

The split is the point. The **nominal** STEP is written from the un-resolved model and describes
the part; the **compensated** STL/3MF is written from a *separate build* of the same program with
re-resolved parameters and describes the part-plus-this-printer's-error. The STEP is never
post-processed into the STL -- that would be a geometric offset, which is exactly the mechanism
PRD 6.4 replaces.

All dimensions are millimetres.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from threedp.compensate import Resolved, resolve

__all__ = [
    "ExportError",
    "CalibrationStaleWarning",
    "ExportResult",
    "export",
    "LINEAR_DEFLECTION",
    "ANGULAR_DEFLECTION",
]

# Tessellation fidelity. The spike measured *identical* fit accuracy at 0.1, 0.01 and 0.001, so
# tightening this is never the fix for a measurement disagreement -- the method dominates, not
# the mesh (PRD 15.5). 0.01 is chosen for file size.
LINEAR_DEFLECTION = 0.01
ANGULAR_DEFLECTION = 0.1


class ExportError(Exception):
    """An export was asked for something it cannot honestly produce."""


class CalibrationStaleWarning(UserWarning):
    """A compensated file was written from a calibration that has never been measured."""


@dataclass
class ExportResult:
    nominal: dict[str, Path] = field(default_factory=dict)
    compensated: dict[str, Path] = field(default_factory=dict)
    material: str | None = None
    stale: bool = False
    resolved: Resolved | None = None

    @property
    def paths(self) -> list[Path]:
        return [*self.nominal.values(), *self.compensated.values()]

    def __str__(self) -> str:
        lines = [f"nominal      {', '.join(str(p) for p in self.nominal.values()) or '(none)'}"]
        if self.compensated:
            tag = f" [{self.material}]" if self.material else ""
            lines.append(
                f"compensated{tag}  {', '.join(str(p) for p in self.compensated.values())}"
            )
        if self.stale:
            lines.append(f"WARNING: {self.resolved.staleness_warning}" if self.resolved else "")
        return "\n".join(x for x in lines if x)


def _write(shape, path: Path, fmt: str) -> Path:
    import trimesh
    from build123d import Mesher, export_step, export_stl

    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(shape, trimesh.Trimesh):
        if fmt == "step":
            raise ExportError(
                "cannot write a STEP from a mesh. A marching-cubes surface has no BREP behind "
                "it, and tessellating one into a STEP produces a file that is technically CAD "
                "and describes nothing -- no faces, no edges, no parametrisation. The organic "
                "path exports meshes only, on purpose."
            )
        if fmt not in ("stl", "3mf", "obj", "ply"):
            raise ExportError(f"unsupported export format {fmt!r}; expected stl, 3mf, obj or ply")
        shape.export(str(path))
        if not path.exists():
            raise ExportError(f"{fmt} export reported success but wrote no file at {path}")
        return path

    if fmt == "step":
        export_step(shape, str(path))
    elif fmt == "stl":
        export_stl(
            shape, str(path), tolerance=LINEAR_DEFLECTION, angular_tolerance=ANGULAR_DEFLECTION
        )
    elif fmt == "3mf":
        m = Mesher()
        m.add_shape(
            shape, linear_deflection=LINEAR_DEFLECTION, angular_deflection=ANGULAR_DEFLECTION
        )
        m.write(str(path))
    else:
        raise ExportError(f"unsupported export format {fmt!r}; expected step, stl or 3mf")
    if not path.exists():
        raise ExportError(f"{fmt} export reported success but wrote no file at {path}")
    return path


def export(
    part: Any | Callable[[dict[str, float]], Any],
    stem: str | Path,
    nominal: Sequence[str] = ("step",),
    compensated: Sequence[str] = ("stl", "3mf"),
    calibration: Any = None,
    params: dict[str, Any] | None = None,
) -> ExportResult:
    """Export a part.

    ``part`` is either a build123d shape or, when compensation is wanted, a callable
    ``build(resolved) -> shape``. Two separate builds are performed: one with nominal parameters
    for the STEP, one with resolved parameters for the mesh formats. There is deliberately no
    code path that derives the compensated mesh from the nominal shape.
    """
    stem = Path(stem)
    result = ExportResult()

    import trimesh

    is_builder = (
        callable(part) and not hasattr(part, "faces") and not isinstance(part, trimesh.Trimesh)
    )

    if is_builder:
        if params is None:
            raise ExportError("a builder callable needs params to resolve; none were given")
        nominal_params = resolve(params, None)
        nominal_shape = part(nominal_params)
    else:
        nominal_shape = part

    for fmt in nominal:
        result.nominal[fmt] = _write(nominal_shape, stem.with_suffix(f".{fmt}"), fmt)

    if not compensated:
        return result

    if calibration is None:
        # No calibration means no compensation. The mesh is the nominal geometry, which is
        # honest -- it is simply not corrected for any printer.
        comp_shape = nominal_shape
        resolved = resolve(params, None) if params else None
    else:
        if not is_builder:
            raise ExportError(
                "compensation needs a parametric model to re-resolve, not a finished shape. "
                "An imported mesh has no parametrization and would have to fall back to a "
                "uniform geometric offset, where the hole/outer asymmetry is unresolvable -- "
                "press fits on imported meshes are not supported (PRD 6.4)."
            )
        if params is None:
            raise ExportError("compensation needs params to resolve; none were given")
        resolved = resolve(params, calibration)
        comp_shape = part(resolved)
        result.material = resolved.material
        result.stale = resolved.stale

    result.resolved = resolved

    for fmt in compensated:
        result.compensated[fmt] = _write(comp_shape, stem.with_suffix(f".{fmt}"), fmt)

    if result.stale and resolved is not None:
        # Risk 7: a published literature default silently standing in for a measurement. The
        # files are still written -- refusing to export would be worse -- but the caller is told
        # in terms that name the material.
        warnings.warn(resolved.staleness_warning, CalibrationStaleWarning, stacklevel=2)

    return result

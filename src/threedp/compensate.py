"""Compensation by re-parametrization.

Compensation is applied to **parameters, not geometry** (PRD 6.4). Because models are programs,
export re-runs the model with resolved values rather than offsetting a surface. This dissolves
the asymmetry problem entirely: hole and outer deltas differ in sign and magnitude, and because
they land on separate parameters they never have to reconcile into a single offset.

``resolve(params, None)`` returns nominal values **unchanged**. Nominal geometry is the truth,
and compensation must never leak into CAD output (PRD Principle 3).

All dimensions are millimetres.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = [
    "CompensationError",
    "Resolved",
    "resolve",
    "load_calibration",
    "profiles_dir",
    "ROLES",
]

ROLES = ("hole", "outer", "neutral")


class CompensationError(Exception):
    """A parameter set or calibration record cannot be resolved. Never silently defaulted."""


class Resolved(dict):
    """Resolved parameter values.

    A ``dict`` of name -> value, so callers can splat it straight into a model, plus the
    provenance needed to warn about it: which material, which deltas, and whether the
    calibration was ever actually measured.
    """

    def __init__(
        self,
        values: dict[str, float],
        material: str | None = None,
        deltas: dict[str, float] | None = None,
        stale: bool = False,
        compensated: bool = False,
    ):
        super().__init__(values)
        self.material = material
        self.deltas = deltas or {}
        self.stale = stale
        self.compensated = compensated

    @property
    def staleness_warning(self) -> str:
        return (
            f"calibration for {self.material!r} is a published literature default "
            f'("measured": null) and has never been verified on this printer. '
            f"Fits derived from it are unvalidated until a coupon is measured (Phase 3)."
        )


def profiles_dir() -> Path:
    """Locate ``profiles/``.

    Hardware values live in configuration from day one (PRD 3, secondary persona), so this has
    to work whether the package is imported from a checkout or installed into a virtualenv.
    """
    env = os.environ.get("THREEDP_PROFILES")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
        raise CompensationError(f"THREEDP_PROFILES={env!r} is not a directory")

    candidates = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[2]]
    for base in candidates:
        p = base / "profiles"
        if (p / "calibration.json").is_file():
            return p
    raise CompensationError(
        "could not locate profiles/calibration.json; set THREEDP_PROFILES or run from the "
        "repository root"
    )


def load_calibration(material: str | None = None, path: str | Path | None = None) -> dict[str, Any]:
    """Load ``profiles/calibration.json``, or one material record from it."""
    p = Path(path) if path is not None else profiles_dir() / "calibration.json"
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CompensationError(f"no calibration profile at {p}") from exc
    except json.JSONDecodeError as exc:
        raise CompensationError(f"{p} is not valid JSON: {exc}") from exc
    if material is None:
        return data
    if material not in data:
        raise CompensationError(
            f"unknown calibration material {material!r}; available: {sorted(data)}"
        )
    return data[material]


def _as_record(calibration: Any) -> tuple[dict[str, Any], str | None]:
    """Normalise the many shapes a caller may pass for ``calibration``."""
    if isinstance(calibration, str):
        return load_calibration(calibration), calibration
    if isinstance(calibration, dict):
        if "hole_delta_mm" in calibration:
            return calibration, calibration.get("material")
        raise CompensationError(
            "calibration dict has no 'hole_delta_mm'; pass one material record, not the whole "
            f"profile (available: {sorted(calibration)})"
        )
    raise CompensationError(
        f"calibration must be a material name, a material record, or None; got "
        f"{type(calibration).__name__}"
    )


def _entry(name: str, entry: Any) -> tuple[float, str]:
    if not isinstance(entry, dict):
        raise CompensationError(
            f"parameter {name!r} is a bare {type(entry).__name__}. Every dimension must declare "
            f"its semantic role: {{'value': ..., 'role': one of {list(ROLES)}}}. An untagged "
            f"dimension would silently escape compensation (PRD 6.4)."
        )
    if "value" not in entry:
        raise CompensationError(f"parameter {name!r} has no 'value'")
    role = entry.get("role")
    if role not in ROLES:
        raise CompensationError(
            f"parameter {name!r} has role {role!r}; expected one of {list(ROLES)}"
        )
    return float(entry["value"]), role


def resolve(params: dict[str, Any], calibration: Any = None) -> Resolved:
    """Resolve tagged parameters, optionally applying a material's compensation deltas.

    ``role: hole`` gets ``+hole_delta_mm``, ``role: outer`` gets ``+outer_delta_mm``, and
    ``role: neutral`` is untouched. The two deltas have opposite signs and are applied
    independently -- they neither cancel nor combine into one offset, which is the whole point
    of compensating parameters rather than geometry.
    """
    if not isinstance(params, dict) or not params:
        raise CompensationError("params must be a non-empty {name: {value, role}} mapping")

    nominal = {name: _entry(name, entry)[0] for name, entry in params.items()}

    if calibration is None:
        # Nominal is the truth. Byte-identical, no arithmetic applied at all.
        return Resolved(nominal, material=None, deltas={}, stale=False, compensated=False)

    record, material = _as_record(calibration)
    try:
        hole_delta = float(record["hole_delta_mm"])
        outer_delta = float(record["outer_delta_mm"])
    except KeyError as exc:
        raise CompensationError(f"calibration record is missing {exc}") from exc

    deltas = {"hole": hole_delta, "outer": outer_delta, "neutral": 0.0}
    values: dict[str, float] = {}
    for name, entry in params.items():
        value, role = _entry(name, entry)
        values[name] = value + deltas[role]

    return Resolved(
        values,
        material=material,
        deltas=deltas,
        stale=record.get("measured") is None,
        compensated=True,
    )

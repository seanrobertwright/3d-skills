"""Caliper readings in, a calibration record out. Pure arithmetic; no printer, no CAD.

``coupon.py`` builds the stepped fit gauge, the printer prints it, a human measures it, and this
turns those readings into the record ``compensate.resolve`` applies. It closes the last place in
the repository where a published literature default stands in for a measurement: every entry in
``profiles/calibration.json`` shipped with ``"measured": null`` and
``"source": "published-default"``, and ``Resolved.stale`` has been saying so on every compensated
export since Phase 1.

**One formula, and the signs come out opposite by themselves.** ``delta = nominal - measured``,
for a bore and for a stud alike. A printed bore comes out undersize, so its delta is positive and
the parameter is modelled larger; a printed stud comes out oversize, so its delta is negative and
the parameter is modelled smaller. They are never averaged into one offset -- that asymmetry is
precisely what compensating *parameters* rather than *geometry* exists to preserve (PRD 6.4), and
it is why the gauge comes in two kinds. A single "fit offset" would be a number that is wrong for
both.

**A record says when it was measured, not that it was.** ``"measured": true`` would satisfy
``Resolved.stale`` and throw away every fact worth keeping -- which nozzle, which gauge, which
day, which raw readings. PRD Risk 7 is that calibration goes stale silently when a nozzle or a
filament changes, so the record carries enough to notice (ADR-18). ``compensate.load_calibration``
rejects the boolean outright.

**What this refuses.** If the per-step deltas disagree by more than one gauge step, the printer's
error is not a pure offset and no single number describes it. Reporting the mean anyway would be
a plausible, confident, wrong number produced from real measurements, which is the most
persuasive kind. It raises instead, with the spread.

All dimensions are millimetres.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from threedp.compensate import CompensationError, load_calibration, profiles_dir

__all__ = [
    "CalibrationError",
    "DeltaFit",
    "Reading",
    "fit_delta",
    "fit_deltas",
    "build_record",
    "WriteResult",
    "write_record",
    "stale_materials",
    "CALIBRATION_FILE",
    "ROLES",
    "FALLBACK_MAX_SPREAD_MM",
]

CALIBRATION_FILE = "calibration.json"

# `neutral` is deliberately absent: a neutral dimension is never compensated, so there is no
# delta to fit and asking for one is a mistake worth naming.
ROLES = ("hole", "outer")

# Used only when the readings do not describe a stepped gauge (one nominal, repeated). The gauge's
# own step pitch is preferred -- a threshold derived from the artefact beats a threshold chosen
# for it. 0.1 mm is coupon.DEFAULT_STEPS' pitch, quoted rather than re-derived.
FALLBACK_MAX_SPREAD_MM = 0.1

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CalibrationError(Exception):
    """Readings, a role, or a record cannot honestly produce a calibration constant."""


Reading = tuple[float, float]
"""One gauge step: ``(nominal_d, measured_d)``, both in millimetres."""


@dataclass(frozen=True)
class DeltaFit:
    """A fitted compensation delta and the evidence for calling it one number."""

    role: str
    delta_mm: float
    spread_mm: float
    max_residual_mm: float
    steps: tuple[Reading, ...]
    per_step_mm: tuple[float, ...]

    @property
    def n(self) -> int:
        return len(self.steps)

    def __str__(self) -> str:
        return (
            f"{self.role:<5} delta {self.delta_mm:+.4f} mm over {self.n} step(s)   "
            f"spread {self.spread_mm:.4f} mm   max residual {self.max_residual_mm:.4f} mm"
        )


def fit_delta(nominal_d: float, measured_d: float, role: str) -> float:
    """One step's compensation delta: ``nominal - measured``.

    ``role`` is validated rather than ignored, because the sign of the answer is only meaningful
    against a role and the two roles must never be pooled. A ``neutral`` dimension is not
    compensated at all and asking for its delta is a modelling error, not a zero.
    """
    if role not in ROLES:
        raise CalibrationError(
            f"role {role!r} has no compensation delta; expected one of {list(ROLES)}. A "
            f"'neutral' dimension is deliberately never compensated, so fitting one would "
            f"produce a number nothing applies."
        )
    nominal_d = float(nominal_d)
    measured_d = float(measured_d)
    if nominal_d <= 0 or measured_d <= 0:
        raise CalibrationError(
            f"a {role} step reads nominal {nominal_d} / measured {measured_d}; both must be "
            f"positive diameters in mm"
        )
    return nominal_d - measured_d


def _max_spread_mm(nominals: Sequence[float]) -> float:
    """One gauge step, derived from the gauge that produced the readings.

    The steps are 0.1 mm apart by design, and ``coupon`` refuses a gauge whose steps are closer
    together than the assertion band. If the per-step deltas disagree by more than a whole step,
    the offset model has stopped describing the printer -- so the tolerance comes from the
    artefact rather than being picked to make the data pass.
    """
    distinct = sorted({round(float(n), 6) for n in nominals})
    gaps = [b - a for a, b in zip(distinct, distinct[1:], strict=False)]
    return min(gaps) if gaps else FALLBACK_MAX_SPREAD_MM


def fit_deltas(readings: Sequence[Reading], role: str) -> DeltaFit:
    """Fit one compensation delta across every step of a gauge.

    The offset that best fits a set of measurements under a pure-offset model *is* the mean of the
    per-step deltas, so there is no fitting machinery here and none is wanted -- the one ruler in
    this repository is ``measure.py`` and this is arithmetic on numbers a human read off a
    caliper.

    Raises when the per-step deltas disagree by more than one gauge step: at that point the
    printer's error depends on the diameter and a single offset is not a description of it.
    """
    if role not in ROLES:
        raise CalibrationError(f"role {role!r} is not one of {list(ROLES)}")
    steps = tuple((float(n), float(m)) for n, m in readings)
    if len(steps) < 2:
        raise CalibrationError(
            f"a {role} fit needs at least two gauge steps, got {len(steps)}. One step cannot show "
            f"whether the error is a constant offset or grows with diameter, and coupon.fit_gauge "
            f"refuses to build a one-step gauge for the same reason."
        )

    per_step = tuple(fit_delta(n, m, role) for n, m in steps)
    delta = sum(per_step) / len(per_step)
    spread = max(per_step) - min(per_step)
    residual = max(abs(d - delta) for d in per_step)

    limit = _max_spread_mm([n for n, _ in steps])
    if spread > limit:
        detail = ", ".join(f"{n:.2f}->{d:+.4f}" for (n, _), d in zip(steps, per_step, strict=True))
        raise CalibrationError(
            f"the {role} deltas span {spread:.4f} mm across the gauge, which is more than one "
            f"{limit:.2f} mm step: [{detail}]. Compensation applies ONE offset per role, so a "
            f"printer whose error changes with diameter is not described by any single number "
            f"here. Reporting the mean ({delta:+.4f} mm) would be a confident, plausible, wrong "
            f"constant computed from real measurements. Re-measure first -- a single mis-read "
            f"step produces exactly this -- and if the spread is real, the part needs a fit "
            f"tested at its own diameter rather than a profile."
        )

    return DeltaFit(
        role=role,
        delta_mm=delta,
        spread_mm=spread,
        max_residual_mm=residual,
        steps=steps,
        per_step_mm=per_step,
    )


def _iso_date(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, str) or not _ISO_DATE.match(value):
        raise CalibrationError(
            f"'measured' must be an ISO date like '2026-08-09', got {value!r}. A boolean would "
            f"satisfy the staleness check and discard the one fact that lets anyone notice the "
            f"calibration has gone stale -- a nozzle swap or a filament change invalidates it "
            f"silently, and only a date makes that visible (ADR-18, PRD Risk 7)."
        )
    return value


def build_record(
    hole: DeltaFit | Sequence[Reading],
    outer: DeltaFit | Sequence[Reading],
    material: str,
    gauge: str,
    nozzle: str,
    date: str,
    first_layer_squish: float | None = None,
    instrument: str = "digital caliper +/-0.01mm",
) -> dict[str, Any]:
    """Assemble one material's calibration record in ADR-18's shape.

    ``hole`` and ``outer`` are each either an already-computed :class:`DeltaFit` or raw
    ``(nominal, measured)`` readings. **Both are required.** A record fitted from one gauge would
    carry a measured delta beside an inherited one and look complete, and the asymmetry between
    them is the whole reason the gauge comes in two kinds.

    ``first_layer_squish`` is ``None`` by default and is written as ``null``: the fit gauge does
    not measure it, and carrying the old published number forward into a record stamped
    ``"measured"`` would launder a default into a measurement. Nothing in ``compensate`` reads it.
    """
    if not material or not str(material).strip():
        raise CalibrationError("a calibration record must name its material")
    if not str(gauge).strip():
        raise CalibrationError(
            "a calibration record must name the gauge that produced it. 'Which coupon was this?' "
            "is the first question anyone asks of a number that disagrees with their part."
        )
    if not str(nozzle).strip():
        raise CalibrationError(
            "a calibration record must name the nozzle. A 0.6 nozzle and a 0.4 nozzle do not "
            "share a compensation constant, and PRD Risk 7 is exactly this going unnoticed."
        )

    hole_fit = hole if isinstance(hole, DeltaFit) else fit_deltas(hole, "hole")
    outer_fit = outer if isinstance(outer, DeltaFit) else fit_deltas(outer, "outer")
    if hole_fit.role != "hole" or outer_fit.role != "outer":
        raise CalibrationError(
            f"build_record takes a hole fit and an outer fit, in that order; got "
            f"{hole_fit.role!r} and {outer_fit.role!r}. Swapping them inverts both signs and "
            f"produces a profile that makes every fit worse by twice the error."
        )

    return {
        "hole_delta_mm": round(hole_fit.delta_mm, 4),
        "outer_delta_mm": round(outer_fit.delta_mm, 4),
        "first_layer_squish": first_layer_squish,
        "measured": _iso_date(date),
        "source": f"{gauge}, {instrument}",
        "nozzle": str(nozzle),
        "readings": {
            "hole": [[round(n, 4), round(m, 4)] for n, m in hole_fit.steps],
            "outer": [[round(n, 4), round(m, 4)] for n, m in outer_fit.steps],
            "hole_spread_mm": round(hole_fit.spread_mm, 4),
            "outer_spread_mm": round(outer_fit.spread_mm, 4),
        },
    }


@dataclass(frozen=True)
class WriteResult:
    """What ``write_record`` changed, and what it left alone."""

    path: Path
    material: str
    record: dict[str, Any] = field(repr=False, default_factory=dict)
    replaced: dict[str, Any] | None = field(repr=False, default=None)
    untouched: tuple[str, ...] = ()

    def __str__(self) -> str:
        was = "a published default" if self.replaced is None else "an earlier record"
        return (
            f"calibration  {self.material}  hole {self.record['hole_delta_mm']:+.4f} mm  "
            f"outer {self.record['outer_delta_mm']:+.4f} mm  measured {self.record['measured']}  "
            f"(replaced {was}; {', '.join(self.untouched) or 'nothing'} left untouched)"
        )


def write_record(
    material: str,
    record: dict[str, Any],
    path: str | Path | None = None,
) -> WriteResult:
    """Merge one material's record into ``profiles/calibration.json``.

    Every other material is preserved byte-for-byte in content and the file keeps its two-space
    indent, so a diff shows one material changing and nothing else.

    **A measured record is never overwritten by an unmeasured one.** Re-running a workflow with a
    missing date would otherwise quietly discard a real measurement and reinstate a literature
    default under the same key -- and the export would stop warning, which is worse than the
    default itself.
    """
    target = Path(path) if path is not None else profiles_dir() / CALIBRATION_FILE
    if not isinstance(record, dict):
        raise CalibrationError(
            f"a calibration record must be an object, got {type(record).__name__}"
        )
    for required in ("hole_delta_mm", "outer_delta_mm", "measured", "source"):
        if required not in record:
            raise CalibrationError(f"the record for {material!r} is missing {required!r}")
    _iso_date(record.get("measured"))

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CalibrationError(f"no calibration profile at {target}") from exc
    except json.JSONDecodeError as exc:
        raise CalibrationError(f"{target} is not valid JSON: {exc}") from exc

    existing = data.get(material)
    replaced = existing if isinstance(existing, dict) and existing.get("measured") else None

    data[material] = record
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return WriteResult(
        path=target,
        material=material,
        record=record,
        replaced=replaced,
        untouched=tuple(sorted(k for k in data if k != material)),
    )


def stale_materials(path: str | Path | None = None) -> list[str]:
    """Materials still carrying a published default. The remaining Phase 3 work, listed."""
    try:
        data = load_calibration(path=path)
    except CompensationError as exc:
        raise CalibrationError(str(exc)) from exc
    return sorted(k for k, v in data.items() if isinstance(v, dict) and v.get("measured") is None)

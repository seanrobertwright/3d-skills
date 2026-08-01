"""The stepped fit gauge: the physical artefact Phase 3's calibration workflow measures.

A calibration constant is a claim about *this printer with this material*, and the only way to
obtain one is to print a part whose nominal dimensions are known, measure it, and subtract. The
gauge is that part: a row of bores (or pins) stepped in 0.1 mm increments either side of a
nominal, so "which one fits" is a reading rather than a judgement.

**The gauge is exported nominal, always.** Printing a *compensated* gauge measures the
compensation and not the printer -- the correction would be baked into the geometry and then
measured back out again, and the result would be a number that says the printer is perfect. That
is not a caveat in a docstring; :func:`write_gauge` refuses a calibration outright, for the same
reason ``io.export`` refuses to write a STEP from a mesh.

Measured on this machine (spike S11): a five-step Ø9.8-10.2 gauge built, exported and probed back
through ``features``/``measure`` read
``[9.7985, 9.8985, 9.9984, 10.0984, 10.1984]`` -- a maximum error of **0.0016 mm** against
nominal, so 0.1 mm steps are resolved with roughly sixty times the margin needed. The gauge
design is sound before a printer exists.

All dimensions are millimetres.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CouponError",
    "Gauge",
    "fit_gauge",
    "write_gauge",
    "DEFAULT_STEPS",
    "DEFAULT_PITCH",
    "DEFAULT_PLATE_T",
    "DEFAULT_TOL",
    "KINDS",
]

# Symmetric about nominal so the gauge reads in both directions: a hole that comes out undersize
# and a hole that comes out oversize are different printer faults with different fixes.
DEFAULT_STEPS = (-0.2, -0.1, 0.0, 0.1, 0.2)
DEFAULT_PITCH = 16.0
DEFAULT_PLATE_T = 6.0
DEFAULT_PIN_H = 8.0
# Comfortably inside half a step. Wide enough to swallow the 0.0016 mm the ruler actually costs
# (25x over), narrow enough that two adjacent bands are strictly disjoint -- which is what makes
# "the assertions passed" mean "each bore is the bore it claims to be" rather than "some bore
# near here is". At exactly half a step the bands touch, and a reading on the boundary would
# satisfy two assertions at once.
DEFAULT_TOL = 0.04

KINDS = ("hole", "pin")

_ROLE = {"hole": "hole", "pin": "outer"}


class CouponError(Exception):
    """A gauge was asked for something that would make it unable to measure a printer."""


@dataclass(frozen=True)
class Gauge:
    """A built gauge and the two files that make it verifiable."""

    shape: Any
    params: dict[str, Any]
    intent: dict[str, Any]
    kind: str
    nominal_d: float
    diameters: tuple[float, ...]
    positions: tuple[float, ...]

    def __iter__(self):
        """Unpacks as ``shape, params, intent``."""
        return iter((self.shape, self.params, self.intent))

    def __str__(self) -> str:
        steps = ", ".join(f"{d:.2f}" for d in self.diameters)
        return (
            f"fit gauge  {self.kind}  nominal {self.nominal_d:.2f} mm  "
            f"{len(self.diameters)} steps [{steps}]"
        )


def _build(kind, plate_x, plate_y, plate_t, positions, diameters, pin_h):
    from build123d import Align, Box, BuildPart, Cylinder, Locations, Mode

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    with BuildPart() as part:
        Box(plate_x, plate_y, plate_t, align=bottom)
        for x, d in zip(positions, diameters, strict=True):
            if kind == "hole":
                with Locations((x, 0, 0)):
                    Cylinder(radius=d / 2.0, height=plate_t * 3.0, mode=Mode.SUBTRACT)
            else:
                with Locations((x, 0, plate_t)):
                    Cylinder(radius=d / 2.0, height=pin_h, align=bottom)
    return part.part


def fit_gauge(
    nominal_d: float = 10.0,
    steps: tuple[float, ...] = DEFAULT_STEPS,
    kind: str = "hole",
    pitch: float = DEFAULT_PITCH,
    plate_t: float = DEFAULT_PLATE_T,
    pin_h: float = DEFAULT_PIN_H,
    tol: float = DEFAULT_TOL,
) -> Gauge:
    """Build a stepped fit gauge and the ``params``/``intent`` records that go with it.

    ``kind="hole"`` steps a row of bores; ``kind="pin"`` steps a row of studs. Both are needed
    because a printer's hole error and its outer error differ in sign *and* magnitude, which is
    the whole reason compensation is applied per-parameter rather than as one offset (PRD 6.4).

    Returns a :class:`Gauge`, which unpacks as ``shape, params, intent``.
    """
    if kind not in KINDS:
        raise CouponError(f"unknown gauge kind {kind!r}; valid kinds: {list(KINDS)}")
    if nominal_d <= 0:
        raise CouponError(f"nominal diameter must be positive, got {nominal_d}")
    if len(steps) < 2:
        raise CouponError(
            f"a gauge needs at least two steps to be a gauge, got {len(steps)}. One step is a "
            f"part with a hole in it and measures nothing about the printer."
        )
    diameters = tuple(float(nominal_d + s) for s in steps)
    if min(diameters) <= 0:
        raise CouponError(f"step {min(steps)} takes the diameter to {min(diameters)}mm or below")
    gaps = [b - a for a, b in zip(sorted(diameters), sorted(diameters)[1:], strict=False)]
    if any(g <= 2.0 * tol for g in gaps):
        raise CouponError(
            f"steps {sorted(diameters)} are closer together than the +/-{tol}mm assertion band, "
            f"so two adjacent steps could satisfy the same assertion and the gauge could not "
            f"tell them apart"
        )

    n = len(diameters)
    positions = tuple((i - (n - 1) / 2.0) * pitch for i in range(n))
    plate_x = pitch * n
    plate_y = pitch

    role = _ROLE[kind]
    params: dict[str, Any] = {
        "PLATE_X": {"value": plate_x, "role": "outer"},
        "PLATE_Y": {"value": plate_y, "role": "outer"},
        "PLATE_T": {"value": plate_t, "role": "neutral"},
        "PITCH": {"value": pitch, "role": "neutral"},
    }
    if kind == "pin":
        params["PIN_H"] = {"value": pin_h, "role": "neutral"}
    for i, d in enumerate(diameters):
        params[f"STEP_{i}_D"] = {
            "value": d,
            "role": role,
            "note": f"{steps[i]:+.2f}mm from the {nominal_d:.2f}mm nominal",
        }

    asserts = [
        {
            f"step_{i}_diameter": [round(d - tol, 4), round(d + tol, 4)],
            "source": "user-confirmed",
            "measure": {"kind": "cylinder_diameter", "at": [round(x, 4), 0], "rank": "largest"},
            "note": f"step {i}: nominal {d:.2f}mm ({steps[i]:+.2f} from {nominal_d:.2f})",
        }
        for i, (x, d) in enumerate(zip(positions, diameters, strict=True))
    ]
    asserts.append(
        {
            "step_count": [n, n],
            "source": "user-confirmed",
            "measure": {
                "kind": "feature_count",
                "diameter": [round(min(diameters) - tol, 4), round(max(diameters) + tol, 4)],
            },
            # A gauge missing a step is a gauge that reads the wrong number confidently: the
            # user counts along the row and lands on a neighbour. Absence is the defect.
            "note": "every step must exist; a missing one shifts every reading after it",
        }
    )
    intent = {
        "holds": (
            f"stepped fit gauge: {n} {kind}s from {min(diameters):.2f} to {max(diameters):.2f}mm "
            f"around a {nominal_d:.2f}mm nominal, for measuring this printer's fit offset"
        ),
        "asserts": asserts,
    }

    shape = _build(kind, plate_x, plate_y, plate_t, positions, diameters, pin_h)
    return Gauge(
        shape=shape,
        params=params,
        intent=intent,
        kind=kind,
        nominal_d=float(nominal_d),
        diameters=diameters,
        positions=positions,
    )


def write_gauge(
    outdir: str | Path,
    gauge: Gauge | None = None,
    calibration: Any = None,
    stem: str = "coupon",
    **kwargs: Any,
) -> dict[str, Path]:
    """Write a gauge's ``params.json``, ``intent.json`` and **nominal** geometry.

    ``calibration`` exists only so that passing one produces an explanation rather than silently
    compensated geometry. A compensated gauge measures the compensation.
    """
    from threedp import io

    if calibration is not None:
        raise CouponError(
            "a fit gauge is exported nominal and cannot be compensated. Printing a compensated "
            "gauge measures the compensation rather than the printer: the correction is baked "
            "into the geometry and then measured back out, and the answer always says the "
            "printer is perfect. Export it nominal, print it, measure it, and feed the result "
            "into calibration.json (Phase 3)."
        )

    gauge = fit_gauge(**kwargs) if gauge is None else gauge
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for name, payload in (("params.json", gauge.params), ("intent.json", gauge.intent)):
        path = out / name
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        written[name] = path

    result = io.export(
        gauge.shape, out / stem, nominal=("step",), compensated=("stl", "3mf"), calibration=None
    )
    for fmt, path in {**result.nominal, **result.compensated}.items():
        written[fmt] = path
    return written

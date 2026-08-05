"""A calibration that has never been measured must WARN, and must not fail the part.

**The false-positive detector for the staleness channel**, and its companion assertion in one
place. Two things have to stay true at once and they pull in opposite directions:

* an unmeasured calibration is not a defect in the geometry, so the part still passes its intent
  -- ``EXPECT = "PASS"``. A verifier that failed every part whose material profile was a published
  default would refuse the entire repository on the day it shipped, which is a slower route to the
  same place as having no verifier at all;
* and the export must still say so. ``Resolved.stale`` and ``CalibrationStaleWarning`` exist
  precisely because a literature default silently standing in for a measurement is PRD Risk 7, and
  a warning nobody emits is a warning nobody reads.

So the assertion that matters here is *inside* ``method_patch``, and it runs before the intent
check: a stale record must produce ``stale=True`` and a ``CalibrationStaleWarning``, a dated one
must produce neither, and a boolean ``"measured": true`` -- the shape someone reaches for when
cutting the corner -- must be refused outright (ADR-18). If any of those stops holding, this
mutation raises and the harness scores it a HARNESS ERROR, which is loud and is not "caught".

The records are constructed here rather than read from ``profiles/calibration.json``, so the
mutation keeps scoring the mechanism after 3B replaces those defaults with real measurements.
"""

import contextlib
import warnings

EXPECT = "PASS"
REASON = "an unmeasured calibration warns about the fit; it does not make the part wrong"
KIND = "method"
SOURCE = "stl"

_STALE = {
    "hole_delta_mm": 0.18,
    "outer_delta_mm": -0.05,
    "measured": None,
    "source": "published-default",
    "material": "PLA_generic",
}
_DATED = {
    **_STALE,
    "measured": "2026-08-09",
    "source": "coupon:hole-10mm-5step + coupon:pin-10mm-5step, digital caliper +/-0.01mm",
}
_BOOLEAN = {**_STALE, "measured": True}

_PARAMS = {
    "BORE": {"value": 22.0, "role": "hole"},
    "OD": {"value": 40.0, "role": "outer"},
    "H": {"value": 12.0, "role": "neutral"},
}


def _build(resolved):
    from build123d import Align, BuildPart, Cylinder, Mode

    with BuildPart() as part:
        Cylinder(
            radius=resolved["OD"] / 2.0,
            height=resolved["H"],
            align=(Align.CENTER, Align.CENTER, Align.MIN),
        )
        Cylinder(
            radius=resolved["BORE"] / 2.0,
            height=resolved["H"] * 3.0,
            align=(Align.CENTER, Align.CENTER, Align.CENTER),
            mode=Mode.SUBTRACT,
        )
    return part.part


@contextlib.contextmanager
def method_patch():
    import tempfile
    from pathlib import Path

    from threedp import compensate, io

    stale = compensate.resolve(_PARAMS, _STALE)
    assert stale.stale, 'a record with "measured": null must resolve as stale'
    # The deltas are applied with opposite signs and never reconciled into one offset -- checked
    # here because a stale record is exactly where somebody would be tempted to shortcut them.
    assert stale["BORE"] > _PARAMS["BORE"]["value"], "the hole delta was not applied"
    assert stale["OD"] < _PARAMS["OD"]["value"], "the outer delta was not applied"

    dated = compensate.resolve(_PARAMS, _DATED)
    assert not dated.stale, 'a record with an ISO "measured" date must NOT resolve as stale'

    try:
        compensate.resolve(_PARAMS, _BOOLEAN)
    except compensate.CompensationError:
        pass
    else:  # pragma: no cover - reaching this is the failure
        raise AssertionError('"measured": true must be refused, not treated as measured (ADR-18)')

    with tempfile.TemporaryDirectory(prefix="stale-cal-") as tmp:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            io.export(
                _build,
                Path(tmp) / "part",
                nominal=(),
                compensated=("stl",),
                calibration=_STALE,
                params=_PARAMS,
            )
        kinds = [w.category for w in caught]
        assert io.CalibrationStaleWarning in kinds, (
            f"exporting against an unmeasured calibration emitted {kinds} and no "
            f"CalibrationStaleWarning; the staleness channel is silent"
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            io.export(
                _build,
                Path(tmp) / "dated",
                nominal=(),
                compensated=("stl",),
                calibration=_DATED,
                params=_PARAMS,
            )
        assert io.CalibrationStaleWarning not in [w.category for w in caught], (
            "a measured calibration warned about staleness; the channel cries wolf and will be "
            "ignored when it matters"
        )

    yield

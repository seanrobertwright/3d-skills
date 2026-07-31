"""``intent.json`` -- the assertions, written before the geometry, that the model is scored against.

The point of writing intent first is that it is the only check not derived from the geometry it
is checking. Golden bounding boxes and volumes are generated *from* the model and therefore
cannot detect first-pass error -- only drift -- so they are reported in their own section and
**never** contribute to the verdict (PRD 6.1).

Three rules this module exists to enforce:

* **An absent feature FAILs with a reason, never skips.** PRD 15.2 defect 2 was "no 4.5mm
  cylinder existed anywhere". A checker that skipped absent features would have scored that
  part green.
* **A non-circular mesh section FAILs with a reason** -- not a crash, and never a pass (ADR-4).
* **Tier 2 dimensional claims are labelled ESTIMATE and excluded from pass/fail.** Reporting an
  unverifiable number as a pass is the failure this project exists to prevent.

Schema (PRD 6.1, plus a ``measure`` block declaring *how* each name is obtained)::

    {
      "holds": "608 bearing (22 OD x 7 W)",
      "asserts": [
        {"bore_diameter": [21.95, 22.05], "source": "parts-db:608.od",
         "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": "largest"}}
      ],
      "golden": {"bbox": [30.0, 30.0, 20.0], "volume": 10455.22, "tol_pct": 1.0}
    }

``hi = null`` means unbounded: ``"min_wall": [3.00, null]``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from threedp import parts
from threedp.features import FeatureSet
from threedp.measure import MeasurementError, NotCircularError

__all__ = [
    "IntentError",
    "Assertion",
    "AssertionResult",
    "DriftResult",
    "Citation",
    "Intent",
    "Report",
    "load",
    "check",
    "MEASURE_KINDS",
    "MEASURE_UNITS",
    "unit_for",
]

RESERVED_KEYS = {"source", "measure", "tier", "note", "unit"}

PASS, FAIL, ESTIMATE = "PASS", "FAIL", "ESTIMATE"


class IntentError(Exception):
    """The intent file itself is malformed. Distinct from a part that fails its intent."""


# --- schema -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Assertion:
    name: str
    lo: float | None
    hi: float | None
    source: str
    spec: dict[str, Any]
    forced_tier: int | None = None
    note: str = ""

    def contains(self, value: float) -> bool:
        if self.lo is not None and value < self.lo:
            return False
        if self.hi is not None and value > self.hi:
            return False
        return True

    @property
    def expected(self) -> str:
        lo = "-inf" if self.lo is None else f"{self.lo:.2f}"
        hi = "+inf" if self.hi is None else f"{self.hi:.2f}"
        return f"{lo}-{hi}"


@dataclass(frozen=True)
class AssertionResult:
    name: str
    value: float | None
    assertion: Assertion
    tier: int
    status: str
    reason: str = ""

    @property
    def gating(self) -> bool:
        """Tier 2 dimensional claims are reported but never gate a verdict (PRD 6.2)."""
        return self.status != ESTIMATE


@dataclass(frozen=True)
class DriftResult:
    name: str
    value: float
    golden: float
    tol_pct: float

    @property
    def delta_pct(self) -> float:
        if self.golden == 0:
            return 0.0 if self.value == 0 else float("inf")
        return 100.0 * (self.value - self.golden) / self.golden

    @property
    def within(self) -> bool:
        return abs(self.delta_pct) <= self.tol_pct


@dataclass(frozen=True)
class Citation:
    name: str
    source: str
    cited_value: float | None
    brackets: bool
    reason: str = ""


@dataclass(frozen=True)
class Intent:
    holds: str
    asserts: list[Assertion]
    golden: dict[str, Any] = field(default_factory=dict)
    path: str = "<inline>"


def _parse_assertion(entry: dict[str, Any], index: int) -> Assertion:
    """Pull the single measurement name out of an assertion entry.

    The name is whatever key is not reserved. Zero or several is an error rather than a guess --
    silently picking one would let a typo'd key become an unchecked assertion.
    """
    if not isinstance(entry, dict):
        raise IntentError(f"assert #{index} is {type(entry).__name__}, expected an object")
    names = [k for k in entry if k not in RESERVED_KEYS]
    if not names:
        raise IntentError(
            f"assert #{index} names no measurement; expected one key "
            f"outside {sorted(RESERVED_KEYS)}"
        )
    if len(names) > 1:
        raise IntentError(
            f"assert #{index} names several measurements {names}; expected exactly one"
        )
    name = names[0]

    rng = entry[name]
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        raise IntentError(f"assert {name!r} must be a [lo, hi] pair, got {rng!r}")
    lo = None if rng[0] is None else float(rng[0])
    hi = None if rng[1] is None else float(rng[1])
    if lo is None and hi is None:
        raise IntentError(f"assert {name!r} is unbounded on both ends and checks nothing")
    if lo is not None and hi is not None and lo > hi:
        raise IntentError(f"assert {name!r} has lo {lo} above hi {hi}")

    source = entry.get("source")
    if not source:
        raise IntentError(
            f"assert {name!r} carries no source. Every assertion must be grounded outside the "
            f"agent's own reasoning: a parts-db citation or 'user-confirmed' (PRD 6.1)."
        )

    spec = entry.get("measure")
    if not isinstance(spec, dict) or "kind" not in spec:
        raise IntentError(
            f"assert {name!r} has no measure block; expected "
            f'"measure": {{"kind": "...", ...}} naming one of {sorted(MEASURE_KINDS)}'
        )
    if spec["kind"] not in MEASURE_KINDS:
        raise IntentError(
            f"assert {name!r} uses unknown measure kind {spec['kind']!r}; "
            f"valid kinds: {sorted(MEASURE_KINDS)}"
        )

    tier = entry.get("tier")
    if tier is not None and tier not in (1, 2):
        raise IntentError(f"assert {name!r} declares tier {tier!r}; expected 1 or 2")

    return Assertion(name, lo, hi, str(source), dict(spec), tier, str(entry.get("note", "")))


def _is_number(v: Any) -> bool:
    # bool is an int subclass; `"volume": true` is a malformed intent, not a volume of 1.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_golden(golden: Any, where: str) -> dict[str, Any]:
    """Validate the golden regression block.

    ``check()`` indexes ``bbox`` by axis and floats ``volume``. Left unvalidated, a two-entry
    bbox raises ``IndexError`` from inside ``check()`` instead of the ``IntentError`` that means
    "the intent file itself is malformed" -- a distinction every other path through ``load()``
    is careful about, and the one that tells a user whether to fix their JSON or their part.
    """
    if not isinstance(golden, dict):
        raise IntentError(f"{where}: 'golden' must be an object, got {type(golden).__name__}")
    if "bbox" in golden:
        bbox = golden["bbox"]
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 3:
            raise IntentError(
                f"{where}: golden 'bbox' must be [x, y, z] - three numbers; got {bbox!r}"
            )
        for axis, v in zip("xyz", bbox, strict=True):
            if not _is_number(v):
                raise IntentError(f"{where}: golden bbox {axis} is {v!r}, expected a number")
    for key in ("volume", "tol_pct"):
        if key in golden and not _is_number(golden[key]):
            raise IntentError(f"{where}: golden {key!r} is {golden[key]!r}, expected a number")
    return dict(golden)


def load(path: str | Path | dict[str, Any]) -> Intent:
    """Load and validate an ``intent.json``."""
    if isinstance(path, dict):
        data, where = path, "<inline>"
    else:
        p = Path(path)
        if not p.exists():
            raise IntentError(f"no intent file at {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IntentError(f"{p} is not valid JSON: {exc}") from exc
        where = str(p)

    if "asserts" not in data:
        raise IntentError(f"{where} has no 'asserts' list")
    if not isinstance(data["asserts"], list) or not data["asserts"]:
        raise IntentError(f"{where} has an empty 'asserts' list and would pass anything")

    asserts = [_parse_assertion(e, i) for i, e in enumerate(data["asserts"])]
    seen: set[str] = set()
    for a in asserts:
        if a.name in seen:
            raise IntentError(f"{where} asserts {a.name!r} twice; one of them is dead")
        seen.add(a.name)

    golden = _validate_golden(data.get("golden", {}), where)
    return Intent(str(data.get("holds", "")), asserts, golden, where)


# --- measurement kinds ------------------------------------------------------------------------
#
# Each kind returns (value, tier, note). Raising MeasurementError is how a kind reports "this
# feature is absent" -- check() turns that into a FAIL with a reason, never a skip.


def _at(spec: dict[str, Any]) -> tuple[float, float]:
    at = spec.get("at", [0.0, 0.0])
    if not isinstance(at, (list, tuple)) or len(at) != 2:
        raise MeasurementError(f"'at' must be an [x, y] pair, got {at!r}")
    return float(at[0]), float(at[1])


def _mesh_tier(fs: FeatureSet, cyl) -> tuple[int, str]:
    """Tier for a mesh-derived cylinder measurement (ADR-4).

    A Z-scan slices an angled bore into an ellipse, which can pass a loose circularity gate
    while reporting a diameter inflated by ~0.4%. Tilt therefore demotes to ESTIMATE rather
    than being quietly accepted.
    """
    if fs.representation != "mesh":
        return 1, ""
    if not cyl.is_axis_aligned:
        return 2, (
            f"axis is {cyl.tilt_deg:.2f} deg off Z; a Z-scan cannot measure it dimensionally"
        )
    return 1, ""


def _k_cylinder_diameter(fs: FeatureSet, spec: dict[str, Any]):
    x, y = _at(spec)
    cyl = fs.select_cylinder(x, y, spec.get("rank", "largest"), float(spec.get("tol_xy", 0.5)))
    tier, note = _mesh_tier(fs, cyl)
    value = cyl.diameter_unchecked if tier == 2 else cyl.diameter
    return value, tier, note


def _k_cylinder_depth(fs: FeatureSet, spec: dict[str, Any]):
    x, y = _at(spec)
    cyl = fs.select_cylinder(x, y, spec.get("rank", "largest"), float(spec.get("tol_xy", 0.5)))
    tier, note = _mesh_tier(fs, cyl)
    return cyl.depth, tier, note


def _k_coaxial_step_radial(fs: FeatureSet, spec: dict[str, Any]):
    """Radial gap between two coaxial cylinders: a wall, or a retaining lip.

    ``between`` indexes the radius-sorted list of cylinders at that XY, largest first, so it
    describes structure ("the gap between the outermost and the bore") rather than presupposing
    a dimension. If a mutation removes a feature the structure changes and the measurement comes
    out wrong -- which is the intended outcome.
    """
    x, y = _at(spec)
    idx = spec.get("between", [0, 1])
    if not isinstance(idx, (list, tuple)) or len(idx) != 2:
        raise MeasurementError(f"'between' must be a pair of indices, got {idx!r}")
    hits = fs.cylinders_at(x, y, float(spec.get("tol_xy", 0.5)))
    i, j = int(idx[0]), int(idx[1])
    if max(i, j) >= len(hits):
        raise MeasurementError(
            f"only {len(hits)} coaxial cylinder(s) at ({x:g}, {y:g}); "
            f"the step between #{i} and #{j} does not exist - a feature is absent"
        )
    outer, inner = hits[i], hits[j]
    tier_o, note_o = _mesh_tier(fs, outer)
    tier_i, note_i = _mesh_tier(fs, inner)
    d_o = outer.diameter_unchecked if tier_o == 2 else outer.diameter
    d_i = inner.diameter_unchecked if tier_i == 2 else inner.diameter
    return (d_o - d_i) / 2.0, max(tier_o, tier_i), (note_o or note_i)


def _k_feature_count(fs: FeatureSet, spec: dict[str, Any]):
    """How many cylinders fall in a diameter band. Zero is a legitimate, reportable answer."""
    band = spec.get("diameter")
    if not isinstance(band, (list, tuple)) or len(band) != 2:
        raise MeasurementError(f"feature_count needs a 'diameter': [lo, hi] band, got {band!r}")
    lo, hi = float(band[0]), float(band[1])
    n = sum(1 for c in fs.cylinders if lo <= c.diameter_unchecked <= hi)
    return float(n), 1, ""


def _k_plane_gap(fs: FeatureSet, spec: dict[str, Any]):
    """Distance between two horizontal planes, selected by index into their sorted Z values.

    This is how a *box* wall gets a Tier 1 number: a floor thickness is the gap between the
    build-plate face and the cavity floor, and no coaxial step describes it. Selection is by
    structural position ("the gap between the lowest and the next plane up") rather than by the
    value being asserted.
    """
    zs = sorted({round(p.z, 4) for p in fs.horizontal_planes()})
    idx = spec.get("between", [0, 1])
    if not isinstance(idx, (list, tuple)) or len(idx) != 2:
        raise MeasurementError(f"'between' must be a pair of indices, got {idx!r}")
    i, j = int(idx[0]), int(idx[1])
    for k in (i, j):
        if not -len(zs) <= k < len(zs):
            raise MeasurementError(
                f"only {len(zs)} horizontal plane(s) found at z={zs}; index {k} names one that "
                f"is absent"
            )
    return abs(zs[j] - zs[i]), 1, ""


def _k_noncircular_count(fs: FeatureSet, spec: dict[str, Any]):
    """How many mesh sections the circularity gate refused.

    A ruler-integrity measurement, not a design dimension: on a part with a known non-circular
    profile this must be non-zero, and it drops to zero the moment the gate stops gating. Only
    the mesh path fits circles, so on a BREP source it is always 0 and asserting on it there
    would be checking nothing.
    """
    if fs.representation != "mesh":
        raise MeasurementError(
            "noncircular_count is a mesh-path measurement; a BREP source fits no circles and "
            "so has no circularity gate to check"
        )
    return float(len(fs.noncircular)), 1, ""


def _k_bbox(axis: int) -> Callable[[FeatureSet, dict[str, Any]], tuple[float, int, str]]:
    def kind(fs: FeatureSet, spec: dict[str, Any]):
        return fs.bbox_size[axis], 1, ""

    return kind


def _k_volume(fs: FeatureSet, spec: dict[str, Any]):
    return fs.volume, 1, ""


def _k_watertight(fs: FeatureSet, spec: dict[str, Any]):
    return (1.0 if fs.watertight else 0.0), 1, ""


def _require_mesh(fs: FeatureSet):
    if fs.mesh is None:
        raise MeasurementError(f"{fs.source} carries no mesh; this measurement needs one")
    return fs.mesh


def _k_sampled_min_wall(fs: FeatureSet, spec: dict[str, Any]):
    """Ray-sampled minimum wall. Sampled, therefore Tier 2 ESTIMATE -- always."""
    from threedp import printability

    report = printability.min_wall(_require_mesh(fs), samples=int(spec.get("samples", 2000)))
    return report.min_mm, 2, f"ray-sampled over {report.samples} surface points"


def _k_max_overhang_deg(fs: FeatureSet, spec: dict[str, Any]):
    from threedp import printability

    report = printability.overhang_histogram(
        _require_mesh(fs), threshold_deg=float(spec.get("threshold_deg", 45.0))
    )
    return report.max_deg, 1, "measured from vertical; 0 = vertical wall, 90 = horizontal ceiling"


def _k_unsupported_area(fs: FeatureSet, spec: dict[str, Any]):
    from threedp import printability

    report = printability.overhang_histogram(
        _require_mesh(fs), threshold_deg=float(spec.get("threshold_deg", 45.0))
    )
    return report.unsupported_area, 1, ""


# Not every measurement is a length, and the report is the one surface a human actually reads
# before committing a part to a multi-hour print. The formatter previously suffixed every value
# with "mm", which printed degrees, areas, volumes and booleans as millimetres on all five
# benchmarks. "All dimensions are millimetres" governs *variable names*; it is not a licence to
# label a number that is not a length.
DEFAULT_UNIT = "mm"
MEASURE_UNITS: dict[str, str] = {
    "max_overhang_deg": "deg",
    "unsupported_area": "mm2",
    "volume": "mm3",
    "watertight": "",  # boolean
    "feature_count": "",  # a count
    "noncircular_count": "",  # a count
}


def unit_for(kind: str) -> str:
    """The unit a measure kind reports in. Lengths are the default; everything else is declared."""
    return MEASURE_UNITS.get(kind, DEFAULT_UNIT)


MEASURE_KINDS: dict[str, Callable[[FeatureSet, dict[str, Any]], tuple[float, int, str]]] = {
    "cylinder_diameter": _k_cylinder_diameter,
    "cylinder_depth": _k_cylinder_depth,
    "coaxial_step_radial": _k_coaxial_step_radial,
    "feature_count": _k_feature_count,
    "plane_gap": _k_plane_gap,
    "noncircular_count": _k_noncircular_count,
    "bbox_x": _k_bbox(0),
    "bbox_y": _k_bbox(1),
    "bbox_z": _k_bbox(2),
    "volume": _k_volume,
    "watertight": _k_watertight,
    "sampled_min_wall": _k_sampled_min_wall,
    "max_overhang_deg": _k_max_overhang_deg,
    "unsupported_area": _k_unsupported_area,
}


# --- checking ---------------------------------------------------------------------------------


@dataclass
class Report:
    part: str
    holds: str
    results: list[AssertionResult]
    drift: list[DriftResult] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    representation: str = ""

    @property
    def failures(self) -> list[AssertionResult]:
        return [r for r in self.results if r.status == FAIL]

    @property
    def estimates(self) -> list[AssertionResult]:
        return [r for r in self.results if r.status == ESTIMATE]

    @property
    def passed(self) -> bool:
        """True only if every gating assertion passed.

        Drift and ESTIMATE lines are deliberately excluded: a golden value cannot detect
        first-pass error, and an unverifiable claim must not be able to produce a green verdict.
        """
        return not self.failures and any(r.gating for r in self.results)

    def __str__(self) -> str:
        ok, bad, est = _symbols()
        header = f"{self.part}  [{self.representation}]"
        lines = [header + (f"  holds: {self.holds}" if self.holds else "")]
        width = max((len(r.name) for r in self.results), default=0)
        for r in self.results:
            mark = {PASS: ok, FAIL: bad, ESTIMATE: est}[r.status]
            value = "     --" if r.value is None else f"{r.value:9.3f}"
            unit = unit_for(r.assertion.spec.get("kind", ""))
            if r.status == ESTIMATE:
                tail = f"ESTIMATE (Tier {r.tier} - not dimensionally verified)"
            else:
                tail = f"expected {r.assertion.expected}"
            lines.append(
                f"{mark} {r.name:<{width}} = {value} {unit:<3}  {tail}   [{r.assertion.source}]"
            )
            if r.reason:
                lines.append(f"   +- {r.reason}")
        if self.drift:
            lines.append("   -- golden regression (drift only; never a pass/fail signal) --")
            for d in self.drift:
                mark = ok if d.within else est
                unit = unit_for(d.name)
                lines.append(
                    f"{mark} {d.name:<{width}} = {d.value:9.3f} {unit:<3}  golden {d.golden:.3f}"
                    f"   drift {d.delta_pct:+.2f}%"
                )
        for c in self.citations:
            if not c.brackets:
                lines.append(f"{est} citation {c.name}: {c.reason}")
        lines.append("")
        verdict = "PASS" if self.passed else "FAIL"
        lines.append(
            f"VERDICT: {verdict}   "
            f"{sum(1 for r in self.results if r.status == PASS)} passed, "
            f"{len(self.failures)} failed, {len(self.estimates)} estimate(s)"
        )
        return "\n".join(lines)


def _symbols() -> tuple[str, str, str]:
    """Unicode marks where the console can render them, ASCII where it cannot.

    A verifier that crashes on a Windows console encoding while printing its own verdict is a
    verifier that reports nothing.
    """
    enc = (getattr(sys.stdout, "encoding", None) or "ascii").lower()
    try:
        "✅❌⚠".encode(enc)
    except (LookupError, UnicodeEncodeError):
        return "[OK]", "[!!]", "[~ ]"
    return "✅", "❌", "⚠ "


def _check_citation(a: Assertion) -> Citation | None:
    """Advisory: does the cited parts-db value actually fall inside the asserted range?

    A citation that does not bracket its own assertion means the intent is wrong, not the part.
    Reported, never gating -- an author legitimately offsets a range from a cited nominal
    (a press fit, a clearance), and crying wolf on that would make the whole report ignorable.
    """
    if not a.source.startswith(parts.CITATION_PREFIX):
        return None
    try:
        value = parts.resolve_citation(a.source)
    except KeyError as exc:
        return Citation(a.name, a.source, None, False, f"unresolvable citation: {exc}")
    if a.contains(value):
        return Citation(a.name, a.source, value, True)
    return Citation(
        a.name,
        a.source,
        value,
        False,
        f"cites {value:.3f}mm but asserts {a.expected} - the citation does not bracket the range",
    )


def check(features: FeatureSet, intent: str | Path | dict[str, Any] | Intent) -> Report:
    """Score a :class:`~threedp.features.FeatureSet` against its ``intent.json``."""
    spec = intent if isinstance(intent, Intent) else load(intent)

    results: list[AssertionResult] = []
    citations: list[Citation] = []
    for a in spec.asserts:
        cite = _check_citation(a)
        if cite is not None:
            citations.append(cite)
        results.append(_check_one(features, a))

    drift: list[DriftResult] = []
    golden = spec.golden or {}
    tol = float(golden.get("tol_pct", 1.0))
    if "volume" in golden:
        drift.append(DriftResult("volume", features.volume, float(golden["volume"]), tol))
    if "bbox" in golden:
        for axis, name in enumerate(("bbox_x", "bbox_y", "bbox_z")):
            drift.append(
                DriftResult(name, features.bbox_size[axis], float(golden["bbox"][axis]), tol)
            )

    return Report(
        part=features.source,
        holds=spec.holds,
        results=results,
        drift=drift,
        citations=citations,
        representation=features.representation,
    )


def _check_one(fs: FeatureSet, a: Assertion) -> AssertionResult:
    kind = MEASURE_KINDS[a.spec["kind"]]
    try:
        value, tier, note = kind(fs, a.spec)
    except NotCircularError as exc:
        # ADR-4: never a silent pass, never a crash.
        return AssertionResult(a.name, None, a, 1, FAIL, str(exc))
    except MeasurementError as exc:
        # An absent feature IS the defect (PRD 15.2 defect 2). Never a skip.
        return AssertionResult(a.name, None, a, 1, FAIL, str(exc))

    if a.forced_tier is not None:
        tier = max(tier, a.forced_tier)

    if tier >= 2:
        detail = note or "Tier 2 - topology and statistics only"
        within = a.contains(value)
        return AssertionResult(
            a.name,
            value,
            a,
            tier,
            ESTIMATE,
            f"{detail}; {'inside' if within else 'OUTSIDE'} {a.expected} but not gating",
        )

    if a.contains(value):
        return AssertionResult(a.name, value, a, tier, PASS, note)
    return AssertionResult(
        a.name,
        value,
        a,
        tier,
        FAIL,
        a.note or f"measured {value:.3f}mm, outside {a.expected}",
    )

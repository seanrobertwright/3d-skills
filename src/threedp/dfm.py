"""The DFM rules engine: cited thresholds in, findings with evidence out.

``printability.py`` measures; this module compares. That split is ADR-7 and it is the whole
design: **no threshold in this file is a number**. Every one of them lives in
``profiles/dfm-rules.json`` next to the ``source`` that justifies it, exactly as every standard
part dimension lives in ``parts.py`` next to its citation. An uncited threshold is an invented
number wearing a lab coat, so ``load_rules`` refuses to load one.

Three refusals, each closing a way a rules engine reports a clean part when it should not:

* **An uncited threshold does not load.**
* **An unknown material does not load**, and the error names the materials that do exist.
* **A missing rule raises rather than defaulting.** A rules engine that skips a rule it does not
  recognise is a rules engine that reports a clean part when the config is typo'd.

Severity is declared per rule per material. Only ``BLOCKER`` is intended to gate, and it gates
only where an ``intent.json`` asserts on ``dfm_violation_count`` (ADR-8) -- DFM is advice about a
*process*, intent is a claim about a *part*, and collapsing the two would fail a dimensionally
perfect part because its owner chose to print it without supports.

This module performs **no measurement of its own**; ``tests/test_one_ruler.py`` scans it
automatically. All dimensions are millimetres; angles are degrees and suffixed ``_deg``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import trimesh

from threedp import printability
from threedp.compensate import profiles_dir

__all__ = [
    "DfmError",
    "Finding",
    "DfmReport",
    "load_rules",
    "evaluate",
    "BLOCKER",
    "WARNING",
    "NOTE",
    "SEVERITIES",
    "RULES_FILE",
    "DEFAULTS_KEY",
]

BLOCKER, WARNING, NOTE = "BLOCKER", "WARNING", "NOTE"
SEVERITIES = (BLOCKER, WARNING, NOTE)

RULES_FILE = "dfm-rules.json"
DEFAULTS_KEY = "_defaults"

# Every field a rule record must carry. `source` is the load-bearing one.
_REQUIRED_FIELDS = ("value", "unit", "compare", "severity", "source")
_COMPARISONS = ("min", "max")

# The physical consequence behind each rule, in the register the critique is written in: what
# goes wrong, not how it feels. Prose belongs in code; the numbers it talks about do not.
_CONSEQUENCE = {
    "min_wall_mm": "a wall under two bead widths extrudes as a gap",
    "min_feature_mm": "a feature thinner than one extrusion bead is never laid down",
    "min_hole_d_mm": "a bore this small closes up from arc faceting and flow",
    "max_overhang_deg": "past this angle from vertical the underside droops without support",
    "max_bridge_mm": "an unsupported span this long sags before it sets",
    "min_footprint_mm2": "this little bed contact lifts under cooling stress",
    "max_aspect_ratio": "a part this slender topples or wobbles under the nozzle",
    "warn_unsupported_mm2": "this much surface past the reporting angle prints with visible sag",
}


class DfmError(Exception):
    """The rules configuration, the material, or the requested severity is not usable."""


# --- findings and the report ------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One rule, violated, carrying everything needed to argue with it."""

    rule: str
    severity: str
    measured: float
    threshold: float
    unit: str
    source: str
    message: str

    def __str__(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return (
            f"{self.severity:<7} {self.rule:<21} measured {self.measured:9.3f}{unit}   "
            f"threshold {self.threshold:.3f}{unit}   {self.message}   [{self.source}]"
        )


@dataclass(frozen=True)
class DfmReport:
    """The findings for one part in one material, plus what could not be checked.

    ``skipped`` is not a formality. "No bore was small" and "no bore was measurable" are
    different facts, and a report that prints only the first would present the second as a clean
    bill of health.
    """

    part: str
    material: str
    findings: list[Finding] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def _of(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def blockers(self) -> list[Finding]:
        return self._of(BLOCKER)

    @property
    def warnings(self) -> list[Finding]:
        return self._of(WARNING)

    @property
    def notes(self) -> list[Finding]:
        return self._of(NOTE)

    @property
    def passed(self) -> bool:
        """No BLOCKER. A WARNING is worth reading and is deliberately not a gate."""
        return not self.blockers

    def count(self, severity: str | None = None) -> int:
        if severity is None:
            return len(self.findings)
        if severity not in SEVERITIES:
            raise DfmError(f"unknown severity {severity!r}; valid severities: {list(SEVERITIES)}")
        return len(self._of(severity))

    def __str__(self) -> str:
        verdict = "no blockers" if self.passed else f"{len(self.blockers)} BLOCKER(s)"
        lines = [
            f"dfm  {self.part}  [{self.material}]  "
            f"{verdict}, {len(self.warnings)} warning(s), {len(self.notes)} note(s)"
        ]
        lines += [str(f) for f in self.findings]
        lines += [f"{'skipped':<7} {rule:<21} {why}" for rule, why in self.skipped]
        if not self.findings:
            lines.append("        no rule was violated")
        return "\n".join(lines)


# --- rules ------------------------------------------------------------------------------------


def _rules_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else profiles_dir() / RULES_FILE


def _validate(record: Any, where: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise DfmError(f"{where} is a bare {type(record).__name__}, expected a rule object")
    # Presence, not truthiness. A ratio's unit is legitimately the empty string, and treating
    # that as absent would reject the one rule that has no unit to declare.
    missing = [f for f in _REQUIRED_FIELDS if f not in record]
    if missing:
        raise DfmError(
            f"{where} is missing {missing}. Every threshold must declare its value, its unit, "
            f"which side of it is a violation, its severity and its source -- an uncited "
            f"threshold is an invented number and cannot be checked by anyone."
        )
    if not str(record["source"]).strip():
        raise DfmError(
            f"{where} has an empty source. A threshold nobody can trace is an invented number; "
            f"cite where it comes from, as parts.py does."
        )
    if not isinstance(record["value"], (int, float)) or isinstance(record["value"], bool):
        raise DfmError(f"{where} has value={record['value']!r}, expected a number")
    if record["compare"] not in _COMPARISONS:
        raise DfmError(
            f"{where} has compare={record['compare']!r}; expected one of {list(_COMPARISONS)}"
        )
    if record["severity"] not in SEVERITIES:
        raise DfmError(
            f"{where} has severity={record['severity']!r}; expected one of {list(SEVERITIES)}"
        )
    return dict(record)


def load_rules(material: str, path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load one material's rules, with ``_defaults`` underneath it.

    Keys beginning with ``_`` inside a material record are documentation, not rules, and are
    dropped. ``load_rules("_defaults")`` returns the base table on its own, which is what makes
    "did this material actually override anything?" a question with an answer.
    """
    p = _rules_path(path)
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DfmError(f"no DFM rules file at {p}") from exc
    except json.JSONDecodeError as exc:
        raise DfmError(f"{p} is not valid JSON: {exc}") from exc

    if DEFAULTS_KEY not in data:
        raise DfmError(f"{p} has no {DEFAULTS_KEY!r} table; there is nothing to inherit from")

    materials = sorted(k for k in data if not k.startswith("_"))
    if material != DEFAULTS_KEY and material not in data:
        raise DfmError(f"unknown DFM material {material!r}; valid materials: {materials}")

    merged: dict[str, dict[str, Any]] = {}
    layers = (
        [data[DEFAULTS_KEY]] if material == DEFAULTS_KEY else [data[DEFAULTS_KEY], data[material]]
    )
    for layer_index, layer in enumerate(layers):
        label = DEFAULTS_KEY if layer_index == 0 else material
        if not isinstance(layer, dict):
            raise DfmError(f"{p}: {label!r} is not an object")
        for name, record in layer.items():
            if name.startswith("_"):
                continue
            merged[name] = _validate(record, f"{p}: {label}.{name}")
    return merged


# --- evaluation ---------------------------------------------------------------------------------


def _require(rules: dict[str, dict[str, Any]], name: str, material: str) -> dict[str, Any]:
    if name not in rules:
        raise DfmError(
            f"rules for {material!r} define no {name!r}; valid rules: {sorted(rules)}. "
            f"A rule the engine needs and the config does not define is refused rather than "
            f"defaulted: a silently skipped rule reports a clean part on a typo'd config."
        )
    return rules[name]


def _judge(rule: str, record: dict[str, Any], measured: float) -> Finding | None:
    threshold = float(record["value"])
    low = record["compare"] == "min"
    violated = measured < threshold if low else measured > threshold
    if not violated:
        return None
    side = "below the" if low else "above the"
    limit = "minimum" if low else "maximum"
    unit = str(record["unit"])
    tail = f" {unit}" if unit else ""
    detail = _CONSEQUENCE.get(rule, "")
    note = record.get("note")
    message = f"{side} {threshold:.3f}{tail} {limit}"
    if detail:
        message = f"{message} - {detail}"
    if note:
        message = f"{message} ({note})"
    return Finding(
        rule=rule,
        severity=str(record["severity"]),
        measured=float(measured),
        threshold=threshold,
        unit=unit,
        source=str(record["source"]),
        message=message,
    )


def evaluate(
    mesh: trimesh.Trimesh,
    material: str,
    rules_path: str | Path | None = None,
    part: str = "<mesh>",
) -> DfmReport:
    """Score a mesh against one material's rules.

    Every number below comes from :mod:`threedp.printability`; nothing is measured here.

    ``min_wall_mm`` and ``min_feature_mm`` share a single inward ray cast, because a ray cannot
    tell a thin wall from a thin pin -- both are "how much material is there in the direction the
    surface faces". They stay separate *rules* because the fix differs (thicken a wall, delete or
    thicken a stud) and because a material may reasonably set them apart. Expect them to fire
    together on the same geometry; the finding says which number it measured either way.
    """
    rules = load_rules(material, rules_path)

    # Every rule is looked up before any measuring happens, so a typo'd config fails in
    # milliseconds instead of after a ray cast.
    wanted = (
        "min_wall_mm",
        "min_feature_mm",
        "min_hole_d_mm",
        "max_overhang_deg",
        "max_bridge_mm",
        "min_footprint_mm2",
        "max_aspect_ratio",
        "warn_unsupported_mm2",
    )
    record = {name: _require(rules, name, material) for name in wanted}

    findings: list[Finding] = []
    skipped: list[tuple[str, str]] = []

    def add(name: str, measured: float) -> None:
        found = _judge(name, record[name], measured)
        if found is not None:
            findings.append(found)

    thickness = printability.min_feature_size(mesh).min_mm
    add("min_wall_mm", thickness)
    add("min_feature_mm", thickness)

    bores = printability.bore_diameters(mesh, threshold_mm=float(record["min_hole_d_mm"]["value"]))
    if not bores.classified:
        skipped.append(("min_hole_d_mm", bores.reason))
    elif bores.min_mm is None:
        skipped.append(("min_hole_d_mm", "no bore was measurable on this mesh"))
    else:
        add("min_hole_d_mm", bores.min_mm)

    overhangs = printability.overhang_histogram(
        mesh, threshold_deg=float(record["max_overhang_deg"]["value"])
    )
    add("max_overhang_deg", overhangs.max_deg)

    # The reporting angle is declared in the rule itself: this is "surfaces already worth
    # mentioning", which is a shallower angle than the one that blocks a print.
    warn_angle = float(record["warn_unsupported_mm2"].get("at_angle_deg", 30.0))
    add("warn_unsupported_mm2", printability.overhang_histogram(mesh, warn_angle).unsupported_area)

    add("max_bridge_mm", printability.bridge_spans(mesh).max_span_mm)

    stance = printability.footprint(mesh)
    add("min_footprint_mm2", stance.contact_area)
    add("max_aspect_ratio", stance.aspect_ratio)

    order = {name: i for i, name in enumerate(wanted)}
    findings.sort(key=lambda f: (SEVERITIES.index(f.severity), order.get(f.rule, 99)))
    return DfmReport(part=part, material=material, findings=findings, skipped=skipped)

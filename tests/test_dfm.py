"""The DFM rules engine, scored against geometry whose printability is known by construction.

Written before ``dfm.py`` existed. The tests pin *behaviour* -- an uncited threshold is refused,
an unknown material is refused, a missing rule is refused, a finding carries its own evidence --
rather than the shape of the implementation.

The two directions matter equally. A rules engine that flags everything is as useless as one
that flags nothing, so every rule that can fire is also tested *not* firing on a part that is
fine.
"""

from __future__ import annotations

import json

import pytest
from conftest import build_overhang_cone

from threedp import dfm

# --- loading -------------------------------------------------------------------------------


def _rules_file(tmp_path, data) -> str:
    p = tmp_path / "dfm-rules.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def test_an_uncited_threshold_is_refused_at_load(tmp_path):
    """A threshold with no source is an invented number. It must never load quietly."""
    path = _rules_file(
        tmp_path,
        {
            "_defaults": {
                "min_wall_mm": {"value": 0.8, "unit": "mm", "compare": "min", "severity": "BLOCKER"}
            },
            "PLA_generic": {},
        },
    )
    with pytest.raises(dfm.DfmError) as exc:
        dfm.load_rules("PLA_generic", path)
    assert "source" in str(exc.value)
    assert "min_wall_mm" in str(exc.value)


def test_unknown_material_raises_with_the_valid_list():
    with pytest.raises(dfm.DfmError) as exc:
        dfm.load_rules("PLA_unobtanium")
    message = str(exc.value)
    assert "PLA_generic" in message and "ABS_generic" in message


def test_material_record_overrides_the_defaults():
    defaults = dfm.load_rules("_defaults")
    abs_rules = dfm.load_rules("ABS_generic")
    assert abs_rules["max_overhang_deg"]["value"] != defaults["max_overhang_deg"]["value"]
    # and an un-overridden rule is inherited verbatim
    assert abs_rules["min_wall_mm"]["value"] == defaults["min_wall_mm"]["value"]


def test_every_loaded_rule_carries_a_source():
    for material in ("PLA_generic", "PETG_generic", "ABS_generic"):
        for name, rule in dfm.load_rules(material).items():
            assert rule.get("source"), f"{material}.{name} has no source"


def test_a_missing_rule_key_raises_rather_than_defaulting(tmp_path, plate_mesh):
    """A rules engine that skips an unknown rule reports a clean part when the config is typo'd."""
    complete = dfm.load_rules("PLA_generic")
    del complete["min_wall_mm"]
    path = _rules_file(tmp_path, {"_defaults": complete, "PLA_generic": {}})
    with pytest.raises(dfm.DfmError) as exc:
        dfm.evaluate(plate_mesh, "PLA_generic", rules_path=path)
    assert "min_wall_mm" in str(exc.value)
    assert "valid" in str(exc.value).lower()


# --- overhangs -----------------------------------------------------------------------------


def test_sixty_degree_cone_is_a_blocker_in_pla(overhang_mesh):
    """Spike 6 truth: 60.00 deg area-weighted, 1339.09 mm2 unsupported."""
    report = dfm.evaluate(overhang_mesh, "PLA_generic", part="overhang-cone")
    rules = {f.rule for f in report.blockers}
    assert "max_overhang_deg" in rules
    assert not report.passed
    finding = next(f for f in report.findings if f.rule == "max_overhang_deg")
    assert finding.measured == pytest.approx(60.0, abs=0.3)
    assert finding.threshold == 45.0
    assert finding.unit == "deg"


def test_thirty_degree_cone_is_not_a_blocker():
    """The false-positive direction: a printable overhang must not be flagged as unprintable."""
    from threedp.features import _tessellate

    mesh = _tessellate(build_overhang_cone(angle_deg=30.0))
    report = dfm.evaluate(mesh, "PLA_generic", part="shallow-cone")
    assert "max_overhang_deg" not in {f.rule for f in report.blockers}


def test_abs_is_stricter_than_pla_on_the_same_geometry():
    """A 42 deg flare passes PLA's 45 deg threshold and fails ABS's 40 deg one."""
    from threedp.features import _tessellate

    mesh = _tessellate(build_overhang_cone(angle_deg=42.0))
    assert "max_overhang_deg" not in {f.rule for f in dfm.evaluate(mesh, "PLA_generic").blockers}
    assert "max_overhang_deg" in {f.rule for f in dfm.evaluate(mesh, "ABS_generic").blockers}


# --- walls and features --------------------------------------------------------------------


def test_a_five_millimetre_wall_produces_no_min_wall_finding(plate_mesh):
    """conftest's plate has a true thinnest wall of 5.0mm. Nothing here is thin."""
    report = dfm.evaluate(plate_mesh, "PLA_generic", part="plate")
    assert "min_wall_mm" not in {f.rule for f in report.findings}
    assert "min_feature_mm" not in {f.rule for f in report.findings}


def test_a_sane_part_produces_no_blockers_at_all(plate_mesh):
    report = dfm.evaluate(plate_mesh, "PLA_generic", part="plate")
    assert report.passed, str(report)
    assert report.count(dfm.BLOCKER) == 0


def _thin_sheet_mesh():
    from build123d import Box, BuildPart

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(20.0, 20.0, 0.4)
    return _tessellate(p.part)


def test_a_thin_part_produces_a_min_wall_finding_carrying_its_evidence():
    report = dfm.evaluate(_thin_sheet_mesh(), "PLA_generic", part="thin-sheet")
    finding = next(f for f in report.findings if f.rule == "min_wall_mm")
    assert finding.severity == dfm.BLOCKER
    assert finding.measured == pytest.approx(0.4, abs=0.05)
    assert finding.threshold == 0.8
    assert finding.unit == "mm"
    assert finding.source, "a finding with no source cannot be argued with"
    assert "two perimeters" in finding.source
    assert not report.passed


def test_bore_smaller_than_the_minimum_is_a_blocker():
    from build123d import Box, BuildPart, Cylinder, Mode

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(20.0, 20.0, 6.0)
        Cylinder(radius=0.6, height=20.0, mode=Mode.SUBTRACT)
    report = dfm.evaluate(_tessellate(p.part), "PLA_generic", part="pinhole")
    assert "min_hole_d_mm" in {f.rule for f in report.blockers}


def test_a_boss_is_not_mistaken_for_a_bore():
    """A thin *pin* is a min_feature problem, not a min_hole_d one.

    Both are cylinders to a Z-scan. Reporting a 0.5mm pin as a 0.5mm hole would name the wrong
    rule, point at the wrong fix, and hide the real one.
    """
    from build123d import Align, Box, BuildPart, Cylinder, Locations

    from threedp.features import _tessellate

    bottom = (Align.CENTER, Align.CENTER, Align.MIN)
    with BuildPart() as p:
        Box(20.0, 20.0, 6.0, align=bottom)
        with Locations((0, 0, 6.0)):
            Cylinder(radius=0.25, height=8.0, align=bottom)
    report = dfm.evaluate(_tessellate(p.part), "PLA_generic", part="thin-pin")
    rules = {f.rule for f in report.findings}
    assert "min_feature_mm" in rules
    assert "min_hole_d_mm" not in rules


def test_a_part_with_no_bores_records_the_rule_as_skipped_not_as_clean(plate_mesh):
    """Silence and "nothing to measure" are different facts; the report says which."""
    from build123d import Box, BuildPart

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(20.0, 20.0, 6.0)
    report = dfm.evaluate(_tessellate(p.part), "PLA_generic", part="solid-block")
    assert "min_hole_d_mm" in dict(report.skipped)
    assert "min_hole_d_mm" in str(report)


# --- the report ----------------------------------------------------------------------------


def test_blockers_and_warnings_partition_the_findings(overhang_mesh):
    report = dfm.evaluate(overhang_mesh, "PLA_generic", part="overhang-cone")
    assert report.findings, "the 60 deg cone must produce findings"
    assert len(report.blockers) + len(report.warnings) + len(report.notes) == len(report.findings)
    assert all(f.severity == dfm.BLOCKER for f in report.blockers)
    assert all(f.severity == dfm.WARNING for f in report.warnings)


def test_count_filters_by_severity(overhang_mesh):
    report = dfm.evaluate(overhang_mesh, "PLA_generic")
    assert report.count() == len(report.findings)
    assert report.count(dfm.BLOCKER) == len(report.blockers)
    assert report.count(dfm.WARNING) == len(report.warnings)


def test_count_rejects_an_unknown_severity(overhang_mesh):
    report = dfm.evaluate(overhang_mesh, "PLA_generic")
    with pytest.raises(dfm.DfmError):
        report.count("CRITICAL")


def test_the_report_states_numbers_not_impressions(overhang_mesh):
    report = dfm.evaluate(overhang_mesh, "PLA_generic", part="overhang-cone")
    text = str(report)
    for banned in ("looks", "seems", "should work", "appears"):
        assert banned not in text.lower(), f"the report editorialises: {banned!r}"
    assert "60." in text, "the measured overhang angle is not in the report"
    assert "45." in text, "the threshold is not in the report"
    assert "conventional FDM support threshold" in text, "the source is not in the report"
    assert "PLA_generic" in text


def test_a_warning_does_not_gate(plate_mesh):
    """A part whose only findings are warnings still passes. BLOCKER is the gate (ADR-8)."""
    from build123d import Box, BuildPart

    from threedp.features import _tessellate

    # 6x6 footprint = 36 mm2, under the 100 mm2 minimum: a warning, not a refusal to print.
    with BuildPart() as p:
        Box(6.0, 6.0, 12.0)
    report = dfm.evaluate(_tessellate(p.part), "PLA_generic", part="tall-post")
    assert "min_footprint_mm2" in {f.rule for f in report.warnings}
    assert report.count(dfm.BLOCKER) == 0
    assert report.passed


def test_evaluate_rejects_a_mesh_with_no_faces():
    import numpy as np
    import trimesh

    empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64))
    with pytest.raises((ValueError, dfm.DfmError)):
        dfm.evaluate(empty, "PLA_generic")


# --- bridges ---------------------------------------------------------------------------------


def test_a_long_bridge_is_a_warning_not_a_blocker(bridge_mesh):
    """The rule fires, and it fires at WARNING. A bridge is a quality risk, not a refusal.

    Until this existed ``max_bridge_mm`` had never produced a finding on any part in the
    repository, so the rule was configuration nothing consumed.
    """
    report = dfm.evaluate(bridge_mesh, "PLA_generic", part="bridge")
    finding = next(f for f in report.findings if f.rule == "max_bridge_mm")
    assert finding.severity == dfm.WARNING
    assert finding.measured == pytest.approx(20.0, abs=0.05)
    assert finding.threshold == 10.0
    assert "max_bridge_mm" not in {f.rule for f in report.blockers}

    # The same deck is also a 90-degree ceiling, so max_overhang_deg blocks it -- correctly, and
    # for a different reason. Two rules describing one surface from two angles is the intended
    # behaviour; what matters is that the span itself is advice rather than a refusal.
    assert "max_overhang_deg" in {f.rule for f in report.blockers}


def test_petg_halves_pla_s_bridge_allowance(bridge_mesh):
    """PETG sags where PLA snaps taut, and the config says so with a reason."""
    pla = dfm.load_rules("PLA_generic")["max_bridge_mm"]["value"]
    petg = dfm.load_rules("PETG_generic")["max_bridge_mm"]["value"]
    assert petg < pla
    assert "max_bridge_mm" in {f.rule for f in dfm.evaluate(bridge_mesh, "PETG_generic").findings}


def test_a_short_bridge_produces_no_finding():
    """The false-positive direction: an 8mm span is inside every material's allowance."""
    from conftest import build_bridge

    from threedp.features import _tessellate

    mesh = _tessellate(build_bridge(span=8.0, depth=8.0))
    assert "max_bridge_mm" not in {f.rule for f in dfm.evaluate(mesh, "PLA_generic").findings}


# --- a tilted bore must not evade the minimum-diameter blocker -------------------------------


def test_a_tilted_bore_is_skipped_loudly_rather_than_passing_min_hole_d():
    """The failure this guards is a FALSE PASS, which is why it is not enough to drop the bore.

    Tilt inflates a fitted diameter, so an undersized bore measured off-axis reads larger than it
    is and clears `min_hole_d_mm`. Refusing to measure it is correct; refusing *silently* would
    leave the report saying "no rule was violated", which is a different and untrue claim.
    """
    from conftest import build_tilted_bore

    from threedp.features import _tessellate

    report = dfm.evaluate(
        _tessellate(build_tilted_bore(tilt_deg=5.0)), "PLA_generic", part="tilted-bore"
    )
    assert "min_hole_d_mm" not in {f.rule for f in report.findings}
    reasons = dict(report.skipped)
    assert "min_hole_d_mm" in reasons, "the rule was neither applied nor reported as unapplied"
    assert "off Z" in reasons["min_hole_d_mm"]
    assert "min_hole_d_mm" in str(report)


def test_an_undersized_tilted_bore_does_not_read_as_acceptable():
    """The concrete false pass: a Ø1.8 bore is under the 2.0 minimum, and tilt would hide it."""
    import math

    from build123d import Box, BuildPart, Cylinder, Mode

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(20.0, 20.0, 12.0)
        Cylinder(radius=0.9, height=40.0, rotation=(5.0, 0, 0), mode=Mode.SUBTRACT)
    report = dfm.evaluate(_tessellate(p.part), "PLA_generic", part="tilted-pinhole")

    # It must NOT come back as a clean measured bore above the threshold.
    measured = [f for f in report.findings if f.rule == "min_hole_d_mm"]
    assert not measured or measured[0].measured < 2.0, (
        "an undersized bore was reported as measured and above the minimum"
    )
    assert "min_hole_d_mm" in dict(report.skipped) or measured, (
        "the rule silently produced neither a finding nor a skip"
    )
    assert math.isclose(0.9 * 2, 1.8), "the fixture is undersized by construction"


# --- slenderness -----------------------------------------------------------------------------


def test_a_slender_part_produces_an_aspect_ratio_finding_carrying_its_evidence():
    """The rule fires *through the rules engine*, not just through the measurement beneath it.

    `test_printability.py` already checks `footprint().flag`. That is a different claim: it proves
    the number is right, not that `dfm.evaluate` ever consults it. Until this existed,
    `max_aspect_ratio` had never produced a Finding anywhere in the repository -- the same shape
    of gap as `bridge_spans` before it.
    """
    from build123d import Box, BuildPart

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(6.0, 6.0, 60.0)  # 60/6 = 10:1, past the 8:1 default
    report = dfm.evaluate(_tessellate(p.part), "PLA_generic", part="tall-post")

    finding = next(f for f in report.findings if f.rule == "max_aspect_ratio")
    assert finding.severity == dfm.WARNING
    assert finding.measured == pytest.approx(10.0, rel=0.01)
    assert finding.threshold == 8.0
    assert finding.unit == "", "a ratio has no unit and must not be printed as millimetres"
    assert "topples" in finding.message
    assert report.passed, "slenderness is a warning about the print, not a refusal"


def test_a_squat_part_produces_no_aspect_ratio_finding(plate_mesh):
    """The false-positive direction: 10mm over a 40mm footprint is 0.25:1 and unremarkable."""
    assert "max_aspect_ratio" not in {
        f.rule for f in dfm.evaluate(plate_mesh, "PLA_generic").findings
    }

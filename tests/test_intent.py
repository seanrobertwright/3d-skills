"""Intent checking: the loop's actual verdict.

Every test here is about a way a checker can be wrong in the direction that *reports green*.
"""

import json

import pytest
from conftest import CANONICAL

from threedp import features, intent
from threedp.intent import ESTIMATE, FAIL, PASS, IntentError


def canonical_intent(**overrides):
    """Intent for the OD30 / Ø22x7 / Ø10 part. Truth is known by construction."""
    spec = {
        "holds": "the canonical spike part (OD30, Ø22 bore 7 deep, Ø10 through)",
        "asserts": [
            {
                "outer_diameter": [29.95, 30.05],
                "source": "user-confirmed",
                "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": "largest"},
            },
            {
                "bore_diameter": [21.95, 22.05],
                "source": "parts-db:608.od",
                "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": 1},
            },
            {
                "shaft_hole_d": [9.95, 10.05],
                "source": "user-confirmed",
                "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": "smallest"},
            },
            {
                "pocket_depth": [6.90, 7.10],
                "source": "parts-db:608.width",
                "measure": {"kind": "cylinder_depth", "at": [0, 0], "rank": 1},
            },
            {
                "min_wall": [3.00, None],
                "source": "user-confirmed",
                "measure": {"kind": "coaxial_step_radial", "at": [0, 0], "between": [0, 1]},
            },
        ],
        "golden": {"bbox": [30.0, 30.0, 20.0], "volume": 10455.22, "tol_pct": 1.0},
    }
    spec.update(overrides)
    return spec


# --- the happy path -----------------------------------------------------------------------


def test_canonical_part_passes_its_own_intent(canonical_step):
    f = features.extract(canonical_step)
    r = intent.check(f, canonical_intent())
    assert r.passed, str(r)
    assert all(x.status == PASS for x in r.results)


def test_every_assertion_reports_a_measured_value_and_a_source(canonical_step):
    f = features.extract(canonical_step)
    r = intent.check(f, canonical_intent())
    for x in r.results:
        assert x.value is not None
        assert x.assertion.source
    text = str(r)
    assert "21.99" in text or "22.000" in text
    assert "parts-db:608.od" in text


def test_measured_values_are_exact_on_the_brep_path(canonical_step):
    f = features.extract(canonical_step)
    r = intent.check(f, canonical_intent())
    got = {x.name: x.value for x in r.results}
    assert got["outer_diameter"] == pytest.approx(30.0, abs=1e-9)
    assert got["bore_diameter"] == pytest.approx(22.0, abs=1e-9)
    assert got["pocket_depth"] == pytest.approx(CANONICAL["pocket_depth"], abs=1e-9)
    assert got["min_wall"] == pytest.approx(4.0, abs=1e-9)


def test_mesh_path_reaches_the_same_verdict(canonical_stl):
    f = features.extract(canonical_stl)
    r = intent.check(f, canonical_intent())
    assert r.passed, str(r)


# --- failure is loud, specific, and numeric -----------------------------------------------


def test_out_of_range_fails_with_the_measured_number(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"][3]["pocket_depth"] = [7.90, 8.10]
    r = intent.check(f, spec)
    assert not r.passed
    bad = r.failures[0]
    assert bad.name == "pocket_depth"
    assert bad.value == pytest.approx(7.0, abs=1e-9)
    assert "7.000" in str(r)


def test_absent_feature_fails_with_a_reason_and_is_never_skipped(canonical_step):
    """PRD 15.2 defect 2: 'no 4.5mm cylinder existed anywhere'.

    A checker that skipped absent features would have scored that part green.
    """
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"].append(
        {
            "counterbore_d": [6.9, 7.1],
            "source": "parts-db:M4.head_d",
            "measure": {"kind": "cylinder_diameter", "at": [20, 0], "rank": "largest"},
        }
    )
    r = intent.check(f, spec)
    assert not r.passed
    missing = [x for x in r.results if x.name == "counterbore_d"][0]
    assert missing.status == FAIL
    assert missing.value is None
    assert "absent" in missing.reason
    assert len(r.results) == len(spec["asserts"]), "an absent feature must still produce a line"


def test_a_missing_coaxial_step_fails_rather_than_reindexing(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"][4]["measure"]["between"] = [0, 7]
    r = intent.check(f, spec)
    assert not r.passed
    assert "absent" in r.failures[0].reason


def test_non_circular_mesh_section_fails_and_does_not_crash(square_pocket_stl):
    """ADR-4: a square pocket must produce a FAIL with a reason -- not a pass, not a traceback."""
    f = features.extract(square_pocket_stl)
    spec = {
        "holds": "a square pocket that a circle fit lies about",
        "asserts": [
            {
                "pocket_d": [24.0, 25.0],
                "source": "user-confirmed",
                "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": "largest"},
            }
        ],
    }
    r = intent.check(f, spec)
    assert not r.passed
    assert r.failures[0].status == FAIL
    assert "not a circle" in r.failures[0].reason
    assert "24.4949" not in str(r), "the confident wrong diameter must never be reported"


def test_tilted_bore_is_demoted_to_estimate_not_passed(tilted_bore_stl):
    """A 5deg-tilted Ø22 bore passes the circularity gate but is not a Tier 1 measurement.

    Its Z-scan diameter is inflated; the axis measurement is what refuses it Tier 1 status.
    """
    f = features.extract(tilted_bore_stl)
    spec = {
        "holds": "a block with a bore tilted 5deg off Z",
        "asserts": [
            {
                "bore_diameter": [21.95, 22.05],
                "source": "parts-db:608.od",
                "measure": {"kind": "cylinder_diameter", "at": [0, 0], "rank": "largest"},
            }
        ],
    }
    r = intent.check(f, spec)
    assert r.results[0].status == ESTIMATE
    assert r.results[0].tier == 2
    assert "off Z" in r.results[0].reason
    assert not r.passed, "an ESTIMATE must never be the sole basis of a green verdict"


# --- tier 2 is reported, never gating -----------------------------------------------------


def test_forced_tier_2_is_labelled_estimate_and_excluded_from_the_verdict(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"][1]["tier"] = 2
    spec["asserts"][1]["bore_diameter"] = [99.0, 100.0]  # wildly wrong on purpose
    r = intent.check(f, spec)
    est = [x for x in r.results if x.name == "bore_diameter"][0]
    assert est.status == ESTIMATE
    assert "ESTIMATE" in str(r)
    assert r.passed, "a Tier 2 claim, however wrong, cannot flip a Tier 1 verdict either way"


def test_sampled_min_wall_is_always_an_estimate(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"].append(
        {
            "sampled_wall": [3.0, None],
            "source": "user-confirmed",
            "measure": {"kind": "sampled_min_wall", "samples": 400},
        }
    )
    r = intent.check(f, spec)
    sampled = [x for x in r.results if x.name == "sampled_wall"][0]
    assert sampled.status == ESTIMATE
    assert sampled.tier == 2
    assert "sampled" in sampled.reason


def test_a_report_of_only_estimates_does_not_pass(canonical_step):
    f = features.extract(canonical_step)
    spec = {
        "holds": "topology only",
        "asserts": [
            {
                "wall": [1.0, None],
                "source": "user-confirmed",
                "measure": {"kind": "sampled_min_wall", "samples": 300},
            }
        ],
    }
    r = intent.check(f, spec)
    assert not r.passed, "nothing gating was checked, so nothing was verified"


# --- golden values are drift only ---------------------------------------------------------


def test_golden_drift_is_reported_but_never_gates(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent(golden={"bbox": [1.0, 1.0, 1.0], "volume": 1.0, "tol_pct": 1.0})
    r = intent.check(f, spec)
    assert r.passed, "a golden mismatch cannot fail a part; it cannot detect first-pass error"
    assert any(not d.within for d in r.drift)
    assert "drift only" in str(r)


def test_golden_drift_computes_a_percentage(canonical_step):
    f = features.extract(canonical_step)
    r = intent.check(f, canonical_intent())
    vol = [d for d in r.drift if d.name == "volume"][0]
    assert vol.within
    assert abs(vol.delta_pct) < 1.0


# --- schema validation --------------------------------------------------------------------


def test_missing_source_is_rejected():
    with pytest.raises(IntentError, match="source"):
        intent.load(
            {
                "asserts": [
                    {"d": [1, 2], "measure": {"kind": "volume"}},
                ]
            }
        )


def test_missing_measure_block_is_rejected():
    with pytest.raises(IntentError, match="measure"):
        intent.load({"asserts": [{"d": [1, 2], "source": "user-confirmed"}]})


def test_unknown_measure_kind_is_rejected_and_lists_valid_kinds():
    with pytest.raises(IntentError) as exc:
        intent.load(
            {"asserts": [{"d": [1, 2], "source": "user-confirmed", "measure": {"kind": "vibes"}}]}
        )
    assert "cylinder_diameter" in str(exc.value)


def test_an_entry_naming_no_measurement_is_rejected():
    with pytest.raises(IntentError, match="names no measurement"):
        intent.load({"asserts": [{"source": "user-confirmed", "measure": {"kind": "volume"}}]})


def test_an_entry_naming_two_measurements_is_rejected():
    """Two names is ambiguous. Silently picking one would let a typo become an unchecked claim."""
    with pytest.raises(IntentError, match="several"):
        intent.load(
            {
                "asserts": [
                    {
                        "d": [1, 2],
                        "diameter": [1, 2],
                        "source": "user-confirmed",
                        "measure": {"kind": "volume"},
                    }
                ]
            }
        )


def test_empty_asserts_is_rejected():
    with pytest.raises(IntentError, match="pass anything"):
        intent.load({"holds": "nothing", "asserts": []})


def test_duplicate_assertion_name_is_rejected():
    entry = {"source": "user-confirmed", "measure": {"kind": "volume"}}
    with pytest.raises(IntentError, match="twice"):
        intent.load({"asserts": [{"d": [1, 2], **entry}, {"d": [3, 4], **entry}]})


def test_a_range_unbounded_on_both_ends_is_rejected():
    with pytest.raises(IntentError, match="checks nothing"):
        intent.load(
            {
                "asserts": [
                    {"d": [None, None], "source": "user-confirmed", "measure": {"kind": "volume"}}
                ]
            }
        )


def test_inverted_range_is_rejected():
    with pytest.raises(IntentError, match="above"):
        intent.load(
            {"asserts": [{"d": [9, 1], "source": "user-confirmed", "measure": {"kind": "volume"}}]}
        )


def test_unbounded_upper_end_is_accepted():
    spec = intent.load(
        {
            "asserts": [
                {"min_wall": [3.0, None], "source": "user-confirmed", "measure": {"kind": "volume"}}
            ]
        }
    )
    a = spec.asserts[0]
    assert a.hi is None
    assert a.contains(1e9)
    assert not a.contains(2.9)


def test_loading_from_disk(tmp_path, canonical_step):
    p = tmp_path / "intent.json"
    p.write_text(json.dumps(canonical_intent()), encoding="utf-8")
    r = intent.check(features.extract(canonical_step), p)
    assert r.passed


def test_bad_json_is_rejected_with_the_path(tmp_path):
    p = tmp_path / "intent.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(IntentError, match="valid JSON"):
        intent.load(p)


def test_missing_intent_file_is_rejected(tmp_path):
    with pytest.raises(IntentError, match="no intent file"):
        intent.load(tmp_path / "nope.json")


# --- citations ----------------------------------------------------------------------------


def test_a_citation_that_does_not_bracket_its_range_is_reported(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"][1]["source"] = "parts-db:623.od"  # 10.0, nowhere near a 22mm bore
    r = intent.check(f, spec)
    bad = [c for c in r.citations if not c.brackets]
    assert bad and "does not bracket" in bad[0].reason
    assert r.passed, "a citation advisory reports the intent's problem; it does not fail the part"


def test_a_valid_citation_is_recorded_as_bracketing(canonical_step):
    f = features.extract(canonical_step)
    r = intent.check(f, canonical_intent())
    cited = {c.name: c for c in r.citations}
    assert cited["bore_diameter"].brackets
    assert cited["bore_diameter"].cited_value == 22.0


def test_user_confirmed_sources_produce_no_citation_line(canonical_step):
    f = features.extract(canonical_step)
    r = intent.check(f, canonical_intent())
    assert all(c.source.startswith("parts-db:") for c in r.citations)


# --- reporting ----------------------------------------------------------------------------


def test_report_renders_without_a_unicode_crash(canonical_step, capsys):
    f = features.extract(canonical_step)
    print(intent.check(f, canonical_intent()))
    out = capsys.readouterr().out
    assert "VERDICT" in out


def test_report_labels_each_value_with_its_own_unit(canonical_step):
    """A measurement that is not a length must not be printed as millimetres.

    The report is the surface a human reads before committing a part to a multi-hour print.
    Suffixing every value with "mm" printed degrees, areas and booleans as lengths on all five
    benchmarks -- a units error in a measurement tool, in its primary output.
    """
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"] += [
        {
            "overhang": [0.0, 90.0],
            "source": "user-confirmed",
            "measure": {"kind": "max_overhang_deg"},
        },
        {"solid": [1, 1], "source": "user-confirmed", "measure": {"kind": "watertight"}},
        {
            "size": [0.0, None],
            "source": "user-confirmed",
            "measure": {"kind": "volume"},
        },
    ]
    lines = {
        line.split("=")[0].split()[-1]: line
        for line in str(intent.check(f, spec)).splitlines()
        if "=" in line and "drift" not in line
    }

    assert " deg" in lines["overhang"], lines["overhang"]
    assert " mm3" in lines["size"], lines["size"]
    assert " mm " not in lines["overhang"] and " mm3" not in lines["overhang"]
    # A boolean is not a length and gets no unit at all.
    assert " mm" not in lines["solid"], lines["solid"]
    # Lengths still say mm.
    assert " mm " in lines["bore_diameter"], lines["bore_diameter"]


@pytest.mark.parametrize(
    "golden",
    [
        {"bbox": [30.0, 30.0]},  # two entries; check() indexed [2] and raised IndexError
        {"bbox": [30.0, 30.0, "twenty"]},
        {"bbox": 30.0},
        {"volume": "big"},
        {"volume": True},  # bool is an int subclass; not a volume of 1
        {"tol_pct": None},
    ],
)
def test_a_malformed_golden_block_is_an_intent_error_not_a_crash(golden):
    """A malformed intent file must say so, not fail somewhere inside check()."""
    spec = canonical_intent()
    spec["golden"] = golden
    with pytest.raises(IntentError):
        intent.load(spec)


def test_a_well_formed_golden_block_still_loads():
    spec = canonical_intent()
    spec["golden"] = {"bbox": [30.0, 30.0, 20.0], "volume": 10455.22, "tol_pct": 1.0}
    assert intent.load(spec).golden["volume"] == 10455.22


def test_report_never_contains_an_impression(canonical_step):
    """Report numbers, never impressions (PRD 6.1 / the report pattern)."""
    f = features.extract(canonical_step)
    text = str(intent.check(f, canonical_intent())).lower()
    for weasel in ("looks correct", "looks good", "seems", "probably", "should be fine"):
        assert weasel not in text


def test_report_lines_carry_a_number_or_an_explicit_estimate_label(canonical_step):
    f = features.extract(canonical_step)
    spec = canonical_intent()
    spec["asserts"].append(
        {
            "sampled_wall": [3.0, None],
            "source": "user-confirmed",
            "measure": {"kind": "sampled_min_wall", "samples": 300},
        }
    )
    r = intent.check(f, spec)
    for x in r.results:
        assert x.value is not None or x.status == FAIL
        if x.status == ESTIMATE:
            assert x.tier == 2

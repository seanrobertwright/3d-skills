"""The parts database is the external truth anchor.

It must be exact, and it must refuse to guess.
"""

import pytest

from threedp import parts


def test_608_bearing_is_exact():
    b = parts.get("bearing", "608")
    assert (b["od"], b["id"], b["width"]) == (22.0, 8.0, 7.0)
    assert b["source"] == "parts-db:608"


def test_623_bearing_is_exact():
    b = parts.get("bearing", "623")
    assert (b["od"], b["id"], b["width"]) == (10.0, 3.0, 4.0)


def test_m4_clearance_and_head():
    s = parts.get("screw", "M4")
    assert s["clearance"] == 4.5
    assert s["tap"] == 3.3
    assert s["head_d"] == 7.0
    # PRD 15.1: a real M4 socket head is 4mm tall. A 4mm counterbore in a 4mm plate leaves zero
    # material -- the model skill can only catch that before geometry if head_h is exposed.
    assert s["head_h"] == 4.0


@pytest.mark.parametrize("key", ["M2", "M2.5", "M3", "M4", "M5", "M6", "M8"])
def test_screw_range_m2_to_m8_is_complete(key):
    s = parts.get("screw", key)
    for field in ("clearance", "tap", "head_d", "head_h"):
        assert isinstance(s[field], float)
        assert s[field] > 0
    assert s["clearance"] > s["tap"], "a clearance hole is always larger than a tapping drill"


def test_heatset_inserts_present():
    ins = parts.get("heatset", "M3-insert")
    assert ins["hole_d"] == 4.0
    assert ins["min_boss_od"] > ins["od"], "a boss must be larger than the insert it holds"


def test_magnets_present():
    m = parts.get("magnet", "6x3")
    assert (m["d"], m["h"]) == (6.0, 3.0)


def test_pi_hole_pattern_present():
    p = parts.get("pattern", "raspberry-pi-4")
    assert (p["spacing_x"], p["spacing_y"]) == (58.0, 49.0)
    assert p["hole_d"] == 2.75


def test_every_record_carries_provenance():
    for category in parts.categories():
        for key in parts.keys(category):
            record = parts.get(category, key)
            assert record["source"].startswith("parts-db:")
            assert record["reference"]
            assert record["category"] == category


# --- refusal to guess ---------------------------------------------------------------------


def test_unknown_key_raises_and_lists_valid_keys():
    with pytest.raises(KeyError) as exc:
        parts.get("bearing", "609")
    assert "608" in str(exc.value)


def test_unknown_category_raises():
    with pytest.raises(KeyError):
        parts.get("sprocket", "608")


def test_mutating_a_returned_record_cannot_corrupt_the_database():
    b = parts.get("bearing", "608")
    b["od"] = 999.0
    assert parts.get("bearing", "608")["od"] == 22.0


# --- citations ----------------------------------------------------------------------------


def test_resolve_citation_round_trips():
    assert parts.resolve_citation(parts.citation("608", "od")) == 22.0
    assert parts.resolve_citation("parts-db:M4.clearance") == 4.5


def test_citation_with_dot_in_key():
    """``M2.5`` puts the field separator inside the key -- split from the right, not the left.

    This is the structurally-significant-character-inside-a-value case, and it is not
    hypothetical: M2.5 is a real screw size shipped in this database.
    """
    assert parts.resolve_citation("parts-db:M2.5.clearance") == 2.9
    assert parts.resolve_citation("parts-db:M2.5.head_h") == 2.5


def test_citation_without_a_field_raises():
    with pytest.raises(KeyError):
        parts.resolve_citation("parts-db:608")


def test_citation_with_unknown_field_raises_and_lists_fields():
    with pytest.raises(KeyError) as exc:
        parts.resolve_citation("parts-db:608.bore")
    assert "od" in str(exc.value)


def test_non_citation_source_raises():
    for bad in ["user-confirmed", "", "parts-db", "608.od"]:
        with pytest.raises(KeyError):
            parts.resolve_citation(bad)


def test_no_key_appears_in_two_categories():
    """A citation names a key, never a category.

    ``M3`` in both the screw and heat-set tables would make ``parts-db:M3.hole_d`` resolve to
    whichever table iterated first -- a plausible number from the wrong record, silently. This is
    also checked at import time; the test names the hazard.
    """
    seen = {}
    for category in parts.categories():
        for key in parts.keys(category):
            assert key not in seen, f"{key!r} is in both {seen.get(key)!r} and {category!r}"
            seen[key] = category


def test_heatset_and_screw_citations_do_not_collide():
    assert parts.resolve_citation("parts-db:M3.clearance") == 3.4
    assert parts.resolve_citation("parts-db:M3-insert.hole_d") == 4.0

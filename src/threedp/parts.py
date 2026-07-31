"""Standard parts dimension database -- the external truth anchor for ``intent.json``.

PRD 6.1: an ``intent.json`` written by the same agent that writes the model is only a real check
if it is grounded outside that agent's own reasoning. Every value here carries a ``source`` so
an assertion can cite it, and an unknown key **raises** rather than returning a guessed default.
A fabricated dimension defeats the entire mechanism.

All dimensions are millimetres.
"""

from __future__ import annotations

from typing import Any

__all__ = ["get", "categories", "keys", "resolve_citation", "citation", "PARTS"]

CITATION_PREFIX = "parts-db:"

# --- screws -------------------------------------------------------------------------------
# clearance : ISO 273 medium-fit through hole
# tap       : ISO 262 coarse-pitch tapping drill
# head_d/h  : ISO 4762 socket head cap screw
# nut_af/h  : ISO 4032 hex nut across-flats and height
_SCREWS: dict[str, dict[str, Any]] = {
    "M2": {"clearance": 2.4, "tap": 1.6, "head_d": 3.8, "head_h": 2.0, "nut_af": 4.0, "nut_h": 1.6},
    "M2.5": {
        "clearance": 2.9,
        "tap": 2.05,
        "head_d": 4.5,
        "head_h": 2.5,
        "nut_af": 5.0,
        "nut_h": 2.0,
    },
    "M3": {"clearance": 3.4, "tap": 2.5, "head_d": 5.5, "head_h": 3.0, "nut_af": 5.5, "nut_h": 2.4},
    "M4": {"clearance": 4.5, "tap": 3.3, "head_d": 7.0, "head_h": 4.0, "nut_af": 7.0, "nut_h": 3.2},
    "M5": {"clearance": 5.5, "tap": 4.2, "head_d": 8.5, "head_h": 5.0, "nut_af": 8.0, "nut_h": 4.7},
    "M6": {
        "clearance": 6.6,
        "tap": 5.0,
        "head_d": 10.0,
        "head_h": 6.0,
        "nut_af": 10.0,
        "nut_h": 5.2,
    },
    "M8": {
        "clearance": 9.0,
        "tap": 6.8,
        "head_d": 13.0,
        "head_h": 8.0,
        "nut_af": 13.0,
        "nut_h": 6.8,
    },
}

# --- bearings -----------------------------------------------------------------------------
_BEARINGS: dict[str, dict[str, Any]] = {
    "608": {"od": 22.0, "id": 8.0, "width": 7.0},
    "623": {"od": 10.0, "id": 3.0, "width": 4.0},
    "624": {"od": 13.0, "id": 4.0, "width": 5.0},
    "625": {"od": 16.0, "id": 5.0, "width": 5.0},
    "626": {"od": 19.0, "id": 6.0, "width": 6.0},
    "688": {"od": 16.0, "id": 8.0, "width": 5.0},
    "6001": {"od": 28.0, "id": 12.0, "width": 8.0},
}

# --- heat-set inserts ---------------------------------------------------------------------
# hole_d is the modelled hole; the insert melts its own interference. min_boss_od keeps 2mm of
# wall around the insert, which is what stops a boss splitting during installation.
# Keys are suffixed "-insert" so they cannot collide with the screw table. A citation is
# "parts-db:<key>.<field>" with no category in it, so a key shared between two tables would
# resolve to whichever table came first -- silently, and to the wrong number.
_HEATSETS: dict[str, dict[str, Any]] = {
    "M2-insert": {"od": 3.6, "length": 4.0, "hole_d": 3.2, "min_boss_od": 7.2},
    "M3-insert": {"od": 4.6, "length": 5.7, "hole_d": 4.0, "min_boss_od": 8.0},
    "M4-insert": {"od": 5.6, "length": 8.1, "hole_d": 5.0, "min_boss_od": 9.0},
    "M5-insert": {"od": 6.9, "length": 9.5, "hole_d": 6.3, "min_boss_od": 10.3},
}

# --- magnets ------------------------------------------------------------------------------
_MAGNETS: dict[str, dict[str, Any]] = {
    "3x2": {"d": 3.0, "h": 2.0},
    "5x2": {"d": 5.0, "h": 2.0},
    "6x3": {"d": 6.0, "h": 3.0},
    "8x3": {"d": 8.0, "h": 3.0},
    "10x2": {"d": 10.0, "h": 2.0},
    "12x2": {"d": 12.0, "h": 2.0},
    "20x3": {"d": 20.0, "h": 3.0},
}

# --- hole patterns ------------------------------------------------------------------------
_PATTERNS: dict[str, dict[str, Any]] = {
    "raspberry-pi-4": {
        "spacing_x": 58.0,
        "spacing_y": 49.0,
        "hole_d": 2.75,
        "board_x": 85.0,
        "board_y": 56.0,
        "edge_offset": 3.5,
    },
    "raspberry-pi-zero": {
        "spacing_x": 58.0,
        "spacing_y": 23.0,
        "hole_d": 2.75,
        "board_x": 65.0,
        "board_y": 30.0,
        "edge_offset": 3.5,
    },
    "nema17": {"spacing_x": 31.0, "spacing_y": 31.0, "hole_d": 3.4, "pilot_d": 22.0},
    "fan-80": {"spacing_x": 71.5, "spacing_y": 71.5, "hole_d": 4.5, "bore_d": 76.0},
    "fan-40": {"spacing_x": 32.0, "spacing_y": 32.0, "hole_d": 3.4, "bore_d": 38.0},
}

_SOURCES = {
    "screw": "ISO 4762 / ISO 273 / ISO 262",
    "bearing": "deep-groove ball bearing standard series",
    "heatset": "McMaster-Carr tapered heat-set inserts for plastic",
    "magnet": "common neodymium disc stock sizes",
    "pattern": "vendor mechanical drawings",
}

PARTS: dict[str, dict[str, dict[str, Any]]] = {
    "screw": _SCREWS,
    "bearing": _BEARINGS,
    "heatset": _HEATSETS,
    "magnet": _MAGNETS,
    "pattern": _PATTERNS,
}


def _assert_keys_are_globally_unique() -> None:
    """A citation names a key, not a category, so two tables must never share one.

    Checked at import rather than in a test alone: the failure mode is a citation resolving to a
    plausible number from the wrong table, which is exactly the class of error the parts database
    exists to make impossible.
    """
    seen: dict[str, str] = {}
    for category, table in PARTS.items():
        for key in table:
            if key in seen:
                raise RuntimeError(
                    f"parts key {key!r} appears in both {seen[key]!r} and {category!r}; "
                    f"a parts-db citation could not tell them apart"
                )
            seen[key] = category


def categories() -> list[str]:
    return sorted(PARTS)


def keys(category: str) -> list[str]:
    if category not in PARTS:
        raise KeyError(f"unknown parts category {category!r}; valid categories: {categories()}")
    return sorted(PARTS[category])


def get(category: str, key: str) -> dict[str, Any]:
    """Look up a standard part. Raises ``KeyError`` on an unknown category or key.

    Never returns a guessed default: a fabricated dimension would be indistinguishable from a
    cited one downstream, which is precisely what PRD 6.1 exists to prevent.
    """
    if category not in PARTS:
        raise KeyError(f"unknown parts category {category!r}; valid categories: {categories()}")
    table = PARTS[category]
    if key not in table:
        raise KeyError(f"unknown {category} {key!r}; valid keys: {sorted(table)}")
    record = dict(table[key])
    record["source"] = f"{CITATION_PREFIX}{key}"
    record["reference"] = _SOURCES[category]
    record["category"] = category
    return record


def citation(key: str, field: str) -> str:
    """Build the citation string an ``intent.json`` assertion carries, e.g. ``parts-db:608.od``."""
    return f"{CITATION_PREFIX}{key}.{field}"


def resolve_citation(source: str) -> float:
    """Resolve ``parts-db:<key>.<field>`` to its value, so a cited assertion can be verified.

    The key may itself contain a dot -- ``parts-db:M2.5.clearance`` is a real, valid citation --
    so the field is split from the **right**, not the left.
    """
    if not isinstance(source, str) or not source.startswith(CITATION_PREFIX):
        raise KeyError(f"not a parts-db citation: {source!r}")
    body = source[len(CITATION_PREFIX) :]
    if "." not in body:
        raise KeyError(f"citation {source!r} names no field; expected 'parts-db:<key>.<field>'")
    key, field = body.rsplit(".", 1)
    for category, table in PARTS.items():
        if key in table:
            if field not in table[key]:
                raise KeyError(
                    f"{category} {key!r} has no field {field!r}; valid fields: {sorted(table[key])}"
                )
            return float(table[key][field])
    raise KeyError(f"citation {source!r} names no known part; key {key!r} is not in the database")


_assert_keys_are_globally_unique()

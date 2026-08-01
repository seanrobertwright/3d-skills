"""G-code parsing, against a committed excerpt of real Bambu Studio CLI output.

``tests/fixtures/plate_1_excerpt.gcode`` was cut out of a genuine 734,912-byte ``plate_1.gcode``
produced on this machine by Bambu Studio 02.07.01.62 slicing ``benchmarks/l-bracket``. Its header
block is verbatim, so the numbers asserted here are the numbers the slicer actually wrote.

The highest-value test in this file is the PrusaSlicer-marker one. A parser written to ``;TYPE:``
and ``;LAYER_CHANGE`` finds **zero** of either in a Bambu file, and produces an empty preview that
looks exactly like an empty part.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from threedp import gcode

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plate_1_excerpt.gcode"


def test_the_fixture_is_present_and_is_real_bambu_output():
    """Skipped-layer guard: an absent fixture would make every assertion below vacuous."""
    assert FIXTURE.exists(), "the committed g-code excerpt is missing"
    text = FIXTURE.read_text(encoding="utf-8")
    assert "; HEADER_BLOCK_START" in text
    assert "BambuStudio" in text


# --- the header -------------------------------------------------------------------------------


def test_read_meta_recovers_the_header_numbers():
    m = gcode.read_meta(FIXTURE)
    assert m.generator.startswith("BambuStudio")
    assert m.weight_g == pytest.approx(10.85)
    assert m.density == pytest.approx(1.26)
    assert m.diameter == pytest.approx(1.75)
    assert m.layers == 250
    assert m.length_mm == pytest.approx(3580.16)
    assert m.max_z == pytest.approx(50.0)
    assert m.filaments == 1


def test_model_printing_time_is_parsed_from_its_duration_text():
    """The header says '25m 8s'; result.json's total_predication (1528 s) is a different number."""
    m = gcode.read_meta(FIXTURE)
    assert m.time_s == pytest.approx(25 * 60 + 8)
    assert m.time_hm == "25m 08s"


def test_the_volume_field_is_millimetres_cubed_despite_the_label():
    """The header labels it cm^3 and it is mm3. The arithmetic is the proof, so assert it."""
    import math

    m = gcode.read_meta(FIXTURE)
    computed_mm3 = m.length_mm * math.pi * (m.diameter / 2.0) ** 2
    assert m.volume_mm3 == pytest.approx(computed_mm3, rel=0.001)
    # ...and the weight follows from it only if the value is read as mm3.
    assert (m.volume_mm3 / 1000.0) * m.density == pytest.approx(m.weight_g, rel=0.001)


def test_a_zero_density_is_carried_not_swallowed(tmp_path):
    """The unflattened-preset case: '0.00 g' from a density of zero is not a mass."""
    broken = tmp_path / "zero.gcode"
    broken.write_text(
        "; HEADER_BLOCK_START\n"
        "; BambuStudio 02.07.01.62\n"
        "; total filament weight [g] : 0.00\n"
        "; filament_density: 0\n"
        "; HEADER_BLOCK_END\n",
        encoding="utf-8",
    )
    m = gcode.read_meta(broken)
    assert m.density == 0.0
    assert not m.density_is_usable
    assert "not a mass" in str(m)


def test_a_missing_field_stays_zero_rather_than_being_invented(tmp_path):
    bare = tmp_path / "bare.gcode"
    bare.write_text("; HEADER_BLOCK_START\n; HEADER_BLOCK_END\n", encoding="utf-8")
    m = gcode.read_meta(bare)
    assert m.weight_g == 0.0 and m.layers == 0 and m.generator == ""


def test_a_missing_file_raises():
    with pytest.raises(gcode.GcodeError):
        gcode.read_meta("no/such/plate.gcode")


# --- the config block -------------------------------------------------------------------------


def test_config_values_reads_the_flush_matrix_and_density():
    cfg = gcode.config_values(FIXTURE)
    assert cfg["filament_density"] == "1.26"
    assert cfg["flush_multiplier"] == "1"
    matrix = [float(v) for v in cfg["flush_volumes_matrix"].split(",")]
    assert len(matrix) == 16, "the measured matrix is 4x4"
    assert set(matrix) == {0.0, 280.0}


def test_config_values_confirms_the_cli_writes_no_thumbnail():
    """PRD correction C2: the CLI emits a thumbnail *size* and no thumbnail block at all."""
    text = FIXTURE.read_text(encoding="utf-8")
    assert gcode.config_values(FIXTURE)["thumbnail_size"] == "50x50"
    assert "thumbnail begin" not in text.lower()


# --- toolpaths --------------------------------------------------------------------------------


def test_bambu_markers_are_found():
    paths = gcode.toolpaths(FIXTURE)
    assert paths["markers_found"]
    assert len(paths["layers"]) == 3
    assert paths["layers"][0] == pytest.approx(0.2)
    assert paths["layers"][2] == pytest.approx(0.6)
    assert "Outer wall" in paths["features"]


def test_extruding_moves_become_segments():
    paths = gcode.toolpaths(FIXTURE)
    counts = paths["counts"]
    assert counts["moves"] > 0
    assert counts["extruding"] > 0
    assert counts["emitted"] == counts["extruding"]
    assert len(paths["segments"]["positions"]) == 6 * counts["emitted"]
    assert len(paths["segments"]["layer"]) == counts["emitted"]
    assert len(paths["segments"]["feature"]) == counts["emitted"]


def test_the_excerpt_yields_the_extruding_moves_it_contains():
    """Counted independently off the file, so a parser regression cannot move both numbers."""
    import re

    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    by_hand = sum(
        1
        for ln in lines
        if re.match(r"^G1 ", ln)
        and re.search(r"\sE\d*\.?\d+", ln)  # a positive E word
        and re.search(r"\s[XY]-?\d", ln)  # ...on a move that actually goes somewhere
    )
    assert by_hand > 0
    assert gcode.toolpaths(FIXTURE)["counts"]["extruding"] == by_hand


def test_relative_and_absolute_extrusion_are_distinguished(tmp_path):
    """Bambu emits M83. Read as absolute E, almost every move after a retraction vanishes.

    The same body under M83 and under M82 must not parse to the same thing -- if it does, the
    mode is being ignored and one of the two readings is silently wrong.
    """
    body = "; CHANGE_LAYER\n; FEATURE: Outer wall\nG1 X0 Y0 Z0.2\nG1 X10 Y0 E1\nG1 X20 Y0 E1\n"
    relative = tmp_path / "rel.gcode"
    relative.write_text("M83\n" + body, encoding="utf-8")
    absolute = tmp_path / "abs.gcode"
    absolute.write_text("M82\n" + body, encoding="utf-8")

    assert gcode.toolpaths(relative)["counts"]["extruding"] == 2
    # Under absolute E, "E1" twice is one extrusion then a move that extrudes nothing.
    assert gcode.toolpaths(absolute)["counts"]["extruding"] == 1


def test_retractions_are_not_drawn(tmp_path):
    g = tmp_path / "r.gcode"
    g.write_text(
        "M83\n; CHANGE_LAYER\n; Z_HEIGHT: 0.2\n; FEATURE: Outer wall\n"
        "G1 X0 Y0 Z0.2\nG1 X10 Y0 E1.0\nG1 X20 Y0 E-1.0\nG1 X30 Y0 E0\n",
        encoding="utf-8",
    )
    paths = gcode.toolpaths(g)
    assert paths["counts"]["extruding"] == 1, "a retraction and a zero-E travel are not extrusion"


def test_prusaslicer_markers_only_report_zero_features_and_say_so(tmp_path):
    """S9, as a unit test rather than a visual inspection.

    A file marked the PrusaSlicer way must not silently produce an empty-looking preview: the
    parser reports that it found no Bambu markers, so the caller can say why the preview is bare
    instead of showing an empty plate.
    """
    g = tmp_path / "prusa.gcode"
    g.write_text(
        "M83\n;LAYER_CHANGE\n;Z:0.2\n;TYPE:Perimeter\nG1 X0 Y0 Z0.2\nG1 X10 Y0 E1.0\n",
        encoding="utf-8",
    )
    paths = gcode.toolpaths(g)
    assert paths["markers_found"] is False
    assert paths["features"] == ["(none)"]
    # The moves themselves are still parsed -- only the labelling is missing.
    assert paths["counts"]["extruding"] == 1


def test_truncation_is_reported_rather_than_silent():
    """A truncated preview that looks complete is the viewer's version of a partial render."""
    paths = gcode.toolpaths(FIXTURE, max_segments=5)
    assert paths["truncated"]
    assert paths["counts"]["emitted"] == 5
    assert paths["counts"]["dropped"] == paths["counts"]["extruding"] - 5
    assert str(paths["counts"]["dropped"]) in paths["note"]


def test_an_untruncated_preview_says_nothing_about_truncation():
    paths = gcode.toolpaths(FIXTURE)
    assert not paths["truncated"]
    assert paths["note"] == ""


# --- the preview file ---------------------------------------------------------------------------


def test_write_preview_writes_json_carrying_the_metadata(tmp_path):
    import json

    out = gcode.write_preview(FIXTURE, tmp_path / "part.preview.json")
    assert out.exists() and out.stat().st_size > 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["meta"]["weight_g"] == pytest.approx(10.85)
    assert data["meta"]["density_is_usable"] is True
    assert data["meta"]["time_hm"] == "25m 08s"
    assert len(data["segments"]["positions"]) == 6 * data["counts"]["emitted"]


def test_nothing_in_this_module_returns_a_verdict():
    """The preview is a channel, not a gate (ADR-11)."""
    public = [n for n in dir(gcode) if not n.startswith("_")]
    for name in ("passed", "verdict", "check", "flag"):
        assert name not in public


# --- structurally significant characters embedded in values ---------------------------------


def test_an_inline_comment_is_not_read_as_gcode_words(tmp_path):
    """`;` is structurally significant, and it appears mid-line in real start G-code.

    ``G1 Z20 F9000 ;Move up to X50`` must move to Z20, not to X50. Later words win in a G-code
    line, so a scanner that reads the whole line ends up taking its coordinate from the prose.
    """
    g = tmp_path / "inline.gcode"
    g.write_text(
        "M83\n"
        "; CHANGE_LAYER\n"
        "; FEATURE: Outer wall\n"
        "G1 X0 Y0 Z0.2\n"
        "G1 X10 Y0 E1 ;extrude to X999 Y999\n",
        encoding="utf-8",
    )
    paths = gcode.toolpaths(g)
    assert paths["counts"]["extruding"] == 1
    positions = paths["segments"]["positions"]
    assert positions[3] == pytest.approx(10.0), f"the comment's X999 leaked in: {positions}"
    assert positions[4] == pytest.approx(0.0)


def test_a_semicolon_in_a_config_value_is_kept(tmp_path):
    """The config block is `; key = value`; a value may itself contain `=` or `;`."""
    g = tmp_path / "cfg.gcode"
    g.write_text(
        "; CONFIG_BLOCK_START\n"
        "; machine_start_gcode = G28 ; home the axes\n"
        "; layer_change_gcode = M73 L[layer_num] ; a=b=c\n"
        "; filament_density = 1.26\n"
        "; CONFIG_BLOCK_END\n",
        encoding="utf-8",
    )
    cfg = gcode.config_values(g)
    assert cfg["filament_density"] == "1.26"
    # The `;` that opens every config line is structural; one inside a value is not.
    assert cfg["machine_start_gcode"] == "G28 ; home the axes"
    # ...and only the FIRST `=` separates key from value.
    assert cfg["layer_change_gcode"] == "M73 L[layer_num] ; a=b=c"


def test_a_semicolon_inside_the_printing_time_field_ends_the_value(tmp_path):
    """The header packs two durations onto one line separated by `;`.

    `; model printing time: 25m 8s; total estimated time: 25m 28s` must parse to 1508, not to
    1508+1528 -- the duration scanner would happily sum every number it saw.
    """
    g = tmp_path / "two.gcode"
    g.write_text(
        "; HEADER_BLOCK_START\n"
        "; model printing time: 1m 0s; total estimated time: 9h 9m 9s\n"
        "; HEADER_BLOCK_END\n",
        encoding="utf-8",
    )
    assert gcode.read_meta(g).time_s == pytest.approx(60.0)

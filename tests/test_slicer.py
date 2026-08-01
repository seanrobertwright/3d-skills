"""The slicer wrapper, and the four measured ways the slicer lies.

Two layers. The first needs no slicer installed and is the higher-value one: it feeds
``accept_slice`` hand-built ``result.json`` fixtures copied from real runs, each reproducing one
observed failure. The second is marked ``slicer`` and drives the real binary; a green suite with
that layer skipped is **not** evidence the wrapper works, so Phase 2's gate requires it to run
with zero skips on this machine.

The fixtures are not imagination. Every one of them was produced on this machine on 2026-07-31:

* ``return_code 0`` with ``"Success."`` and **no ``sliced_plates`` key at all** -- ``--slice 3``
  on a single-plate model. A wrapper keyed on the return code reports a successful slice of
  nothing.
* ``return_code 0`` with ``total_used_g == 0`` -- the unflattened-preset case. Correct printer,
  correct process, and a mass computed from a density of zero.
* ``return_code -13`` **while ``plate_1.gcode`` was written correctly** -- ``--export-3mf`` with
  an absolute path. Neither the return code nor the file's existence is sound on its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from threedp import slicer

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "plate_1_excerpt.gcode"


def _outdir(tmp_path, result: dict, gcode: bool = True, plate: int = 1) -> Path:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    (out / "result.json").write_text(json.dumps(result), encoding="utf-8")
    if gcode:
        (out / f"plate_{plate}.gcode").write_text(
            FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return out


def _good_result(grams: float = 10.850234) -> dict:
    """The shape of a real successful run (S2), trimmed to the keys the wrapper reads."""
    return {
        "return_code": 0,
        "error_string": "Success.",
        "total_predication": 1528.091674,
        "filament_change_times": 0,
        "warning_message": "",
        "sliced_plates": [
            {
                "id": 1,
                "filaments": [
                    {"filament_id": "GFA00", "id": 1, "main_used_g": grams, "total_used_g": grams}
                ],
            }
        ],
    }


# --- configuration and discovery ----------------------------------------------------------------


def test_the_shipped_config_names_presets_that_exist_or_says_so():
    cfg = slicer.load_config()
    assert cfg["backend"] == "bambu-studio"
    assert cfg["presets"]["machine"] == "Bambu Lab P1S 0.4 nozzle"
    # The P1S's own default process really is named "@BBL X1C"; renaming it fails with rc -17.
    assert "X1C" in cfg["presets"]["process"]
    assert cfg["timeout_s"] > 0


def test_no_slicer_installed_raises_naming_the_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv("THREEDP_SLICER", raising=False)
    cfg = dict(slicer.load_config())
    cfg["executable_candidates"] = [str(tmp_path / "nope.exe"), str(tmp_path / "also-nope.exe")]
    with pytest.raises(slicer.SlicerNotFound) as exc:
        slicer.find_slicer(cfg)
    assert "nope.exe" in str(exc.value)
    assert "also-nope.exe" in str(exc.value)


def test_the_env_override_raises_when_it_points_at_nothing(tmp_path, monkeypatch):
    """Mirrors compensate.profiles_dir: an override that is wrong is louder than a fallback."""
    monkeypatch.setenv("THREEDP_SLICER", str(tmp_path / "ghost.exe"))
    with pytest.raises(slicer.SlicerError) as exc:
        slicer.find_slicer()
    assert "THREEDP_SLICER" in str(exc.value)


def test_the_env_override_is_honoured_when_it_points_at_a_file(tmp_path, monkeypatch):
    fake = tmp_path / "fake-slicer.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("THREEDP_SLICER", str(fake))
    assert slicer.find_slicer() == fake


# --- preset flattening (S3, S4) -----------------------------------------------------------------


def _preset_tree(tmp_path) -> Path:
    """The measured four-deep PLA chain, with filament_density living two files up."""
    root = tmp_path / "BBL"
    (root / "filament").mkdir(parents=True)
    files = {
        "Bambu PLA Basic @BBL P1S 0.4 nozzle": {
            "name": "Bambu PLA Basic @BBL P1S 0.4 nozzle",
            "inherits": "Bambu PLA Basic @base",
            "nozzle_temperature": ["220"],
        },
        "Bambu PLA Basic @base": {
            "name": "Bambu PLA Basic @base",
            "inherits": "fdm_filament_pla",
            "filament_density": ["1.26"],
        },
        "fdm_filament_pla": {
            "name": "fdm_filament_pla",
            "inherits": "fdm_filament_common",
            "filament_density": ["1.24"],
        },
        "fdm_filament_common": {"name": "fdm_filament_common", "filament_density": ["0"]},
    }
    for name, data in files.items():
        (root / "filament" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return root


def test_flattening_resolves_the_density_the_cli_does_not_walk(tmp_path):
    """S3: the leaf preset has no filament_density; unflattened the CLI reports 0.00 g."""
    root = _preset_tree(tmp_path)
    leaf = json.loads(
        (root / "filament" / "Bambu PLA Basic @BBL P1S 0.4 nozzle.json").read_text(encoding="utf-8")
    )
    assert "filament_density" not in leaf, "the fixture no longer reproduces the trap"

    merged = slicer.flatten_preset("filament", "Bambu PLA Basic @BBL P1S 0.4 nozzle", root)
    assert merged["filament_density"] == ["1.26"], "the child must win over both parents"
    assert "inherits" not in merged
    assert merged["nozzle_temperature"] == ["220"], "the leaf's own values survive"


def test_flattening_keeps_the_original_preset_name(tmp_path):
    """S4: renaming a preset breaks compatible_printers and the slice fails with rc -17."""
    root = _preset_tree(tmp_path)
    name = "Bambu PLA Basic @BBL P1S 0.4 nozzle"
    assert slicer.flatten_preset("filament", name, root)["name"] == name


def test_a_missing_preset_raises_naming_the_path_it_looked_in(tmp_path):
    root = _preset_tree(tmp_path)
    with pytest.raises(slicer.SlicerError) as exc:
        slicer.flatten_preset("filament", "Bambu PLA Basic @BBL P1S 0.8 nozzle", root)
    assert "0.8 nozzle" in str(exc.value)
    assert "filament" in str(exc.value)


def test_the_real_profile_tree_flattens_to_the_measured_density():
    """Against the installed Bambu Studio profile tree, if it is present."""
    cfg = slicer.load_config()
    root = Path(cfg["profile_root"])
    if not root.is_dir():
        pytest.skip("no Bambu Studio profile tree installed")
    merged = slicer.flatten_preset("filament", cfg["presets"]["filament"]["PLA"], root)
    assert float(slicer.first_value(merged["filament_density"])) == pytest.approx(1.26)


# --- the ADR-10 acceptance gate -----------------------------------------------------------------


def test_a_well_formed_run_is_accepted(tmp_path):
    result = slicer.accept_slice(_outdir(tmp_path, _good_result()), plate=0, material="PLA")
    assert result.weight_g == pytest.approx(10.850234)
    assert result.density == pytest.approx(1.26)
    assert result.time_s == pytest.approx(1528.091674)
    assert result.filament_id == "GFA00"
    assert result.gcode.exists()


def test_return_code_zero_with_no_sliced_plates_is_rejected(tmp_path):
    """S6: --slice 3 on a single-plate model. rc 0, 'Success.', and nothing was sliced."""
    bad = {"return_code": 0, "error_string": "Success.", "plate_index": 3, "layer_height": 0.0}
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(_outdir(tmp_path, bad, gcode=False), plate=3)
    assert "sliced_plates" in str(exc.value)


def test_return_code_zero_with_zero_grams_is_rejected(tmp_path):
    """S3: the unflattened-preset case -- a plausible number computed from a density of zero."""
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(_outdir(tmp_path, _good_result(grams=0.0)), plate=0)
    message = str(exc.value)
    assert "0.00" in message or "0.0" in message
    assert "flatten" in message.lower(), "the exception must name the fix"


def test_a_zero_density_in_the_gcode_header_is_rejected(tmp_path):
    """The same trap from the other side: mass present, density zero, so the mass is not a mass."""
    out = _outdir(tmp_path, _good_result())
    text = (out / "plate_1.gcode").read_text(encoding="utf-8")
    (out / "plate_1.gcode").write_text(
        text.replace("; filament_density: 1.26", "; filament_density: 0"), encoding="utf-8"
    )
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(out, plate=0)
    assert "density" in str(exc.value).lower()
    assert "flatten" in str(exc.value).lower()


def test_a_nonzero_return_code_is_rejected_even_with_valid_gcode_present(tmp_path):
    """S5: rc -13 from --export-3mf with an absolute path, while plate_1.gcode was written fine.

    Never infer success from the presence of a G-code file.
    """
    bad = {**_good_result(), "return_code": -13, "error_string": "Failed exporting 3mf files."}
    out = _outdir(tmp_path, bad)
    assert (out / "plate_1.gcode").exists(), "the premise is that the g-code IS there"
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(out, plate=0)
    assert "Failed exporting 3mf files." in str(exc.value), "error_string must be verbatim"
    assert "-13" in str(exc.value)


def test_a_missing_result_json_is_rejected(tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(out, plate=0)
    assert "result.json" in str(exc.value)


def test_a_missing_gcode_is_rejected(tmp_path):
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(_outdir(tmp_path, _good_result(), gcode=False), plate=0)
    assert "plate_1.gcode" in str(exc.value)


def test_an_empty_gcode_is_rejected(tmp_path):
    out = _outdir(tmp_path, _good_result())
    (out / "plate_1.gcode").write_text("", encoding="utf-8")
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(out, plate=0)
    assert "empty" in str(exc.value).lower()


def test_a_zero_gram_slice_result_cannot_be_constructed(tmp_path):
    """Acceptance criterion: a 0.00 g SliceResult is unobtainable from the accepted path."""
    for grams in (0.0, -1.0):
        with pytest.raises(slicer.SliceRejected):
            slicer.accept_slice(_outdir(tmp_path, _good_result(grams=grams)), plate=0)


def test_the_result_renders_its_numbers(tmp_path):
    text = str(slicer.accept_slice(_outdir(tmp_path, _good_result()), plate=0, material="PLA"))
    assert "10.85" in text
    assert "25m" in text
    for banned in ("looks", "seems", "should"):
        assert banned not in text.lower()


# --- AMS mapping (PRD 9, correction C4) ----------------------------------------------------------


def test_ams_mapping_is_reverse_indexed():
    """Array POSITION is the 3MF filament index; array VALUE is the AMS slot. Not the other way."""
    mapping = slicer.ams_mapping(["PETG", "PLA"])
    assert mapping == [2, 0], "PETG lives in slot 2 and PLA in slot 0 in profiles/filaments.json"


def test_ams_mapping_assigns_distinct_slots_to_repeated_materials():
    """Two PLA filaments in one print are two spools, not one spool used twice."""
    assert slicer.ams_mapping(["PLA", "PLA"]) == [0, 1]


def test_ams_mapping_runs_out_of_slots_loudly():
    with pytest.raises(slicer.SlicerError) as exc:
        slicer.ams_mapping(["PLA", "PLA", "PLA"])
    assert "PLA" in str(exc.value)


def test_ams_mapping_to_an_external_spool_raises():
    """Slot 4 is {"type": "external", "bay": null}. It is not AMS slot 4, and it is not null."""
    with pytest.raises(slicer.SlicerError) as exc:
        slicer.ams_mapping(["PC"])
    message = str(exc.value)
    assert "external" in message.lower()
    assert "PC" in message


def test_ams_mapping_rejects_an_unknown_material():
    with pytest.raises(slicer.SlicerError) as exc:
        slicer.ams_mapping(["UNOBTANIUM"])
    assert "PLA" in str(exc.value) and "PETG" in str(exc.value)


def test_slot_is_not_bay():
    """profiles/filaments.json has five slots and the fifth has bay=null. slot != bay."""
    inventory = slicer.load_inventory()
    assert len(inventory) == 5
    assert inventory[4]["type"] == "external"
    assert inventory[4]["bay"] is None


# --- purge waste (S8) ----------------------------------------------------------------------------

S8_MATRIX = [0, 280, 280, 280, 280, 0, 280, 280, 280, 280, 0, 280, 280, 280, 280, 0]


def test_purge_waste_sums_the_measured_matrix():
    mm3, grams = slicer.purge_waste(S8_MATRIX, [0, 1, 0], density=1.26)
    assert mm3 == pytest.approx(560.0), "two changes at 280 mm3 each"
    assert grams == pytest.approx(560.0 / 1000.0 * 1.26)


def test_purge_waste_applies_the_multiplier():
    mm3, _g = slicer.purge_waste(S8_MATRIX, [0, 1], multiplier=1.2)
    assert mm3 == pytest.approx(336.0)


def test_purge_waste_ignores_a_change_to_the_same_filament():
    mm3, _g = slicer.purge_waste(S8_MATRIX, [1, 1, 1])
    assert mm3 == 0.0


def test_purge_waste_without_a_density_returns_none_grams_never_zero():
    """S3's lesson applied to purge: an unknown mass is None, never a plausible 0.0."""
    mm3, grams = slicer.purge_waste(S8_MATRIX, [0, 1])
    assert mm3 == pytest.approx(280.0)
    assert grams is None


def test_purge_waste_accepts_a_nested_matrix():
    nested = [[0, 280], [280, 0]]
    assert slicer.purge_waste(nested, [0, 1])[0] == pytest.approx(280.0)


def test_purge_waste_rejects_a_matrix_that_is_not_square():
    with pytest.raises(slicer.SlicerError):
        slicer.purge_waste([0, 280, 280], [0, 1])


def test_purge_waste_rejects_an_out_of_range_filament_index():
    with pytest.raises(slicer.SlicerError) as exc:
        slicer.purge_waste(S8_MATRIX, [0, 9])
    assert "9" in str(exc.value)


# --- the real binary ------------------------------------------------------------------------------


@pytest.mark.slicer
def test_a_real_slice_produces_a_mass_a_density_and_gcode(tmp_path, artifacts_dir):
    """S12: a full invocation costs about 0.92 s wall clock, so this needs no `slow` marker."""
    from build123d import export_stl
    from conftest import build_plate

    part = artifacts_dir / "slicer-plate.stl"
    if not part.exists():
        export_stl(build_plate(), str(part), tolerance=0.01, angular_tolerance=0.1)

    result = slicer.slice_part(part, material="PLA", outdir=tmp_path / "out")
    assert result.weight_g > 0
    assert result.density > 0
    assert result.time_s > 0
    assert result.gcode.exists() and result.gcode.stat().st_size > 0
    assert result.filament_id, "filament_id must be set or Phase 3's use_ams is silently ignored"


@pytest.mark.slicer
def test_a_real_slice_can_export_a_3mf(tmp_path, artifacts_dir):
    """S5: --export-3mf needs a *relative* filename with cwd set, or rc -13."""
    from build123d import export_stl
    from conftest import build_plate

    part = artifacts_dir / "slicer-plate.stl"
    if not part.exists():
        export_stl(build_plate(), str(part), tolerance=0.01, angular_tolerance=0.1)

    result = slicer.slice_part(
        part, material="PLA", outdir=tmp_path / "out3mf", export_3mf="sliced.3mf"
    )
    assert result.export_3mf is not None
    assert result.export_3mf.exists() and result.export_3mf.stat().st_size > 0


@pytest.mark.slicer
def test_a_real_slice_of_a_plate_that_does_not_exist_is_rejected(tmp_path, artifacts_dir):
    """S6, end to end: rc 0, 'Success.', and no plate was sliced."""
    from build123d import export_stl
    from conftest import build_plate

    part = artifacts_dir / "slicer-plate.stl"
    if not part.exists():
        export_stl(build_plate(), str(part), tolerance=0.01, angular_tolerance=0.1)

    with pytest.raises(slicer.SliceRejected):
        slicer.slice_part(part, material="PLA", plate=3, outdir=tmp_path / "out3")


@pytest.mark.slicer
def test_the_real_slicer_writes_nothing_to_stdout(tmp_path, artifacts_dir):
    """S1: 0 bytes of stdout on every run, without exception. Never parse it as data."""
    import subprocess

    from build123d import export_stl
    from conftest import build_plate

    part = artifacts_dir / "slicer-plate.stl"
    if not part.exists():
        export_stl(build_plate(), str(part), tolerance=0.01, angular_tolerance=0.1)

    out = tmp_path / "stdout-probe"
    out.mkdir()
    exe = slicer.find_slicer()
    completed = subprocess.run(
        [str(exe), "--slice", "0", "--outputdir", str(out), str(part)],
        cwd=str(out),
        capture_output=True,
        timeout=slicer.load_config()["timeout_s"],
        check=False,
    )
    assert completed.stdout == b"", "stdout is empty on every measured run; do not parse it"


def test_the_slicer_marked_layer_is_not_empty():
    """Skipped-layer guard: `-m slicer` selecting nothing would silently pass forever."""
    source = Path(__file__).read_text(encoding="utf-8")
    assert source.count("@pytest.mark.slicer") >= 6


@pytest.mark.slicer
def test_the_slicer_is_installed_on_this_machine():
    """Not a capability claim -- a statement of what this run actually exercised.

    Marked ``slicer`` deliberately. Unmarked it would *fail* rather than deselect on a machine
    with no slicer, which would break the one thing `-m "not slicer"` promises. Marked, asking
    for the slicer layer on a machine without one is a loud failure, which is correct: you asked
    to exercise the wrapper and it was not exercised.
    """
    if os.environ.get("THREEDP_NO_SLICER"):
        pytest.skip("slicer deliberately disabled for this run")
    assert slicer.find_slicer().exists()


# --- print time, which is not reliably where you first look ---------------------------------------


def test_print_time_is_read_from_the_plate_when_the_top_level_has_none(tmp_path):
    """Measured: slicing a .stl puts total_predication only inside sliced_plates."""
    data = _good_result()
    del data["total_predication"]
    data["sliced_plates"][0]["total_predication"] = 833.768
    result = slicer.accept_slice(_outdir(tmp_path, data), plate=0)
    assert result.time_s == pytest.approx(833.768)


def test_print_time_falls_back_to_the_gcode_header(tmp_path):
    """Last resort: the header's own 'model printing time', 25m 8s in the fixture."""
    data = _good_result()
    del data["total_predication"]
    result = slicer.accept_slice(_outdir(tmp_path, data), plate=0)
    assert result.time_s == pytest.approx(25 * 60 + 8)


def test_a_slice_with_no_print_time_anywhere_is_rejected(tmp_path):
    """Reporting 0m 00s for a real print is the 0.00 g trap from a different direction."""
    data = _good_result()
    del data["total_predication"]
    out = _outdir(tmp_path, data)
    text = (out / "plate_1.gcode").read_text(encoding="utf-8")
    (out / "plate_1.gcode").write_text(
        text.replace("; model printing time: 25m 8s; total estimated time: 25m 28s", "; x"),
        encoding="utf-8",
    )
    with pytest.raises(slicer.SliceRejected) as exc:
        slicer.accept_slice(out, plate=0)
    assert "print time" in str(exc.value)


@pytest.mark.slicer
def test_a_relative_outdir_still_lands_where_the_caller_asked(artifacts_dir, monkeypatch):
    """The process runs with cwd set to the output directory, so relative paths resolve twice.

    Measured: a relative ``--outputdir`` produced ``out/slice/benchmarks/.../out/slice`` and no
    ``result.json`` anywhere the caller was looking -- which the ADR-10 gate then reported as
    "the slicer wrote no result.json", correctly and unhelpfully.
    """
    from build123d import export_stl
    from conftest import build_plate

    part = artifacts_dir / "slicer-plate.stl"
    if not part.exists():
        export_stl(build_plate(), str(part), tolerance=0.01, angular_tolerance=0.1)

    monkeypatch.chdir(artifacts_dir)
    result = slicer.slice_part("slicer-plate.stl", material="PLA", outdir="relative-out")
    assert result.gcode.is_absolute()
    assert result.gcode.parent == (artifacts_dir / "relative-out").resolve()

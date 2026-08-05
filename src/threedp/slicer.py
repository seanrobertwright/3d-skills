"""Bambu Studio's command line, wrapped -- and the four measured ways it reports a lie.

The module is ``slicer.py`` and not ``slice.py`` (ADR-6): ``threedp.slice`` shadows the builtin
the moment anyone writes ``from threedp import slice``, and this wraps *a slicer program* rather
than performing *a slicing operation*.

**The hardest job here is refusing to report a number the slicer did not produce.** Each of the
following was observed on this machine on 2026-07-31, and each defeats the obvious check:

* ``return_code == 0`` and ``"Success."`` on a slice that produced **nothing** -- ``--slice 3`` on
  a single-plate model writes a ``result.json`` with no ``sliced_plates`` key and no G-code. A
  wrapper keyed on the return code reports a successful slice of nothing.
* ``return_code == -13`` **while the G-code was written correctly** -- ``--export-3mf`` with an
  absolute path. So the presence of a plausible output file is not evidence either.
* ``return_code == 0``, correct printer, correct process, and ``0.00 g`` -- the BBL system presets
  are not self-contained and the CLI does **not** walk ``inherits``. The leaf PLA preset carries
  23 keys and no ``filament_density``; 1.26 lives one file up in its immediate parent, 1.24 two up,
  and ``fdm_filament_common``'s **0** is what ships. See :func:`flatten_preset`.
* ``return_code == -17`` -- a flattened preset that was *renamed*. A process preset's
  ``compatible_printers`` is a list of printer **names**; rename the machine and the match fails.

So :func:`accept_slice` requires **all four** of ADR-10's conditions, and the exception says which
one failed and what to do about it.

Two more facts that shape the code: the CLI writes **zero bytes to stdout** on every run, so
stdout is never parsed; and timeouts are enforced Python-side with ``subprocess.run(timeout=)``
rather than the community-documented ``--mstpp``, which is not in the official wiki and was not
exercised in the spike.

**Nothing here sends anything to a printer.** ``--export-3mf`` produces a file, and putting that
file on the printer is ``printer.py``'s job in Phase 3, behind ``lril3d-print``'s approval gate.
This module still has no socket in it and that boundary is enforced mechanically by
``tests/test_printer_path_is_narrow.py``.

Masses are grams and suffixed ``_g``; times are seconds and suffixed ``_s``; volumes are mm3 and
suffixed ``_mm3``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from threedp.compensate import profiles_dir

__all__ = [
    "SlicerError",
    "SlicerNotFound",
    "SliceRejected",
    "SliceResult",
    "load_config",
    "load_inventory",
    "find_slicer",
    "profile_root",
    "flatten_preset",
    "first_value",
    "accept_slice",
    "slice_part",
    "ams_mapping",
    "purge_waste",
    "CONFIG_FILE",
    "ENV_EXECUTABLE",
    "ENV_PROFILES",
]

CONFIG_FILE = "slicer.json"
INVENTORY_FILE = "filaments.json"
ENV_EXECUTABLE = "THREEDP_SLICER"
ENV_PROFILES = "THREEDP_SLICER_PROFILES"

_FLATTEN_HINT = (
    "Flatten the preset's `inherits` chain before passing it to --load-filaments: the CLI does "
    "not walk it, and fdm_filament_common ships filament_density 0. See slicer.flatten_preset."
)


class SlicerError(Exception):
    """The slicer could not be found, configured, or run."""


class SlicerNotFound(SlicerError):
    """No slicer executable exists at any configured location."""


class SliceRejected(SlicerError):
    """A slice completed and its result was refused (ADR-10). Never a warning, never a default."""


# --- configuration -------------------------------------------------------------------------


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``profiles/slicer.json``."""
    p = Path(path) if path is not None else profiles_dir() / CONFIG_FILE
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SlicerError(f"no slicer profile at {p}") from exc
    except json.JSONDecodeError as exc:
        raise SlicerError(f"{p} is not valid JSON: {exc}") from exc


def load_inventory(path: str | Path | None = None) -> list[dict[str, Any]]:
    """The AMS slot inventory from ``profiles/filaments.json``."""
    p = Path(path) if path is not None else profiles_dir() / INVENTORY_FILE
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SlicerError(f"no filament inventory at {p}") from exc
    except json.JSONDecodeError as exc:
        # Every other profile loader in the package converts this; this one did not, so a
        # malformed filaments.json escaped as a bare JSONDecodeError that no caller catching
        # SlicerError would see.
        raise SlicerError(f"{p} is not valid JSON: {exc}") from exc
    slots = data.get("slots")
    if not isinstance(slots, list) or not slots:
        raise SlicerError(f"{p} has no 'slots' list")
    return slots


def find_slicer(config: dict[str, Any] | None = None) -> Path:
    """Locate the slicer executable.

    ``THREEDP_SLICER`` takes precedence and **raises** when it points at nothing, rather than
    falling back to a candidate -- the same reflex as ``compensate.profiles_dir``. An override
    that silently does not apply is worse than no override.
    """
    env = os.environ.get(ENV_EXECUTABLE)
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise SlicerError(f"{ENV_EXECUTABLE}={env!r} is not a file")

    config = load_config() if config is None else config
    candidates = [Path(c) for c in config.get("executable_candidates", [])]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SlicerNotFound(
        f"no slicer executable found. Tried: {[str(c) for c in candidates]}. Install Bambu "
        f"Studio, or set {ENV_EXECUTABLE} to the executable. Tests that need one are marked "
        f"`slicer`; run `pytest -m 'not slicer'` on a machine without it."
    )


def profile_root(config: dict[str, Any] | None = None) -> Path:
    """Locate the vendor profile tree. ``THREEDP_SLICER_PROFILES`` overrides, and raises."""
    env = os.environ.get(ENV_PROFILES)
    if env:
        p = Path(env)
        if p.is_dir():
            return p
        raise SlicerError(f"{ENV_PROFILES}={env!r} is not a directory")

    config = load_config() if config is None else config
    root = Path(config.get("profile_root", ""))
    if not root.is_dir():
        raise SlicerError(
            f"slicer profile tree not found at {root}. Set {ENV_PROFILES}, or correct "
            f"'profile_root' in profiles/{CONFIG_FILE}."
        )
    return root


# --- preset flattening (S3, S4) ------------------------------------------------------------


def flatten_preset(kind: str, name: str, root: str | Path) -> dict[str, Any]:
    """Resolve a Bambu preset's ``inherits`` chain into one self-contained config.

    Measured 2026-07-31: the CLI does **not** walk ``inherits``. Verified against the installed
    tree, the PLA chain is four deep and the density it needs is *not* at the leaf::

        0  Bambu PLA Basic @BBL P1S 0.4 nozzle    23 keys   filament_density absent
        1  Bambu PLA Basic @base                  20 keys   filament_density 1.26  <- wanted
        2  fdm_filament_pla                       40 keys   filament_density 1.24
        3  fdm_filament_common                   136 keys   filament_density 0      <- what ships

    Unflattened, the slice succeeds and reports ``; total filament weight [g] : 0.00``.

    The original ``name`` is preserved deliberately (S4). A process preset's
    ``compatible_printers`` is a list of printer *names*, so renaming the machine preset to
    ``"... (flattened)"`` makes the match fail and the slice returns ``-17`` with "The selected
    printer is not compatible with the process preset in the 3mf." Only ``inherits`` is dropped.

    It is also not cosmetic for Phase 3: flattening is what makes ``filament_id`` land in the
    3MF, and PRD 9 records that ``use_ams`` is silently ignored without it.
    """
    base = Path(root) / kind
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current: str | None = name
    while current:
        if current in seen:
            raise SlicerError(f"preset inheritance cycle at {current!r} under {base}")
        seen.add(current)
        fp = base / f"{current}.json"
        if not fp.exists():
            raise SlicerError(
                f"preset {current!r} not found at {fp}. A Bambu Studio update can rename a "
                f"process preset; check profiles/{CONFIG_FILE} against the installed tree."
            )
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SlicerError(f"{fp} is not valid JSON: {exc}") from exc
        chain.append(data)
        current = data.get("inherits")

    merged: dict[str, Any] = {}
    for data in reversed(chain):  # root first, so a child overrides its parent
        merged.update(data)
    merged.pop("inherits", None)
    merged["name"] = name  # S4: renaming breaks compatible_printers => rc -17
    return merged


def first_value(value: Any) -> Any:
    """Bambu stores most scalars as one-element lists. Unwrap without guessing at the rest."""
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


# --- the result ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SliceResult:
    """An accepted slice. Every number here survived all four ADR-10 conditions."""

    gcode: Path
    result_json: Path
    plate: int
    time_s: float
    weight_g: float
    density: float
    filament_id: str
    changes: int
    warnings: str
    material: str
    export_3mf: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def time_hm(self) -> str:
        total = int(round(self.time_s))
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {seconds:02d}s"

    def __str__(self) -> str:
        lines = [
            f"slice    plate {self.plate}   {self.time_hm} ({self.time_s:.0f} s)   "
            f"{self.weight_g:.2f} g of {self.material} "
            f"(density {self.density:.2f} g/cm3, filament_id {self.filament_id})",
            f"         {self.gcode}",
        ]
        if self.changes:
            lines.append(f"         {self.changes} filament change(s)")
        if self.export_3mf:
            lines.append(f"         3mf {self.export_3mf}  (for MANUAL transfer; nothing is sent)")
        if self.warnings:
            lines.append(f"         slicer warnings: {self.warnings}")
        return "\n".join(lines)


def expected_gcode(outdir: str | Path, plate: int) -> Path:
    """``--slice 0`` means "every plate" and still writes ``plate_1.gcode``."""
    return Path(outdir) / f"plate_{max(int(plate), 1)}.gcode"


def _print_time(data: dict[str, Any], plates: list, meta) -> float:
    """Print time in seconds, from wherever this run happened to put it.

    ``total_predication`` is **not** reliably a top-level key. Measured on this machine: slicing a
    ``.3mf`` puts it at the top level, and slicing a ``.stl`` puts it only inside each entry of
    ``sliced_plates`` -- top level carries no prediction at all. A wrapper reading only the top
    level reports ``0m 00s`` for a fourteen-minute print, which is the same class of plausible
    zero as the ``0.00 g`` in condition 4, arrived at from a different direction.

    Three sources are tried in order of authority: per-plate, top-level, then the G-code header's
    own "model printing time". Only if all three are silent is the time refused -- at which point
    it genuinely is unobtainable, and reporting zero would be inventing it.
    """
    per_plate = sum(float(p.get("total_predication", 0.0) or 0.0) for p in plates)
    time_s = per_plate or float(data.get("total_predication", 0.0) or 0.0) or meta.time_s
    if time_s <= 0.0:
        raise SliceRejected(
            "the slice reported no print time: no 'total_predication' on any plate, none at the "
            "top level of result.json, and no 'model printing time' in the G-code header. "
            "Reporting 0s would be inventing a number nothing produced."
        )
    return float(time_s)


def accept_slice(
    outdir: str | Path,
    plate: int = 0,
    material: str = "PLA",
    export_3mf: str | None = None,
) -> SliceResult:
    """Apply ADR-10's conditions to a finished run, or raise :class:`SliceRejected`.

    Four conditions come from ADR-10 and are each a measured failure: the return code, the
    presence of ``sliced_plates``, a non-empty G-code file, and a mass backed by a real density.
    Three more were added while building on top of them, each closing the same shape of gap --
    a number reported next to an artifact it does not describe:

    * **more than one plate** -- every number here is summed across plates and the G-code is one
      file, so the pairing would be wrong;
    * **no print time anywhere** -- see :func:`_print_time`;
    * **a requested 3MF that was not written** -- a partial success is not a success.

    Separated from :func:`slice_part` so the gate can be driven against hand-built ``result.json``
    fixtures without a slicer installed. Those fixtures are the highest-value tests in the suite:
    they encode three measured ways this program reports a lie.
    """
    from threedp import gcode as gcode_mod

    outdir = Path(outdir)
    result_json = outdir / "result.json"

    # 1. result.json exists and return_code is 0.
    if not result_json.exists():
        raise SliceRejected(
            f"the slicer wrote no result.json in {outdir}. It is written even on failure, so its "
            f"absence means the process never got as far as reporting -- check that the "
            f"executable ran at all."
        )
    try:
        data = json.loads(result_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SliceRejected(f"{result_json} is not valid JSON: {exc}") from exc

    code = data.get("return_code")
    if code != 0:
        raise SliceRejected(
            f"the slicer returned {code}: {data.get('error_string', '(no error_string)')!r}. "
            f"Note that a non-zero code does not mean no G-code was written -- rc -13 from "
            f"--export-3mf was measured alongside a perfectly good plate_1.gcode -- so this is "
            f"a refusal to report numbers from a run that reported failure, not a claim that "
            f"nothing was produced."
        )

    # 2. sliced_plates is present and non-empty (the S6 trap).
    plates = data.get("sliced_plates")
    if not plates:
        raise SliceRejected(
            f"return_code 0 and {data.get('error_string', '')!r}, but result.json carries no "
            f"'sliced_plates'. Measured: --slice 3 on a single-plate model reports exactly this "
            f"and writes no G-code at all. Nothing was sliced; plate {plate} probably does not "
            f"exist in this model."
        )

    # Every number below is summed over `sliced_plates`, and the G-code reported beside them is
    # ONE plate. On a single-plate model those describe the same thing; on a multi-plate model
    # they do not, and the result would pair plate 1's toolpath with every plate's filament.
    # Refused rather than silently mismatched -- the same reflex as every other condition here.
    if len(plates) > 1:
        raise SliceRejected(
            f"the slicer produced {len(plates)} plates, and this wrapper reports one G-code file "
            f"with one mass. Pairing plate {max(int(plate), 1)}'s toolpath with every plate's "
            f"filament would be a number that does not describe the file beside it. Slice one "
            f"plate at a time (plate=1, 2, ...) until multi-plate results are modelled properly."
        )

    # 3. the expected G-code exists and is non-empty.
    gcode_path = expected_gcode(outdir, plate)
    if not gcode_path.exists():
        raise SliceRejected(
            f"the slicer reported success but wrote no {gcode_path.name} in {outdir}"
        )
    if gcode_path.stat().st_size == 0:
        raise SliceRejected(f"{gcode_path} is empty; the slicer reported success and wrote 0 bytes")

    # 4. mass > 0 AND the G-code header's density > 0 (the S3 trap).
    grams = 0.0
    filament_id = ""
    for entry in plates:
        for filament in entry.get("filaments", []) or []:
            grams += float(filament.get("total_used_g", 0.0) or 0.0)
            filament_id = filament_id or str(filament.get("filament_id", "") or "")
    meta = gcode_mod.read_meta(gcode_path)
    if grams <= 0.0 or not meta.density_is_usable:
        raise SliceRejected(
            f"the slice reported {grams:.2f} g at filament_density {meta.density:g}. This is not "
            f"a light part -- it is a mass computed from a density of zero, which the BBL system "
            f"presets ship because they are not self-contained. {_FLATTEN_HINT}"
        )

    time_s = _print_time(data, plates, meta)

    # 5. a 3MF that was ASKED for and not written is a partial success, and a partial success
    # rendered as a success is what this whole module exists to refuse. `io.py:88` raises on
    # exactly this shape ("reported success but wrote no file"); returning None here would make a
    # dropped export indistinguishable from one nobody requested.
    exported = None
    if export_3mf:
        exported = outdir / export_3mf
        if not exported.exists() or exported.stat().st_size == 0:
            raise SliceRejected(
                f"a 3MF export was requested and {exported} was not written (or is empty), "
                f"while the slice itself succeeded. Measured: --export-3mf with an absolute path "
                f"returns -13 and writes nothing, so pass a bare filename -- the process already "
                f"runs with its cwd set to the output directory."
            )

    return SliceResult(
        gcode=gcode_path,
        result_json=result_json,
        plate=int(plate),
        time_s=time_s,
        weight_g=grams,
        density=meta.density,
        filament_id=filament_id,
        changes=int(data.get("filament_change_times", 0) or 0),
        warnings=str(data.get("warning_message", "") or ""),
        material=material,
        export_3mf=exported,
        raw=data,
    )


# --- running it ----------------------------------------------------------------------------


def _write_presets(
    config: dict[str, Any], material: str, root: Path, into: Path
) -> dict[str, Path]:
    filaments = config["presets"]["filament"]
    if material not in filaments:
        raise SlicerError(
            f"no filament preset configured for {material!r}; available: {sorted(filaments)}. "
            f"Add one to profiles/{CONFIG_FILE} rather than passing a preset name here."
        )
    wanted = {
        "machine": config["presets"]["machine"],
        "process": config["presets"]["process"],
        "filament": filaments[material],
    }
    overrides = config.get("preset_overrides", {}) or {}
    unknown = sorted(set(overrides) - set(wanted))
    if unknown:
        # A typo'd override kind would apply to nothing, silently, and the value it was meant
        # to correct would stay wrong -- which for `curr_bed_type` means a first-layer bed
        # temperature baked into the G-code for a plate that is not on the machine.
        raise SlicerError(
            f"profiles/{CONFIG_FILE}: preset_overrides names {unknown}; "
            f"valid preset kinds are {sorted(wanted)}"
        )

    written: dict[str, Path] = {}
    for kind, name in wanted.items():
        merged = flatten_preset(kind, name, root)
        for key, value in (overrides.get(kind) or {}).items():
            if key == "name":
                raise SlicerError(
                    "preset_overrides must never set 'name': a process preset's "
                    "compatible_printers is a list of printer names, and renaming fails the "
                    "match with return_code -17 (S4)"
                )
            merged[key] = value
        path = into / f"{kind}.json"
        path.write_text(json.dumps(merged), encoding="utf-8")
        written[kind] = path
    return written


def slice_part(
    path: str | Path,
    material: str = "PLA",
    plate: int = 0,
    outdir: str | Path | None = None,
    config: dict[str, Any] | None = None,
    export_3mf: str | None = None,
) -> SliceResult:
    """Slice a model and return an accepted :class:`SliceResult`, or raise.

    ``outdir`` defaults to a ``slice/`` directory beside the input. ``export_3mf`` takes a **bare
    filename**: an absolute path returns ``-13`` (S5), so the process runs with its cwd set to the
    output directory and the name is passed relative.
    """
    source = Path(path)
    if not source.exists():
        raise SlicerError(f"no model file at {source}")
    # Absolute from here on. The process runs with its cwd set to the output directory (S5 needs
    # that for --export-3mf), so a relative --outputdir or model path is resolved against the
    # output directory instead of against the caller's cwd -- measured producing
    # `out/slice/benchmarks/.../out/slice` and no result.json anywhere the caller was looking.
    source = source.resolve()

    config = load_config() if config is None else config
    exe = find_slicer(config)
    root = profile_root(config)
    timeout_s = float(config.get("timeout_s", 300))

    out = Path(outdir) if outdir is not None else source.parent / "slice"
    out.mkdir(parents=True, exist_ok=True)
    out = out.resolve()

    if export_3mf and (os.path.isabs(export_3mf) or "/" in export_3mf or "\\" in export_3mf):
        raise SlicerError(
            f"--export-3mf needs a bare filename, got {export_3mf!r}. Measured: an absolute path "
            f"returns -13 'Failed exporting 3mf files.' while still writing the G-code."
        )

    presets_dir = Path(tempfile.mkdtemp(prefix="threedp-presets-"))
    try:
        presets = _write_presets(config, material, root, presets_dir)
        # The --load-settings separator is a semicolon. Windows paths contain colons but never
        # semicolons, so this is unambiguous.
        command = [
            str(exe),
            "--load-settings",
            f"{presets['machine']};{presets['process']}",
            "--load-filaments",
            str(presets["filament"]),
            "--slice",
            str(int(plate)),
            "--outputdir",
            str(out),
        ]
        if export_3mf:
            command += ["--export-3mf", export_3mf]
        command.append(str(source))

        try:
            subprocess.run(
                command,
                cwd=str(out),
                timeout=timeout_s,
                # Measured: 0 bytes of stdout on every run, without exception. It is discarded
                # rather than captured so that nobody is tempted to parse it as data (S1).
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SlicerError(
                f"the slicer did not finish within {timeout_s:g}s. A comparable part slices in "
                f"0.92 s on this machine, so this is a hang rather than a slow model. Raise "
                f"'timeout_s' in profiles/{CONFIG_FILE} only if you know why."
            ) from exc
    finally:
        shutil.rmtree(presets_dir, ignore_errors=True)

    return accept_slice(out, plate=plate, material=material, export_3mf=export_3mf)


# --- AMS mapping and purge (PRD 9, correction C4) ------------------------------------------------


def ams_mapping(used_filaments, inventory: list[dict[str, Any]] | None = None) -> list[int]:
    """Map the filaments a print uses onto AMS slots.

    Bambu's ``ams_mapping`` is **forward-indexed** (correction C5): array *position* is the
    filament index inside the 3MF, array *value* is the AMS slot. Getting it backwards prints in
    the wrong colours and looks like a slicing bug rather than a mapping one, which is why it is
    built and tested here in Phase 2 even though publishing it over MQTT is Phase 3.

    PRD 9 and this docstring both used to say "reverse-indexed" and then correctly describe
    forward indexing in the next clause. Bambu Studio's own ``DevMapping.cpp`` settles it: the
    result vector is indexed by filament source index (``result[picked_src_idx].tray_id``) and
    unmapped entries are ``-1``. **Only the word was wrong; the behaviour was always this.**

    Two further facts PRD 9 omits. Slot values are **not** capped at 0-3: the wire value is
    ``ams_id * 4 + tray_id``, so a second AMS unit occupies 4-7. And the external spool is
    ``254``/``255`` -- observed as ``vt_tray.id == "254"`` on this machine -- which is why an
    external spool raises below rather than mapping to "slot 4".

    ``used_filaments`` is the materials the print uses, **in 3MF order** -- either names
    (``["PETG", "PLA"]``) or records carrying a ``material`` key. Two entries of the same material
    are two spools and get two slots.

    **This function knows nothing about the printer, and that is deliberate** (ADR-16). It maps
    the inventory it is given, faithfully, including when the inventory is wrong -- measured:
    asked for ABS it answered slot 3, and slot 3 held green PETG. Checking the inventory against
    live telemetry is :func:`threedp.printer.reconcile_ams`, a separate gate that runs first.
    """
    slots = load_inventory() if inventory is None else inventory
    wanted: list[str] = []
    for entry in used_filaments:
        if isinstance(entry, dict):
            material = entry.get("material")
            if not material:
                raise SlicerError(f"filament record {entry!r} names no material")
            wanted.append(str(material))
        else:
            wanted.append(str(entry))

    known = sorted({str(s.get("material")) for s in slots})
    mapping: list[int] = []
    taken: set[int] = set()
    for index, material in enumerate(wanted):
        matches = [s for s in slots if str(s.get("material")) == material]
        if not matches:
            raise SlicerError(
                f"filament {index} is {material!r}, which is not loaded. Available: {known}. "
                f"Update profiles/{INVENTORY_FILE} to match what is actually in the AMS."
            )
        usable = [s for s in matches if s.get("type") == "ams" and s.get("bay") is not None]
        if not usable:
            raise SlicerError(
                f"filament {index} is {material!r}, which is on an external spool "
                f"(type 'external', bay null) and has no AMS slot to map to. An external spool "
                f"is fed by hand; it is not AMS slot {matches[0].get('slot')}."
            )
        free = [s for s in usable if int(s["slot"]) not in taken]
        if not free:
            raise SlicerError(
                f"filament {index} needs another {material!r} spool, and all "
                f"{len(usable)} AMS slot(s) holding it are already mapped. Load another spool "
                f"or reduce the number of {material} filaments in the model."
            )
        slot = min(int(s["slot"]) for s in free)
        taken.add(slot)
        mapping.append(slot)
    return mapping


def _square(matrix) -> list[list[float]]:
    if matrix and isinstance(matrix[0], (list, tuple)):
        rows = [[float(v) for v in row] for row in matrix]
        if any(len(row) != len(rows) for row in rows):
            raise SlicerError(f"flush matrix is {len(rows)} rows of uneven length")
        return rows
    flat = [float(v) for v in matrix]
    size = int(round(len(flat) ** 0.5))
    if size * size != len(flat):
        raise SlicerError(
            f"flush matrix has {len(flat)} entries, which is not a square. Bambu writes "
            f"flush_volumes_matrix as N*N comma-separated values (measured: 4x4)."
        )
    return [flat[i * size : (i + 1) * size] for i in range(size)]


def purge_waste(
    flush_matrix,
    sequence,
    multiplier: float = 1.0,
    density: float | None = None,
) -> tuple[float, float | None]:
    """Purge volume for a filament-change ``sequence``, and its mass when a density is known.

    Measured on this machine (S8): the matrix is 4x4 with every off-diagonal entry 280 mm3, and
    ``flush_multiplier`` is 1. ``sequence`` is the filament indices in print order, so
    ``[0, 1, 0]`` is two changes.

    With no density the mass is **None**, never ``0.0``. That is S3's lesson applied here: a
    plausible zero is worse than an admitted unknown, because only one of the two gets questioned.
    """
    rows = _square(flush_matrix)
    order = [int(i) for i in sequence]
    for i in order:
        if not 0 <= i < len(rows):
            raise SlicerError(
                f"filament index {i} is outside the {len(rows)}x{len(rows)} flush matrix"
            )
    total_mm3 = 0.0
    for a, b in zip(order, order[1:], strict=False):
        if a != b:
            total_mm3 += rows[a][b]
    total_mm3 *= float(multiplier)
    grams = None if density is None else (total_mm3 / 1000.0) * float(density)
    return total_mm3, grams

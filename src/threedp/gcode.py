"""Reading Bambu G-code: metadata, config values, and a toolpath preview for the viewer.

The parsing lives here rather than in the browser (ADR-11) because parsing is the part with the
traps, and the browser is the one place in this project with no tests. ``gcode.py`` parses; the
viewer renders what it emits.

Three traps, all measured on real CLI output from Bambu Studio 02.07.01.62:

* **Bambu's markers are not PrusaSlicer's.** A parser written to ``;TYPE:`` and ``;LAYER_CHANGE``
  finds **zero** of each in a 31,270-line file. Bambu emits, with a leading space,
  ``; FEATURE: Inner wall``, ``; CHANGE_LAYER``, ``; Z_HEIGHT: 0.2``. Reading a Bambu file with
  PrusaSlicer's markers yields an empty preview that looks like an empty part.
* **The header's volume unit label is wrong.** ``; total filament volume [cm^3] : 8611.30`` is
  mm3, not cm3: 3580.16 mm of 1.75 mm filament is 8611 mm3 = 8.611 cm3, and 8.611 cm3 x
  1.26 g/cm3 = 10.85 g, which is what the same header says it weighs. The field here is therefore
  named ``volume_mm3``. Do not "fix" it back to match the label.
* **A density of zero is not a density.** An unflattened preset produces a header reading
  ``; filament_density: 0`` and ``; total filament weight [g] : 0.00`` -- a plausible number
  nobody computed. :class:`GcodeMeta` carries the density so the caller can refuse; this module
  does not silently drop the weight.

Nothing here returns a pass/fail. The preview is a **channel, not a gate**, the same rule as
renders and the live viewer.

All lengths are millimetres; times are seconds and suffixed ``_s``; masses are grams and
suffixed ``_g``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "GcodeError",
    "GcodeMeta",
    "BAMBU_FEATURE",
    "BAMBU_LAYER",
    "BAMBU_Z_HEIGHT",
    "read_meta",
    "config_values",
    "toolpaths",
    "write_preview",
    "DEFAULT_MAX_SEGMENTS",
]

# NOT ";TYPE:" and NOT ";LAYER_CHANGE" -- see the module docstring. The leading space is real.
BAMBU_FEATURE = re.compile(r"^; FEATURE:\s*(.+?)\s*$")
BAMBU_LAYER = re.compile(r"^; CHANGE_LAYER")
BAMBU_Z_HEIGHT = re.compile(r"^; Z_HEIGHT:\s*([-\d.]+)")

_HEADER_END = "; HEADER_BLOCK_END"
_CONFIG_START = "; CONFIG_BLOCK_START"
_CONFIG_END = "; CONFIG_BLOCK_END"
_CONFIG_LINE = re.compile(r"^;\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

_HEADER_PATTERNS = {
    "generator": re.compile(r"^;\s*(BambuStudio\s+\S+|OrcaSlicer\s+\S+|PrusaSlicer\s+\S+)"),
    "time_text": re.compile(r"^;\s*model printing time:\s*([^;]+)"),
    "layers": re.compile(r"^;\s*total layer number:\s*(\d+)"),
    "length_mm": re.compile(r"^;\s*total filament length \[mm\]\s*:\s*([-\d.]+)"),
    "volume_mm3": re.compile(r"^;\s*total filament volume \[cm\^3\]\s*:\s*([-\d.]+)"),
    "weight_g": re.compile(r"^;\s*total filament weight \[g\]\s*:\s*([-\d.]+)"),
    "density": re.compile(r"^;\s*filament_density:\s*([-\d.]+)"),
    "diameter": re.compile(r"^;\s*filament_diameter:\s*([-\d.]+)"),
    "max_z": re.compile(r"^;\s*max_z_height:\s*([-\d.]+)"),
    "filaments": re.compile(r"^;\s*filament:\s*(\d+)"),
}

_DURATION = re.compile(r"(\d+)\s*([dhms])")

# A preview with more segments than this is truncated. 200k indexed line segments is already an
# order of magnitude past what the viewer needs to be legible; the point of the cap is that a
# pathological file cannot make the browser hang, and the point of reporting the drop is that a
# truncated preview must never look complete (the bug fixed in df6ed5f).
DEFAULT_MAX_SEGMENTS = 200_000

_EPS_E = 1e-9


class GcodeError(Exception):
    """A G-code file could not be read as G-code."""


@dataclass(frozen=True)
class GcodeMeta:
    """The header block of a sliced plate.

    ``volume_mm3`` is mm3 despite the file labelling it cm^3 -- see the module docstring.
    ``density`` is carried rather than applied: a zero density means the weight beside it was
    computed from nothing, and only the caller can decide what to do about that.
    """

    generator: str = ""
    time_s: float = 0.0
    layers: int = 0
    length_mm: float = 0.0
    volume_mm3: float = 0.0
    weight_g: float = 0.0
    density: float = 0.0
    diameter: float = 0.0
    max_z: float = 0.0
    filaments: int = 0
    source: str = ""

    @property
    def time_hm(self) -> str:
        total = int(round(self.time_s))
        hours, rest = divmod(total, 3600)
        minutes, seconds = divmod(rest, 60)
        return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m {seconds:02d}s"

    @property
    def density_is_usable(self) -> bool:
        return self.density > 0.0

    def __str__(self) -> str:
        weight = (
            f"{self.weight_g:.2f} g"
            if self.density_is_usable
            else f"{self.weight_g:.2f} g  <- computed from filament_density 0; not a mass"
        )
        return (
            f"gcode    {self.generator or 'unknown generator'}   {self.time_hm}   "
            f"{self.layers} layers   {weight}\n"
            f"         filament {self.length_mm:.2f} mm / {self.volume_mm3:.2f} mm3 "
            f"(the header labels this cm^3; it is mm3)   max z {self.max_z:.2f} mm"
        )


def _seconds(text: str) -> float:
    """Parse Bambu's ``25m 8s`` / ``1h 3m 20s`` duration text."""
    total = 0.0
    scale = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    for value, unit in _DURATION.findall(text):
        total += float(value) * scale[unit]
    return total


def _read_lines(path: str | Path):
    p = Path(path)
    if not p.exists():
        raise GcodeError(f"no g-code file at {p}")
    try:
        return p, p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise GcodeError(f"could not read {p}: {exc}") from exc


def read_meta(path: str | Path) -> GcodeMeta:
    """Parse the header block. Missing fields stay at zero rather than being invented."""
    p, lines = _read_lines(path)
    found: dict[str, str] = {}
    for line in lines:
        if line.startswith(_HEADER_END):
            break
        if not line.startswith(";"):
            continue
        for name, pattern in _HEADER_PATTERNS.items():
            if name not in found:
                match = pattern.match(line)
                if match:
                    found[name] = match.group(1).strip()

    def number(name: str) -> float:
        try:
            return float(found.get(name, 0.0))
        except ValueError:
            return 0.0

    return GcodeMeta(
        generator=found.get("generator", ""),
        time_s=_seconds(found.get("time_text", "")),
        layers=int(number("layers")),
        length_mm=number("length_mm"),
        volume_mm3=number("volume_mm3"),
        weight_g=number("weight_g"),
        density=number("density"),
        diameter=number("diameter"),
        max_z=number("max_z"),
        filaments=int(number("filaments")),
        source=str(p),
    )


def config_values(path: str | Path) -> dict[str, str]:
    """The ``; key = value`` config block, verbatim as strings.

    Left as strings on purpose: the block mixes scalars, percentages (``50%``), comma-separated
    vectors and free text, and coercing them here would have to guess which is which.
    """
    _p, lines = _read_lines(path)
    values: dict[str, str] = {}
    inside = False
    for line in lines:
        if line.startswith(_CONFIG_START):
            inside = True
            continue
        if line.startswith(_CONFIG_END):
            break
        if not inside:
            continue
        match = _CONFIG_LINE.match(line)
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


# --- toolpaths ----------------------------------------------------------------------------------


@dataclass
class _State:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    e: float = 0.0
    relative_e: bool = False
    known: bool = False


_WORD = re.compile(r"([XYZEF])(-?\d*\.?\d+)")


def _strip_inline_comment(text: str) -> str:
    """Everything from the first ``;`` is a comment, including on a command line.

    Not a nicety. Real start G-code carries lines like ``G1 Z20 F9000 ;Move up to X50`` and
    ``G92 E0 ;Reset Extruder``, and a word scanner run over the whole line picks ``X50`` out of
    the *comment* -- then, because later words win, moves the toolhead there. The result is a
    preview with a stray segment shooting across the plate, which reads as a slicer bug.
    """
    cut = text.find(";")
    return text if cut < 0 else text[:cut]


def _words(text: str) -> dict[str, float]:
    return {letter: float(value) for letter, value in _WORD.findall(_strip_inline_comment(text))}


def toolpaths(path: str | Path, max_segments: int = DEFAULT_MAX_SEGMENTS) -> dict:
    """Extract extruding moves as flat typed arrays, ready for one ``LineSegments``.

    Returns ``{"layers": [...z...], "features": [names], "segments": {...}, "counts": {...}}``.
    ``segments.positions`` holds ``x,y,z`` for both ends of every extruding move, so it is six
    floats per segment; ``layer`` and ``feature`` hold one index per segment.

    Extrusion mode is tracked, not assumed. Bambu emits ``M83`` in its start G-code and works in
    relative E; reading a relative-E file as absolute makes every move after the first retraction
    look like a retraction, and the preview comes out nearly empty.
    """
    _p, lines = _read_lines(path)

    state = _State()
    layers: list[float] = []
    features: list[str] = []
    feature_index: dict[str, int] = {}
    current_layer = -1
    current_feature = -1

    positions: list[float] = []
    layer_of: list[int] = []
    feature_of: list[int] = []
    moves = extruding = emitted = dropped = 0

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            if BAMBU_LAYER.match(line):
                current_layer = len(layers)
                layers.append(state.z)
            else:
                height = BAMBU_Z_HEIGHT.match(line)
                if height and layers:
                    layers[-1] = float(height.group(1))
                    continue
                feature = BAMBU_FEATURE.match(line)
                if feature:
                    name = feature.group(1)
                    if name not in feature_index:
                        feature_index[name] = len(features)
                        features.append(name)
                    current_feature = feature_index[name]
            continue

        code = line.split(maxsplit=1)[0].upper()
        if code == "M83":
            state.relative_e = True
            continue
        if code == "M82":
            state.relative_e = False
            continue
        if code == "G92":
            words = _words(line)
            if "E" in words:
                state.e = words["E"]
            continue
        if code not in ("G0", "G1"):
            continue

        moves += 1
        words = _words(line)
        nx = words.get("X", state.x)
        ny = words.get("Y", state.y)
        nz = words.get("Z", state.z)

        extrudes = False
        if "E" in words:
            delta_e = words["E"] if state.relative_e else words["E"] - state.e
            extrudes = delta_e > _EPS_E
            state.e = words["E"] if not state.relative_e else state.e

        travelled = (nx != state.x) or (ny != state.y) or (nz != state.z)
        if extrudes and travelled and state.known:
            extruding += 1
            if emitted < max_segments:
                positions += [state.x, state.y, state.z, nx, ny, nz]
                layer_of.append(max(current_layer, 0))
                feature_of.append(max(current_feature, 0))
                emitted += 1
            else:
                dropped += 1

        state.x, state.y, state.z = nx, ny, nz
        state.known = True

    if not features:
        features = ["(none)"]
    if not layers:
        layers = [state.z]

    return {
        "source": str(_p),
        "layers": layers,
        "features": features,
        "segments": {"positions": positions, "layer": layer_of, "feature": feature_of},
        "counts": {
            "moves": moves,
            "extruding": extruding,
            "emitted": emitted,
            "dropped": dropped,
            "max_segments": int(max_segments),
        },
        "truncated": dropped > 0,
        # Stated rather than implied. A preview that was cut short and does not say so is the
        # viewer's version of a silent partial render.
        "note": (
            f"preview truncated: {dropped} of {extruding} extruding moves were dropped at the "
            f"{max_segments} segment cap"
            if dropped
            else ""
        ),
        "markers_found": bool(feature_index),
    }


@dataclass(frozen=True)
class _Preview:
    path: Path
    meta: GcodeMeta
    counts: dict = field(default_factory=dict)


def write_preview(
    gcode_path: str | Path,
    out_path: str | Path,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> Path:
    """Write the viewer's preview JSON next to a model, and return its path.

    The metadata block travels with the toolpaths so the viewer can state the print time and mass
    without re-parsing 30,000 lines in the browser -- and so that a zero density is visible there
    too, rather than only in the terminal.
    """
    data = toolpaths(gcode_path, max_segments=max_segments)
    meta = read_meta(gcode_path)
    data["meta"] = {
        "generator": meta.generator,
        "time_s": meta.time_s,
        "time_hm": meta.time_hm,
        "layers": meta.layers,
        "weight_g": meta.weight_g,
        "density": meta.density,
        "density_is_usable": meta.density_is_usable,
        "length_mm": meta.length_mm,
        "volume_mm3": meta.volume_mm3,
        "max_z": meta.max_z,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data), encoding="utf-8")
    if not out.exists():
        raise GcodeError(f"preview write reported success but wrote no file at {out}")
    return out

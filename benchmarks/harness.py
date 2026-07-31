"""Shared plumbing for benchmark models and the mutation harness.

Kept deliberately thin: every benchmark is a plain ``model.py`` exposing ``load_params()`` and
``build(params, **options)``, so a benchmark can be run and read on its own without knowing the
harness exists.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parent
REPO_ROOT = BENCHMARKS.parent

if str(REPO_ROOT / "src") not in sys.path:  # running a model.py directly, without an install
    sys.path.insert(0, str(REPO_ROOT / "src"))


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def export_benchmark(model_dir: Path, build, params, calibration=None, stem: str = "part"):
    """Export a benchmark part: nominal STEP plus STL/3MF.

    With ``calibration=None`` the mesh formats are nominal too -- which is what the benchmarks
    want, because ``intent.json`` asserts nominal values and is checked against the nominal
    model (PRD 6.4).
    """
    from threedp import io

    return io.export(
        build,
        Path(model_dir) / "out" / stem,
        nominal=("step",),
        compensated=("stl", "3mf"),
        calibration=calibration,
        params=params,
    )


def run_model_cli(model_dir: Path, build, load_params, description: str = "") -> int:
    """A ``python model.py`` entry point shared by every benchmark."""
    import argparse

    from threedp import features, intent

    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--calibration", default=None, help="material key, e.g. PLA_generic")
    ap.add_argument("--check", action="store_true", help="check intent.json after exporting")
    ap.add_argument(
        "--source", default="step", choices=("step", "stl", "3mf"), help="what to check"
    )
    args = ap.parse_args()

    params = load_params()
    result = export_benchmark(model_dir, build, params, calibration=args.calibration)
    print(result)

    if not args.check:
        return 0

    path = Path(model_dir) / "out" / f"part.{args.source}"
    report = intent.check(features.extract(path), Path(model_dir) / "intent.json")
    print()
    print(report)
    return 0 if report.passed else 1

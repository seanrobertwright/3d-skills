"""Score the verifier itself on caught / missed / false-positive / harness-error.

**This is the gate, not the benchmarks.** A run can pass every benchmark part with a completely
broken verifier, purely because generation happened to be right (PRD Principle 5). So each
benchmark carries injected defects with declared expected verdicts, and this harness scores the
verifier against them.

Four outcomes, and the fourth is the one that is usually swept up:

* **caught** -- ``EXPECT = FAIL`` and the verifier said FAIL.
* **missed** -- ``EXPECT = FAIL`` and the verifier said PASS. The defect got through.
* **false positive** -- ``EXPECT = PASS`` and the verifier said FAIL. The verifier cries wolf.
* **harness error** -- the mutation could not be built or measured at all. This is neither
  caught nor missed; counting a crash as "caught" would let a broken harness wear a green badge.

Exit code is non-zero on any miss, false positive, or harness error -- **and on finding zero
mutations**, which is a skipped layer, not a pass.

Mutations run against the **mesh** export by default. The mesh path is the one with a ruler in
it: a BREP face query reads a radius straight off the surface and never fits a circle, so a
measurement-method mutation cannot bite there at all. The BREP path is not left unexercised --
the harness cross-checks STEP against STL on every baseline build, and a disagreement is a
harness error.

Usage::

    uv run python benchmarks/run_mutations.py
    uv run python benchmarks/run_mutations.py --part bearing-holder
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import importlib.util
import json
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for extra in (str(REPO_ROOT / "src"), str(HERE)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

CAUGHT = "caught"
MISSED = "MISSED"
FALSE_POSITIVE = "FALSE POSITIVE"
NO_FALSE_POSITIVE = "no false positive"
HARNESS_ERROR = "HARNESS ERROR"

# BREP and mesh must agree on the same part to this tolerance, or one path has a bug.
CROSS_CHECK_TOL = 0.01


@dataclass
class Outcome:
    part: str
    mutation: str
    expect: str
    got: str
    outcome: str
    reason: str = ""
    detail: str = ""

    @property
    def bad(self) -> bool:
        return self.outcome in (MISSED, FALSE_POSITIVE, HARNESS_ERROR)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"mutation_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def discover(part_filter: list[str] | None) -> list[Path]:
    parts = sorted(p for p in HERE.iterdir() if p.is_dir() and (p / "model.py").is_file())
    if part_filter:
        wanted = set(part_filter)
        unknown = wanted - {p.name for p in parts}
        if unknown:
            raise SystemExit(
                f"unknown benchmark(s) {sorted(unknown)}; available: {[p.name for p in parts]}"
            )
        parts = [p for p in parts if p.name in wanted]
    return parts


def apply_overrides(params: dict, overrides: dict, where: str) -> dict:
    params = copy.deepcopy(params)
    for key, value in overrides.items():
        if key not in params:
            # A typo'd override would mutate nothing and then be scored as a miss forever.
            raise KeyError(
                f"{where}: PARAMS_OVERRIDE names unknown parameter {key!r}; "
                f"valid parameters: {sorted(params)}"
            )
        params[key]["value"] = value
    return params


def intent_with_extras(intent_path: Path, extras: list[dict] | None):
    from threedp import intent as intent_mod

    data = json.loads(intent_path.read_text(encoding="utf-8"))
    if extras:
        data["asserts"] = [*data["asserts"], *extras]
    return intent_mod.load(data)


def build_and_export(model, params, mutation, outdir: Path) -> dict:
    """Build one variant and export whatever representations it actually has.

    A mesh-native benchmark (the organic path) has no BREP, so it exports meshes only. Writing a
    tessellated STEP to keep the shapes uniform would produce a file that is CAD-shaped and
    describes nothing.
    """
    import trimesh

    from threedp import compensate, io

    resolved = compensate.resolve(params, None)
    patch = getattr(mutation, "patch", None) if mutation is not None else None
    options = getattr(mutation, "BUILD_OPTIONS", {}) if mutation is not None else {}
    shape = patch(model, resolved) if patch else model.build(resolved, **options)

    if isinstance(shape, trimesh.Trimesh):
        result = io.export(shape, outdir / "part", nominal=(), compensated=("stl",))
    else:
        result = io.export(shape, outdir / "part", nominal=("step",), compensated=("stl",))
    return {**result.nominal, **result.compensated}


def cross_check(paths: dict, part: str) -> None:
    """Every mesh-measured cylinder must have a BREP counterpart at the same radius.

    A one-sided bug -- a drift in the circle fit, a bad axis, a mis-bisected transition --
    survives no other test, because both paths are measuring geometry whose truth is identical
    by construction.

    The check is deliberately one-directional. A Z-scan resolves a closed *ring*, not a face, so
    a small corner fillet blended into a rounded-rectangular profile is one ring to the mesh and
    four separate cylindrical faces to BREP. That is a real difference between the two
    representations, not a disagreement about a dimension.
    """
    from threedp import features

    if "step" not in paths or "stl" not in paths:
        return
    brep = sorted(c.radius for c in features.extract(paths["step"]).cylinders)
    mesh = sorted(c.radius for c in features.extract(paths["stl"]).cylinders)
    orphans = [round(m, 4) for m in mesh if not any(abs(m - b) <= CROSS_CHECK_TOL for b in brep)]
    if orphans:
        raise AssertionError(
            f"{part}: mesh reports cylinder radii {orphans} with no BREP counterpart within "
            f"{CROSS_CHECK_TOL}mm. BREP radii: {[round(b, 4) for b in brep]}"
        )


def run_part(part_dir: Path, verbose: bool = False) -> list[Outcome]:
    from threedp import features, intent

    part = part_dir.name
    mutation_dir = part_dir / "mutations"
    mutation_files = sorted(mutation_dir.glob("*.py")) if mutation_dir.is_dir() else []
    mutation_files = [p for p in mutation_files if not p.name.startswith("_")]
    if not mutation_files:
        return [
            Outcome(
                part, "(none)", "-", "-", HARNESS_ERROR, "no mutations found for this benchmark"
            )
        ]

    outcomes: list[Outcome] = []
    model = load_module(part_dir / "model.py")
    base_params = model.load_params()
    intent_path = part_dir / "intent.json"

    with tempfile.TemporaryDirectory(prefix=f"mut-{part}-") as tmp:
        tmp = Path(tmp)

        # --- baseline: the unmutated part must pass its own intent ------------------------
        baseline_paths = build_and_export(model, base_params, None, tmp / "_baseline")
        cross_check(baseline_paths, part)
        baseline_features = {k: features.extract(v) for k, v in baseline_paths.items()}

        for i, path in enumerate(mutation_files):
            name = path.stem
            try:
                mutation = load_module(path)
                expect = mutation.EXPECT
                if expect not in ("PASS", "FAIL"):
                    raise ValueError(f"EXPECT must be 'PASS' or 'FAIL', got {expect!r}")
                reason = getattr(mutation, "REASON", "")
                kind = getattr(mutation, "KIND", "geometry")
                source = getattr(mutation, "SOURCE", "stl")
                extras = getattr(mutation, "EXTRA_ASSERTS", None)
                spec = intent_with_extras(intent_path, extras)

                # The unmutated part must pass, including any extra ruler assertions -- an
                # extra assertion that already fails would make every verdict meaningless.
                base_report = intent.check(baseline_features[source], spec)
                if not base_report.passed:
                    raise AssertionError(
                        f"baseline {part} does not pass its own intent on the {source} path:\n"
                        f"{base_report}"
                    )

                if kind == "method":
                    with mutation.method_patch():
                        fs = features.extract(baseline_paths[source])
                        report = intent.check(fs, spec)
                else:
                    params = apply_overrides(
                        base_params, getattr(mutation, "PARAMS_OVERRIDE", {}), f"{part}/{name}"
                    )
                    paths = build_and_export(model, params, mutation, tmp / f"m{i}")
                    report = intent.check(features.extract(paths[source]), spec)

                got = "PASS" if report.passed else "FAIL"
                if expect == "FAIL":
                    outcome = CAUGHT if got == "FAIL" else MISSED
                else:
                    outcome = NO_FALSE_POSITIVE if got == "PASS" else FALSE_POSITIVE
                quiet = outcome in (CAUGHT, NO_FALSE_POSITIVE) or not verbose
                detail = "" if quiet else str(report)
                if outcome == FALSE_POSITIVE:
                    detail = "; ".join(f"{f.name}={f.value} ({f.reason})" for f in report.failures)
                elif outcome == CAUGHT and verbose:
                    detail = "; ".join(f.name for f in report.failures)
                outcomes.append(Outcome(part, name, expect, got, outcome, reason, detail))

            except Exception as exc:  # a crash is its own loud category, never "caught"
                outcomes.append(
                    Outcome(
                        part,
                        name,
                        getattr(locals().get("mutation"), "EXPECT", "?"),
                        "ERROR",
                        HARNESS_ERROR,
                        str(exc),
                        traceback.format_exc() if verbose else "",
                    )
                )
    return outcomes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", action="append", help="benchmark directory name; repeatable")
    ap.add_argument("-v", "--verbose", action="store_true", help="print full reports on failures")
    args = ap.parse_args(argv)

    parts = discover(args.part)
    if not parts:
        print("no benchmarks found - that is a FAILURE, not a pass")
        return 1

    outcomes: list[Outcome] = []
    for part_dir in parts:
        outcomes.extend(run_part(part_dir, verbose=args.verbose))

    width = max(len(f"{o.part}/{o.mutation}") for o in outcomes)
    for o in outcomes:
        label = f"{o.part}/{o.mutation}"
        print(f"{label:<{width}}  expect {o.expect:<5} got {o.got:<5}  {o.outcome}")
        if o.reason and o.bad:
            print(f"{'':<{width}}  +- {o.reason}")
        if o.detail:
            for line in o.detail.splitlines():
                print(f"{'':<{width}}     {line}")

    caught = sum(1 for o in outcomes if o.outcome == CAUGHT)
    missed = sum(1 for o in outcomes if o.outcome == MISSED)
    false_positives = sum(1 for o in outcomes if o.outcome == FALSE_POSITIVE)
    errors = sum(1 for o in outcomes if o.outcome == HARNESS_ERROR)
    must_fail = sum(1 for o in outcomes if o.expect == "FAIL" and o.outcome != HARNESS_ERROR)

    print("---")
    if not outcomes:
        print("zero mutations found - that is a FAILURE, not a pass")
        return 1
    ok = missed == 0 and false_positives == 0 and errors == 0 and len(outcomes) > 0
    print(
        f"caught {caught}/{must_fail}   missed {missed}   "
        f"false-positives {false_positives}   harness-errors {errors}"
        f"        VERDICT: {'PASS' if ok else 'FAIL'}"
    )
    print(f"({len(outcomes)} mutations across {len(parts)} benchmark(s))")
    return 0 if ok else 1


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        raise SystemExit(main())
    raise SystemExit(130)

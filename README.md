# 3d-skills

Claude Code skills that take a plain-language description of a physical object to a printable
part. The differentiator is the **verification loop**: *understand → confirm → model → measure
against intent → iterate*.

See [`PRD.md`](PRD.md) for the product definition and [`CLAUDE.md`](CLAUDE.md) for the
conventions that govern this repository.

## Quick start

```bash
uv sync --extra dev
uv run pytest -v
uv run python benchmarks/run_mutations.py
```

## Optional prerequisite: a slicer

`lril3d-slice` wraps **Bambu Studio**'s command line (02.07.01.62 measured). It is an external
program discovered at runtime, never a Python dependency, and everything else in the repository
works without it. Set `THREEDP_SLICER` to point at a different executable; the candidate list
lives in [`profiles/slicer.json`](profiles/slicer.json).

Without a slicer installed, run:

```bash
uv run pytest -m "not slicer"       # green on a machine with no slicer
```

With one installed, `uv run pytest -m slicer` must actually **run** — a green suite with that
layer skipped is not evidence the wrapper works.

Nothing in this repository sends anything to a printer. `--export-3mf` produces a file for manual
transfer; see [`.claude/PRINT-GATE.md`](.claude/PRINT-GATE.md).

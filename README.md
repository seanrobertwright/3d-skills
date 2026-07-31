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

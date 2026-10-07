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

## Use the skills from any folder

The `lril3d-*` skills live in `.claude/skills/`, so a session started inside this checkout sees
them. To have them in every session, link them into your user skills folder and install the
package once, as a `uv` tool:

```bash
# Pin the tool to uv.lock, then install. Without the pin the tool resolves fresh and gets
# newer trimesh, vtk and build123d than the tests ran against.
uv export --frozen --no-dev --no-hashes --no-emit-project -o tool-requirements.txt
uv tool install --editable . --python 3.13 --with-requirements tool-requirements.txt
```

```powershell
# Windows: a junction needs no admin rights. On macOS or Linux use `ln -s`.
Get-ChildItem .claude\skills -Directory -Filter "lril3d-*" | ForEach-Object {
  New-Item -ItemType Junction -Path "$HOME\.claude\skills\$($_.Name)" -Target $_.FullName
}
```

Every skill runs its snippets with `threedp-python`, the interpreter of that tool environment, so
`from threedp import ...` resolves wherever the session is. The install is editable: a `git pull`
here is live everywhere with no reinstall. After `uv.lock` changes, run both commands again with
`--reinstall` added to the second. `profiles/` is read from this checkout unless
`THREEDP_PROFILES` points elsewhere; `models/<name>/...` paths are relative to the folder you are
working in.

Check it from any other folder:

```bash
threedp-python -c "from threedp import compensate; print(compensate.profiles_dir())"
```

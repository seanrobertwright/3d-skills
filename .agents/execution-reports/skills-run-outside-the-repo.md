---
slice: skills-run-outside-the-repo
title: "feat(skills): run the lril3d skills from any folder via threedp-python"
executed: 2026-10-07
base: master @ 370459b
---

# Execution report — `skills-run-outside-the-repo`

The eight `lril3d-*` skills were project-scoped: they live in `.claude/skills/`, and every snippet
in them begins `from threedp import ...`, which resolves only inside the checkout's `.venv`. Linked
into `~/.claude/skills` they appeared in every session and failed on their first line anywhere
else. This slice gives them an interpreter that works from any folder.

## What was done

1. **`src/threedp/launcher.py` and a `[project.scripts]` entry.** `uv tool install --editable .`
   now puts `threedp-python` on the PATH. It runs `-c CODE`, `-m MODULE`, a script path, or `-`
   (stdin) in-process, the way `python` would: same `sys.argv` shape, the script's folder first on
   `sys.path`, exit codes and tracebacks passed through. Any other option is a usage error (exit 2).
2. **`tests/test_launcher.py`, 12 tests.** Every case runs from the checkout's *parent* folder,
   because passing from inside the repo would pass for the wrong reason. They cover each accepted
   form, `SystemExit` and uncaught-exception exit codes, three malformed invocations, the console
   script declaration in `pyproject.toml`, and `profiles_dir()` resolving to the checkout.
3. **A five-line "Where the Python runs" note at the top of each `SKILL.md`.** It names
   `threedp-python`, keeps `uv run python` as the in-checkout spelling, and says where `profiles/`
   and `models/<name>/...` resolve. The viewer's note says `npm` still runs from the checkout.
4. **README "Use the skills from any folder".** The pinned install, the junction loop for Windows,
   and a one-line check to run from another folder.

## Design decisions, with reasons

**In-process, not a child interpreter.** The first draft of the launcher was one line,
`subprocess.call([sys.executable, *args])`. It would have been the second `subprocess` call in the
package, and `test_the_only_subprocess_invocation_is_the_discovered_slicer` exists so that the
only way out of the process is the discovered slicer. Widening that test to make room for a
convenience is the edit the test is written to make visible. `runpy` and `exec` keep the count at
one, at the cost of a narrower option set, which the tests pin.

**The tool is pinned to `uv.lock`, and that was measured, not assumed.** A plain
`uv tool install --editable . --python 3.13` resolved fresh. Read back from the tool environment:

```
package      tool env (fresh)   uv.lock
trimesh      5.1.1              4.12.2
vtk          9.7.1              9.6.2
numpy        2.5.3              2.5.1
build123d    0.13.0             0.11.1
shapely      2.2.0              2.1.2
manifold3d   3.5.4              3.5.2
bpy          5.2.2              5.2.0
```

trimesh is under the one ruler, and a major-version jump there is exactly what the mutation suite
has never seen. The README now exports the lock (`uv export --frozen --no-dev --no-hashes
--no-emit-project`) and installs with `--with-requirements`. After reinstalling that way all seven
read back equal to `uv.lock`. The exported file is gitignored so the lock stays the only source.

**No change to `compensate.profiles_dir()`.** Its existing fallback,
`Path(__file__).resolve().parents[2]`, is the checkout because the install is editable. That is
enough, and the README says `--editable` for that reason.

## Validation — all measured 2026-10-07 at this tree

```
ruff check . && ruff format --check .     All checks passed!  79 files already formatted
interpreter + root-import gate            OK 3.13.15
pytest -m "not printer"                   512 passed, 12 deselected, 0 skipped
pytest -m "not printer and not slicer"    495 passed, 19 deselected, 0 skipped
pytest -m slicer                            7 passed, 517 deselected, 0 skipped
run_mutations.py                          caught 20/20  missed 0  false-positives 0
                                          harness-errors 0   VERDICT: PASS (30 mutations)
```

The hardware-free lane moves **483 → 495**, exactly **+12**, all in `test_launcher.py`. 483 is the
count the 2026-09-15 addendum recorded on master, and no other test file changed.

**An earlier run of `-m "not printer"` reported `1 failed, 511 passed`.** The failure was
`test_this_repository_has_the_artifacts_the_ci_job_demands`, naming this slice: the code review
had been written and this file had not. Reported rather than replaced, because it is the guard
working. The figure in the table is the re-run after this file existed.

**From outside the checkout**, with `threedp-python` installed as the README says and the session
in `D:\repos\claude-mods`:

```
root-import gate + import sdf, bpy        OK 3.13.15
threedp.__file__                          D:\repos\3d-skills\src\threedp\__init__.py
compensate.profiles_dir()                 D:\repos\3d-skills\profiles
raise SystemExit(7)                       exit 7
parts.get("bearing","608")["od"] (stdin)  22.0
```

`-m printer` was **not run**: it needs the P1S powered on, and this slice adds nothing on that path.

## Not done, and not claimed

- **`.claude/settings.json` does not apply outside the checkout.** The six `ask` rules on the send
  path and the `Read(.env)` deny are project settings. The code review's Finding 1 covers what
  still holds: credentials come only from `os.environ`, so with them unset a send from another
  folder raises `PrinterNotConfigured` before any socket opens, and `lril3d-print`'s pre-send
  summary travels with the skill. Copying the `ask` rules into user-level settings was not done;
  it is the person's own configuration, not this repository's.
- **The viewer is still repo-bound.** `vite.config.js` serves only files under the checkout.
- **No CI change.** The launcher tests run in the existing hardware-free lane; nothing in
  `verify.yml` needed to move.
- **The junctions into `~/.claude/skills` are machine state**, made by the README's loop on this
  machine and not by anything committed.

---
slice: skills-run-outside-the-repo
title: "feat(skills): run the lril3d skills from any folder via threedp-python"
author: "seanrobertwright"
reviewed: 2026-10-07
recommendation: approve
---

# Code review — `skills-run-outside-the-repo`

Working-tree review, run before the PR was opened. The slice makes the eight `lril3d-*` skills
usable when they are linked into `~/.claude/skills` and invoked from a session whose working
folder is not this checkout.

| File | Change |
|---|---|
| `src/threedp/launcher.py` | new — the `threedp-python` console script |
| `tests/test_launcher.py` | new — 12 tests, all run from the checkout's parent folder |
| `pyproject.toml` | `[project.scripts]` gains `threedp-python` |
| `.claude/skills/lril3d-*/SKILL.md` | a five-line "Where the Python runs" note in each of the eight |
| `README.md` | new "Use the skills from any folder" section |
| `.gitignore` | ignores the generated `tool-requirements.txt` |

## Findings

### 1 — HIGH · outside the checkout, `.claude/settings.json` is not in force

The `ask` rules on the send path and the `deny` on `Read(.env)` are **project** settings. A session
started in another folder does not load them. `CLAUDE.md` already names those rules as the weaker
half of the print gate ("they catch a shell command routing around the library and cannot see a
Python call"), and the stronger half — `lril3d-print`'s pre-send summary and the human yes — is in
the `SKILL.md` and travels with the skill. So the gate that matters is intact, and the one that is
lost is the one that was already documented as insufficient on its own.

What is still true outside the checkout, checked rather than assumed:

- `printer.credentials()` reads `PRINTER_IP`, `PRINTER_SERIAL` and `PRINTER_ACCESS_CODE` from
  `os.environ` only. Nothing in `src/threedp` loads `.env`. From another folder, with those three
  unset, a send raises `PrinterNotConfigured` before any socket opens.
- `test_printer_path_is_narrow` still holds: the launcher adds no network import and no
  `subprocess` call.

**Not fixed, and stated in the PR.** Copying the six `ask` entries into user-level settings would
restore the shell-layer gate everywhere, but that is a change to the person's own settings and not
to this repository, so it is offered rather than made.

### 2 — MEDIUM · a plain `uv tool install` does not use `uv.lock`

Measured on this machine: `uv tool install --editable .` resolved fresh and installed
**trimesh 5.1.1** against the lock's **4.12.2**, plus newer vtk, numpy, build123d, shapely,
manifold3d and bpy. A major-version move in trimesh sits under the one ruler, and the 495-test lane
and the mutation suite had never seen it.

Fixed: the README exports the lock with `uv export --frozen` and installs with
`--with-requirements`. Re-measured after reinstalling that way: all seven packages match `uv.lock`
exactly. The generated file is gitignored, so the lock stays the only source.

### 3 — MEDIUM · the launcher runs the program in-process, which is narrower than `python`

`launcher.main` accepts `-c`, `-m`, a script path and `-` (stdin), and nothing else. Any other
option (`-u`, `-X`, `-i`, `--version`) is a usage error with exit code 2, not a silent pass-through.

Running in-process rather than through a child interpreter was a deliberate choice:
`test_the_only_subprocess_invocation_is_the_discovered_slicer` asserts there is exactly one
`subprocess` call in the package, and a second one here would have meant widening that test.
The cost is the narrower option set, and the tests pin it from both sides — four accepted forms
work, three malformed ones return 2 and name the tool on stderr.

Exit codes are faithful: `SystemExit(7)` exits 7, an uncaught exception exits 1 with its
traceback on stderr. A launcher that returned 0 over a traceback would let an agent believe
whichever of the two it preferred.

### 4 — LOW · `profiles/` resolution depends on the install being editable

`compensate.profiles_dir()` falls back to `Path(__file__).resolve().parents[2] / "profiles"`. That
is the checkout only because the install is editable; a wheel install would point into
`site-packages` and fail with the existing "set THREEDP_PROFILES" error. The README says
`--editable`, and `test_profiles_resolve_from_outside_the_checkout` asserts the resolution from the
parent folder. No code change: the error is already loud and names the fix.

### 5 — LOW · `models/<name>/...` paths now resolve against the session's folder

Inside the checkout every `models/<name>/out/...` path in the skills landed under the repo. From
another folder they land under that folder. Each skill's note says so. This is the intended
behaviour for a part that belongs to another project, and it is called out rather than changed.

### 6 — LOW · the viewer stays repo-bound

`vite.config.js` serves only files under the checkout, so the viewer note says to run `npm` from
the checkout's `viewer/` folder. Making the viewer folder-independent is a separate slice.

## What was verified, not assumed

- `threedp-python` on PATH, run from `D:\repos\claude-mods`: the full root-import gate passes on
  3.13.15, `sdf` and `bpy` import, `profiles_dir()` is the checkout's `profiles/`, a snippet raising
  `SystemExit(7)` exits 7, and the stdin form reads `parts.get("bearing", "608")["od"]` as 22.0.
- `ruff check .` and `ruff format --check .` clean.
- `test_launcher.py` 12 passed; `test_one_ruler.py`, `test_printer_path_is_narrow.py` and
  `test_ci_runs_the_gates.py` unchanged and passing.

## Recommendation

**Approve.** Finding 1 is the one the person should read before using `lril3d-print` from another
folder.

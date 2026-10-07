"""``threedp-python`` -- the interpreter the ``lril3d-*`` skills run in, from any folder.

The skills are plain Python snippets that begin ``from threedp import ...``. Inside this checkout
``uv run python`` resolves that import because ``uv sync`` installed the package into ``.venv``.
Outside it there is no such environment, so a skill symlinked into ``~/.claude/skills`` shows up
in every session and then fails on its first line.

``uv tool install --editable <checkout>`` builds one environment for this package and puts the
console scripts declared in ``pyproject.toml`` on the PATH. This is that script. It accepts the
four spellings a skill snippet is run with -- ``-c CODE``, ``-m MODULE``, ``SCRIPT`` and ``-``
(stdin) -- and runs them **in this process**, the way ``python`` would: same ``sys.argv`` shape,
the script's folder first on ``sys.path``, ``SystemExit`` and tracebacks reaching the shell as the
exit code. It does not start a second process. ``tests/test_printer_path_is_narrow.py`` allows
exactly one ``subprocess`` call in this package, the discovered slicer, and that stays true.

Editable means a ``git pull`` in the checkout is live without reinstalling, and
``compensate.profiles_dir`` already falls back to the checkout for ``profiles/`` when the current
folder has none, so a skill reads the same configuration it would inside the repo.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

USAGE = (
    "usage: threedp-python -c CODE [arg ...]\n"
    "       threedp-python -m MODULE [arg ...]\n"
    "       threedp-python SCRIPT [arg ...]\n"
    "       threedp-python - [arg ...]        (read the program from stdin)\n"
    "Runs the lril3d-* skill snippets in the environment that has `threedp` installed."
)


def main(argv: list[str] | None = None) -> int:
    """Run one program the way ``python`` would, in this interpreter. Returns the exit code."""
    args = sys.argv[1:] if argv is None else list(argv)
    if not args or args[0] == "-":
        if not args and sys.stdin.isatty():
            print(USAGE, file=sys.stderr)
            return 2
        sys.argv = ["-", *args[1:]]
        _exec(sys.stdin.read(), "<stdin>")
        return 0
    head, rest = args[0], args[1:]
    if head == "-c":
        if not rest:
            print("threedp-python: -c needs the code to run", file=sys.stderr)
            return 2
        sys.argv = ["-c", *rest[1:]]
        _exec(rest[0], "<string>")
        return 0
    if head == "-m":
        if not rest:
            print("threedp-python: -m needs a module name", file=sys.stderr)
            return 2
        sys.argv = [rest[0], *rest[1:]]
        runpy.run_module(rest[0], run_name="__main__", alter_sys=True)
        return 0
    if head.startswith("-"):
        print(f"threedp-python: unknown option {head!r}\n{USAGE}", file=sys.stderr)
        return 2
    script = Path(head)
    if not script.is_file():
        print(f"threedp-python: can't open file {head!r}: no such file", file=sys.stderr)
        return 2
    sys.argv = [head, *rest]
    sys.path.insert(0, str(script.resolve().parent))
    runpy.run_path(str(script), run_name="__main__")
    return 0


def _exec(code: str, filename: str) -> None:
    sys.path.insert(0, "")
    exec(compile(code, filename, "exec"), {"__name__": "__main__", "__builtins__": __builtins__})


if __name__ == "__main__":
    raise SystemExit(main())

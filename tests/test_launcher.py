"""``threedp-python`` runs a skill snippet the way ``python`` would, from any folder.

The launcher exists so the skills work outside this checkout; see ``launcher.py``. Two things it
must not do: start a second process (the package allows exactly one ``subprocess`` call, the
slicer's, and ``test_printer_path_is_narrow`` holds it there), and lose information on the way
through -- a snippet that fails has to fail the shell too, or an agent reads a traceback beside a
zero exit code and believes whichever it prefers.

Every case here runs from the checkout's *parent* folder on purpose: that is the case the
launcher is for, and running from inside the repo would pass for the wrong reason.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PACKAGE_INIT = (REPO / "src" / "threedp" / "__init__.py").resolve()


def run_launcher(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "threedp.launcher", *args],
        capture_output=True,
        text=True,
        input=stdin,
        cwd=REPO.parent,
    )


def test_pyproject_declares_the_console_script():
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["scripts"]["threedp-python"] == "threedp.launcher:main", (
        "the threedp-python entry point is gone; `uv tool install` would put nothing on the PATH"
    )


def test_dash_c_runs_in_this_interpreter_with_the_package_importable():
    code = "import sys, threedp; print(sys.executable); print(threedp.__file__)"
    result = run_launcher("-c", code)
    assert result.returncode == 0, result.stderr
    executable, module = result.stdout.splitlines()
    assert Path(executable).resolve() == Path(sys.executable).resolve(), "a second process"
    assert Path(module).resolve() == PACKAGE_INIT


def test_dash_c_sets_argv_the_way_python_does():
    result = run_launcher("-c", "import sys; print(sys.argv)", "a", "b")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "['-c', 'a', 'b']"


def test_a_script_file_runs_with_its_folder_first_on_the_path(tmp_path):
    (tmp_path / "helper.py").write_text("ANSWER = 42\n", encoding="utf-8")
    script = tmp_path / "snippet.py"
    script.write_text(
        "import sys, helper, threedp\n"
        "print(__name__, helper.ANSWER, sys.argv[1:], threedp.__file__)\n",
        encoding="utf-8",
    )
    result = run_launcher(str(script), "x")
    assert result.returncode == 0, result.stderr
    name, answer, argv, module = result.stdout.split(maxsplit=3)
    assert (name, answer, argv) == ("__main__", "42", "['x']")
    assert Path(module.strip()).resolve() == PACKAGE_INIT


def test_stdin_is_the_program_when_the_argument_is_a_dash():
    result = run_launcher("-", stdin="import threedp; print(threedp.__version__)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0.1.0"


def test_dash_m_runs_a_module():
    result = run_launcher("-m", "json.tool", stdin='{"a": 1}')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("{")


@pytest.mark.parametrize(
    ("code", "expected"),
    [("raise SystemExit(7)", 7), ("1/0", 1)],
    ids=["SystemExit", "uncaught exception"],
)
def test_a_failing_snippet_fails_the_shell(code, expected):
    result = run_launcher("-c", code)
    assert result.returncode == expected, "the exit code must survive the launcher"
    if expected == 1:
        assert "ZeroDivisionError" in result.stderr, "the traceback must survive too"


@pytest.mark.parametrize("args", [("--version",), ("-c",), ("missing.py",)])
def test_a_malformed_invocation_is_a_usage_error_not_a_crash(args):
    result = run_launcher(*args)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "threedp-python" in result.stderr


def test_profiles_resolve_from_outside_the_checkout(monkeypatch):
    """The fallback in ``compensate.profiles_dir`` is what makes the editable install sufficient."""
    monkeypatch.delenv("THREEDP_PROFILES", raising=False)
    result = run_launcher("-c", "from threedp import compensate; print(compensate.profiles_dir())")
    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == (REPO / "profiles").resolve()

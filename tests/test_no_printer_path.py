"""Phase 2 ships no printer path, proved mechanically rather than promised.

`.claude/PRINT-GATE.md` states the rule and `.claude/settings.json` enforces it at the harness
layer. Both are documents, and a rule with no enforcement decays -- the same reasoning as
``test_one_ruler.py``, whose scanner this file reuses rather than copies.

Two things are checked, and they fail in different ways:

* **No send path exists in the library.** No ``ftplib``, ``socket``, ``paho``, ``requests``,
  ``httpx`` or ``urllib.request`` anywhere under ``src/threedp/``, and the one ``subprocess``
  call in the package invokes the discovered slicer and nothing else.
* **The harness gate is intact.** All six printer-send ``deny`` entries are still in the
  committed ``.claude/settings.json``, and they have not migrated into the gitignored
  ``settings.local.json`` where they would be invisible to everyone else.

Converting those ``deny`` entries to ``ask`` is a Phase 3 task that arrives *with*
``lril3d-print``. Doing it early removes a guardrail in exchange for nothing.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

# Imported, never copied: a second scanner would be a second thing to keep correct, and this one
# already handles the case that matters -- a banned name discussed in a docstring is prose, not a
# send path.
from test_one_ruler import REPO, strip_strings_and_comments

PACKAGE = REPO / "src" / "threedp"
SETTINGS = REPO / ".claude" / "settings.json"
LOCAL_SETTINGS = REPO / ".claude" / "settings.local.json"

NETWORK_MODULES = {
    "ftplib",
    "socket",
    "socketserver",
    "paho",
    "requests",
    "httpx",
    "urllib.request",
    "http.client",
    "telnetlib",
    "smtplib",
    "asyncio",
    "websockets",
}

PRINTER_DENY = (
    "Bash(uv run lril3d-send*)",
    "Bash(python*send_to_printer*)",
    "Bash(python*lril3d_print*)",
    "Bash(curl*://*/upload*)",
    "Bash(ftp*)",
    "Bash(lftp*)",
)


def package_files() -> list[Path]:
    return sorted(PACKAGE.glob("*.py"))


def test_the_scan_actually_covers_something():
    """Skipped-layer guard: a broken glob passes everything, silently and forever."""
    files = package_files()
    assert len(files) >= 8, f"only {len(files)} package files scanned; the walk is broken"
    names = {p.name for p in files}
    for expected in ("slicer.py", "gcode.py", "io.py", "render.py"):
        assert expected in names, f"{expected} was not scanned"


def _imported_names(source: str) -> set[str]:
    """Every module name imported by a file, including dotted roots."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.add(node.module.split(".")[0])
    return found


def test_no_module_imports_anything_that_could_reach_a_printer():
    offences = []
    for path in package_files():
        imported = _imported_names(path.read_text(encoding="utf-8"))
        for banned in sorted(NETWORK_MODULES & imported):
            offences.append(f"{path.relative_to(REPO)} imports {banned}")
    assert not offences, "Phase 2 ships no send path:\n" + "\n".join(offences)


def test_a_banned_import_named_only_in_prose_is_not_an_offence():
    """The counterpart. `slicer.py` explains that no FTPS path exists; that is documentation."""
    text = (PACKAGE / "slicer.py").read_text(encoding="utf-8")
    assert "printer" in text.lower(), "the module no longer discusses the boundary at all"
    assert "socket" not in _imported_names(text)


def test_the_only_subprocess_invocation_is_the_discovered_slicer():
    """A subprocess call is the one remaining way out of the process. There is exactly one."""
    users = []
    for path in package_files():
        code = strip_strings_and_comments(path.read_text(encoding="utf-8"))
        if "subprocess." in code:
            users.append(path.name)
    assert users == ["slicer.py"], f"subprocess is used outside the slicer wrapper: {users}"

    source = (PACKAGE / "slicer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr in ("run", "Popen", "call", "check_call", "check_output")
    ]
    assert len(calls) == 1, f"expected exactly one subprocess invocation, found {len(calls)}"

    # ...and the executable it launches is the one find_slicer() located, not an arbitrary
    # program. Resolve the argv variable back to its assignment and read element zero.
    argv = calls[0].args[0]
    assert isinstance(argv, ast.Name), f"argv is {ast.unparse(argv)}; expected a named list"
    assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == argv.id for t in node.targets)
    ]
    assert len(assignments) == 1, f"{argv.id} is assigned {len(assignments)} times; ambiguous"
    built = assignments[0].value
    assert isinstance(built, ast.List) and built.elts, f"{argv.id} is not built as a literal list"
    launched = ast.unparse(built.elts[0])
    assert launched == "str(exe)", (
        f"the subprocess launches {launched}, not the executable find_slicer() returned"
    )
    assert "exe = find_slicer(" in source, "the executable no longer comes from find_slicer()"


def test_no_upload_shaped_helper_exists():
    """Names are the cheapest early warning: a `send_gcode` would fail this before it worked."""
    banned = ("def send", "def upload", "def push_to", "def transfer", "ftps", "mqtt")
    offences = []
    for path in package_files():
        code = strip_strings_and_comments(path.read_text(encoding="utf-8")).lower()
        for name in banned:
            if name in code:
                offences.append(f"{path.name}: {name}")
    assert not offences, "a send path is taking shape:\n" + "\n".join(offences)


# --- the harness gate ---------------------------------------------------------------------------


def test_the_committed_settings_still_deny_every_printer_send_entry():
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    deny = data.get("permissions", {}).get("deny", [])
    for entry in PRINTER_DENY:
        assert entry in deny, f"{entry} is no longer denied in {SETTINGS.name}"
    assert "Read(.env)" in deny, "printer credentials must never be read into a transcript"


def test_the_gate_has_not_migrated_into_the_gitignored_local_settings():
    """`settings.local.json` is gitignored, so a rule moved there is a rule nobody else has."""
    if not LOCAL_SETTINGS.exists():
        return
    data = json.loads(LOCAL_SETTINGS.read_text(encoding="utf-8"))
    permissions = data.get("permissions", {})
    for entry in PRINTER_DENY:
        for bucket in ("deny", "ask", "allow"):
            assert entry not in permissions.get(bucket, []), (
                f"{entry} appears in {LOCAL_SETTINGS.name}, which is gitignored. PRD 9 requires "
                f"the guardrail to be committed."
            )


def test_nothing_has_been_relaxed_from_deny_to_ask_yet():
    """The deny -> ask conversion arrives WITH lril3d-print, in Phase 3. Not before (ADR-5)."""
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    ask = data.get("permissions", {}).get("ask", [])
    for entry in PRINTER_DENY:
        assert entry not in ask, (
            f"{entry} was moved to 'ask' while no send path exists. That removes a guardrail in "
            f"exchange for nothing; see .claude/PRINT-GATE.md."
        )


def test_the_print_gate_document_is_present():
    gate = REPO / ".claude" / "PRINT-GATE.md"
    assert gate.exists()
    assert "Phase 3" in gate.read_text(encoding="utf-8")

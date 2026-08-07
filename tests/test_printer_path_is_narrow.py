"""There is exactly one way out to a printer, and it is ``printer.py``.

The predecessor of this file, ``test_no_printer_path.py``, asserted that **no** module could reach
a printer. Phase 3 makes that false for exactly one module, and the temptation on the day
``printer.py`` lands is to delete the file. That would throw away the guarantee for the other
fourteen modules, which is where most of its value always was: a ``render.py`` that grew a socket
must still fail the suite.

So the ban narrows rather than lifting (ADR-15). Four things are checked, and they fail in
different ways:

* **The network-import ban still applies to every module except ``printer.py``**, which is named
  as the single exception. A *second* send path anywhere fails this test.
* **The one ``subprocess`` invocation is still the discovered slicer.** Unchanged from Phase 2 --
  the other way out of the process did not move.
* **The harness gate has converted, and only where it was meant to.** The six printer-send entries
  are now under ``ask``; ``Read(.env)`` and ``Read(.env.*)`` stay under ``deny``, permanently.
* **The gate is still committed.** A rule that migrated into the gitignored
  ``settings.local.json`` is a rule nobody else has, which PRD §9 forbids.

The scanner is imported from ``test_one_ruler``, never copied: a banned name discussed in a
docstring is prose, not a send path, and there should be exactly one thing that knows the
difference.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from test_one_ruler import REPO, strip_strings_and_comments

PACKAGE = REPO / "src" / "threedp"
SETTINGS = REPO / ".claude" / "settings.json"
LOCAL_SETTINGS = REPO / ".claude" / "settings.local.json"

# The single module allowed to reach the network, asserted by name. Widening this list is a
# decision somebody has to make in a diff, which is the point.
SEND_PATH = "printer.py"

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

PRINTER_SEND = (
    "Bash(uv run lril3d-send*)",
    "Bash(python*send_to_printer*)",
    "Bash(python*lril3d_print*)",
    "Bash(curl*://*/upload*)",
    "Bash(ftp*)",
    "Bash(lftp*)",
)

CREDENTIAL_DENY = ("Read(.env)", "Read(.env.*)")


def package_files() -> list[Path]:
    # rglob, not glob. The exemption is granted to one *file*, so the scan has to reach every file
    # that could take it -- and `src/threedp/net/client.py` would import `socket`, reach a printer,
    # and never be looked at by a non-recursive walk. The package is flat today, so this returns
    # the same list; it stops being the same list on the day somebody adds a subpackage, which is
    # the day the guarantee would otherwise have gone quiet.
    return sorted(PACKAGE.rglob("*.py"))


def test_the_scan_actually_covers_something():
    """Skipped-layer guard: a broken glob passes everything, silently and forever."""
    files = package_files()
    assert len(files) >= 8, f"only {len(files)} package files scanned; the walk is broken"
    names = {p.name for p in files}
    for expected in ("slicer.py", "gcode.py", "io.py", "render.py", "printer.py", "calibrate.py"):
        assert expected in names, f"{expected} was not scanned"

    # ...and counted independently, because the named-file check above stays true no matter how
    # many modules the walk misses. This is the assertion that fails if the glob ever stops being
    # recursive again.
    every = {p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts}
    missed = sorted(str(p.relative_to(REPO)) for p in every - set(files))
    assert not missed, f"the walk skipped {missed}; a module outside it is a module outside the ban"


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


def test_no_module_except_the_send_path_imports_anything_that_could_reach_a_printer():
    offences = []
    for path in package_files():
        if path.name == SEND_PATH:
            continue
        imported = _imported_names(path.read_text(encoding="utf-8"))
        for banned in sorted(NETWORK_MODULES & imported):
            offences.append(f"{path.relative_to(REPO)} imports {banned}")
    assert not offences, (
        "the send path is meant to be one module wide, and it is not:\n" + "\n".join(offences)
    )


def test_the_send_path_is_the_module_it_is_supposed_to_be():
    """Asserted positively too: an empty exception is not the same thing as a narrow one."""
    imported = _imported_names((PACKAGE / SEND_PATH).read_text(encoding="utf-8"))
    assert NETWORK_MODULES & imported, (
        f"{SEND_PATH} imports nothing that could reach a printer, so either the send path moved "
        f"somewhere this test is not looking, or this exemption is now dead and should be removed"
    )


def test_diagnostics_in_tools_still_go_through_the_one_send_path():
    """``tools/`` is outside the package, so the scan above does not reach it.

    That is precisely why it needs saying. Diagnostic scripts talk to the printer, live outside
    ``src/threedp`` to avoid claiming the send-path exemption, and would otherwise be the one
    directory in the repository where a second ``paho.mqtt.Client`` could appear with nothing to
    stop it -- a loophole created by the very rule it evades.

    A script here may import ``threedp.printer`` and use ``PrinterLink`` (including subclassing
    it). It may not open its own connection.
    """
    tools = REPO / "tools"
    if not tools.is_dir():
        return
    scripts = sorted(tools.rglob("*.py"))
    assert scripts, "tools/ exists but holds no scripts; either populate it or delete it"

    offences = []
    for path in scripts:
        imported = _imported_names(path.read_text(encoding="utf-8"))
        for banned in sorted(NETWORK_MODULES & imported):
            offences.append(f"{path.relative_to(REPO)} imports {banned}")
    assert not offences, (
        "a diagnostic in tools/ reaches the network directly instead of going through "
        "printer.PrinterLink:\n" + "\n".join(offences)
    )


def test_a_banned_import_named_only_in_prose_is_not_an_offence():
    """The counterpart. `slicer.py` explains where the boundary is; that is documentation."""
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


def test_no_second_upload_shaped_helper_exists():
    """Names are the cheapest early warning: a `send_gcode` in gcode.py fails before it works."""
    banned = ("def send", "def upload", "def push_to", "def transfer", "ftps", "mqtt")
    offences = []
    for path in package_files():
        if path.name == SEND_PATH:
            continue
        code = strip_strings_and_comments(path.read_text(encoding="utf-8")).lower()
        for name in banned:
            if name in code:
                offences.append(f"{path.name}: {name}")
    assert not offences, "a second send path is taking shape:\n" + "\n".join(offences)


# --- the harness gate, after the ADR-5 conversion -------------------------------------------------


def _permissions() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8")).get("permissions", {})


def test_the_printer_send_entries_have_converted_from_deny_to_ask():
    """ADR-5's conversion. It arrives WITH lril3d-print, and lril3d-print now exists."""
    permissions = _permissions()
    ask, deny = permissions.get("ask", []), permissions.get("deny", [])
    for entry in PRINTER_SEND:
        assert entry in ask, f"{entry} is not under 'ask' in {SETTINGS.name}"
        assert entry not in deny, (
            f"{entry} is under both 'ask' and 'deny'. deny takes precedence, so the capability "
            f"this phase shipped would be unreachable and the reason would be invisible."
        )


def test_the_credential_rules_stay_denied_permanently():
    """Printer IP, serial and access code are never read into a transcript. Not now, not later."""
    deny = _permissions().get("deny", [])
    for entry in CREDENTIAL_DENY:
        assert entry in deny, f"{entry} must stay denied; it is not a Phase 3 conversion"
    ask_allow = _permissions().get("ask", []) + _permissions().get("allow", [])
    for entry in CREDENTIAL_DENY:
        assert entry not in ask_allow


def test_the_print_skill_exists_because_the_gate_was_relaxed_for_it():
    """The conversion is only justified by the capability it guards. Assert it is there."""
    assert (REPO / ".claude" / "skills" / "lril3d-print" / "SKILL.md").is_file()
    assert (PACKAGE / SEND_PATH).is_file()


def test_the_gate_has_not_migrated_into_the_gitignored_local_settings():
    """`settings.local.json` is gitignored, so a rule moved there is a rule nobody else has."""
    if not LOCAL_SETTINGS.exists():
        return
    data = json.loads(LOCAL_SETTINGS.read_text(encoding="utf-8"))
    permissions = data.get("permissions", {})
    for entry in (*PRINTER_SEND, *CREDENTIAL_DENY):
        for bucket in ("deny", "ask", "allow"):
            assert entry not in permissions.get(bucket, []), (
                f"{entry} appears in {LOCAL_SETTINGS.name}, which is gitignored. PRD 9 requires "
                f"the guardrail to be committed."
            )


def test_the_print_gate_document_is_present_and_describes_the_conversion_as_done():
    gate = REPO / ".claude" / "PRINT-GATE.md"
    assert gate.exists()
    text = gate.read_text(encoding="utf-8")
    assert "Phase 3" in text
    assert "When `lril3d-print` exists" not in text, (
        "PRINT-GATE.md still describes the conversion in the future tense, and it has happened"
    )


def test_the_env_template_is_committed_and_the_env_itself_is_not():
    """Correction C9: `.gitignore`'s `.env.*` swallows `.env.example` without the negation."""
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    stripped = [line.strip() for line in ignore]
    assert ".env" in stripped and ".env.*" in stripped
    assert "!.env.example" in stripped, "without this, the template is invisible to every clone"
    assert stripped.index("!.env.example") > stripped.index(".env.*"), (
        "a negation before the pattern it undoes does nothing"
    )
    assert (REPO / ".env.example").is_file()
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for key in ("PRINTER_IP", "PRINTER_SERIAL", "PRINTER_ACCESS_CODE"):
        assert f"{key}=" in example
        assert f"{key}=\n" in example or example.rstrip().endswith(f"{key}="), (
            f"{key} in .env.example has a value; the template must ship empty"
        )

"""The printer link, against fakes, with no printer on the network.

Two layers, mirroring ``test_slicer.py``. This one must be **fully green on a machine that has
never seen a P1S** -- it is the "someone cloned the repo" gate. The hardware layer is
``test_printer_live.py``, marked ``printer``.

The fixtures are not imagination. ``push_status_full.json`` and ``push_status_delta.json`` were
captured off this printer on 2026-08-02 and redacted, and the delta is the one that matters:
it carries **four keys** -- ``bed_temper``, ``command``, ``msg``, ``sequence_id`` -- and a merge
tested only against full pushes passes while being wrong about every one of them.

Three things here are testing an *absence*, which is unusual enough to say out loud:

* that the reply listener does **not** whitelist ``result`` / ``reason`` / ``errno``. That filter
  is what made the first two readings of the dispatch spike wrong -- the printer had been
  answering the whole time with an ``err_code`` echo, and the instrument silently dropped it;
* that :func:`threedp.printer.upload` does **not** call ``conn.unwrap()`` and **does** call
  ``voidresp()``. Both were measured; getting either wrong truncates a file silently;
* that the access code appears in no ``repr``, no exception and no test output.
"""

from __future__ import annotations

import ast
import ftplib
import json
import zipfile
from pathlib import Path

import pytest

from threedp import printer

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]

ACCESS_CODE = "s3cr3tAC"  # only ever appears in this file, never in output
CREDS = printer.Credentials(ip="192.0.2.10", serial="01P00A000000000", access_code=ACCESS_CODE)


def full_push() -> dict:
    return json.loads((FIXTURES / "push_status_full.json").read_text(encoding="utf-8"))["print"]


def delta_push() -> dict:
    return json.loads((FIXTURES / "push_status_delta.json").read_text(encoding="utf-8"))["print"]


def drifted_inventory() -> list[dict]:
    """profiles/filaments.json exactly as it shipped through Phases 1 and 2, before S16."""
    return json.loads((FIXTURES / "filaments_drifted_s16.json").read_text(encoding="utf-8"))[
        "slots"
    ]


def reconciled_inventory() -> list[dict]:
    return json.loads((FIXTURES / "filaments_reconciled.json").read_text(encoding="utf-8"))["slots"]


@pytest.fixture
def conn_config():
    """The shipped profile, with the waiting cut to something a test can afford."""
    config = printer.load_conn_config()
    config["dispatch"] = {
        **config["dispatch"],
        "echo_timeout_s": 1.0,
        "settle_s": 1.0,
        "poll_interval_s": 0.01,
    }
    config["mqtt"] = {**config["mqtt"], "full_push_timeout_s": 1.0}
    return config


# --- configuration and credentials --------------------------------------------------------------


def test_the_shipped_connection_profile_loads_and_is_cited():
    config = printer.load_conn_config()
    assert config["ftps"]["port"] == 990
    assert config["mqtt"]["port"] == 8883
    assert config["source"].strip()
    # Bambu Studio's own bambu_networking.hpp spells it with one 'l'. OpenBambuAPI does not, and
    # a misspelled key is ignored rather than rejected.
    assert "bed_leveling" in config["dispatch"]["project_file_defaults"]
    assert "bed_levelling" not in config["dispatch"]["project_file_defaults"]


def test_the_task_identity_fields_are_the_string_zero():
    """Correction C6: the firmware clamps them, so an epoch id collides with the last job."""
    defaults = printer.load_conn_config()["dispatch"]["project_file_defaults"]
    for key in ("task_id", "project_id", "subtask_id"):
        assert defaults[key] == "0", f"{key} must be the string '0', got {defaults[key]!r}"


def test_a_connection_profile_with_no_source_is_refused(tmp_path):
    path = tmp_path / "printer-conn.json"
    path.write_text(json.dumps({"ftps": {"port": 990}}), encoding="utf-8")
    with pytest.raises(printer.PrinterNotConfigured, match="source"):
        printer.load_conn_config(path)


def test_credentials_come_from_the_environment_and_name_what_is_missing():
    with pytest.raises(printer.PrinterNotConfigured) as exc:
        printer.credentials({"PRINTER_IP": "192.0.2.10"})
    assert "PRINTER_SERIAL" in str(exc.value)
    assert "PRINTER_ACCESS_CODE" in str(exc.value)


def test_the_access_code_appears_in_no_repr_and_no_error():
    """Acceptance criterion, asserted rather than promised."""
    rendered = f"{CREDS!r} {CREDS!s} {CREDS}"
    assert ACCESS_CODE not in rendered
    assert "redacted" in rendered

    # There is no __dict__ to walk either, so a generic attribute-dumping logger finds nothing.
    with pytest.raises(TypeError):
        vars(CREDS)

    with pytest.raises(printer.PrinterNotConfigured) as exc:
        printer.credentials({"PRINTER_IP": "", "PRINTER_SERIAL": "", "PRINTER_ACCESS_CODE": ""})
    assert ACCESS_CODE not in str(exc.value)


def test_no_exception_in_the_module_interpolates_an_access_code():
    """A source-level guard: `{creds.access_code}` inside a message would leak on every failure."""
    source = (REPO / "src" / "threedp" / "printer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offences = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for value in node.values:
                if not isinstance(value, ast.FormattedValue):
                    continue
                rendered = ast.unparse(value.value)
                if "access_code" in rendered and "len(" not in rendered:
                    offences.append(rendered)
    assert not offences, f"an f-string interpolates the access code itself: {offences}"


# --- FTPS (3A-3) ----------------------------------------------------------------------------------


def test_ftps_the_sock_setter_wraps_before_the_greeting_is_read():
    """(a) Implicit TLS means the socket is wrapped from byte zero; AUTH TLS is never sent."""
    assert isinstance(printer.ImplicitFTP_TLS.sock, property)
    assert printer.ImplicitFTP_TLS.sock.fset is not None, (
        "the sock SETTER is the whole mechanism: without it ftplib reads the greeting off a bare "
        "socket and the connection is never implicit"
    )
    source = ast.unparse(
        ast.parse((REPO / "src" / "threedp" / "printer.py").read_text(encoding="utf-8"))
    )
    assert "wrap_socket" in source


def test_ftps_the_data_channel_reuses_the_control_session():
    """(b) The server runs require_ssl_reuse; ftplib has never supported it (cpython#63699)."""
    import inspect

    body = inspect.getsource(printer.ImplicitFTP_TLS.ntransfercmd)
    assert (
        "session=self.sock.session"
        in body.replace(" ", "")
        .replace("\n", "")
        .replace("session=self.sock.session", "session=self.sock.session")
        or "self.sock.session" in body
    )


class FakeFtp:
    """A session double that records exactly which ftplib calls were made."""

    def __init__(
        self,
        listing: list[str] | None = None,
        response: str = "226 Transfer complete.",
        readback: bytes | type | None = None,
    ):
        self.calls: list[str] = []
        self.sent = b""
        self.listing = listing if listing is not None else []
        self.response = response
        self.readback = readback
        self.unwrapped = False

    def voidcmd(self, command):
        self.calls.append(f"voidcmd:{command}")
        return "200 Type set to I."

    def retrbinary(self, command, callback):
        """Serve back whatever `readback` says the card holds -- not necessarily what was sent."""
        self.calls.append(f"retrbinary:{command}")
        if self.readback is RuntimeError:
            raise ftplib.error_temp("451 Failure reading from the card.")
        callback(self.sent if self.readback is None else self.readback)

    def transfercmd(self, command):
        self.calls.append(f"transfercmd:{command}")
        outer = self

        class Conn:
            def sendall(self, data):
                outer.calls.append("sendall")
                outer.sent += data

            def close(self):
                outer.calls.append("close")

            def unwrap(self):  # must never be reached
                outer.unwrapped = True
                raise AssertionError("conn.unwrap() hangs against this firmware and must not run")

        return Conn()

    def voidresp(self):
        self.calls.append("voidresp")
        return self.response

    def retrlines(self, command, callback):
        self.calls.append(f"retrlines:{command}")
        for line in self.listing:
            callback(line)

    def quit(self):
        self.calls.append("quit")

    def close(self):
        self.calls.append("close-session")


def _listing(name: str, size: int) -> str:
    return f"-rw-r--r--    1 0        0        {size:>8} Aug 02 10:04 {name}"


def test_ftps_upload_waits_for_the_226_and_never_unwraps(tmp_path):
    payload = b"x" * 1234
    local = tmp_path / "job.3mf"
    local.write_bytes(payload)
    fake = FakeFtp(listing=[_listing("job.3mf", 1234)])

    result = printer.upload(local, "/", config=printer.load_conn_config(), ftp=fake)

    assert not fake.unwrapped, "conn.unwrap() was called; it hangs against this firmware"
    assert "voidresp" in fake.calls, (
        "voidresp() was skipped. The transfer then truncates silently and the printer answers "
        "0500-C010 on a file that looks perfect locally."
    )
    assert fake.calls.index("sendall") < fake.calls.index("voidresp")
    # ...and the session was put into binary mode first. `retrlines` (the readback) switches to
    # TYPE A, so a session reused for a second upload would otherwise STOR in ASCII.
    assert fake.calls.index("voidcmd:TYPE I") < fake.calls.index("sendall")
    assert fake.sent == payload
    assert result.size_bytes == 1234
    assert result.remote_size_bytes == 1234
    assert result.remote_md5 == result.md5, "the readback must hash to what was sent"
    assert result.complete
    assert result.remote == "/job.3mf"
    assert "verified by readback" in str(result)


def test_ftps_upload_verifies_by_hash_not_only_by_byte_count(tmp_path):
    """A LIST entry is the filesystem's claim about a file. On a failing card it is not the file."""
    payload = b"x" * 1234
    local = tmp_path / "job.3mf"
    local.write_bytes(payload)
    # Right length, wrong bytes -- exactly what a bad sector looks like from the directory.
    fake = FakeFtp(listing=[_listing("job.3mf", 1234)], readback=b"y" * 1234)

    result = printer.upload(local, "/", config=printer.load_conn_config(), ftp=fake)

    assert result.remote_size_bytes == 1234, "the byte count agrees, which is the whole problem"
    assert result.remote_md5 != result.md5
    assert not result.complete, (
        "a file with the right length and the wrong contents was accepted as a complete upload"
    )
    assert "MISMATCH" in str(result)


def test_ftps_upload_that_cannot_be_read_back_is_not_complete(tmp_path):
    """Unreadable is not unverified: a file the printer cannot serve it probably cannot print."""
    local = tmp_path / "job.3mf"
    local.write_bytes(b"x" * 1234)
    fake = FakeFtp(listing=[_listing("job.3mf", 1234)], readback=RuntimeError)
    result = printer.upload(local, "/", config=printer.load_conn_config(), ftp=fake)
    assert result.remote_md5 is not None and result.remote_md5.startswith("unreadable")
    assert not result.complete


def test_a_hash_mismatch_is_refused_by_condition_one(conn_config):
    evidence = _evidence(
        upload=printer.UploadResult(
            local=Path("job.3mf"),
            remote="/job.3mf",
            directory="/",
            size_bytes=1234,
            remote_size_bytes=1234,
            response="226 Transfer complete.",
            md5="a" * 32,
            elapsed_s=1.0,
            remote_md5="b" * 32,
        )
    )
    with pytest.raises(printer.DispatchRejected, match="condition 1") as exc:
        printer.accept_dispatch(evidence, conn_config)
    assert "failing SD card" in str(exc.value)


def test_ftps_upload_is_incomplete_when_the_printer_lists_fewer_bytes(tmp_path):
    """Interrupted mid-STOR: the 226 arrives and the file on the card is short."""
    local = tmp_path / "job.3mf"
    local.write_bytes(b"x" * 1234)
    fake = FakeFtp(listing=[_listing("job.3mf", 900)])
    result = printer.upload(local, "/", config=printer.load_conn_config(), ftp=fake)
    assert result.response.startswith("226")
    assert not result.complete, "a 226 beside a short file must not read as a complete upload"


def test_ftps_upload_refuses_an_empty_file(tmp_path):
    local = tmp_path / "empty.3mf"
    local.write_bytes(b"")
    with pytest.raises(printer.PrinterError, match="0 bytes"):
        printer.upload(local, "/", config=printer.load_conn_config(), ftp=FakeFtp())


def test_the_list_parser_keeps_a_filename_containing_spaces():
    """A space is the field separator, and a filename legitimately contains one.

    Splitting the ninth field further truncates the name, the size lookup misses, and the upload
    reports an unverifiable byte count on a file that is perfectly fine -- a refusal caused by
    the parser rather than by the printer.
    """
    parsed = printer._parse_list_line(
        "-rw-r--r--    1 0        0          135726 Aug 02 10:04 bearing holder v2.3mf"
    )
    assert parsed == ("bearing holder v2.3mf", 135726)


def test_the_list_parser_skips_directories_and_unparseable_lines():
    assert printer._parse_list_line("drwxr-xr-x 2 0 0 4096 Aug 02 10:04 cache") is None
    assert printer._parse_list_line("") is None
    assert printer._parse_list_line("total 12") is None
    assert printer._parse_list_line("-rw-r--r-- 1 0 0 notanumber Aug 02 10:04 x.3mf") is None


def test_remote_sizes_reads_a_whole_listing():
    fake = FakeFtp(
        listing=[
            "drwxr-xr-x    2 0        0            4096 Aug 02 10:04 cache",
            _listing("a.3mf", 10),
            _listing("b with space.3mf", 20),
        ]
    )
    assert printer.remote_sizes(fake, "/") == {"a.3mf": 10, "b with space.3mf": 20}


def test_a_rejected_login_names_the_shape_of_the_code_and_not_the_code(monkeypatch):
    def explode(self, *args, **kwargs):
        raise ftplib.error_perm("530 Login incorrect.")

    monkeypatch.setattr(printer.ImplicitFTP_TLS, "connect", lambda self, **kw: "220")
    monkeypatch.setattr(printer.ImplicitFTP_TLS, "login", explode)
    monkeypatch.setattr(printer.ImplicitFTP_TLS, "close", lambda self: None)
    with pytest.raises(printer.PrinterAuthError) as exc:
        printer.connect_ftps(CREDS, printer.load_conn_config())
    message = str(exc.value)
    assert ACCESS_CODE not in message
    assert f"{len(ACCESS_CODE)} characters" in message
    assert "Developer Mode" in message


# --- the 3MF (3A-6) ------------------------------------------------------------------------------


def _make_3mf(
    path: Path,
    gcode: bytes = b"; G-code\nG1 X1\n",
    filament_ids=("GFA00",),
    filaments=((1, "GFA00", "PLA"),),
    omit: tuple[str, ...] = (),
) -> Path:
    entries = []
    for one_based, tray, material in filaments:
        entries.append(
            f'<filament id="{one_based}" tray_info_idx="{tray}" type="{material}" '
            f'color="#00AE42" used_m="3.58" used_g="10.85"/>'
        )
    slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?><config><plate>'
        + "".join(entries)
        + "</plate></config>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        if "gcode" not in omit:
            archive.writestr("Metadata/plate_1.gcode", gcode)
        if "settings" not in omit:
            archive.writestr(
                "Metadata/project_settings.config",
                json.dumps({"filament_ids": list(filament_ids)}),
            )
        if "slice_info" not in omit:
            archive.writestr("Metadata/slice_info.config", slice_info)
    return path


def test_dispatchable_returns_filaments_in_3mf_order_zero_based(tmp_path):
    path = _make_3mf(
        tmp_path / "job.3mf",
        filament_ids=("GFA00", "GFG00"),
        filaments=((1, "GFA00", "PLA"), (2, "GFG00", "PETG")),
    )
    parsed = printer.assert_3mf_is_dispatchable(path)
    # slice_info.config is 1-based; ams_mapping is 0-based. The conversion happens once, here.
    assert [f.slice_info_id for f in parsed.filaments] == [1, 2]
    assert [f.index for f in parsed.filaments] == [0, 1]
    assert parsed.materials == ["PLA", "PETG"]


def test_dispatchable_refuses_a_3mf_with_no_gcode(tmp_path):
    path = _make_3mf(tmp_path / "model.3mf", omit=("gcode",))
    with pytest.raises(printer.PrinterError, match="plate_1.gcode"):
        printer.assert_3mf_is_dispatchable(path)


def test_dispatchable_refuses_empty_filament_ids(tmp_path):
    """Correction C8: empty ids make use_ams silently ineffective, which prints successfully."""
    path = _make_3mf(tmp_path / "job.3mf", filament_ids=("",))
    with pytest.raises(printer.PrinterError, match="filament_ids"):
        printer.assert_3mf_is_dispatchable(path)
    path = _make_3mf(tmp_path / "job2.3mf", filament_ids=())
    with pytest.raises(printer.PrinterError, match="filament_ids"):
        printer.assert_3mf_is_dispatchable(path)


def test_dispatchable_refuses_an_empty_tray_info_idx(tmp_path):
    path = _make_3mf(tmp_path / "job.3mf", filaments=((1, "", "PLA"),))
    with pytest.raises(printer.PrinterError, match="tray_info_idx"):
        printer.assert_3mf_is_dispatchable(path)


def test_dispatchable_refuses_a_gap_in_the_filament_ids(tmp_path):
    path = _make_3mf(
        tmp_path / "job.3mf",
        filament_ids=("GFA00", "GFG00"),
        filaments=((1, "GFA00", "PLA"), (3, "GFG00", "PETG")),
    )
    with pytest.raises(printer.PrinterError, match="1..2"):
        printer.assert_3mf_is_dispatchable(path)


def test_dispatchable_refuses_a_file_that_is_not_a_zip(tmp_path):
    path = tmp_path / "job.3mf"
    path.write_text("this is not a 3mf", encoding="utf-8")
    with pytest.raises(printer.PrinterError, match="zip"):
        printer.assert_3mf_is_dispatchable(path)


def test_dispatchable_tolerates_a_brace_in_a_field_value(tmp_path):
    """The XML attributes are values, not structure; a `{` in a colour must not be read as one."""
    path = tmp_path / "job.3mf"
    slice_info = (
        '<?xml version="1.0"?><config><plate>'
        '<filament id="1" tray_info_idx="GFA00" type="PLA" color="{#00AE42}" used_g="1.0"/>'
        "</plate></config>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", b"G1\n")
        settings = json.dumps({"filament_ids": ["GFA00"]})
        archive.writestr("Metadata/project_settings.config", settings)
        archive.writestr("Metadata/slice_info.config", slice_info)
    parsed = printer.assert_3mf_is_dispatchable(path)
    assert parsed.filaments[0].color == "{#00AE42}"


# --- telemetry (3A-8, ADR-17) -----------------------------------------------------------------


def test_state_starts_unknown_and_every_accessor_raises():
    state = printer.PrinterState()
    assert not state.known
    for read in (
        lambda: state.gcode_state,
        lambda: state.percent,
        lambda: state.remaining_min,
        lambda: state.subtask_name,
        lambda: state.snapshot(),
        lambda: state.ams_slots,
    ):
        with pytest.raises(printer.TelemetryUnknown):
            read()


def test_a_delta_before_any_full_push_raises_rather_than_reporting_idle():
    """The real capture: four keys, none of them gcode_state. Defaulted, it reads as IDLE."""
    state = printer.PrinterState()
    delta = delta_push()
    assert "gcode_state" not in delta, "the fixture stopped being a delta"
    assert state.merge(delta) is False
    assert not state.known
    with pytest.raises(printer.TelemetryUnknown, match="UNKNOWN"):
        _ = state.gcode_state


def test_a_full_push_makes_the_state_readable():
    state = printer.PrinterState()
    assert state.merge(full_push()) is True
    assert state.known
    assert state.gcode_state == "IDLE"
    assert state.nozzle_type == "stainless_steel"
    assert state.nozzle_diameter == "0.4"
    assert "IDLE" in str(state)


def test_a_delta_merges_into_the_full_push_without_erasing_it():
    state = printer.PrinterState()
    state.merge(full_push())
    before = state.nozzle_type
    state.merge(delta_push())
    assert state.nozzle_type == before, "a delta wiped a key it never mentioned"
    assert state.bed_temper == delta_push()["bed_temper"]
    assert state.deltas == 1


def test_a_nested_delta_does_not_replace_a_whole_subtree():
    """A shallow update would blow away every AMS field the delta did not restate."""
    state = printer.PrinterState()
    state.merge(full_push())
    assert len(state.ams_slots) == 5
    state.merge({"msg": 1, "ams": {"ams_status": 7}})
    assert state.get("ams")["ams_status"] == 7
    assert len(state.ams_slots) == 5, "the tray list was lost to a shallow merge"


def test_remaining_time_is_unknown_when_absent_and_never_zero():
    state = printer.PrinterState()
    push = full_push()
    push.pop("mc_remaining_time")
    state.merge(push)
    assert state.remaining_min is None
    assert state.remaining_s is None
    assert "unknown" in str(state)


def test_remaining_time_is_minutes_not_seconds():
    """Correction C10, a documented-nowhere unit that produces a silent 60x error."""
    state = printer.PrinterState()
    state.merge({**full_push(), "mc_remaining_time": 42})
    assert state.remaining_min == 42
    assert state.remaining_s == 42 * 60


# --- AMS reconciliation (3A-8, ADR-16) ---------------------------------------------------------


def test_live_slots_are_global_and_the_external_spool_is_not_a_slot():
    slots = printer.live_ams_slots(full_push())
    assert [s.slot for s in slots] == [0, 1, 2, 3, 254]
    assert [s.material for s in slots] == ["PLA", "PLA-CF", "PLA", "PETG", "PLA"]
    assert slots[-1].kind == "external"


def test_a_second_ams_unit_occupies_slots_four_to_seven():
    """`ams_id * 4 + tray_id` -- values are not capped at 0-3 (correction C5)."""
    telemetry = {
        "ams": {"ams": [{"id": "1", "tray": [{"id": "0", "tray_type": "PLA"}]}]},
    }
    assert [s.slot for s in printer.live_ams_slots(telemetry)] == [4]


def test_reconcile_blocks_the_exact_shipped_drift_for_abs_and_for_petg():
    """S16, turned into a regression test. This drift shipped, tested and green.

    The drifted inventory is a FROZEN fixture, not ``profiles/filaments.json``. The live file has
    since been corrected from telemetry, and pointing this at it would mean the drift stopped
    being tested on the day somebody fixed it -- which is how the defect survived two phases in
    the first place.
    """
    from threedp import dfm, slicer

    live = full_push()
    shipped = drifted_inventory()

    for material in ("ABS", "PETG"):
        slot = slicer.ams_mapping([material], shipped)
        report = printer.reconcile_ams(live, shipped, used_slots=slot)
        assert not report.passed, f"{material} -> slot {slot} was not blocked"
        blocker = report.blockers[0]
        assert blocker.severity == dfm.BLOCKER
        assert blocker.kind == "material"
        assert blocker.expected == material
        assert blocker.actual != material


def test_reconcile_treats_a_colour_only_difference_as_a_note():
    """Slot 0 is PLA in both; only the colour moved. Refusing on colour is refusing on nothing."""
    from threedp import dfm

    report = printer.reconcile_ams(full_push(), drifted_inventory(), used_slots=[0])
    slot_zero = [f for f in report.findings if f.slot == 0]
    assert slot_zero, "slot 0's colour difference was not reported at all"
    assert all(f.severity == dfm.NOTE for f in slot_zero)
    assert all(f.kind == "colour" for f in slot_zero)


def test_reconcile_downgrades_a_mismatch_in_an_unused_slot_to_a_warning():
    from threedp import dfm

    report = printer.reconcile_ams(full_push(), drifted_inventory(), used_slots=[0])
    assert report.passed, "an unused slot's drift must not gate a print that does not touch it"
    assert {f.slot for f in report.warnings} == {1, 2, 3, 4}
    assert all(f.severity == dfm.WARNING for f in report.warnings)


def test_reconcile_passes_against_the_inventory_that_matches_the_printer():
    report = printer.reconcile_ams(full_push(), reconciled_inventory(), used_slots=[0, 1, 2, 3])
    assert report.passed
    assert report.count("BLOCKER") == 0
    assert report.count("NOTE") == 0, str(report)


def test_reconcile_blocks_an_unreadable_spool_in_a_slot_the_print_uses():
    """The degraded path: a non-Bambu spool reports no material. Unknown is not agreement."""
    telemetry = {"ams": {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": ""}]}]}}
    inventory = [{"slot": 0, "type": "ams", "bay": 0, "material": "PLA", "color": "#101010"}]
    blocked = printer.reconcile_ams(telemetry, inventory, used_slots=[0])
    assert not blocked.passed
    assert blocked.blockers[0].kind == "unreadable"
    assert printer.reconcile_ams(telemetry, inventory, used_slots=[]).passed


def test_reconcile_reports_a_slot_the_inventory_claims_and_the_printer_does_not_have():
    telemetry = {"ams": {"ams": [{"id": "0", "tray": [{"id": "0", "tray_type": "PLA"}]}]}}
    inventory = [
        {"slot": 0, "type": "ams", "bay": 0, "material": "PLA"},
        {"slot": 1, "type": "ams", "bay": 1, "material": "PETG"},
    ]
    report = printer.reconcile_ams(telemetry, inventory, used_slots=[1])
    assert not report.passed
    assert report.blockers[0].kind == "missing"


def test_reconcile_performs_no_io():
    """ADR-16: it takes already-fetched telemetry, exactly as dfm.evaluate takes measurements."""
    import inspect

    body = inspect.getsource(printer.reconcile_ams)
    for banned in ("connect_ftps", "PrinterLink", "pushall", "open("):
        assert banned not in body, f"reconcile_ams reaches for {banned}"


def test_ams_mapping_still_refuses_a_material_in_no_slot():
    from threedp import slicer

    with pytest.raises(slicer.SlicerError, match="not loaded"):
        slicer.ams_mapping(["NYLON"], reconciled_inventory())


# --- the reply channel (3A-7, S18) ---------------------------------------------------------------


class FakeMqttClient:
    """An in-process publish/subscribe double. No paho connection, no network."""

    def __init__(self, responder=None):
        self.published: list[tuple[str, str]] = []
        self.subscribed: list[str] = []
        self.on_connect = None
        self.on_message = None
        self.loop_running = False
        self.disconnected = False
        self.responder = responder

    # -- the paho surface PrinterLink uses --
    def connect(self, host, port, keepalive):
        self.on_connect(self, None, {}, 0)

    def loop_start(self):
        self.loop_running = True

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def publish(self, topic, payload):
        self.published.append((topic, payload))
        if self.responder is not None:
            self.responder(self, json.loads(payload))

    # -- test-side helper: deliver a report as bytes, through the real decoder --
    def deliver(self, payload: dict):
        message = type("Message", (), {"payload": json.dumps(payload).encode("utf-8")})()
        self.on_message(self, None, message)


def _link(conn_config, responder=None):
    client = FakeMqttClient(responder)
    link = printer.PrinterLink(creds=CREDS, config=conn_config, client=client)
    link.connect(timeout_s=1.0)
    return link, client


def test_the_link_subscribes_to_the_report_topic_for_this_serial(conn_config):
    link, client = _link(conn_config)
    assert client.subscribed == [f"device/{CREDS.serial}/report"]
    assert link.request_topic == f"device/{CREDS.serial}/request"
    link.close()


def test_the_listener_captures_an_echo_that_has_none_of_result_reason_errno(conn_config):
    """The regression test for the spike's own bug.

    The refusal really looks like this -- ``0502-4007`` on the wire, and not one of the three
    field names a listener written from the protocol reference would look for.
    """
    link, client = _link(conn_config)
    echo = {
        "print": {
            "sequence_id": "500",
            "command": "project_file",
            "param": "Metadata/plate_1.gcode",
            "url": "ftp:///threedp-spike.3mf",
            "md5": "",
            "err_code": 84033543,
        }
    }
    assert not any(k in echo["print"] for k in ("result", "reason", "errno"))
    client.deliver(echo)

    captured = link.replies(command="project_file", sequence_id="500")
    assert len(captured) == 1, (
        "the echo was dropped. A listener that whitelists ack field names sees nothing here and "
        "reports a timeout -- which is exactly how S18 concluded, twice, that the printer had "
        "accepted the job in silence."
    )
    assert captured[0]["err_code"] == 84033543
    assert captured[0]["url"] == "ftp:///threedp-spike.3mf", "the echo was summarised, not kept"
    link.close()


def test_the_listener_keeps_a_reply_whose_shape_it_has_never_seen(conn_config):
    link, client = _link(conn_config)
    client.deliver({"system": {"sequence_id": "9", "command": "ledctrl", "result": "success"}})
    client.deliver({"info": {"sequence_id": "8", "command": "get_version", "module": []}})
    assert {r["command"] for r in link.replies()} == {"ledctrl", "get_version"}
    link.close()


def test_status_reports_go_to_the_state_and_not_to_the_reply_log(conn_config):
    link, client = _link(conn_config)
    client.deliver({"print": full_push()})
    assert link.state.known
    assert link.replies() == []
    link.close()


def test_an_undecodable_payload_is_counted_and_not_silently_dropped(conn_config):
    link, client = _link(conn_config)
    message = type("Message", (), {"payload": b"\xff\xfe not json"})()
    client.on_message(client, None, message)
    assert link.undecodable == 1
    link.close()


def test_pushall_is_rate_limited(conn_config):
    link, client = _link(conn_config)
    assert link.pushall() is True
    assert link.pushall() is False, "a second pushall inside the interval must be withheld"
    assert link.pushall(force=True) is True
    assert len(client.published) == 2
    link.close()


def test_waiting_for_a_full_push_that_never_arrives_raises(conn_config):
    link, client = _link(conn_config)
    client.deliver({"print": delta_push()})
    with pytest.raises(printer.TelemetryUnknown, match="UNKNOWN"):
        link.wait_for_full_push(timeout_s=0.2)
    link.close()


def test_closing_the_link_stops_the_network_loop(conn_config):
    link, client = _link(conn_config)
    link.close()
    assert client.loop_running is False
    assert client.disconnected is True
    link.close()  # idempotent


def test_the_link_tears_down_when_used_as_a_context_manager(conn_config):
    client = FakeMqttClient()
    with printer.PrinterLink(creds=CREDS, config=conn_config, client=client):
        assert client.loop_running
    assert not client.loop_running


# --- the payload and the pre-flight gate (3A-7) ---------------------------------------------------


def test_the_shipped_url_scheme_is_the_measured_one():
    """The gate is closed, and the winner is recorded with the measurement that won it."""
    config = printer.load_conn_config()
    assert printer.resolve_url_scheme(config) == "ftp:///{name}"
    winners = [
        c for c in config["dispatch"]["url_scheme_candidates"] if c["status"] == "measured-winner"
    ]
    assert len(winners) == 1, "exactly one candidate may be the measured winner"
    assert winners[0]["template"] == config["dispatch"]["url_scheme"]
    assert "Developer Mode ON" in winners[0]["measured"], (
        "the winner must cite the measurement that produced it, not just be selected"
    )


def test_an_unmeasured_url_scheme_refuses_rather_than_guessing():
    """The gate itself, still asserted: a null scheme is an open measurement, not a default.

    S19 rejected every candidate identically -- including a path that does not exist -- so no
    amount of permuting could have found the answer while the authorization gate was shut. If
    this repository is ever pointed at a printer whose accepted form has not been measured, it
    must say so rather than reach for the one that happened to work here.
    """
    config = printer.load_conn_config()
    config["dispatch"] = {**config["dispatch"], "url_scheme": None}
    with pytest.raises(printer.PreFlightGateOpen) as exc:
        printer.resolve_url_scheme(config)
    assert "Developer Mode" in str(exc.value)
    assert "before the url was parsed" in str(exc.value)


def test_a_url_scheme_without_a_name_placeholder_is_refused():
    config = printer.load_conn_config()
    config["dispatch"]["url_scheme"] = "ftp:///fixed.3mf"
    with pytest.raises(printer.PrinterNotConfigured, match="name"):
        printer.resolve_url_scheme(config)


def test_the_payload_carries_ams_mapping2_beside_ams_mapping():
    """Measured: without the companion the firmware resolves no tray and prints through air."""
    command = printer.project_file_command(
        remote_name="job.3mf",
        subtask_name="job",
        sequence_id="7",
        url_scheme="ftp:///{name}",
        use_ams=True,
        ams_mapping=[0, 6],
    )["print"]
    assert command["ams_mapping"] == [0, 6]
    assert command["ams_mapping2"] == [
        {"ams_id": 0, "slot_id": 0},
        {"ams_id": 1, "slot_id": 2},
    ], "the global slot must be spelled out as unit and slot; 6 is unit 1 slot 2"


def test_the_external_spool_is_minus_one_in_the_flat_mapping():
    """Raw 254/255 makes the firmware target AMS tray 0 instead of the external spool."""
    flat, detailed = printer.ams_mapping_fields([254])
    assert flat == [-1]
    assert detailed == [{"ams_id": 255, "slot_id": 0}]


def test_use_ams_with_no_mapping_is_refused():
    with pytest.raises(printer.PrinterNotConfigured, match="through air"):
        printer.project_file_command(
            remote_name="job.3mf",
            subtask_name="job",
            sequence_id="7",
            url_scheme="ftp:///{name}",
            use_ams=True,
            ams_mapping=None,
        )


def test_the_project_file_payload_keeps_the_string_zero_identities():
    command = printer.project_file_command(
        remote_name="job.3mf",
        subtask_name="job",
        sequence_id="7",
        url_scheme="ftp:///{name}",
        md5="deadbeef",
        use_ams=True,
        ams_mapping=[2],
    )["print"]
    assert command["url"] == "ftp:///job.3mf"
    assert command["task_id"] == "0" and command["subtask_id"] == "0"
    assert command["ams_mapping"] == [2]
    assert command["bed_type"] == "auto"
    assert command["command"] == "project_file"


def test_the_project_file_payload_sends_an_empty_mapping_when_ams_is_off():
    command = printer.project_file_command(
        remote_name="job.3mf",
        subtask_name="job",
        sequence_id="7",
        url_scheme="ftp:///{name}",
    )["print"]
    assert command["use_ams"] is False
    assert command["ams_mapping"] == ""


# --- accept_dispatch: ADR-14's four conditions ----------------------------------------------------


def _upload_result(size=1234, remote_size=1234, response="226 Transfer complete."):
    return printer.UploadResult(
        local=Path("job.3mf"),
        remote="/job.3mf",
        directory="/",
        size_bytes=size,
        remote_size_bytes=remote_size,
        response=response,
        md5="d" * 32,
        elapsed_s=1.0,
    )


def _evidence(**overrides):
    base = dict(
        upload=_upload_result(),
        echo={"command": "project_file", "sequence_id": "1"},
        sequence_id="1",
        subtask_name="job",
        gcode_state_before="IDLE",
        gcode_state_after="RUNNING",
        printer_subtask_name="job",
        printer_gcode_file="job.3mf",
        settle_s=3.0,
    )
    base.update(overrides)
    return printer.DispatchEvidence(**base)


def test_accept_dispatch_accepts_when_all_four_conditions_hold(conn_config):
    job = printer.accept_dispatch(_evidence(), conn_config)
    assert job.gcode_state == "RUNNING"
    assert job.started_from == "IDLE"
    assert "job" in str(job)


def test_an_accepted_dispatch_does_not_claim_to_be_a_print(conn_config):
    """Measured: all four conditions satisfied, PREPARE, then back to IDLE at layer 0 of 30.

    So the object must not read as a finished print, because a human skimming the line is the
    last check before somebody walks away from a machine that is doing nothing.
    """
    rendered = str(printer.accept_dispatch(_evidence(gcode_state_after="PREPARE"), conn_config))
    assert "ACCEPTED" in rendered
    assert "NOT a finished print" in rendered
    assert "watch()" in rendered


class _FakeState:
    """A PrinterState stand-in that replays a scripted sequence of pushes.

    It advances on ``gcode_state``, which :func:`watch` reads exactly once per sample and reads
    first. Every other property answers from the *current* entry -- advancing per property access
    would consume several script entries per loop and silently test a sequence nobody wrote.
    """

    def __init__(self, script):
        self.script = list(script)
        self.current = dict(self.script[0])
        self.known = True
        self._first = True

    @property
    def gcode_state(self):
        if self._first:
            self._first = False
        elif len(self.script) > 1:
            self.script.pop(0)
            self.current = dict(self.script[0])
        return self.current["gcode_state"]

    @property
    def layer_num(self):
        return self.current.get("layer_num", 0)

    @property
    def total_layer_num(self):
        return 30

    @property
    def percent(self):
        return self.current.get("mc_percent", 0)

    @property
    def print_error(self):
        return self.current.get("print_error", 0)

    @property
    def filament_at_extruder(self):
        return bool(self.current.get("hw_switch_state", 0))

    @property
    def tray_target(self):
        value = self.current.get("tray_tar", 255)
        return None if value == 255 else int(value)


def _watch(script, conn_config):
    link = printer.PrinterLink(creds=CREDS, config=conn_config, client=FakeMqttClient())
    link.state = _FakeState(script)
    job = printer.accept_dispatch(_evidence(gcode_state_after="PREPARE"), conn_config)
    return printer.watch(link, job, timeout_s=5.0, poll_interval_s=0.01)


def test_watch_reports_a_finished_print(conn_config):
    outcome = _watch(
        [
            {"gcode_state": "PREPARE"},
            {
                "gcode_state": "RUNNING",
                "layer_num": 15,
                "mc_percent": 50,
                "hw_switch_state": 1,
                "tray_tar": 0,
            },
            {
                "gcode_state": "FINISH",
                "layer_num": 30,
                "mc_percent": 100,
                "hw_switch_state": 1,
                "tray_tar": 0,
            },
        ],
        conn_config,
    )
    assert outcome.finished
    assert outcome.layers == 30
    assert outcome.filament_seen
    assert not outcome.reason
    assert "FINISHED" in str(outcome)


def test_watch_refuses_a_finish_that_no_filament_passed_through(conn_config):
    """THE measurement of this phase: 30/30 layers, 100%, print_error 0, and no object.

    Every field the printer publishes agrees the print succeeded. Only ``hw_switch_state``
    dissents, and it is right. A wrapper that trusted ``FINISH`` would tell someone their part is
    ready and send them to an empty plate.
    """
    outcome = _watch(
        [
            {"gcode_state": "PREPARE", "hw_switch_state": 0, "tray_tar": 255},
            {
                "gcode_state": "RUNNING",
                "layer_num": 15,
                "mc_percent": 50,
                "hw_switch_state": 0,
                "tray_tar": 255,
            },
            {
                "gcode_state": "FINISH",
                "layer_num": 30,
                "mc_percent": 100,
                "hw_switch_state": 0,
                "tray_tar": 255,
                "print_error": 0,
            },
        ],
        conn_config,
    )
    assert outcome.state == "FINISH"
    assert outcome.layers == 30
    assert outcome.percent == 100
    assert outcome.print_error == 0
    assert not outcome.filament_seen
    assert not outcome.finished, (
        "a FINISH with no filament was reported as a finished print; this is the exact failure "
        "the whole repository exists to refuse, arriving at the last layer"
    )
    assert "NO FILAMENT EVER REACHED THE EXTRUDER" in outcome.reason
    assert "NO PART" in str(outcome)


def test_filament_seen_only_briefly_still_counts(conn_config):
    """The sensor reads present only while filament is there; the flag latches."""
    outcome = _watch(
        [
            {"gcode_state": "RUNNING", "layer_num": 1, "hw_switch_state": 1, "tray_tar": 0},
            {"gcode_state": "FINISH", "layer_num": 30, "mc_percent": 100, "hw_switch_state": 0},
        ],
        conn_config,
    )
    assert outcome.filament_seen
    assert outcome.finished


def test_watch_refuses_to_call_prepare_then_idle_a_print(conn_config):
    """The measured failure: every ADR-14 condition satisfied and zero layers laid."""
    outcome = _watch(
        [
            {"gcode_state": "PREPARE"},
            {"gcode_state": "IDLE", "layer_num": 0, "print_error": 0x05008003},
        ],
        conn_config,
    )
    assert not outcome.finished
    assert outcome.layers == 0
    assert "without laying a single layer" in outcome.reason
    assert "0500-8003" in outcome.reason or "05008003" in outcome.reason.upper()
    assert "Do not report this as a print" in outcome.reason


def test_watch_separates_a_cancellation_from_a_fault(conn_config):
    outcome = _watch(
        [
            {"gcode_state": "RUNNING", "layer_num": 12, "hw_switch_state": 1},
            {"gcode_state": "FAILED", "layer_num": 12, "print_error": 0x05008003},
        ],
        conn_config,
    )
    assert not outcome.finished
    assert outcome.layers == 12
    assert "cancellation rather than a fault" in outcome.reason


def test_condition_1_a_short_file_is_refused_even_with_a_226(conn_config):
    evidence = _evidence(upload=_upload_result(size=1234, remote_size=900))
    with pytest.raises(printer.DispatchRejected, match="condition 1"):
        printer.accept_dispatch(evidence, conn_config)


def test_condition_1_a_non_226_reply_is_refused(conn_config):
    evidence = _evidence(upload=_upload_result(response="550 Permission denied."))
    with pytest.raises(printer.DispatchRejected, match="condition 1"):
        printer.accept_dispatch(evidence, conn_config)


def test_condition_2_the_authorization_refusal_is_named_not_timed_out(conn_config):
    """0502-4007 must produce a Developer-Mode message by name, within seconds."""
    evidence = _evidence(
        echo={"command": "project_file", "sequence_id": "1", "err_code": 84033543},
        gcode_state_after="IDLE",
    )
    with pytest.raises(printer.DispatchRejected) as exc:
        printer.accept_dispatch(evidence, conn_config)
    message = str(exc.value)
    assert "0502-4007" in message
    assert "Developer Mode" in message
    assert "timeout" not in message.lower()
    assert "84033543" in message


def test_condition_2_an_unknown_err_code_is_reported_whole(conn_config):
    evidence = _evidence(echo={"command": "project_file", "sequence_id": "1", "err_code": 1234})
    with pytest.raises(printer.DispatchRejected) as exc:
        printer.accept_dispatch(evidence, conn_config)
    assert "0000-04D2" in str(exc.value)
    assert '"err_code": 1234' in str(exc.value)


def test_condition_2_silence_points_at_the_link_and_not_at_the_printer(conn_config):
    with pytest.raises(printer.DispatchRejected, match="condition 2"):
        printer.accept_dispatch(_evidence(echo=None), conn_config)


def test_condition_3_a_printer_still_idle_after_settling_is_refused(conn_config):
    """The spike's 'successful' dispatch: conditions 1 and 2 satisfied, and no job."""
    with pytest.raises(printer.DispatchRejected, match="condition 3") as exc:
        printer.accept_dispatch(_evidence(gcode_state_after="IDLE"), conn_config)
    assert "printed nothing" in str(exc.value)


def test_condition_3_an_unknown_state_is_not_a_started_job(conn_config):
    with pytest.raises(printer.DispatchRejected, match="condition 3"):
        printer.accept_dispatch(_evidence(gcode_state_after=""), conn_config)


def test_condition_4_a_printer_that_was_already_running_is_refused(conn_config):
    with pytest.raises(printer.DispatchRejected, match="condition 4"):
        printer.accept_dispatch(
            _evidence(gcode_state_before="RUNNING", gcode_state_after="RUNNING"), conn_config
        )


def test_condition_4_someone_elses_job_is_not_ours(conn_config):
    evidence = _evidence(
        printer_subtask_name="someone-elses-part", printer_gcode_file="other.gcode"
    )
    with pytest.raises(printer.DispatchRejected, match="condition 4"):
        printer.accept_dispatch(evidence, conn_config)


# --- dispatch end to end, against fakes ----------------------------------------------------------


def _dispatch_config(conn_config):
    config = json.loads(json.dumps(conn_config))
    config["dispatch"]["url_scheme"] = "ftp:///{name}"
    return config


def test_dispatch_refuses_before_uploading_when_the_ams_disagrees(
    tmp_path, conn_config, monkeypatch
):
    """The BLOCKER stops the run *before* anything is uploaded and before anything is sent."""
    path = _make_3mf(
        tmp_path / "job.3mf", filament_ids=("GFG00",), filaments=((1, "GFG00", "PETG"),)
    )
    config = _dispatch_config(conn_config)

    uploads: list[Path] = []

    def record_and_upload(local, *args, **kwargs):
        uploads.append(local)
        return _upload_result()

    monkeypatch.setattr(printer, "upload", record_and_upload)

    # The frozen pre-S16 inventory: it maps PETG onto slot 2, and slot 2 holds PLA.
    link, client = _link(config)
    client.deliver({"print": full_push()})
    with pytest.raises(printer.DispatchRejected, match="does not describe what is loaded"):
        printer.dispatch(path, link, inventory=drifted_inventory(), config=config)
    assert uploads == [], "a file was uploaded despite a BLOCKER"
    assert client.published == [], "a command was published despite a BLOCKER"
    link.close()


def test_dispatch_publishes_and_accepts_when_the_printer_starts(tmp_path, conn_config, monkeypatch):
    path = _make_3mf(tmp_path / "job.3mf")
    config = _dispatch_config(conn_config)
    monkeypatch.setattr(printer, "upload", lambda *a, **kw: _upload_result())

    def responder(client, payload):
        command = payload.get("print", {})
        if command.get("command") != "project_file":
            return
        # Echo the whole command back, exactly as the printer does -- no err_code this time.
        client.deliver({"print": dict(command)})
        client.deliver({"print": {**full_push(), "gcode_state": "RUNNING", "subtask_name": "job"}})

    link, client = _link(config, responder)
    client.deliver({"print": full_push()})
    job = printer.dispatch(
        path, link, inventory=reconciled_inventory(), subtask_name="job", config=config
    )
    assert job.gcode_state == "RUNNING"
    assert job.subtask_name == "job"
    sent = json.loads(client.published[-1][1])["print"]
    assert sent["url"] == "ftp:///job.3mf"
    assert sent["use_ams"] is True
    assert sent["ams_mapping"] == [0]
    link.close()


def test_dispatch_reports_the_developer_mode_refusal_from_the_echo(
    tmp_path, conn_config, monkeypatch
):
    path = _make_3mf(tmp_path / "job.3mf")
    config = _dispatch_config(conn_config)
    monkeypatch.setattr(printer, "upload", lambda *a, **kw: _upload_result())

    def responder(client, payload):
        command = payload.get("print", {})
        if command.get("command") == "project_file":
            client.deliver({"print": {**command, "err_code": 84033543}})

    link, client = _link(config, responder)
    client.deliver({"print": full_push()})
    with pytest.raises(printer.DispatchRejected) as exc:
        printer.dispatch(path, link, inventory=reconciled_inventory(), config=config)
    assert "Developer Mode" in str(exc.value)
    link.close()


# --- the profile (3A-5) --------------------------------------------------------------------------


def test_the_p1s_profile_matches_what_the_printer_reports():
    """S17: the vendor spec said hardened steel; the printer says stainless."""
    profile = json.loads((REPO / "profiles" / "printer-p1s.json").read_text(encoding="utf-8"))
    reported = full_push()
    assert profile["nozzle_material"].replace("-", "_") == reported["nozzle_type"]
    assert str(profile["nozzle_diameter"]) == reported["nozzle_diameter"]
    assert "vendor-spec" != profile["source"], "the source must name the measurement, not the spec"
    assert "2026-08-02" in profile["source"]


def test_the_p1s_profile_names_the_plate_that_is_on_the_machine():
    profile = json.loads((REPO / "profiles" / "printer-p1s.json").read_text(encoding="utf-8"))
    slicer_config = json.loads((REPO / "profiles" / "slicer.json").read_text(encoding="utf-8"))
    assert profile["plate"]["type"] == "Textured PEI Plate"
    assert (
        slicer_config["preset_overrides"]["process"]["curr_bed_type"] == profile["plate"]["type"]
    ), "the slicer would bake a first-layer temperature for a plate that is not on the printer"


# --- the skill (3A-10) ----------------------------------------------------------------------------

SKILL = REPO / ".claude" / "skills" / "lril3d-print" / "SKILL.md"


def test_the_print_skill_exists_and_declares_itself():
    assert SKILL.is_file()
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: lril3d-print" in text


def test_the_print_skill_carries_no_numeric_thresholds_or_payload_literals():
    """Thin skills, thick library: a threshold here is a threshold outside the config and tests."""
    import re

    text = SKILL.read_text(encoding="utf-8")
    body = re.sub(r"```.*?```", "", text, flags=re.S)  # fenced code is quoted API, not policy
    offences = [
        line.strip()
        for line in body.splitlines()
        if re.search(r"\b\d+\.\d+\s*(mm|s|g|C)\b", line) or re.search(r"\btimeout\s*=\s*\d", line)
    ]
    assert not offences, f"a threshold has leaked into the skill: {offences}"
    for literal in ("8883", "990", "ftp:///", "project_file", "err_code"):
        assert literal not in body, (
            f"{literal!r} is a protocol detail; it belongs in profiles/printer-conn.json or in "
            f"printer.py, not in a skill"
        )


def test_the_print_skill_refuses_on_a_blocker_and_says_so():
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "blocker" in text
    assert "reconcil" in text
    assert "developer mode" in text

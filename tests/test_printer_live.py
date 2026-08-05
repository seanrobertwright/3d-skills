"""The printer layer against the real P1S. Marked ``printer``; **a skip is not a pass**.

``CLAUDE.md``'s rule for the slicer applies here unchanged: a green suite with this layer skipped
is not evidence the layer works. On the machine that owns this printer these must **run**, and the
count must be non-zero with zero skips.

Everything here is read-only or upload-only **except** :func:`test_the_url_scheme_matrix`, which is
the pre-flight gate's measurement and is the one thing in this repository that can start a physical
print. It is gated behind ``THREEDP_APPROVE_A_REAL_PRINT`` and it stops the print the moment a
scheme wins. Telemetry and FTPS are explicitly exempt from Bambu's Authorization Control, which is
why the rest of this file worked on a printer that was refusing every dispatch.

Credentials come from ``.env`` via the environment, in-process. Nothing here prints one.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from threedp import printer, slicer

pytestmark = pytest.mark.printer

FIXTURES = Path(__file__).resolve().parent / "fixtures"
APPROVAL_ENV = "THREEDP_APPROVE_A_REAL_PRINT"


def _load_dotenv_into_environ() -> None:
    """Read ``.env`` into this process, once.

    ``Read(.env)`` is denied at the harness layer so the file never reaches a transcript; a
    process reading it is the intended path and is what every spike did. Values already in the
    environment win, so CI or a shell export overrides the file.
    """
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@pytest.fixture(scope="module")
def creds():
    _load_dotenv_into_environ()
    try:
        return printer.credentials()
    except printer.PrinterNotConfigured as exc:
        pytest.fail(
            f"the `printer` marker means this layer must RUN, and it cannot: {exc}. Copy "
            f".env.example to .env. Skipping would let a missing layer wear a green badge."
        )


@pytest.fixture(scope="module")
def config():
    return printer.load_conn_config()


@pytest.fixture(scope="module")
def link(creds, config):
    with printer.PrinterLink(creds=creds, config=config) as session:
        session.wait_for_full_push()
        yield session


# --- FTPS round trip ------------------------------------------------------------------------------


def test_ftps_logs_in_and_lists_the_card(creds, config):
    ftp = printer.connect_ftps(creds, config)
    try:
        # The welcome banner does NOT contain "vsFTPd" on this firmware -- do not fingerprint on it.
        assert ftp.sock.version().startswith("TLS")
        for directory in ("/", "/cache"):
            assert isinstance(printer.remote_sizes(ftp, directory), dict)
    finally:
        ftp.quit()


def test_an_upload_round_trips_at_the_exact_byte_count(creds, config, tmp_path):
    """ADR-14 condition 1, both halves, against the machine that motivated them."""
    payload = bytes(range(256)) * 401  # 102,656 bytes, not a round number
    local = tmp_path / "threedp-upload-probe.bin"
    local.write_bytes(payload)

    result = printer.upload(local, "/cache", creds=creds, config=config)
    assert result.response.strip().startswith("226")
    assert result.remote_size_bytes == len(payload), (
        f"the printer lists {result.remote_size_bytes} bytes for a {len(payload)}-byte upload; "
        f"a skipped voidresp() truncates exactly like this"
    )
    assert result.complete


def test_a_wrong_access_code_fails_without_echoing_it(creds, config):
    wrong = printer.Credentials(ip=creds.ip, serial=creds.serial, access_code="00000000")
    with pytest.raises(printer.PrinterError) as exc:
        printer.connect_ftps(wrong, config)
    assert "00000000" not in str(exc.value)
    assert creds.access_code not in str(exc.value)


# --- telemetry ------------------------------------------------------------------------------------


def test_pushall_produces_a_full_push_and_the_state_becomes_readable(link):
    assert link.state.known
    assert link.state.full_pushes >= 1
    assert link.state.gcode_state, "a readable state must report a gcode_state"


def test_the_printer_sends_one_full_push_and_never_repeats_it(link):
    """S15's finding, re-measured -- and this is the half that ADR-17 actually rests on.

    The load-bearing claim is **not** "a delta will arrive within N seconds". Deltas are emitted
    when something *changes*, so a thermally stable idle printer legitimately sends nothing at all,
    and an earlier version of this test failed for exactly that reason -- it asserted a cadence the
    protocol never promises. That is a test inventing a guarantee, which is the same error this
    repository exists to catch, pointed at its own instrumentation.

    What is guaranteed, and what makes the merge necessary, is that the printer sends the full
    state **once** and then stops. If it re-sent everything on every message there would be
    nothing to merge and ADR-17 would be pointless.
    """
    full_pushes_before = link.state.full_pushes
    deltas_before = link.state.deltas
    time.sleep(30.0)

    assert link.state.full_pushes == full_pushes_before, (
        f"the printer sent {link.state.full_pushes - full_pushes_before} further full push(es) "
        f"unprompted. If that is now its behaviour, ADR-17's merge is unnecessary and this "
        f"module is more complicated than it needs to be -- worth knowing either way."
    )
    # Reported, never asserted: zero is a legitimate reading from a printer with nothing to say.
    seen = link.state.deltas - deltas_before
    print("")
    print(f"{seen} delta(s) in 30 s, 0 further full pushes")


def test_the_nozzle_the_profile_claims_is_the_nozzle_reported(link):
    """S17. The profile said hardened steel; the printer says otherwise, and it is the authority."""
    profile = json.loads(
        (Path(__file__).resolve().parents[1] / "profiles" / "printer-p1s.json").read_text(
            encoding="utf-8"
        )
    )
    assert link.state.nozzle_type == profile["nozzle_material"].replace("-", "_")
    assert link.state.nozzle_diameter == str(profile["nozzle_diameter"])


def test_remaining_time_is_reported_in_minutes_or_not_at_all(link):
    """Correction C10. An idle printer reports 0, which cannot settle the unit -- so this asserts
    the weaker thing that is actually knowable while idle: the field is either an int or absent,
    and it is never silently turned into seconds. Task 3B-7 settles the unit against a real print.
    """
    minutes = link.state.remaining_min
    assert minutes is None or isinstance(minutes, int)
    if minutes is not None:
        assert link.state.remaining_s == minutes * 60


# --- reconciliation against the live AMS ---------------------------------------------------------


def test_the_captured_fixture_still_describes_this_printers_ams(link):
    """If the spools changed, the fixture is stale and everything built on it is fiction."""
    live = {s.slot: s.material for s in link.state.ams_slots}
    captured = json.loads((FIXTURES / "push_status_full.json").read_text(encoding="utf-8"))["print"]
    recorded = {s.slot: s.material for s in printer.live_ams_slots(captured)}
    assert live == recorded, (
        f"the AMS has changed since the fixture was captured: live {live} vs recorded {recorded}. "
        f"Re-capture tests/fixtures/push_status_full.json and re-check "
        f"tests/fixtures/filaments_reconciled.json against it."
    )


def test_the_shipped_inventory_is_reconciled_against_the_printer(link):
    """The Phase 3 headline, as a standing check rather than a one-off spike.

    This test FAILS while ``profiles/filaments.json`` disagrees with the AMS, and that is its job:
    the drift shipped green for a whole phase because nothing ever asked the printer.
    """
    report = printer.reconcile_ams(link.state, slicer.load_inventory())
    material_drift = [f for f in report.findings if f.kind in ("material", "missing", "unreadable")]
    assert not material_drift, (
        f"profiles/filaments.json does not describe what is loaded:\n{report}\n"
        f"Correct the inventory (or change the spools). Every dispatch that uses one of these "
        f"slots is blocked until it agrees."
    )


# --- the pre-flight gate: the one thing here that can start a print ------------------------------


def _stop_and_settle(link, config, timeout_s: float = 45.0) -> str:
    """Publish `stop` and wait for the printer to actually reach an idle state.

    Waiting for "not RUNNING" is a bug, not a shortcut: a job stopped during PREPARE is *already*
    not RUNNING, so the predicate is satisfied the instant it is evaluated and the test returns
    while the machine is still heating. Wait for the idle set instead.

    The printer records ``print_error 0500-8003`` after a stop. That is the record of the stop,
    not a fault, and nothing in ``accept_dispatch`` keys on ``print_error`` for exactly this
    reason.
    """
    idle = {str(s).upper() for s in config["dispatch"]["idle_states"]}
    link.publish({"print": {"sequence_id": link.next_sequence_id(), "command": "stop"}})
    reached = link.wait_for(lambda: link.state.gcode_state.upper() in idle, timeout_s, 0.5)
    assert reached, (
        f"the printer did not reach an idle state within {timeout_s:g}s of `stop`; it is "
        f"{link.state.gcode_state} and may still be heating. Stop it at the machine."
    )
    return link.state.gcode_state


def test_a_project_file_for_a_missing_file_is_echoed_without_an_err_code_and_starts_nothing():
    """Conditions 1 and 2 satisfied, no job -- which is why ADR-14 condition 3 is not redundant.

    Measured with Developer Mode ON: publishing ``project_file`` for a filename that is **not** on
    the SD card produces an echo carrying no ``err_code`` at all, sets ``subtask_name`` on the
    printer, and leaves ``gcode_state`` at IDLE. A wrapper that accepted on "the printer answered
    and did not complain" would report a started print here.

    Read-only in the way that matters: the file genuinely does not exist, so there is nothing the
    printer could start even if it wanted to.
    """
    missing = "threedp-there-is-no-such-file.3mf"
    creds_, config_ = printer.credentials(), printer.load_conn_config()

    ftp = printer.connect_ftps(creds_, config_)
    try:
        assert missing not in printer.remote_sizes(ftp, "/"), f"{missing} exists; rename the probe"
    finally:
        ftp.quit()

    with printer.PrinterLink(creds=creds_, config=config_) as link:
        link.wait_for_full_push()
        before = link.state.gcode_state
        sequence_id = link.next_sequence_id()
        link.publish(
            printer.project_file_command(
                remote_name=missing,
                subtask_name="threedp-missing-file-probe",
                sequence_id=sequence_id,
                url_scheme=printer.resolve_url_scheme(config_),
                config=config_,
            )
        )
        echoes = link.wait_for(lambda: link.replies("project_file", sequence_id), 15.0, 0.25)
        assert echoes, "the printer did not echo the command at all"
        assert not echoes[-1].get("err_code"), (
            f"expected no err_code for a missing file, got {echoes[-1].get('err_code')}"
        )
        link.wait_for(lambda: link.state.gcode_state.upper() != before.upper(), 15.0, 0.5)
        assert link.state.gcode_state.upper() in ("IDLE", "FINISH", "FAILED"), (
            f"the printer started something from a file that does not exist: "
            f"{link.state.gcode_state}"
        )


@pytest.mark.skipif(
    os.environ.get(APPROVAL_ENV) != "yes",
    reason=(
        f"starts a REAL print. Set {APPROVAL_ENV}=yes and stand at the printer. It is stopped as "
        f"soon as the four ADR-14 conditions have been judged."
    ),
)
def test_dispatch_end_to_end_and_stop(creds, config, tmp_path):
    """The whole send path against the real machine, then stopped.

    This is the only test that exercises :func:`printer.dispatch` itself -- reconciliation, upload
    with byte-count readback, publish, the echo, and all four acceptance conditions -- against
    hardware. It prints for a few seconds and is stopped before the first layer.
    """
    from threedp import coupon

    gauge = coupon.write_gauge(tmp_path / "probe", kind="hole")
    sliced = slicer.slice_part(
        gauge["stl"], material="PLA", outdir=tmp_path / "slice", export_3mf="threedp-e2e.3mf"
    )
    assert sliced.export_3mf is not None

    with printer.PrinterLink(creds=creds, config=config) as link:
        link.wait_for_full_push()
        job = printer.dispatch(sliced.export_3mf, link, subtask_name="threedp-e2e")
        print("")
        print(job)
        try:
            # The failure this exists to catch: the firmware accepts the job, resolves NO tray,
            # and prints through air. tray_tar leaving 255 is the earliest sign it will feed.
            targeted = link.wait_for(lambda: link.state.tray_target is not None, 90.0, 1.0)
            assert targeted, (
                "the printer resolved no AMS tray (tray_tar stayed 255) within 90 s. Measured: "
                "this is what a project_file missing its ams_mapping2 companion does, and the "
                "print then runs to FINISH at 100% having extruded nothing."
            )
            print(f"AMS targeted tray {link.state.tray_target}")
            assert job.gcode_state.upper() in (
                s.upper() for s in config["dispatch"]["started_states"]
            )
            assert job.size_bytes == sliced.export_3mf.stat().st_size
        finally:
            print(f"stopped: {_stop_and_settle(link, config)}  {link.state}")


@pytest.mark.skipif(
    os.environ.get(APPROVAL_ENV) != "yes",
    reason=(
        f"starts a REAL print. Set {APPROVAL_ENV}=yes, stand at the printer, and read the "
        f"pre-flight gate in the Phase 3 plan first. This is the only skip in this file and it "
        f"guards a physical action, not a missing dependency."
    ),
)
def test_the_url_scheme_matrix(creds, config, tmp_path):
    """Measure which ``url`` form this firmware accepts, and stop the print the moment one wins.

    S19 published eight variants and every one returned ``0502-4007`` -- including a path that does
    not exist -- which is what proves the rejection happens before the url is parsed. So this is
    unknowable until Developer Mode is on, and permuting further while ``0502-4007`` is still
    coming back is exactly what S19 already did, exhaustively.

    Run it, read the winner, and write it into ``dispatch.url_scheme`` with a source naming this
    measurement. Leave the losers in the file as documented, disabled candidates.
    """
    from threedp import coupon

    gauge = coupon.write_gauge(tmp_path / "probe", kind="hole")
    sliced = slicer.slice_part(
        gauge["stl"], material="PLA", outdir=tmp_path / "slice", export_3mf="threedp-probe.3mf"
    )
    assert sliced.export_3mf is not None
    parsed = printer.assert_3mf_is_dispatchable(sliced.export_3mf)
    assert parsed.materials == ["PLA"]

    candidates = config["dispatch"]["url_scheme_candidates"]
    results: list[tuple[str, int | None, str]] = []
    winner: str | None = None

    with printer.PrinterLink(creds=creds, config=config) as link:
        link.wait_for_full_push()
        assert link.state.gcode_state.upper() == "IDLE", (
            f"the printer is {link.state.gcode_state}; this test needs an idle machine"
        )

        uploaded: dict[str, printer.UploadResult] = {}
        for candidate in candidates:
            if candidate.get("status") == "rejected":
                continue
            directory = candidate["upload_dir"]
            if directory not in uploaded:
                uploaded[directory] = printer.upload(
                    sliced.export_3mf, directory, creds=creds, config=config
                )
            result = uploaded[directory]
            assert result.complete

            sequence_id = link.next_sequence_id()
            link.publish(
                printer.project_file_command(
                    remote_name=result.name,
                    subtask_name="threedp-probe",
                    sequence_id=sequence_id,
                    url_scheme=candidate["template"],
                    md5=result.md5,
                    config=config,
                )
            )
            echoes = link.wait_for(
                lambda sid=sequence_id: link.replies("project_file", sid), 10.0, 0.25
            )
            err_code = (echoes[-1].get("err_code") if echoes else None) or None
            started = link.wait_for(
                lambda: link.state.gcode_state.upper() not in ("IDLE", "FAILED"), 20.0, 0.5
            )
            results.append((candidate["template"], err_code, link.state.gcode_state))
            if started:
                winner = candidate["template"]
                _stop_and_settle(link, config)
                break

        print("\nurl scheme matrix:")
        for template, err_code, state in results:
            hexed = "-" if err_code is None else f"{err_code >> 16:04X}-{err_code & 0xFFFF:04X}"
            print(f"  {template:34s} err_code {str(err_code):>10s}  {hexed:>10s}  {state}")
        print(f"WINNER: {winner}")

    refused = [e for _, e, _ in results if e == printer.AUTHORIZATION_REFUSED]
    assert not refused or winner, (
        f"{len(refused)}/{len(results)} forms returned 0502-4007, the LAN authorization refusal. "
        f"Developer Mode is not enabled, or .env still holds the pre-toggle access code -- it "
        f"CHANGES when you toggle it. Nothing here can resolve the url scheme until it is on."
    )
    assert winner, (
        f"Developer Mode appears to be on and no url form started a print: {results}. "
        f"Stop and report; do not guess a scheme into profiles/printer-conn.json."
    )

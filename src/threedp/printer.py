"""The P1S's LAN interface, wrapped -- and the measured ways it reports a lie.

Two transports, both ours rather than a library's (ADR-13): implicit FTPS on 990 to put a sliced
3MF on the SD card, and MQTT over TLS on 8883 to start it and to watch it. Roughly sixty lines of
MIT ``ImplicitFTP_TLS`` are vendored; everything else is written here so that every byte on the
wire is reviewable.

**The hardest job here is refusing to report a job the printer never started.** Each of the
following was observed on this machine on 2026-08-02, against the real printer, and each defeats
the obvious check:

* **A refused dispatch answers with an echo of your own command, not with an ack.** ``project_file``
  is replied to by the whole command echoed back with an ``err_code`` field appended. A listener
  that whitelists ``result`` / ``reason`` / ``errno`` -- which is what every ack in the protocol
  reference looks like -- sees nothing, reports a timeout, and is wrong twice: about *whether* the
  printer answered and about *what it said*. This module keeps every non-status reply **whole**.
* **``err_code`` 84033543 is ``0502-4007``, the LAN authorization refusal**, and it is *not* the
  documented HMS ``0500-0500-0001-0007``; this machine never emits that. Eight url forms were
  published -- including a path that does not exist and a bare filename -- and all eight returned
  ``0502-4007``, which is what proves the rejection happens **before the url is parsed**.
* **A ``226`` on the upload is not a complete file.** ``storbinary``'s stock ``conn.unwrap()``
  hangs against this firmware and must be dropped; drop the ``voidresp()`` with it and the
  transfer truncates silently and the printer throws ``0500-C010``. So the byte count is read back
  off the printer and compared.
* **The first telemetry you receive is a delta, and a delta looks exactly like an idle printer.**
  Over 30 s the P1 sent *one* full push (``msg == 0``) and then deltas. A fresh subscriber that
  defaults its missing fields reports ``gcode_state='IDLE'``, ``mc_percent=0`` about a printer it
  has learned nothing about. :class:`PrinterState` is UNKNOWN until a full push lands, and its
  accessors **raise** until then (ADR-17).
* **``profiles/filaments.json`` is a hand-written claim and it had silently drifted in four of five
  slots.** ``slicer.ams_mapping`` faithfully mapped ABS to slot 3; slot 3 holds green PETG. So
  :func:`reconcile_ams` checks the claim against the printer before any dispatch (ADR-16), exactly
  as ``intent.json`` checks a geometric claim against a measurement.

* **⚠ THE PRINTER REPORTS ``FINISH`` AT 100% FOR A PART THAT DOES NOT EXIST.** Measured
  2026-08-03: a dispatch ran all **30 of 30 layers**, reported ``mc_percent 100``,
  ``gcode_state FINISH``, ``print_error 0`` and an empty ``hms`` -- and produced no object,
  because no filament was ever loaded. ``hw_switch_state`` stayed **0** and ``tray_now``/
  ``tray_tar`` stayed **255** for the entire run: the AMS never targeted a tray, the extruder
  never saw filament, and the machine traced the whole toolpath through air for nine minutes and
  called it a success. Nothing in the return code, the percentage, the layer counter, the error
  field or the fault list dissents. **This is the repository's founding failure at the last
  possible layer**, and it is why :func:`watch` refuses a ``FINISH`` that no filament passed
  through.

  **The root cause is not established.** ``ams_mapping2`` was missing from the payload and has
  been added -- Bambu Studio sends it and the firmware needs it to turn a global tray number into
  a unit and a slot -- but a re-run with it present *still* resolved no tray and *still* loaded
  nothing. So the missing companion field was **a** defect and is not **the** defect. Recorded
  that way on purpose: a plausible cause standing in for a measured one is the thing this
  repository exists to refuse, and it does not stop being that when the code is the subject. The
  detection does not depend on the cause and stays regardless of it.
* **All four acceptance conditions can be satisfied by a job that prints nothing.** Measured after
  Developer Mode was enabled: a dispatch reached ``PREPARE`` -- upload verified, echo clean, state
  left ``IDLE``, job name ours -- and then returned to ``IDLE`` having laid **0 of 30 layers**,
  with ``print_error 0500-8003`` and an empty ``hms``. ``PREPARE`` is transient; the printer is
  still heating and levelling and the job can be abandoned or stopped from there. So
  :class:`PrintJob` means *"the dispatch was accepted"* and nothing more, and :func:`watch` is what
  reports whether a part exists.

So :func:`accept_dispatch` requires **all four** of ADR-14's conditions, and the exception says
which one failed and what to do about it -- and even then it claims only that a dispatch landed.

Two units that are documented nowhere and produce silent errors: ``mc_remaining_time`` is in
**minutes** (correction C10) and is exposed as ``remaining_min``; ``task_id`` and its siblings are
the **string** ``"0"`` and must stay that way (correction C6).

Credentials are read from the environment and never printed. :class:`Credentials` redacts in
``repr``, and no exception in this module interpolates an access code.

Sizes are bytes and suffixed ``_bytes``; times are seconds and suffixed ``_s`` unless they are the
printer's own minutes, which are suffixed ``_min``.
"""

from __future__ import annotations

import ftplib
import hashlib
import json
import os
import ssl
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import paho.mqtt.client as mqtt

from threedp.compensate import profiles_dir

__all__ = [
    "PrinterError",
    "PrinterNotConfigured",
    "PrinterAuthError",
    "PreFlightGateOpen",
    "TelemetryUnknown",
    "DispatchRejected",
    "Credentials",
    "credentials",
    "load_conn_config",
    "ImplicitFTP_TLS",
    "UploadResult",
    "connect_ftps",
    "upload",
    "remote_sizes",
    "Filament3mf",
    "Dispatchable3mf",
    "assert_3mf_is_dispatchable",
    "PrinterState",
    "AmsSlot",
    "AmsFinding",
    "AmsReport",
    "live_ams_slots",
    "reconcile_ams",
    "PrinterLink",
    "resolve_url_scheme",
    "project_file_command",
    "DispatchEvidence",
    "PrintJob",
    "PrintOutcome",
    "accept_dispatch",
    "watch",
    "dispatch",
    "CONFIG_FILE",
    "ENV_IP",
    "ENV_SERIAL",
    "ENV_ACCESS_CODE",
    "AUTHORIZATION_REFUSED",
]

CONFIG_FILE = "printer-conn.json"
INVENTORY_FILE = "filaments.json"

ENV_IP = "PRINTER_IP"
ENV_SERIAL = "PRINTER_SERIAL"
ENV_ACCESS_CODE = "PRINTER_ACCESS_CODE"

# 0x05024007. The LAN authorization refusal (S19). Named here rather than in the config because
# the *handling* is code -- the config carries the human-facing message and its source.
AUTHORIZATION_REFUSED = 0x05024007

# The external spool is not an AMS slot. The P1S reports it as `vt_tray` with id 254; 255 is the
# "nothing selected" sentinel that appears in `tray_now` / `tray_tar`.
EXTERNAL_SPOOL_IDS = (254, 255)

_TRAYS_PER_AMS = 4


class PrinterError(Exception):
    """The printer could not be configured, reached, or trusted."""


class PrinterNotConfigured(PrinterError):
    """Credentials or connection config are missing or unusable."""


class PrinterAuthError(PrinterError):
    """The printer rejected the credentials. Never carries the credential itself."""


class PreFlightGateOpen(PrinterError):
    """A dispatch was attempted while the url scheme is still unmeasured."""


class TelemetryUnknown(PrinterError):
    """State was read before a full push arrived. UNKNOWN is never IDLE (ADR-17)."""


class DispatchRejected(PrinterError):
    """A dispatch completed and its result was refused (ADR-14). Never a warning."""


# --- configuration and credentials --------------------------------------------------------------


def load_conn_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load ``profiles/printer-conn.json``."""
    p = Path(path) if path is not None else profiles_dir() / CONFIG_FILE
    try:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PrinterNotConfigured(f"no printer connection profile at {p}") from exc
    except json.JSONDecodeError as exc:
        raise PrinterNotConfigured(f"{p} is not valid JSON: {exc}") from exc
    # Same discipline as dfm.load_rules and parts.py: a config that cannot say where its values
    # came from is a set of invented numbers, and these ones move real hardware.
    if not str(data.get("source", "")).strip():
        raise PrinterNotConfigured(
            f"{p} has no 'source'. Every profile in this repository names where its values were "
            f"measured; a port, a timeout or a payload default nobody can trace is an invented "
            f"number that starts a physical print."
        )
    return data


@dataclass(frozen=True, repr=False, slots=True)
class Credentials:
    """Printer address and login. **The access code never appears in ``repr`` or in an error.**

    ``slots=True`` is not a micro-optimisation here: it removes ``__dict__``, so a generic
    "dump every attribute" debug helper -- the usual way a secret reaches a log -- has nothing to
    walk. The redacting ``__repr__`` covers the deliberate paths; this covers the accidental one.
    """

    ip: str
    serial: str
    access_code: str

    def __repr__(self) -> str:
        return (
            f"Credentials(ip={self.ip!r}, serial=<{len(self.serial)} chars, "
            f"...{self.serial[-4:]}>, access_code=<redacted, {len(self.access_code)} chars>)"
        )

    __str__ = __repr__


def credentials(env: dict[str, str] | None = None) -> Credentials:
    """Read ``PRINTER_IP`` / ``PRINTER_SERIAL`` / ``PRINTER_ACCESS_CODE`` from the environment.

    ``.env`` is gitignored and ``Read(.env)`` is denied at the harness layer. The values are read
    into *this process* and never into a transcript, which is why this returns a redacting
    dataclass rather than a plain dict.

    The error names the missing keys and nothing else -- an error that echoed a partial value back
    would defeat the whole arrangement.
    """
    source = os.environ if env is None else env
    wanted = (ENV_IP, ENV_SERIAL, ENV_ACCESS_CODE)
    values = {k: str(source.get(k, "") or "").strip() for k in wanted}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise PrinterNotConfigured(
            f"missing printer credentials: {missing}. Copy .env.example to .env and fill them in "
            f"from the printer (Settings -> WLAN). The access code CHANGES when Developer Mode is "
            f"toggled, so a code that worked yesterday is not evidence it is current."
        )
    return Credentials(
        ip=values[ENV_IP], serial=values[ENV_SERIAL], access_code=values[ENV_ACCESS_CODE]
    )


# --- FTPS ---------------------------------------------------------------------------------------


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """Implicit FTPS on 990, plus data-channel TLS session reuse.

    Three deviations from stdlib ``ftplib``, each measured necessary against this firmware:

    (a) the ``sock`` **setter** wraps the socket before the greeting is read, so the connection is
        TLS from byte zero and ``AUTH TLS`` is never sent -- that is what "implicit" means, and
        ``ftplib`` only implements the explicit form;
    (b) ``ntransfercmd`` re-wraps the data connection with ``session=self.sock.session``. The
        server runs ``require_ssl_reuse``, and ``ftplib`` has never supported data-channel session
        reuse (cpython#63699, open since 2013);
    (c) :func:`upload` does **not** call ``conn.unwrap()`` the way ``storbinary`` does -- the
        firmware often never replies to ``close_notify`` and the call hangs forever. The
        ``voidresp()`` that follows it is **kept**: without it the transfer truncates silently,
        and the printer reports ``0500-C010`` on a file that looks fine locally.

    Adapted from ``bambulabs_api``'s ``ftp_client.py`` (MIT).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._sock: Any = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session
            )
        return conn, size


def _tls_context(config: dict[str, Any]) -> ssl.SSLContext:
    """A client context that does not verify the certificate, and says why.

    The printer's certificate is issued by a Bambu CA with ``CN = <printer serial>``, so hostname
    verification against an IP address cannot succeed and there is no chain to a public root. The
    connection is on a private LAN to an address the operator typed. Verification is disabled
    deliberately and in one place rather than incidentally in three.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    minimum = str(config.get("ftps", {}).get("minimum_tls_version", "TLSv1_2"))
    version = getattr(ssl.TLSVersion, minimum, None)
    if version is None:
        raise PrinterNotConfigured(
            f"ftps.minimum_tls_version={minimum!r} is not an ssl.TLSVersion name; "
            f"measured on this machine: the printer negotiates TLSv1_2"
        )
    context.minimum_version = version
    return context


def connect_ftps(
    creds: Credentials | None = None, config: dict[str, Any] | None = None
) -> ImplicitFTP_TLS:
    """Open an authenticated, ``PROT P`` implicit-FTPS session."""
    config = load_conn_config() if config is None else config
    creds = credentials() if creds is None else creds
    ftps_config = config.get("ftps", {})
    ftp = ImplicitFTP_TLS(context=_tls_context(config))
    try:
        ftp.connect(
            host=creds.ip,
            port=int(ftps_config.get("port", 990)),
            timeout=float(ftps_config.get("timeout_s", 20)),
        )
        ftp.login(user=str(ftps_config.get("user", "bblp")), passwd=creds.access_code)
        ftp.prot_p()
    except ftplib.error_perm as exc:
        # `exc` is the server's own response line; it carries no credential. The message below
        # deliberately describes the code's *shape* and never its value.
        try:
            ftp.close()
        except Exception:  # noqa: BLE001 - closing a failed socket must not mask the auth error
            pass
        raise PrinterAuthError(
            f"the printer rejected the FTPS login ({exc}). The access code in the environment is "
            f"{len(creds.access_code)} characters. It CHANGES when LAN Developer Mode is toggled "
            f"-- read it off the printer screen again rather than assuming yesterday's is current."
        ) from None
    except OSError as exc:
        try:
            ftp.close()
        except Exception:  # noqa: BLE001
            pass
        raise PrinterError(
            f"could not reach the printer's FTPS port at {creds.ip}:"
            f"{ftps_config.get('port', 990)} -- {type(exc).__name__}: {exc}"
        ) from exc
    return ftp


def _parse_list_line(line: str) -> tuple[str, int] | None:
    """One ``LIST`` line -> ``(name, size_bytes)``, or ``None`` if it is not a plain file.

    The format is the unix ``ls -l`` one::

        -rw-r--r--    1 0        0          135726 Aug 02 10:04 threedp-spike.3mf

    Nine fields, and **the ninth is the rest of the line** -- a filename legitimately contains
    spaces, so splitting it into a tenth field truncates the name and the lookup silently misses.
    Directories and links are skipped: a directory has no byte count worth comparing.
    """
    line = line.rstrip("\r\n")
    if not line or line[0] in "dl":
        return None
    parts = line.split(maxsplit=8)
    if len(parts) < 9:
        return None
    try:
        size = int(parts[4])
    except ValueError:
        return None
    return parts[8], size


def remote_sizes(ftp: ftplib.FTP, directory: str) -> dict[str, int]:
    """Every plain file in ``directory`` and its byte count, read back off the printer."""
    lines: list[str] = []
    ftp.retrlines(f"LIST {directory}", lines.append)
    sizes: dict[str, int] = {}
    for line in lines:
        parsed = _parse_list_line(line)
        if parsed is not None:
            sizes[parsed[0]] = parsed[1]
    return sizes


@dataclass(frozen=True)
class UploadResult:
    """A completed transfer, and the readback that makes it believable."""

    local: Path
    remote: str
    directory: str
    size_bytes: int
    remote_size_bytes: int | None
    response: str
    md5: str
    elapsed_s: float
    remote_md5: str | None = None

    @property
    def name(self) -> str:
        return Path(self.remote).name

    @property
    def complete(self) -> bool:
        """``226``, the right byte count, **and** the right bytes. No one of the three is enough.

        The third was added after a failing SD card was found in this printer. A ``LIST`` entry is
        the filesystem's *claim* about a file's length; it is not the file. On a card that is going
        bad those diverge, and a wrapper that stops at the byte count would hand a multi-hour print
        a file it never actually read. Hashing the readback costs about a second on 135 kB.
        """
        if not self.response.strip().startswith("226"):
            return False
        if self.remote_size_bytes != self.size_bytes:
            return False
        return self.remote_md5 is None or self.remote_md5 == self.md5

    def __str__(self) -> str:
        readback = (
            "not readable" if self.remote_size_bytes is None else f"{self.remote_size_bytes} bytes"
        )
        if self.remote_md5 is None:
            verdict = "md5 NOT verified"
        elif self.remote_md5 == self.md5:
            verdict = "md5 verified by readback"
        else:
            verdict = f"md5 MISMATCH (read back {self.remote_md5[:8]}...)"
        return (
            f"upload   {self.remote}   {self.size_bytes} bytes in {self.elapsed_s:.1f} s   "
            f"reply {self.response.strip()!r}   readback {readback}   "
            f"md5 {self.md5[:8]}...   {verdict}"
        )


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_back_md5(ftp: ftplib.FTP, remote: str) -> str:
    """Download ``remote`` and hash it, without keeping the file.

    The only way to know the printer can read what we wrote. Streamed through the hash rather than
    buffered, so a large 3MF costs a constant few kilobytes of memory.
    """
    digest = hashlib.md5(usedforsecurity=False)
    ftp.voidcmd("TYPE I")
    ftp.retrbinary(f"RETR {remote}", digest.update)
    return digest.hexdigest()


def upload(
    path: str | Path,
    directory: str | None = None,
    creds: Credentials | None = None,
    config: dict[str, Any] | None = None,
    ftp: ftplib.FTP | None = None,
    verify_md5: bool | None = None,
) -> UploadResult:
    """Put a file on the printer's SD card and read its size back.

    Both halves of ADR-14 condition 1 live here: the ``226`` from ``voidresp()`` **and** a
    follow-up ``LIST`` showing the file at the exact byte count. The ``226`` alone is not
    evidence -- a transfer whose ``voidresp()`` was skipped truncates and still looks fine from
    the client's side.

    ``ftp`` is for tests and for callers that already hold a session; when it is ``None`` one is
    opened and closed here.
    """
    config = load_conn_config() if config is None else config
    source = Path(path)
    if not source.is_file():
        raise PrinterError(f"no file to upload at {source}")
    payload = source.read_bytes()
    if not payload:
        raise PrinterError(
            f"{source} is 0 bytes. Uploading it would produce a 226 and a file the printer cannot "
            f"parse; refused here rather than diagnosed on the printer's screen."
        )

    directory = str(config["ftps"]["upload_dir"]) if directory is None else directory
    if not directory.startswith("/"):
        directory = "/" + directory
    remote = directory.rstrip("/") + "/" + source.name

    owned = ftp is None
    session = connect_ftps(creds, config) if owned else ftp
    try:
        started = time.monotonic()
        # `storbinary` sends this and we do not use `storbinary`. It matters because
        # `remote_sizes` below issues LIST, and `retrlines` switches the session to TYPE A -- so
        # a second upload on the same session would STOR in ASCII mode and a strict server would
        # translate line endings inside the 3MF. The byte-count readback would then catch it, but
        # only after a corrupt file was already on the card.
        session.voidcmd("TYPE I")
        conn = session.transfercmd(f"STOR {remote}")
        try:
            conn.sendall(payload)
        finally:
            # NOT conn.unwrap(): the firmware often never answers close_notify and the call
            # never returns. Closing the socket outright is what the spike measured working.
            conn.close()
        response = session.voidresp()  # (c) -- dropping this truncates the file silently
        elapsed_s = time.monotonic() - started
        sizes = remote_sizes(session, directory)
        if verify_md5 is None:
            verify_md5 = bool(config.get("ftps", {}).get("verify_md5", True))
        remote_md5 = None
        if verify_md5:
            try:
                remote_md5 = read_back_md5(session, remote)
            except (ftplib.Error, OSError) as exc:
                # Unreadable is not "unverified": a file the printer cannot serve back is a file
                # it probably cannot print either, and this is exactly the SD-card failure the
                # check exists for. Recorded as a mismatch rather than skipped.
                remote_md5 = f"unreadable: {type(exc).__name__}"
    finally:
        if owned:
            try:
                session.quit()
            except Exception:  # noqa: BLE001 - a failed QUIT must not mask a successful transfer
                session.close()

    return UploadResult(
        local=source,
        remote=remote,
        directory=directory,
        size_bytes=len(payload),
        remote_size_bytes=sizes.get(source.name),
        response=str(response),
        md5=_md5(source),
        elapsed_s=elapsed_s,
        remote_md5=remote_md5,
    )


# --- the 3MF, before anything is sent -----------------------------------------------------------


@dataclass(frozen=True)
class Filament3mf:
    """One filament a 3MF uses.

    ``index`` is 0-based (``ams_mapping``'s convention); ``slice_info_id`` is the file's own
    1-based id. Converting between them is done exactly once, in
    :func:`assert_3mf_is_dispatchable`.
    """

    index: int
    slice_info_id: int
    material: str
    tray_info_idx: str
    color: str
    used_g: float | None


@dataclass(frozen=True)
class Dispatchable3mf:
    """A 3MF that carries everything the printer needs to run it from the AMS."""

    path: Path
    filaments: tuple[Filament3mf, ...]
    filament_ids: tuple[str, ...]
    md5: str

    @property
    def materials(self) -> list[str]:
        """The materials in **3MF order** -- what ``slicer.ams_mapping`` takes."""
        return [f.material for f in self.filaments]

    def __str__(self) -> str:
        listed = ", ".join(f"{f.index}:{f.material}/{f.tray_info_idx}" for f in self.filaments)
        return f"3mf      {self.path.name}   {len(self.filaments)} filament(s) [{listed}]"


_GCODE_ENTRY = "Metadata/plate_1.gcode"
_SETTINGS_ENTRY = "Metadata/project_settings.config"
_SLICE_INFO_ENTRY = "Metadata/slice_info.config"


def assert_3mf_is_dispatchable(path: str | Path) -> Dispatchable3mf:
    """Refuse a 3MF the printer would accept and then print wrong.

    Three checks, and the second two are correction C8 turned into a test on *this file* rather
    than a belief about the toolchain. PRD §9 records that ``use_ams`` is silently ignored unless
    ``filament_id`` is set inside the 3MF. Measured here, Bambu Studio's CLI does write both
    ``filament_ids`` and a populated ``tray_info_idx``; the trap is real but traces to
    **OrcaSlicer's** CLI emitting empty ids, and this repo does not use OrcaSlicer. Checking it
    costs one read and is the difference between believing it is fine and having verified it.

    The ``id`` in ``slice_info.config`` is **1-based** and ``ams_mapping`` is **0-based**. The
    conversion happens exactly once, here.
    """
    source = Path(path)
    if not source.is_file():
        raise PrinterError(f"no 3MF at {source}")
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise PrinterError(f"{source} is not a readable 3MF (zip) archive: {exc}") from exc

    with archive:
        names = set(archive.namelist())
        if _GCODE_ENTRY not in names:
            raise PrinterError(
                f"{source.name} carries no {_GCODE_ENTRY}. A 3MF exported without slicing is a "
                f"model file, not a print job -- the printer would accept it and produce nothing. "
                f"Slice it with slicer.slice_part(..., export_3mf=...) rather than exporting "
                f"geometry directly."
            )
        if archive.getinfo(_GCODE_ENTRY).file_size == 0:
            raise PrinterError(f"{source.name}'s {_GCODE_ENTRY} is 0 bytes")

        if _SETTINGS_ENTRY not in names:
            raise PrinterError(f"{source.name} carries no {_SETTINGS_ENTRY}")
        try:
            settings = json.loads(archive.read(_SETTINGS_ENTRY))
        except json.JSONDecodeError as exc:
            raise PrinterError(
                f"{source.name}: {_SETTINGS_ENTRY} is not valid JSON: {exc}"
            ) from exc
        ids = settings.get("filament_ids") or []
        if not isinstance(ids, list) or not ids or any(not str(i).strip() for i in ids):
            raise PrinterError(
                f"{source.name} has filament_ids={ids!r}. An empty or missing filament id makes "
                f"the printer silently ignore use_ams and print from whatever is loaded -- which "
                f"looks like a successful print of the wrong material rather than an error "
                f"(PRD §9). Re-slice with flattened presets."
            )

        if _SLICE_INFO_ENTRY not in names:
            raise PrinterError(f"{source.name} carries no {_SLICE_INFO_ENTRY}")
        try:
            root = ElementTree.fromstring(archive.read(_SLICE_INFO_ENTRY))
        except ElementTree.ParseError as exc:
            raise PrinterError(
                f"{source.name}: {_SLICE_INFO_ENTRY} is not valid XML: {exc}"
            ) from exc

    filaments: list[Filament3mf] = []
    for element in root.iter("filament"):
        tray = str(element.get("tray_info_idx", "") or "").strip()
        raw_id = str(element.get("id", "") or "").strip()
        if not raw_id.isdigit():
            raise PrinterError(
                f"{source.name}: a <filament> in {_SLICE_INFO_ENTRY} has id={raw_id!r}, which is "
                f"not a number. The id is the 1-based filament index and the AMS mapping is "
                f"derived from it."
            )
        one_based = int(raw_id)
        if not tray:
            raise PrinterError(
                f"{source.name}: filament {one_based} has an empty tray_info_idx. That is the "
                f"field the printer matches against the AMS; empty, it loads whatever is in the "
                f"active slot and reports success."
            )
        used = element.get("used_g")
        filaments.append(
            Filament3mf(
                index=one_based - 1,  # 1-based in the file, 0-based for ams_mapping (S22)
                slice_info_id=one_based,
                material=str(element.get("type", "") or "").strip(),
                tray_info_idx=tray,
                color=str(element.get("color", "") or "").strip(),
                used_g=float(used) if used not in (None, "") else None,
            )
        )

    if not filaments:
        raise PrinterError(
            f"{source.name}: {_SLICE_INFO_ENTRY} lists no <filament> at all, so nothing can be "
            f"mapped onto an AMS slot"
        )
    filaments.sort(key=lambda f: f.index)
    expected = list(range(len(filaments)))
    if [f.index for f in filaments] != expected:
        raise PrinterError(
            f"{source.name}: filament ids in {_SLICE_INFO_ENTRY} are "
            f"{[f.slice_info_id for f in filaments]}, which is not 1..{len(filaments)}. "
            f"ams_mapping is positional, so a gap would shift every slot after it."
        )
    missing_material = [f.slice_info_id for f in filaments if not f.material]
    if missing_material:
        raise PrinterError(
            f"{source.name}: filament(s) {missing_material} declare no material type in "
            f"{_SLICE_INFO_ENTRY}; there is nothing to reconcile against the AMS"
        )

    return Dispatchable3mf(
        path=source,
        filaments=tuple(filaments),
        filament_ids=tuple(str(i) for i in ids),
        md5=_md5(source),
    )


# --- telemetry (ADR-17) -------------------------------------------------------------------------


def _merge(into: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge; lists and scalars are replaced wholesale.

    A delta carrying ``{"ams": {"ams": [...]}}`` must not blow away ``ams.tray_exist_bits``, and a
    shallow ``update`` does exactly that. Lists *are* replaced: the printer sends whole tray
    arrays, and merging them element-wise would invent a state that is a blend of two moments.
    """
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(into.get(key), dict):
            _merge(into[key], value)
        else:
            into[key] = value
    return into


class PrinterState:
    """Merged telemetry. **UNKNOWN until a full push, and UNKNOWN is never IDLE** (ADR-17).

    Measured: over 30 s the P1 sends exactly one full push (``msg == 0``) and then deltas. A
    subscriber whose first message is a delta sees a near-empty object; code that defaults its
    missing fields then reports a confident ``IDLE`` about a printer it knows nothing about. So
    every accessor here raises :class:`TelemetryUnknown` until a full push has been merged --
    the same reflex as ``CircleFit.diameter`` refusing without a circularity verdict.

    ``pushall`` is what ends the UNKNOWN period, and it is rate-limited: Bambu warn against
    polling the P1 faster than five minutes.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._full_push_seen = False
        self._pushes = 0
        self._deltas = 0
        self._lock = threading.Lock()

    # -- ingestion ------------------------------------------------------------------------

    def merge(self, section: dict[str, Any]) -> bool:
        """Merge one ``print`` section. Returns ``True`` if it was the full push."""
        if not isinstance(section, dict):
            raise PrinterError(
                f"a telemetry section must be an object, got {type(section).__name__}"
            )
        is_full = section.get("msg") == 0
        with self._lock:
            _merge(self._data, section)
            if is_full:
                self._full_push_seen = True
                self._pushes += 1
            else:
                self._deltas += 1
        return is_full

    @property
    def known(self) -> bool:
        return self._full_push_seen

    @property
    def full_pushes(self) -> int:
        return self._pushes

    @property
    def deltas(self) -> int:
        return self._deltas

    def snapshot(self) -> dict[str, Any]:
        """The merged state. Raises while UNKNOWN, like every other accessor."""
        self._require()
        with self._lock:
            return json.loads(json.dumps(self._data))

    def _require(self) -> dict[str, Any]:
        if not self._full_push_seen:
            raise TelemetryUnknown(
                f"no full push has been merged yet, so the printer's state is UNKNOWN "
                f"({self._deltas} delta(s) seen). A delta carries only what changed, so a "
                f"defaulted read of one reports gcode_state='IDLE' and mc_percent=0 about a "
                f"printer that may well be mid-print. Publish `pushall` and wait for a message "
                f"with msg == 0 before reading anything."
            )
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._require().get(key, default)

    # -- the fields callers actually read -------------------------------------------------

    @property
    def gcode_state(self) -> str:
        return str(self._require().get("gcode_state", "") or "")

    @property
    def print_error(self) -> int:
        return int(self._require().get("print_error", 0) or 0)

    @property
    def subtask_name(self) -> str:
        return str(self._require().get("subtask_name", "") or "")

    @property
    def gcode_file(self) -> str:
        return str(self._require().get("gcode_file", "") or "")

    @property
    def percent(self) -> int:
        return int(self._require().get("mc_percent", 0) or 0)

    @property
    def layer_num(self) -> int:
        return int(self._require().get("layer_num", 0) or 0)

    @property
    def total_layer_num(self) -> int:
        return int(self._require().get("total_layer_num", 0) or 0)

    @property
    def remaining_min(self) -> int | None:
        """``mc_remaining_time``, which is in **MINUTES** (correction C10).

        ``None`` when the field is absent, and never ``0``. pybambu's ``get_end_time`` does
        ``timedelta(minutes=remaining_time)``; reading it as seconds is a silent 60x error, and
        defaulting an absent field to zero reports "done in a moment" about an unknown.
        """
        data = self._require()
        if "mc_remaining_time" not in data:
            return None
        return int(data["mc_remaining_time"] or 0)

    @property
    def remaining_s(self) -> int | None:
        minutes = self.remaining_min
        return None if minutes is None else minutes * 60

    @property
    def nozzle_type(self) -> str:
        return str(self._require().get("nozzle_type", "") or "")

    @property
    def nozzle_diameter(self) -> str:
        return str(self._require().get("nozzle_diameter", "") or "")

    @property
    def nozzle_temper(self) -> float:
        return float(self._require().get("nozzle_temper", 0.0) or 0.0)

    @property
    def bed_temper(self) -> float:
        return float(self._require().get("bed_temper", 0.0) or 0.0)

    @property
    def filament_at_extruder(self) -> bool:
        """``hw_switch_state`` -- the toolhead's own filament sensor.

        The single most load-bearing field in this module. It stayed **0** through a print that
        reported ``FINISH`` at 100% over 30 of 30 layers, which is what "the printer traced the
        toolpath through air" looks like in telemetry. Nothing else dissented.
        """
        return bool(self._require().get("hw_switch_state", 0))

    @property
    def tray_target(self) -> int | None:
        """The AMS tray the printer is trying to load. ``None`` means it resolved none.

        ``255`` is the "nothing selected" sentinel, and it is what this field reads when an
        ``ams_mapping`` was sent without its ``ams_mapping2`` companion -- the firmware accepts
        the job and silently resolves no tray at all.
        """
        value = (self._require().get("ams") or {}).get("tray_tar")
        try:
            tray = int(value)
        except (TypeError, ValueError):
            return None
        return None if tray == 255 else tray

    @property
    def ams_slots(self) -> list[AmsSlot]:
        return live_ams_slots(self._require())

    def __str__(self) -> str:
        if not self.known:
            return "printer  state UNKNOWN (no full push merged yet)"
        remaining = "unknown" if self.remaining_min is None else f"{self.remaining_min} min"
        return (
            f"printer  {self.gcode_state}   {self.percent}%   "
            f"layer {self.layer_num}/{self.total_layer_num}   remaining {remaining}   "
            f"nozzle {self.nozzle_temper:.1f} C   bed {self.bed_temper:.1f} C   "
            f"job {self.subtask_name!r}"
        )


# --- AMS reconciliation (ADR-16) ------------------------------------------------------------------


@dataclass(frozen=True)
class AmsSlot:
    """One physically loaded spool, as the printer reports it."""

    slot: int
    kind: str  # "ams" | "external"
    material: str | None  # None == the printer could not read it
    color: str | None
    tray_info_idx: str

    def __str__(self) -> str:
        material = self.material or "UNREADABLE"
        colour = f" #{self.color}" if self.color else ""
        return f"slot {self.slot}  {self.kind:<8} {material}{colour}  ({self.tray_info_idx or '-'})"


def _normalise_colour(value: Any) -> str | None:
    """``'#1e6fd9'`` and ``'FFF144FF'`` onto the same six upper-case hex digits."""
    text = str(value or "").strip().lstrip("#").upper()
    if len(text) < 6:
        return None
    text = text[:6]
    return text if all(c in "0123456789ABCDEF" for c in text) else None


def _normalise_material(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def live_ams_slots(telemetry: dict[str, Any] | PrinterState) -> list[AmsSlot]:
    """Extract the loaded spools from merged telemetry. Pure; no I/O.

    Slot numbers are **global**: ``ams_id * 4 + tray_id``, so a second AMS unit occupies 4-7. The
    external spool is ``vt_tray`` and is reported at its own id (254), which is deliberately not
    an AMS slot number -- it is fed by hand and ``ams_mapping`` refuses to map to it.
    """
    if isinstance(telemetry, PrinterState):
        telemetry = telemetry.snapshot()
    slots: list[AmsSlot] = []

    ams = telemetry.get("ams")
    units = (ams or {}).get("ams") or [] if isinstance(ams, dict) else []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        try:
            unit_id = int(unit.get("id", 0) or 0)
        except (TypeError, ValueError):
            continue
        for tray in unit.get("tray") or []:
            if not isinstance(tray, dict):
                continue
            try:
                tray_id = int(tray.get("id", 0) or 0)
            except (TypeError, ValueError):
                continue
            slots.append(
                AmsSlot(
                    slot=unit_id * _TRAYS_PER_AMS + tray_id,
                    kind="ams",
                    material=_normalise_material(tray.get("tray_type")),
                    color=_normalise_colour(tray.get("tray_color")),
                    tray_info_idx=str(tray.get("tray_info_idx", "") or ""),
                )
            )

    vt = telemetry.get("vt_tray")
    if isinstance(vt, dict) and vt:
        try:
            vt_id = int(vt.get("id", EXTERNAL_SPOOL_IDS[0]) or EXTERNAL_SPOOL_IDS[0])
        except (TypeError, ValueError):
            vt_id = EXTERNAL_SPOOL_IDS[0]
        slots.append(
            AmsSlot(
                slot=vt_id,
                kind="external",
                material=_normalise_material(vt.get("tray_type")),
                color=_normalise_colour(vt.get("tray_color")),
                tray_info_idx=str(vt.get("tray_info_idx", "") or ""),
            )
        )
    return sorted(slots, key=lambda s: s.slot)


@dataclass(frozen=True)
class AmsFinding:
    """One disagreement between ``filaments.json`` and the printer."""

    slot: int
    severity: str
    kind: str
    expected: str
    actual: str
    message: str

    def __str__(self) -> str:
        return (
            f"{self.severity:<7} slot {self.slot:<3} {self.kind:<10} "
            f"claimed {self.expected!r}   loaded {self.actual!r}   {self.message}"
        )


@dataclass(frozen=True)
class AmsReport:
    """What the inventory claims versus what is loaded, and which of it gates.

    The severity vocabulary is ``dfm.py``'s, reused rather than reinvented: only ``BLOCKER``
    gates, a ``WARNING`` is reported with both values, and a ``NOTE`` is a difference nobody
    should be refused over.
    """

    findings: list[AmsFinding] = field(default_factory=list)
    used_slots: tuple[int, ...] = ()
    live: tuple[AmsSlot, ...] = ()

    def _of(self, severity: str) -> list[AmsFinding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def blockers(self) -> list[AmsFinding]:
        from threedp import dfm

        return self._of(dfm.BLOCKER)

    @property
    def warnings(self) -> list[AmsFinding]:
        from threedp import dfm

        return self._of(dfm.WARNING)

    @property
    def notes(self) -> list[AmsFinding]:
        from threedp import dfm

        return self._of(dfm.NOTE)

    @property
    def passed(self) -> bool:
        return not self.blockers

    def count(self, severity: str | None = None) -> int:
        from threedp import dfm

        if severity is None:
            return len(self.findings)
        if severity not in dfm.SEVERITIES:
            raise PrinterError(
                f"unknown severity {severity!r}; valid severities: {list(dfm.SEVERITIES)}"
            )
        return len(self._of(severity))

    def __str__(self) -> str:
        used = ", ".join(str(s) for s in self.used_slots) or "none"
        verdict = (
            "inventory agrees with the printer"
            if self.passed
            else (f"{len(self.blockers)} BLOCKER(s)")
        )
        lines = [
            f"ams      {verdict}, {len(self.warnings)} warning(s), {len(self.notes)} note(s)   "
            f"(slots this print uses: {used})"
        ]
        lines += [str(f) for f in self.findings]
        lines += [f"        {s}" for s in self.live]
        return "\n".join(lines)


def reconcile_ams(
    live: dict[str, Any] | PrinterState | list[AmsSlot],
    inventory: list[dict[str, Any]] | None = None,
    used_slots: list[int] | tuple[int, ...] = (),
) -> AmsReport:
    """Check ``profiles/filaments.json`` against what is physically loaded (ADR-16).

    This is the same move ``intent.json`` makes for geometry: a hand-written claim is checked
    against a measurement of the real thing. It exists because the claim had already drifted --
    four of five slots disagreed with the printer, and ``ams_mapping`` converted that into a
    confidently wrong slot with no exception and no warning. Asked for ABS it answered slot 3;
    slot 3 holds green PETG, and an ABS process would have been driven into it at 255 °C.

    * A **material** mismatch in a slot this print uses is a ``BLOCKER``.
    * The same mismatch in an unused slot is a ``WARNING``: reported with both values, not a gate.
    * A **colour**-only difference is a ``NOTE``. Refusing on colour would make this useless
      inside a week, and a colour cannot melt a hotend.

    ``live`` is already-fetched telemetry -- **no I/O happens here**, exactly as ``dfm.evaluate``
    takes already-taken measurements. That is what makes it testable against the captured push.
    ``ams_mapping()`` gains no printer knowledge either; this runs *before* it.
    """
    from threedp import dfm, slicer

    if isinstance(live, (dict, PrinterState)):
        live_slots = live_ams_slots(live)
    else:
        live_slots = sorted(live, key=lambda s: s.slot)
    if inventory is None:
        inventory = slicer.load_inventory()

    used = tuple(sorted({int(s) for s in used_slots}))
    by_slot = {s.slot: s for s in live_slots}
    external = [s for s in live_slots if s.kind == "external"]
    findings: list[AmsFinding] = []

    def gate(slot: int) -> str:
        return dfm.BLOCKER if slot in used else dfm.WARNING

    matched: set[int] = set()
    for entry in inventory:
        claimed_slot = int(entry.get("slot", -1))
        claimed_material = _normalise_material(entry.get("material")) or "?"
        claimed_colour = _normalise_colour(entry.get("color"))

        if str(entry.get("type")) == "external":
            actual = external[0] if external else None
        else:
            actual = by_slot.get(claimed_slot)

        if actual is None:
            findings.append(
                AmsFinding(
                    slot=claimed_slot,
                    severity=gate(claimed_slot),
                    kind="missing",
                    expected=claimed_material,
                    actual="(no spool)",
                    message=(
                        "the inventory claims a spool here and the printer reports none; nothing "
                        "would be fed from this slot"
                    ),
                )
            )
            continue
        matched.add(actual.slot)

        if actual.material is None:
            findings.append(
                AmsFinding(
                    slot=claimed_slot,
                    severity=gate(claimed_slot),
                    kind="unreadable",
                    expected=claimed_material,
                    actual="(unreadable)",
                    message=(
                        "the printer cannot read this spool's material -- a non-Bambu spool "
                        "reports tray_info_idx poorly or not at all. Unknown is not agreement; "
                        "load a spool the AMS can read, or print from the external holder"
                    ),
                )
            )
            continue

        if actual.material != claimed_material:
            findings.append(
                AmsFinding(
                    slot=claimed_slot,
                    severity=gate(claimed_slot),
                    kind="material",
                    expected=claimed_material,
                    actual=actual.material,
                    message=(
                        f"profiles/{INVENTORY_FILE} is out of date. Printing a {claimed_material} "
                        f"process into {actual.material} is a hotend temperature applied to the "
                        f"wrong polymer, not a colour mistake"
                    ),
                )
            )
            continue

        if claimed_colour and actual.color and claimed_colour != actual.color:
            findings.append(
                AmsFinding(
                    slot=claimed_slot,
                    severity=dfm.NOTE,
                    kind="colour",
                    expected=f"#{claimed_colour}",
                    actual=f"#{actual.color}",
                    message="material agrees; only the colour has changed",
                )
            )

    for slot in live_slots:
        if slot.slot in matched:
            continue
        findings.append(
            AmsFinding(
                slot=slot.slot,
                severity=dfm.BLOCKER if slot.slot in used else dfm.NOTE,
                kind="extra",
                expected="(not in the inventory)",
                actual=slot.material or "(unreadable)",
                message=(
                    f"the printer reports a spool in a slot profiles/{INVENTORY_FILE} does not "
                    f"describe"
                ),
            )
        )

    order = {dfm.BLOCKER: 0, dfm.WARNING: 1, dfm.NOTE: 2}
    findings.sort(key=lambda f: (order.get(f.severity, 9), f.slot))
    return AmsReport(findings=findings, used_slots=used, live=tuple(live_slots))


# --- the MQTT link --------------------------------------------------------------------------------


class PrinterLink:
    """A subscribed MQTT session: merged telemetry in, commands out.

    **Nothing about the reply channel is filtered by field name.** ``project_file`` is answered by
    an echo of the command with ``err_code`` appended -- no ``result``, no ``reason``, no
    ``errno``. The first two readings of that spike whitelisted exactly those three names, saw
    nothing, and concluded the printer had accepted the job in silence; a malformed-command
    control probe then appeared to confirm it, because that produced no *matching* field either.
    Two mutually reinforcing wrong readings from one filtering bug. So every non-``push_status``
    report is kept whole and inspected afterwards.

    The link is **never torn down while a dispatch is settling**: an ack can exceed 15 s, and a
    client that reconnects mid-dispatch induces a ``0500-4003`` parse error on the printer (S25).
    """

    def __init__(
        self,
        creds: Credentials | None = None,
        config: dict[str, Any] | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = load_conn_config() if config is None else config
        self.credentials = credentials() if creds is None else creds
        self.state = PrinterState()
        self._client = client
        self._replies: deque[dict[str, Any]] = deque(maxlen=256)
        self._undecodable = 0
        # `_replies` is appended to by paho's network thread and read by whoever is polling
        # `wait_for`. `list(deque)` raises "deque mutated during iteration" if an append lands
        # mid-copy, which is exactly the hot path during a dispatch: a reply every second or so
        # against a poll every 0.25 s.
        self._replies_lock = threading.Lock()
        self._sequence = 0
        self._last_pushall = 0.0
        self._connected = threading.Event()
        self._closed = False
        mqtt_config = self.config.get("mqtt", {})
        serial = self.credentials.serial
        self.request_topic = str(mqtt_config["request_topic"]).format(serial=serial)
        self.report_topic = str(mqtt_config["report_topic"]).format(serial=serial)

    # -- lifecycle -------------------------------------------------------------------------

    def __enter__(self) -> PrinterLink:
        self.connect()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def connect(self, timeout_s: float | None = None) -> PrinterLink:
        """Connect, subscribe, and wait for the broker to acknowledge the subscription."""
        mqtt_config = self.config.get("mqtt", {})
        if timeout_s is None:
            timeout_s = float(mqtt_config.get("connect_timeout_s", 20))

        if self._client is None:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            client.username_pw_set("bblp", self.credentials.access_code)
            client.tls_set_context(_tls_context(self.config))
            self._client = client
        client = self._client
        client.on_connect = self._on_connect
        client.on_message = self._on_message

        # Teardown is armed BEFORE the first blocking wait: a failure inside connect() must not
        # leave a network thread running with nobody holding a reference to stop it.
        try:
            client.connect(
                self.credentials.ip,
                int(mqtt_config.get("port", 8883)),
                int(mqtt_config.get("keepalive_s", 30)),
            )
            client.loop_start()
        except OSError as exc:
            self.close()
            raise PrinterError(
                f"could not reach the printer's MQTT port at {self.credentials.ip}:"
                f"{mqtt_config.get('port', 8883)} -- {type(exc).__name__}: {exc}"
            ) from exc

        if not self._connected.wait(timeout_s):
            self.close()
            raise PrinterError(
                f"connected to the MQTT port but the broker did not acknowledge within "
                f"{timeout_s:g}s. The access code is {len(self.credentials.access_code)} "
                f"characters; it CHANGES when Developer Mode is toggled."
            )
        return self

    def close(self) -> None:
        """Idempotent teardown. Safe to call from an error path and from ``__exit__``.

        The network thread is stopped whoever *constructed* the client, because this class is what
        started it. Ownership decides who builds the object; it does not decide who is holding a
        running loop when an exception unwinds.
        """
        if self._closed:
            return
        self._closed = True
        client = self._client
        if client is None:
            return
        for step in (client.loop_stop, client.disconnect):
            try:
                step()
            except Exception:  # noqa: BLE001 - teardown must not raise over the original error
                pass

    # -- paho callbacks --------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        client.subscribe(self.report_topic)
        self._connected.set()

    def _on_message(self, client, userdata, message) -> None:
        try:
            payload = json.loads(message.payload)
        except (TypeError, ValueError, UnicodeDecodeError):
            # Counted, not dropped silently. "The printer said nothing" and "the printer said
            # something I could not parse" are different facts and this module has already been
            # bitten once by conflating them.
            with self._replies_lock:
                self._undecodable += 1
            return
        self.handle(payload)

    def handle(self, payload: dict[str, Any]) -> None:
        """Route one decoded report. Public so a fake broker can drive it with no network."""
        if not isinstance(payload, dict):
            with self._replies_lock:
                self._undecodable += 1
            return
        for section, body in payload.items():
            if not isinstance(body, dict):
                continue
            if section == "print" and body.get("command") == "push_status":
                self.state.merge(body)
                continue
            # Everything else is kept WHOLE -- no whitelist of ack field names. See the class
            # docstring; this single line is the fix for S18's first two readings.
            with self._replies_lock:
                self._replies.append({"_section": section, **body})

    # -- reading ---------------------------------------------------------------------------

    @property
    def undecodable(self) -> int:
        with self._replies_lock:
            return self._undecodable

    def replies(
        self, command: str | None = None, sequence_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Every captured non-status reply, newest last, optionally narrowed."""
        with self._replies_lock:
            found = list(self._replies)
        if command is not None:
            found = [r for r in found if r.get("command") == command]
        if sequence_id is not None:
            found = [r for r in found if str(r.get("sequence_id", "")) == str(sequence_id)]
        return found

    def wait_for(self, predicate, timeout_s: float, poll_interval_s: float = 0.25):
        """Poll ``predicate()`` until it returns something truthy, or the deadline passes.

        Polling rather than a condition variable, and **never a reconnect**: the failure this
        avoids is S25's, where a client that tears the session down on a slow ack induces a parse
        error on the printer. A missed deadline returns ``None``; the caller decides what that
        means.
        """
        deadline = time.monotonic() + float(timeout_s)
        while True:
            found = predicate()
            if found:
                return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(poll_interval_s)

    # -- writing ---------------------------------------------------------------------------

    def next_sequence_id(self) -> str:
        self._sequence += 1
        return str(self._sequence)

    def publish(self, payload: dict[str, Any]) -> None:
        if self._client is None:
            raise PrinterError("the link is not connected")
        self._client.publish(self.request_topic, json.dumps(payload))

    def pushall(self, force: bool = False) -> bool:
        """Ask for a full push. Rate-limited; returns ``False`` when the request was withheld.

        Bambu's own documentation warns against polling the P1 faster than five minutes. A caller
        that "makes it reliable" by pushing every second degrades the printer, so the interval
        lives in the config with its reason and this refuses to beat it.
        """
        interval = float(self.config.get("mqtt", {}).get("pushall_min_interval_s", 300))
        now = time.monotonic()
        if not force and self._last_pushall and (now - self._last_pushall) < interval:
            return False
        self._last_pushall = now
        self.publish({"pushing": {"sequence_id": self.next_sequence_id(), "command": "pushall"}})
        return True

    def wait_for_full_push(self, timeout_s: float | None = None) -> PrinterState:
        """Publish ``pushall`` and block until the state stops being UNKNOWN."""
        if timeout_s is None:
            timeout_s = float(self.config.get("mqtt", {}).get("full_push_timeout_s", 20))
        if not self.state.known:
            self.pushall()
        if not self.wait_for(lambda: self.state.known, timeout_s):
            raise TelemetryUnknown(
                f"no full push arrived within {timeout_s:g}s of `pushall`. The state stays "
                f"UNKNOWN rather than being defaulted to IDLE -- {self.state.deltas} delta(s) "
                f"were seen, and a delta is not a status."
            )
        return self.state


# --- dispatch (ADR-14) ------------------------------------------------------------------------


def resolve_url_scheme(config: dict[str, Any] | None = None) -> str:
    """The measured ``url`` template, or a refusal naming the pre-flight gate.

    S19 published eight ``project_file`` variants -- three-slash ``ftp:``, two-slash, ``file:``
    under two roots, ``/cache``, and a bare filename -- and every one returned ``0502-4007``,
    identically, *including a path that does not exist*. A file-or-path error cannot be invariant
    across those, so the rejection happens **before the url is parsed**, and which form is correct
    is unknowable until Developer Mode is on. Permuting further is what S19 already did,
    exhaustively, to no effect.

    So there is no default here. Guessing would produce exactly the class of confident, plausible,
    wrong result this repository exists to refuse.
    """
    config = load_conn_config() if config is None else config
    scheme = config.get("dispatch", {}).get("url_scheme")
    if not scheme:
        candidates = [
            c.get("template") for c in config.get("dispatch", {}).get("url_scheme_candidates", [])
        ]
        raise PreFlightGateOpen(
            f"profiles/{CONFIG_FILE} carries no measured dispatch.url_scheme, so there is nothing "
            f"to send. This is not a missing default -- it is an open measurement. Every one of "
            f"{candidates} was rejected identically with 0502-4007 before the url was parsed, so "
            f"the correct form cannot be determined until LAN Developer Mode is enabled on the "
            f"printer. Enable it (Settings -> WLAN -> LAN Only Mode -> Yes, power-cycle, then "
            f"Developer Mode -> Enable), update .env with the NEW access code, run "
            f"`pytest -m printer -k url_scheme`, and write the winner into "
            f"dispatch.url_scheme with a source naming that measurement."
        )
    if "{name}" not in str(scheme):
        raise PrinterNotConfigured(
            f"dispatch.url_scheme={scheme!r} has no '{{name}}' placeholder, so the uploaded "
            f"filename would never appear in the url"
        )
    return str(scheme)


def ams_mapping_fields(mapping: list[int] | None) -> tuple[list[int], list[dict[str, int]]]:
    """Bambu's ``ams_mapping`` **and** its companion ``ams_mapping2``.

    Measured 2026-08-03, and it cost a nine-minute print of nothing: sending ``use_ams: true``
    with a flat ``ams_mapping: [0]`` and **no ``ams_mapping2``** makes the firmware accept the
    job, never resolve a target tray (``tray_tar`` stays ``255``), never load filament, and print
    the whole toolpath in air. There is no error anywhere in the telemetry.

    ``bambu_networking.hpp`` declares ``ams_mapping`` and ``ams_mapping2`` side by side, and the
    firmware needs the second to turn a global tray number into a unit and a slot. The flat array
    stays the global ``ams_id * 4 + slot_id``; ``ams_mapping2`` spells that out.

    The external spool is the exception in both: the flat entry is ``-1`` (raw ``254``/``255``
    makes the firmware target AMS tray 0 instead) and ``ams_mapping2`` carries
    ``{"ams_id": 255, "slot_id": 0}``.

    Scoped to this repository's one single-nozzle P1S. AMS-HT and dual-nozzle racks have their own
    conventions and are deliberately not guessed at here.
    """
    flat: list[int] = []
    detailed: list[dict[str, int]] = []
    for entry in mapping or []:
        tray = int(entry)
        if tray < 0:
            flat.append(-1)
            detailed.append({"ams_id": 255, "slot_id": 255})
        elif tray in EXTERNAL_SPOOL_IDS:
            flat.append(-1)
            detailed.append({"ams_id": 255, "slot_id": 0})
        elif tray >= _TRAYS_PER_AMS * 4:
            raise PrinterNotConfigured(
                f"AMS slot {tray} is outside the range this wrapper knows how to describe. "
                f"Global slots are ams_id * 4 + slot_id for regular AMS units; AMS-HT and "
                f"dual-nozzle racks use different conventions and are not guessed at here."
            )
        else:
            flat.append(tray)
            detailed.append({"ams_id": tray // _TRAYS_PER_AMS, "slot_id": tray % _TRAYS_PER_AMS})
    return flat, detailed


def project_file_command(
    remote_name: str,
    subtask_name: str,
    sequence_id: str,
    url_scheme: str,
    md5: str = "",
    use_ams: bool = False,
    ams_mapping: list[int] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the ``project_file`` payload. Pure -- nothing is published here.

    ``task_id`` / ``project_id`` / ``subtask_id`` come from the config as the **string** ``"0"``
    and stay that way (correction C6): firmware ``01.10.00.00`` clamps task-identity fields to
    2^31-1, so an epoch-ms id collides and the printer treats a new dispatch as a continuation of
    the previous FAILED job. Do not "improve" it into a timestamp.
    """
    config = load_conn_config() if config is None else config
    defaults = dict(config.get("dispatch", {}).get("project_file_defaults", {}))
    payload = {
        **defaults,
        "sequence_id": str(sequence_id),
        "command": "project_file",
        "subtask_name": subtask_name,
        # `file` is the bare filename beside the url. Bambu Studio sends both.
        "file": remote_name,
        "url": url_scheme.format(name=remote_name),
        "md5": md5 or str(defaults.get("md5", "")),
        "use_ams": bool(use_ams),
    }
    if use_ams and not ams_mapping:
        raise PrinterNotConfigured(
            "use_ams is set with no ams_mapping. The firmware would accept the job, resolve no "
            "target tray, load no filament, and print the toolpath through air -- measured, with "
            "a FINISH at 100% and no object. Pass slicer.ams_mapping(...) or set use_ams=False."
        )
    flat, detailed = ams_mapping_fields(ams_mapping)
    payload["ams_mapping"] = flat if flat else ""
    if detailed:
        # NOT optional. Without it tray_tar stays 255 and the print is made of air.
        payload["ams_mapping2"] = detailed
    return {"print": payload}


@dataclass(frozen=True)
class DispatchEvidence:
    """Everything ADR-14 judges, collected in one place so the judgement is a pure function."""

    upload: UploadResult
    echo: dict[str, Any] | None
    sequence_id: str
    subtask_name: str
    gcode_state_before: str
    gcode_state_after: str
    printer_subtask_name: str
    printer_gcode_file: str
    settle_s: float


@dataclass(frozen=True)
class PrintJob:
    """An accepted **dispatch**. Every fact here survived all four ADR-14 conditions.

    **It is not a finished part, and it is not even a started one.** Measured on this machine on
    2026-08-02: a dispatch satisfying all four conditions reached ``PREPARE`` and then returned to
    ``IDLE`` having laid **zero of thirty layers**, with ``print_error 0500-8003`` and an empty
    ``hms``. ``PREPARE`` is transient by nature -- the printer is heating, homing and levelling,
    and it can abandon the job from there, or a human can stop it at the machine.

    So what the four conditions establish is exactly this: *the file arrived intact, the printer
    accepted the command, and it began preparing our job rather than someone else's.* Anything
    further is :func:`watch`'s to report, and reporting a `PrintJob` as "printing" is the same
    class of claim this whole module exists to refuse.
    """

    subtask_name: str
    remote: str
    size_bytes: int
    md5: str
    sequence_id: str
    gcode_state: str
    started_from: str
    settle_s: float
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __str__(self) -> str:
        return (
            f"dispatch {self.subtask_name!r}   ACCEPTED, printer is {self.gcode_state} "
            f"(was {self.started_from})   {self.size_bytes} bytes at {self.remote}   "
            f"md5 {self.md5[:8]}...   after {self.settle_s:.1f} s\n"
            f"         this is an accepted dispatch, NOT a finished print -- "
            f"printer.watch() reports the outcome"
        )


def _err_code_message(err_code: int, config: dict[str, Any]) -> str:
    known = config.get("err_codes", {}).get(str(err_code))
    if known:
        return (
            f"err_code {err_code} ({known.get('code')}): {known.get('meaning')}. "
            f"{known.get('action')}"
        )
    return (
        f"err_code {err_code} (0x{err_code:08X} = "
        f"{err_code >> 16:04X}-{err_code & 0xFFFF:04X}), which is not a code this wrapper knows. "
        f"The echo is reported verbatim rather than summarised, because summarising an "
        f"unrecognised refusal is how a refusal becomes a timeout."
    )


def accept_dispatch(evidence: DispatchEvidence, config: dict[str, Any] | None = None) -> PrintJob:
    """Apply ADR-14's four conditions to a finished dispatch, or raise :class:`DispatchRejected`.

    Each condition alone was measured being satisfied by a dispatch that never started:

    1. **The upload landed whole.** ``226``, the byte count read back off the printer, *and* the
       file hashing to what we sent when it is downloaded again. A ``226`` with a skipped
       ``voidresp()`` truncates and the printer throws ``0500-C010``; and a byte count is the
       filesystem's claim about a file rather than the file, which stops being a distinction
       without a difference the moment the SD card starts failing.
    2. **The echo carries no ``err_code``.** ``project_file`` is answered by an echo of the
       command, not by an ack, so silence here means *the listener is broken*, not that the
       printer consented. ``84033543`` is the Developer-Mode refusal and is named as such.
    3. **``gcode_state`` left IDLE.** The only positive evidence a job started, and the condition
       the spike's "successful" dispatch actually failed while satisfying 1 and 2.
    4. **The printer's own job name matches what we sent**, and it was idle before. Otherwise a
       printer that was *already busy* satisfies condition 3 and we congratulate ourselves on
       someone else's print.

    Separated from :func:`dispatch` so the gate can be driven against fixtures with no printer --
    the same split as ``slicer.accept_slice``, and for the same reason.
    """
    config = load_conn_config() if config is None else config
    dispatch_config = config.get("dispatch", {})
    idle_states = {str(s).upper() for s in dispatch_config.get("idle_states", ["IDLE"])}

    # 1. the upload
    upload_result = evidence.upload
    if not str(upload_result.response).strip().startswith("226"):
        raise DispatchRejected(
            f"condition 1 (the upload landed whole) failed: the transfer replied "
            f"{upload_result.response.strip()!r} rather than 226. Nothing was published to the "
            f"printer; the file on the SD card is not trustworthy and should be re-uploaded."
        )
    if upload_result.remote_md5 is not None and upload_result.remote_md5 != upload_result.md5:
        raise DispatchRejected(
            f"condition 1 (the upload landed whole) failed: {upload_result.remote} is "
            f"{upload_result.size_bytes} bytes on the printer as expected, but reading it back "
            f"hashes to {upload_result.remote_md5} instead of {upload_result.md5}. The directory "
            f"entry is right and the contents are not, which is what a failing SD card looks "
            f"like. Do not start this; check the card."
        )
    if upload_result.remote_size_bytes != upload_result.size_bytes:
        raise DispatchRejected(
            f"condition 1 (the upload landed whole) failed: {upload_result.size_bytes} bytes were "
            f"sent and the printer lists {upload_result.remote_size_bytes} at "
            f"{upload_result.remote}. A 226 on its own is not evidence -- a transfer whose "
            f"voidresp() is skipped truncates silently, and the printer answers 0500-C010 on a "
            f"file that looks perfect locally. Re-upload; do not start this."
        )

    # 2. the echo -- captured whole, never filtered by field name
    echo = evidence.echo
    if echo is None:
        raise DispatchRejected(
            f"condition 2 (the printer answered) failed: no reply carrying sequence_id "
            f"{evidence.sequence_id!r} arrived within the window. Measured: a refusal comes back "
            f"in about a second as an echo of the command with err_code appended, so genuine "
            f"silence points at the *link* -- wrong serial in the report topic, or the "
            f"subscription never established -- rather than at the printer thinking about it."
        )
    err_code = echo.get("err_code") or 0
    if err_code:
        raise DispatchRejected(
            f"condition 2 (the printer answered without an error) failed. "
            f"{_err_code_message(int(err_code), config)}\nThe echo, whole: {json.dumps(echo)}"
        )

    # 4. checked before 3, because "already busy" explains a non-IDLE state and must not be
    # allowed to masquerade as our job starting.
    before = str(evidence.gcode_state_before or "").upper()
    if not before:
        raise DispatchRejected(
            "condition 4 (this is our job) failed: the printer's state before the dispatch is "
            "UNKNOWN, so there is nothing to compare a state change against. A printer that was "
            "already RUNNING satisfies condition 3 for free, and accepting on that basis reports "
            "someone else's print as ours. Wait for a full push before dispatching (ADR-17)."
        )
    if before not in idle_states:
        raise DispatchRejected(
            f"condition 4 (this is our job) failed: the printer was {before} before the dispatch, "
            f"so any state change afterwards is not evidence that *our* file started. Wait for "
            f"the current job to finish."
        )
    reported = evidence.printer_subtask_name or evidence.printer_gcode_file
    if evidence.subtask_name and reported and evidence.subtask_name not in reported:
        raise DispatchRejected(
            f"condition 4 (this is our job) failed: we sent {evidence.subtask_name!r} and the "
            f"printer reports it is running {reported!r}. Accepting this would report someone "
            f"else's print as ours."
        )

    # 3. the only positive evidence anything started
    after = str(evidence.gcode_state_after or "").upper()
    if not after:
        raise DispatchRejected(
            "condition 3 (a job started) failed: the printer reported no gcode_state at all "
            "after the dispatch. UNKNOWN is not IDLE and it is not RUNNING either (ADR-17)."
        )
    if after in idle_states:
        raise DispatchRejected(
            f"condition 3 (a job started) failed: gcode_state is still {after} "
            f"{evidence.settle_s:.0f} s after the dispatch, with the upload complete and the echo "
            f"carrying no err_code. This is the exact shape of the spike's 'successful' dispatch "
            f"that printed nothing: conditions 1 and 2 satisfied, and no job. Check that the url "
            f"scheme in profiles/{CONFIG_FILE} is the measured one for this firmware."
        )

    return PrintJob(
        subtask_name=evidence.subtask_name,
        remote=upload_result.remote,
        size_bytes=upload_result.size_bytes,
        md5=upload_result.md5,
        sequence_id=evidence.sequence_id,
        gcode_state=after,
        started_from=before or "UNKNOWN",
        settle_s=evidence.settle_s,
        raw=dict(echo),
    )


@dataclass(frozen=True)
class PrintOutcome:
    """How a dispatched job actually ended. The thing :class:`PrintJob` deliberately is not."""

    job: PrintJob
    state: str
    layers: int
    total_layers: int
    percent: int
    print_error: int
    elapsed_s: float
    reason: str = ""
    filament_seen: bool = False
    tray_targeted: int | None = None

    @property
    def finished(self) -> bool:
        """``FINISH`` **and** filament actually passed through the extruder.

        The second half is not belt-and-braces. Measured 2026-08-03: ``FINISH``, ``100%``,
        ``30/30`` layers, ``print_error 0``, empty ``hms`` -- and no object, because
        ``hw_switch_state`` was ``0`` from start to end. Every field the printer offers agreed
        that the print had succeeded. Only the filament sensor knew.
        """
        return self.state == "FINISH" and self.filament_seen

    def __str__(self) -> str:
        verdict = "FINISHED" if self.finished else "NO PART"
        return (
            f"print    {self.job.subtask_name!r}   {verdict}   printer said {self.state}   "
            f"layer {self.layers}/{self.total_layers}   {self.percent}%   "
            f"filament at the extruder: {'yes' if self.filament_seen else 'NEVER'}   "
            f"after {self.elapsed_s / 60:.1f} min"
            + (f"\n         {self.reason}" if self.reason else "")
        )


def watch(
    link: PrinterLink,
    job: PrintJob,
    timeout_s: float = 3600.0,
    poll_interval_s: float = 10.0,
    on_sample=None,
) -> PrintOutcome:
    """Follow a dispatched job to its end and report what actually happened.

    Three endings, and **the third is the one that needs naming**:

    * ``FINISH`` **and filament was seen at the extruder** -- the part is on the plate. The second
      half is the whole point: measured 2026-08-03, a job reported ``FINISH`` at 100% over 30 of
      30 layers with ``print_error 0`` and an empty ``hms``, having never loaded any filament, and
      produced nothing. ``PrintOutcome.finished`` requires both.
    * ``FAILED`` -- the printer says so. Note that a *stopped* job also reports ``FAILED``, with
      ``print_error 0500-8003`` and an empty ``hms``; that is the record of a cancellation, not a
      fault, so the two are distinguished here rather than conflated.
    * **back to ``IDLE`` having printed nothing.** Measured: a dispatch that satisfied every
      ADR-14 condition reached ``PREPARE``, returned to ``IDLE`` at layer 0 of 30, and left no
      HMS entry at all. Code that stopped at :func:`accept_dispatch` would have reported that as
      a successful print, which is this repository's founding failure mode wearing a new hat.
    """
    idle_states = {"IDLE", "FINISH", "FAILED"}
    started = time.monotonic()
    saw_progress = False
    saw_filament = False
    targeted: int | None = None
    while True:
        elapsed_s = time.monotonic() - started
        state = link.state.gcode_state.upper() if link.state.known else ""
        layers = link.state.layer_num if link.state.known else 0
        saw_progress = saw_progress or layers > 0
        if link.state.known:
            # Sampled every pass and latched, because both are transient: filament is present
            # only while the sensor sees it, and tray_tar returns to 255 when the job ends.
            saw_filament = saw_filament or link.state.filament_at_extruder
            targeted = link.state.tray_target if targeted is None else targeted
        if on_sample is not None:
            on_sample(link.state, elapsed_s)
        if state in idle_states and elapsed_s > poll_interval_s:
            break
        if elapsed_s > timeout_s:
            return PrintOutcome(
                job=job,
                state=state or "UNKNOWN",
                layers=layers,
                total_layers=link.state.total_layer_num if link.state.known else 0,
                percent=link.state.percent if link.state.known else 0,
                print_error=link.state.print_error if link.state.known else 0,
                elapsed_s=elapsed_s,
                filament_seen=saw_filament,
                tray_targeted=targeted,
                reason=(
                    f"still {state or 'UNKNOWN'} after {timeout_s / 60:.0f} min; this is a report "
                    f"that the watch gave up, not that the print failed"
                ),
            )
        time.sleep(poll_interval_s)

    error = link.state.print_error
    layers = link.state.layer_num
    reason = ""
    if state == "FINISH" and not saw_filament:
        # THE headline measurement of this phase. Every field the printer publishes says the
        # print succeeded; the toolhead's filament sensor says nothing ever went through it.
        reason = (
            f"the printer reports FINISH at {link.state.percent}% over "
            f"{layers}/{link.state.total_layer_num} layers with print_error {error} and no HMS "
            f"entry -- and NO FILAMENT EVER REACHED THE EXTRUDER (hw_switch_state stayed 0 for "
            f"the whole run, ams tray_tar resolved to {targeted!r}). The machine traced the "
            f"toolpath through air. There is no part on the plate. The cause is NOT established "
            f"-- adding the ams_mapping2 companion field, which Bambu Studio sends and which was "
            f"missing here, did not make the printer resolve a tray -- so verify the AMS "
            f"physically fed rather than trusting any part of the printer's success report."
        )
    elif state == "IDLE" and not saw_progress:
        reason = (
            f"the printer accepted the job, entered PREPARE and returned to IDLE without laying "
            f"a single layer (0 of {link.state.total_layer_num}). print_error is "
            f"{error} (0x{error:08X}) and hms is empty, so the printer reports no fault -- "
            f"0500-8003 is the code for a CANCELLED job, which is what a stop at the machine "
            f"produces. Nothing was printed. Do not report this as a print."
        )
    elif state == "FAILED":
        reason = (
            f"print_error {error} (0x{error:08X}). 0500-8003 is a cancellation rather than a "
            f"fault; anything else is worth reading off the printer's own screen."
        )
    return PrintOutcome(
        job=job,
        state=state,
        layers=layers,
        total_layers=link.state.total_layer_num,
        percent=link.state.percent,
        print_error=error,
        elapsed_s=time.monotonic() - started,
        reason=reason,
        filament_seen=saw_filament,
        tray_targeted=targeted,
    )


def dispatch(
    path: str | Path,
    link: PrinterLink,
    use_ams: bool = True,
    ams_mapping: list[int] | None = None,
    subtask_name: str | None = None,
    inventory: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    reconcile: bool = True,
) -> PrintJob:
    """Upload a sliced 3MF and start it, or raise.

    Order is deliberate and each step refuses before the next becomes possible:

    1. the 3MF is checked for the things that make ``use_ams`` silently ineffective;
    2. the AMS inventory is reconciled against live telemetry (ADR-16) -- **a BLOCKER here stops
       the dispatch before anything is uploaded**, because the failure it prevents is an ABS
       process driven into PETG;
    3. the file is uploaded and its byte count read back;
    4. ``project_file`` is published and the reply captured whole;
    5. ADR-14's four conditions are applied.

    ``link`` is required rather than optional: a dispatch needs telemetry from *before* the
    upload, and a function that opened its own connection would have nowhere to have got it.
    """
    config = load_conn_config() if config is None else config
    from threedp import slicer

    parsed = assert_3mf_is_dispatchable(path)

    mapping = ams_mapping
    if use_ams and mapping is None:
        mapping = slicer.ams_mapping(parsed.materials, inventory)

    if reconcile:
        report = reconcile_ams(link.state, inventory, used_slots=mapping or ())
        if not report.passed:
            raise DispatchRejected(
                f"the AMS inventory does not describe what is loaded, in a slot this print uses. "
                f"Nothing was uploaded and nothing was published.\n{report}"
            )

    before = link.state.gcode_state
    result = upload(path, config=config, creds=link.credentials)

    sequence_id = link.next_sequence_id()
    name = subtask_name or parsed.path.stem
    command = project_file_command(
        remote_name=result.name,
        subtask_name=name,
        sequence_id=sequence_id,
        url_scheme=resolve_url_scheme(config),
        md5=result.md5,
        use_ams=use_ams,
        ams_mapping=mapping,
        config=config,
    )

    dispatch_config = config.get("dispatch", {})
    echo_timeout_s = float(dispatch_config.get("echo_timeout_s", 30))
    settle_s = float(dispatch_config.get("settle_s", 45))
    poll_s = float(dispatch_config.get("poll_interval_s", 0.25))
    idle_states = {str(s).upper() for s in dispatch_config.get("idle_states", ["IDLE"])}

    started = time.monotonic()
    link.publish(command)

    echoes = link.wait_for(
        lambda: link.replies(command="project_file", sequence_id=sequence_id),
        echo_timeout_s,
        poll_s,
    )
    echo = echoes[-1] if echoes else None

    # A refusal is in hand within about a second; there is no reason to sit out the full settle
    # window before reporting it. A *silent* echo still waits, because that is the case where the
    # job may genuinely be starting.
    if echo is None or not echo.get("err_code"):
        link.wait_for(
            lambda: link.state.known and link.state.gcode_state.upper() not in idle_states,
            settle_s,
            poll_s,
        )

    after = link.state.gcode_state if link.state.known else ""
    evidence = DispatchEvidence(
        upload=result,
        echo=echo,
        sequence_id=sequence_id,
        subtask_name=name,
        gcode_state_before=before,
        gcode_state_after=after,
        printer_subtask_name=link.state.subtask_name if link.state.known else "",
        printer_gcode_file=link.state.gcode_file if link.state.known else "",
        settle_s=time.monotonic() - started,
    )
    return accept_dispatch(evidence, config)

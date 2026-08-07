"""Capture the printer's MQTT traffic while somebody else drives it -- **step 3** of the bisect.

``PrinterLink`` subscribes to ``device/{serial}/report``, the telemetry the printer publishes. This
subclasses it to *also* subscribe to ``device/{serial}/request`` -- the topic Bambu Studio publishes
its commands on. If the broker grants that subscription, a print sent from Bambu Studio hands you
its exact ``project_file`` payload, and the diff against ``printer.project_file_command()`` is the
answer rather than another guess.

That is the whole point. ``ams_mapping2`` was missing, was added, and the next dispatch still
resolved no tray -- so it was *a* defect and not *the* defect. Permuting payload fields against a
machine that answers every variant identically is how two hours disappear looking like progress;
the pre-flight url matrix already demonstrated that here. A known-good payload from the vendor's
own client ends the guessing.

**Whether the broker allows it is unknown and this script tells you which.** ``on_subscribe``
reports the granted QoS per topic, and a refusal arrives as a failure reason code rather than as
silence -- so a denied request-topic subscription is reported as denied, not as "Studio sent
nothing". That distinction is the same one this module learned the hard way: a refusal that arrives
as an echo of your own command reads as silence to a listener that expects an ack.

Nothing here opens a socket, publishes a command, or starts a print. The transport is
``threedp.printer.PrinterLink``, the one module permitted to reach a printer (ADR-15). A
``pushall`` is published only if you pass ``--pushall``, and it is the only publish this file can
ever make.

Usage::

    uv run python tools/ams_capture.py --seconds 900 --out ams-capture.jsonl

Then, in Bambu Studio, slice something small, assign it to an AMS slot, and send it. Watch this
script's live transitions while it runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from threedp import printer

NOTHING_SELECTED = 255


class RequestTopicCapture(printer.PrinterLink):
    """A ``PrinterLink`` that also listens on the request topic and journals every frame.

    Two private hooks are overridden (``_on_connect``, ``_on_message``). That is a deliberate
    trade: the alternative is a second paho client, and "there is exactly one way out to a printer"
    is a rule worth more than the mild fragility of subclassing. Both overrides call ``super()``,
    so telemetry still flows into ``PrinterState`` exactly as it does in production.
    """

    def __init__(self, sink, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sink = sink
        self._sink_lock = threading.Lock()
        self.frames = 0
        self.request_frames = 0
        self.subscriptions: dict[int, str] = {}
        self.granted: dict[str, bool] = {}

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        # Armed before super() subscribes, or the report topic's grant is missed.
        client.on_subscribe = self._on_subscribe
        super()._on_connect(client, userdata, flags, reason_code, properties)
        _result, mid = client.subscribe(self.request_topic)
        self.subscriptions[mid] = self.request_topic

    def _on_subscribe(self, client, userdata, mid, reason_code_list, properties=None) -> None:
        topic = self.subscriptions.get(mid, self.report_topic)
        ok = all(not getattr(rc, "is_failure", False) for rc in reason_code_list)
        self.granted[topic] = ok
        print(f"  subscribe {'GRANTED ' if ok else 'REFUSED '} {topic}")

    def _on_message(self, client, userdata, message) -> None:
        self.frames += 1
        if message.topic.endswith("/request"):
            self.request_frames += 1
        record = {
            "t": round(time.time(), 3),
            "topic": message.topic,
            "payload": message.payload.decode("utf-8", errors="replace"),
        }
        with self._sink_lock:
            self._sink.write(json.dumps(record) + "\n")
            self._sink.flush()
        super()._on_message(client, userdata, message)


def _raw(state: printer.PrinterState, *path: str):
    """Absent stays absent. See ADR-17 -- a defaulted field is a confident lie."""
    node = state.snapshot()
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _observables(state: printer.PrinterState) -> tuple:
    """The three fields that decide whether an object ends up on the plate."""
    return (
        _raw(state, "ams", "tray_tar"),
        _raw(state, "ams", "tray_now"),
        _raw(state, "hw_switch_state"),
        _raw(state, "gcode_state"),
    )


def _render(observables: tuple) -> str:
    tray_tar, tray_now, switch, gcode_state = observables

    def tray(value):
        if value is None:
            return "UNKNOWN"
        return f"{value}(none)" if str(value) == str(NOTHING_SELECTED) else str(value)

    return (
        f"tray_tar={tray(tray_tar):<10} tray_now={tray(tray_now):<10} "
        f"hw_switch_state={'UNKNOWN' if switch is None else switch:<8} "
        f"gcode_state={gcode_state or 'UNKNOWN'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=900.0, help="how long to listen")
    parser.add_argument("--out", default="ams-capture.jsonl", help="journal path")
    parser.add_argument(
        "--pushall",
        action="store_true",
        help="publish one pushall to establish a baseline (the only publish this script makes)",
    )
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    print(f"journalling every frame to {out}")

    try:
        printer.credentials()
    except printer.PrinterError as exc:
        print(f"credentials: {exc}", file=sys.stderr)
        return 2

    with out.open("w", encoding="utf-8") as sink:
        link = RequestTopicCapture(sink)
        try:
            link.connect()
        except printer.PrinterError as exc:
            print(f"connect failed: {exc}", file=sys.stderr)
            return 2

        with link:
            time.sleep(1.0)  # let the SUBACKs land so the grants print before anything else
            if not link.granted.get(link.request_topic, False):
                print(
                    "\n  NOTE: the request topic was not granted. Telemetry still records whether\n"
                    "  the AMS resolves a tray, which is step 2's question and is the one that\n"
                    "  matters most -- you simply will not get Bambu Studio's payload to diff."
                )
            if args.pushall and not link.pushall():
                print("  pushall suppressed by the 5-minute rate limit")

            print(f"\nlistening for {args.seconds:g}s. Send the print from Bambu Studio now.")
            print("transitions only -- a quiet channel is normal on a settled printer.\n")

            started = time.monotonic()
            last = None
            try:
                while time.monotonic() - started < args.seconds:
                    current = _observables(link.state)
                    if current != last:
                        print(f"  t+{time.monotonic() - started:7.1f}s  {_render(current)}")
                        last = current
                    time.sleep(0.25)
            except KeyboardInterrupt:
                print("\n  interrupted")

            print(f"\nframes: {link.frames} total, {link.request_frames} on the request topic")

    # Re-read the journal rather than accumulating commands in memory: the file is the artifact,
    # and a summary that disagreed with it would be worse than no summary.
    commands: list[str] = []
    for line in out.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            payload = json.loads(record["payload"])
        except (ValueError, KeyError):
            continue
        if record["topic"].endswith("/request"):
            for key, value in payload.items():
                if isinstance(value, dict) and "command" in value:
                    commands.append(f"{key}.{value['command']}")

    if commands:
        print("\ncommands captured on the request topic:")
        for name in sorted(set(commands)):
            print(f"  {name}  x{commands.count(name)}")
        print(
            "\nIf `print.project_file` is there, that is Bambu Studio's payload. Diff it against\n"
            "printer.project_file_command() -- particularly ams_mapping, ams_mapping2 and the\n"
            "task-identity fields."
        )
    else:
        print("\nno commands captured on the request topic.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

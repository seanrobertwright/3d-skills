"""Read-only AMS snapshot -- **step 0** of the feed bisect.

Prints what the AMS currently reports about itself: which slots hold what, which tray (if any) is
targeted, and whether the toolhead's own filament sensor sees filament. It starts no print, uploads
nothing, and changes nothing on the machine.

Why this exists as its own step. Three dispatches through this repository were *accepted* and
produced no object; ``ams.tray_tar`` stayed at 255 and ``hw_switch_state`` stayed 0 for the whole
of a thirty-layer run that reported ``FINISH`` at 100%. Before asking why a job fails to select a
tray, it is worth establishing whether the AMS believes it has anything to select -- a slot that
reads empty or reads unknown material explains everything downstream and costs five minutes to
rule out.

**This is not purely passive.** It publishes exactly one ``pushall``, because telemetry arrives as
one full push and then deltas (ADR-17), so a subscriber that only listens can sit indefinitely
next to a settled printer and learn nothing. ``pushall`` is rate-limited -- Bambu warn against
polling the P1 under five minutes -- so ``PrinterLink.pushall()`` refuses a second one inside that
window and this script reports the refusal rather than pretending it sent one.

Nothing here opens a socket. Every byte goes through ``threedp.printer.PrinterLink``, which is the
only module in this repository permitted to reach a printer (ADR-15). This file lives in ``tools/``
rather than ``src/threedp/`` for exactly that reason: a diagnostic beside the library would have to
be exempted from the ban, and the ban is worth more than the convenience.

Usage::

    uv run python tools/ams_snapshot.py
    uv run python tools/ams_snapshot.py --force-pushall   # ignore the 5-minute interval
"""

from __future__ import annotations

import argparse
import sys
import time

from threedp import printer

# The "nothing selected" sentinel. `tray_now` and `tray_tar` read this when the AMS has resolved
# no tray at all -- which is the exact state all three failed dispatches sat in.
NOTHING_SELECTED = 255


def _raw(state: printer.PrinterState, *path: str):
    """Dig a key out of the merged telemetry without going through a raising accessor.

    Returns the sentinel ``None`` for *absent*, which the caller prints as UNKNOWN. Defaulting an
    absent field to a plausible number is the specific mistake ADR-17 exists to prevent: the
    smallest real delta measured here carries four keys and none of them identifies state.
    """
    node = state.snapshot()
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _describe_tray(value) -> str:
    if value is None:
        return "UNKNOWN (field absent from telemetry)"
    try:
        tray = int(value)
    except (TypeError, ValueError):
        return f"UNPARSEABLE ({value!r})"
    if tray == NOTHING_SELECTED:
        return f"{tray}  <- NOTHING SELECTED"
    return str(tray)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force-pushall",
        action="store_true",
        help="publish pushall even inside the rate-limit window (use sparingly)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=20.0,
        help="seconds to wait for the full push (default: 20)",
    )
    args = parser.parse_args(argv)

    try:
        printer.credentials()
    except printer.PrinterError as exc:
        print(f"credentials: {exc}", file=sys.stderr)
        return 2
    # Deliberately not echoed. The access code never enters a transcript, a log, or this stdout.
    print("credentials loaded from .env")

    try:
        link = printer.PrinterLink().connect()
    except printer.PrinterError as exc:
        print(f"connect failed: {exc}", file=sys.stderr)
        return 2

    with link:
        sent = link.pushall(force=args.force_pushall)
        if not sent:
            print(
                "pushall SUPPRESSED by the 5-minute rate limit; waiting for whatever arrives.\n"
                "  (re-run with --force-pushall if you need a fresh full push now)"
            )
        else:
            print("pushall published; waiting for the full push...")

        deadline = time.monotonic() + args.wait
        while not link.state.known and time.monotonic() < deadline:
            time.sleep(0.25)

        if not link.state.known:
            print(
                f"\nNO FULL PUSH within {args.wait:g}s. Telemetry is UNKNOWN, and UNKNOWN is not "
                f"IDLE.\n"
                f"  full pushes: {link.state.full_pushes}   deltas: {link.state.deltas}\n"
                f"  A silent channel is not a broken one -- a thermally settled idle printer\n"
                f"  sends nothing at all. But without a full push nothing below can be reported,\n"
                f"  so try --force-pushall, or check the serial in the report topic.",
                file=sys.stderr,
            )
            return 1

        print(f"full pushes: {link.state.full_pushes}   deltas: {link.state.deltas}")
        print()

        print("=== machine ===")
        print(f"  gcode_state          {link.state.gcode_state}")
        print(f"  print_error          {link.state.print_error}")
        print(f"  bed_temper           {link.state.bed_temper}")
        print()

        print("=== the two fields that decide whether a part exists ===")
        seen = link.state.filament_at_extruder
        print(f"  hw_switch_state      {int(seen)}  ({'filament seen' if seen else 'NO FILAMENT'})")
        print(f"  ams.tray_now         {_describe_tray(_raw(link.state, 'ams', 'tray_now'))}")
        print(f"  ams.tray_tar         {_describe_tray(_raw(link.state, 'ams', 'tray_tar'))}")
        print()

        print("=== loaded spools (slot = ams_id * 4 + tray_id; 254 is the external spool) ===")
        slots = link.state.ams_slots
        if not slots:
            print("  NONE REPORTED. The AMS is telling us it holds nothing at all.")
        for slot in slots:
            # AmsSlot.__str__ already renders slot / kind / material / colour / tray_info_idx.
            # Re-deriving that here would give the repo two spellings of the same record.
            print(f"  {slot}")
            if not slot.material:
                print(
                    "     ^ material UNREADABLE. A non-Bambu spool reports tray_info_idx poorly "
                    "or not at all;\n       reconciliation degrades to 'unknown material' here."
                )
        print()

        print("=== inventory reconciliation (ADR-16: the inventory is a claim) ===")
        try:
            report = printer.reconcile_ams(link.state)
        except Exception as exc:  # noqa: BLE001 - a diagnostic must not die on a config problem
            print(f"  could not reconcile: {type(exc).__name__}: {exc}")
        else:
            if not report.findings:
                print("  no findings; profiles/filaments.json agrees with the AMS")
            for finding in report.findings:
                print(f"  {finding}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

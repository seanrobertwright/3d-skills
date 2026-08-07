# The AMS feed bisect

**Status:** open. **Written:** 2026-08-07. **Blocks:** Phase 3B calibration (plan tasks 3B-5…3B-8).

---

## The problem, stated in measurements

The AMS has never successfully fed a print through this code path. Three dispatches were accepted
by `accept_dispatch` — upload byte-verified, echo clean, `gcode_state` left `IDLE` for `PREPARE`,
`subtask_name` ours — and **none of them loaded filament**.

The worst of the three is the one worth remembering. Measured 2026-08-03:

| Field | Reported | Reality |
|---|---|---|
| `gcode_state` | `FINISH` | nothing on the plate |
| `mc_percent` | `100` | — |
| layers | `30 / 30` | — |
| `print_error` | `0` | — |
| `hms` | empty | — |
| `hw_switch_state` | **`0` for the entire run** | no filament ever reached the extruder |
| `ams.tray_now` / `tray_tar` | **`255` for the entire run** | the AMS never targeted a tray |

**Not one field the printer publishes dissents.** The machine traced the toolpath through air for
nine minutes and reported a successful print. This is the repository's founding failure mode —
confident, plausible, wrong — arriving at the last possible layer.

### What has already been ruled out

`ams_mapping2` was missing from the `project_file` payload. Bambu Studio sends it,
`bambu_networking.hpp` declares it beside `ams_mapping`, and the firmware needs it to turn a global
tray number into `{ams_id, slot_id}`. **It was added, and a re-run still resolved no tray and still
loaded nothing.**

So it was *a* defect and it is not *the* defect. That result is why this document exists and why
its first steps involve no code at all: `CLAUDE.md` records the next step as **the physical AMS
path, not more payload fields**.

### Why not just try more payload fields

Because this machine has already demonstrated it will answer every variant identically. During the
pre-flight url gate, eight `project_file` variants — including `file:///mnt/sdcard/…`, a path that
does not exist, and a bare filename — returned an *identical* `err_code 0502-4007`. A file-or-path
error cannot be invariant across those. Permuting fields against a machine that refuses uniformly
looks like progress for two hours and produces nothing.

---

## The logic of the bisect

One question — "why does no tray get selected?" — split into two that can each be answered
decisively:

1. **Can this machine feed filament at all?** (physical path)
2. **If so, does it feed when someone other than us asks?** (our payload vs the machine)

Each step below eliminates a chunk of the search space. **Stop as soon as one fails — that is your
answer**, and the remaining steps are about a problem you no longer have.

```
Step 0  read the AMS state ─────────► slot empty / unreadable?     → explained. stop.
Step 1  load from the panel ────────► filament never arrives?      → mechanical. stop.
Step 2  print from Bambu Studio ────► tray_tar stays 255?          → the machine. stop.
                                    └ tray_tar resolves?           → our payload. go to 3.
Step 3  capture Studio's payload ───► diff against ours            → the specific field.
Step 4  re-run ours with the fix ───► watch the same two fields.
```

---

## Step 0 — Read the AMS state without touching anything

**Cost:** 5 minutes. **Changes nothing on the machine.**

```bash
uv run python tools/ams_snapshot.py
```

Confirm the AMS believes it has something to select before asking why a job fails to select it.

**Record:** each slot's material, colour and `tray_info_idx`; `ams.tray_now`; `ams.tray_tar`;
`hw_switch_state`.

| Outcome | Conclusion |
|---|---|
| The intended slot reads **empty**, or material **UNREADABLE** | The AMS never had a candidate. Everything downstream is explained. Reseat the spool, check the RFID tag sits at the reader. |
| Slots read correctly, `tray_tar` is `255` at idle | Normal — `tray_tar` returns to 255 when no job is running. Continue. |

> ⚠️ This is **not** purely passive: it publishes one `pushall`, because telemetry is one full push
> then deltas (ADR-17) and a settled printer sends nothing unprompted. `pushall` is rate-limited —
> Bambu warn against polling the P1 under five minutes — so a second run inside that window reports
> the suppression rather than pretending it sent one.

---

## Step 1 — Load filament from the printer's own screen

**Cost:** 5 minutes. **Zero software of ours involved.**

On the printer panel: **AMS → select the slot → Load**, and feed through to the extruder.

This exercises the entire physical path — feed motor, hub, PTFE tube, extruder gear, and the
toolhead's own filament sensor — with nothing of ours anywhere near it.

| Outcome | Conclusion |
|---|---|
| Filament does **not** reach the extruder | **Stop.** Mechanical or firmware. No payload field will ever fix this. Check the PTFE routing, the hub, whether the feed motor engages, and whether the buffer is seated. |
| Filament loads, `hw_switch_state` → **1** | The physical path works. The defect is in how a *job* selects a tray. Continue. |

That `hw_switch_state` transition is the single most valuable observation in the exercise. It is the
sensor that stayed `0` through all thirty layers of the phantom print, and it is the one field
`PrintOutcome.finished` refuses to proceed without.

Leave `tools/ams_snapshot.py` handy — re-run it right after the manual load to see the sensor state
change.

---

## Step 2 — Have Bambu Studio drive a print

**Cost:** ~15 minutes and a gram of filament.

Slice something tiny in Bambu Studio — a 10 mm calibration cube is ideal — **explicitly assign it
to an AMS slot**, and send it in LAN mode.

Run the capture alongside it so the telemetry is journalled rather than watched:

```bash
uv run python tools/ams_capture.py --seconds 900 --out ams-studio.jsonl
```

| Outcome | Conclusion |
|---|---|
| `tray_tar` stays **255**, no filament loads | The machine will not resolve a tray **even for its own vendor's software**. That is a printer/AMS/firmware problem and our payload was never the story. This retires the entire line of investigation and is the highest-value negative result available. |
| `tray_tar` resolves, filament loads | **Our payload is at fault — and you now hold a known-good reference to diff against.** Go to step 3. |

---

## Step 3 — Capture what Bambu Studio actually sends

The printer's MQTT topics are `device/{serial}/request` (commands in) and `device/{serial}/report`
(telemetry out). `PrinterLink` subscribes only to `report`; `tools/ams_capture.py` subclasses it to
also subscribe to `request`.

**Whether the broker permits that is unknown, and the script tells you which** — `on_subscribe`
reports the granted QoS per topic, so a refusal is reported as a refusal rather than as "Studio
sent nothing". That distinction matters here more than most places: this module has already been
bitten by a refusal that arrived as an echo of its own command and read as silence to a listener
expecting an ack.

If granted, the journal contains Bambu Studio's exact `project_file` payload. Diff it against
`printer.project_file_command()` (`src/threedp/printer.py:1514`), paying particular attention to:

- `ams_mapping` — **forward**-indexed: array *position* is the 3MF filament index, array *value* is
  the global slot (`ams_id * 4 + tray_id`).
- `ams_mapping2` — the `{ams_id, slot_id}` companion.
- `task_id` / `project_id` / `subtask_id` — the string `"0"` here, because firmware `01.10.00.00`
  clamps them to 2³¹−1 and a colliding id makes the printer treat a new dispatch as a continuation
  of the previous FAILED job.
- `use_ams`, `bed_leveling` (**one `l`** — OpenBambuAPI's `bed_levelling` is wrong, and a
  misspelled key is ignored rather than rejected).

**The diff is the answer.** One field, identified rather than guessed.

---

## Step 4 — Re-run ours, watching the same fields

Only after step 3 yields a concrete difference. Same object, same slot, dispatched through
`lril3d-print`, with `watch()` reporting `tray_tar` and `hw_switch_state`.

> ⚠️ A print needs a human yes, in the conversation, for that part. Nothing in this document
> authorises a dispatch.

Success is not `FINISH`. Success is **`FINISH` and filament seen at the extruder** — and even that
is a claim about a machine, not a measurement of an object. Verifying the part is `lril3d-inspect`'s
job, on something taken off the plate.

---

## What to record, whatever happens

For each step: `ams.tray_now` · `ams.tray_tar` · `hw_switch_state` · each slot's `tray_info_idx` ·
and for steps 2 and 4, the timestamp at which `tray_tar` left 255, or that it never did.

**A negative result is a real finding.** "Bambu Studio cannot make this AMS load either" belongs in
`CLAUDE.md` beside the existing entry, recorded with the same weight as a fix. A plausible cause
standing in for a measured one is exactly what this project exists to refuse, and that does not
change when the subject is our own code.

---

## Notes on the tools

Both scripts live in `tools/` rather than `src/threedp/` deliberately. **There is exactly one way
out to a printer and it is `printer.py`** (ADR-15); a diagnostic sitting beside the library would
have to be granted that exemption, and the exemption is worth more than the convenience. Neither
script opens a socket — both go through `PrinterLink`, and
`tests/test_printer_path_is_narrow.py::test_diagnostics_in_tools_still_go_through_the_one_send_path`
fails the suite if that ever stops being true.

| Script | Publishes | Starts a print |
|---|---|---|
| `tools/ams_snapshot.py` | one `pushall` | no |
| `tools/ams_capture.py` | nothing, unless `--pushall` | no |

Neither can dispatch a job. That is not a policy statement — there is no code path in either file
that reaches `dispatch()`.

## Known gaps in this procedure

- **`reconcile_ams` compares material *names* from AMS RFID.** A non-Bambu spool reports
  `tray_info_idx` poorly or not at all, degrading to "unknown material in this slot". Every spool on
  this machine is Bambu, so that path stays untested against real hardware.
- **The request-topic subscription may simply be refused**, in which case step 3 is unavailable and
  step 2's answer is all you get. Step 2 is still the load-bearing one.
- **Nothing here can tell you a part is on the plate.** The whole procedure reasons about a
  machine's self-report, which is the thing that produced the 100%-complete phantom print in the
  first place.

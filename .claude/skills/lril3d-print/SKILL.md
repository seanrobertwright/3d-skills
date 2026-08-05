---
name: lril3d-print
description: Use when a sliced part is ready to go to the physical printer — sending a job, starting a print, checking what the printer is doing, or confirming which filament is actually loaded. Also when the user asks to "print it", "send it", or what the printer is currently running.
---

# lril3d-print — the send path, and the human gate in front of it

Thin skill, thick library. **No ports, no payload fields, no timeouts belong in this file** — they
live in `profiles/printer-conn.json` beside the measurement that produced them. Read `PRD.md` §9
and §12.

This is the **second** of PRD §9's two approval layers. The first is the harness rule in
`.claude/settings.json`, which is not yours to relax. This one is a conversation with a person,
and it exists because a print is the only irreversible thing this toolkit does: it consumes
material, occupies a machine for hours, and can drive a hot nozzle into the wrong polymer.

## Never send without showing, and never show after sending

The order is fixed and it is the whole point of the skill:

1. **Summarise.** Print time, filament grams, purge waste, per-slot filament, the render, and the
   reconciliation report.
2. **Ask.** In plain words, naming the material and the machine. Wait for an explicit yes.
3. **Only then** call `printer.dispatch`.

If the user declines, **nothing is uploaded and nothing is published.** Say that plainly. Do not
offer to "just upload it for later" — a file on the SD card is one screen tap from being a print.

## The pre-send summary

```python
from threedp import printer, slicer

parsed = printer.assert_3mf_is_dispatchable(path)
with printer.PrinterLink() as link:
    link.wait_for_full_push()
    mapping = slicer.ams_mapping(parsed.materials)
    report = printer.reconcile_ams(link.state, used_slots=mapping)
    print(report)
    print(link.state)
```

Report the numbers from the `SliceResult` and the `AmsReport`. Never "roughly" or "about" — the
objects carry exact values.

## Refuse on a BLOCKER. Always.

`reconcile_ams` compares what `profiles/filaments.json` claims against what the printer says is
physically loaded. **A material mismatch in a slot this print uses is a BLOCKER and the dispatch
does not happen.**

This is not defensive coding. On the day the printer first became readable, the committed
inventory disagreed with the AMS in four of five slots, and the mapping happily answered with a
slot holding a different plastic — no exception, no warning. Report the finding with **both**
values and ask the user to correct the inventory or change the spool. Do not offer to skip the
check.

- **WARNING** — drift in a slot this print does not touch. Report it with both values; it is not
  a gate.
- **NOTE** — the colour changed and the material did not. Mention it once and move on.

## What `dispatch` refuses, and why that matters more than what it returns

`dispatch` raises `DispatchRejected` rather than reporting a job the printer never started. When
it does, **report the refusal**. Do not retry with a different url form hoping for a different
answer — that has already been done exhaustively and it produced the same rejection every time.

- **The printer refused it: Developer Mode is not enabled.** The most likely message you will
  see. The fix is on the printer's own screen — `Settings → WLAN → LAN Only Mode → Yes`,
  power-cycle, then `Developer Mode → Enable` — and **the access code changes when you toggle
  it**, so `.env` must be updated too. It is not a Bambu Studio setting and you cannot do it
  remotely; tell the user what to press.
- **The upload landed but the byte count disagrees.** The file on the card is short. Re-upload;
  do not start it.
- **The printer never left idle.** The upload succeeded and the printer accepted the command and
  nothing is printing. Report exactly that; it is not a slow start.
- **The printer was already busy.** Someone else's job. Wait for it.
- **`PreFlightGateOpen`** — the url form has not been measured on this firmware yet. This is an
  open measurement, not a missing default. Say so and stop.

## A returned job is not a printed part

```python
job = printer.dispatch(path, link, subtask_name="...")
print(job)                       # the dispatch was ACCEPTED
outcome = printer.watch(link, job)
print(outcome)                   # what actually happened
```

**Never tell the user their part is printing on the strength of `dispatch` returning.** Measured
on this machine: a dispatch that satisfied every acceptance condition — file verified on the card,
the printer's own echo clean, the state left idle, the job name ours — went into `PREPARE` and
came back to idle having laid **zero of thirty layers**, with no fault recorded anywhere. The
printer is still heating and levelling in that state and the job can be abandoned, or a person can
stop it at the machine.

`watch` distinguishes the three endings, and the third is the one that matters: finished; failed;
or returned to idle having printed nothing. Report the outcome, not the dispatch. If `watch` says
nothing was printed, say exactly that — do not soften it into "it may still be starting".

**`RUNNING` at 0% is normal for about nine minutes.** The printer levels the bed and wipes the
nozzle before it heats to printing temperature, so the layer counter and the percentage sit at
zero for a long time on a healthy print. Do not report that as a stall, and do not offer to
restart it.

A **stopped** job reports as failed with a cancellation code and an empty fault list. That is
someone changing their mind, not a defect; say so rather than reporting a failure.

## Watching a print

```python
link.wait_for_full_push()
print(link.state)
```

**An unknown state is not an idle printer.** Telemetry arrives as deltas — one full push, then
changes — so `PrinterState` raises until a full push has landed rather than reporting a confident
`IDLE` about a machine it has learned nothing about. If you get that exception, say the state is
unknown; never fill it in.

Time remaining is reported in **minutes** and is `None` when the printer has not said. Report
"unknown", never zero.

`pushall` is rate-limited on purpose. Do not poll it in a loop to make things feel responsive —
that degrades the printer, and the deltas already carry the changes.

## The viewer

`lril3d-viewer` alongside a running print is a **channel, not a gate**. It never contributes to a
verdict about whether the print is going well.

## Non-negotiable

- Never call `dispatch` before an explicit human yes, in the same conversation, for this part.
- Never proceed past a BLOCKER, and never suggest a flag that would skip one.
- Never read `.env` into the transcript, quote an access code, or ask the user to paste one.
- Never claim a print started. `dispatch` returns a `PrintJob` only when the printer's own state
  says so; anything else is a refusal, and a refusal is reported as one.

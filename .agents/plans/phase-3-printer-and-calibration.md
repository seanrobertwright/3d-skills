# Feature: Phase 3 — The Printer and Calibration

The following plan should be complete, but it is important that you validate documentation and
codebase patterns and task sanity before you start implementing.

Pay special attention to naming of existing utils, types and models. Import from the right files.

> **Read [`CLAUDE.md`](../../CLAUDE.md) first.** It is the source of truth for conventions,
> non-negotiable rules and environment gotchas. This plan does **not** restate them; duplicated
> conventions drift. Where this plan contradicts a *number* in `PRD.md`, see
> [PRD CORRECTIONS](#prd-corrections) — the corrections win, and each is backed by a spike below.

---

## Feature Description

Phase 3 closes the loop from a verified part to a physical object, and then uses that physical
object to replace the repository's last remaining invented numbers.

It has two halves, and they are in the right order — the second depends on the first:

- **3A — the send path.** A thin `printer.py` that uploads a sliced 3MF over implicit FTPS and
  starts it over MQTT, wrapped in `lril3d-print`, whose approval gate is the *second* of PRD §9's
  two layers. The first layer, the harness `deny` rule, has been committed since Phase 1 and now
  converts to `ask` — the conversion ADR-5 has been deferring for two phases.
- **3B — calibration.** `coupon.py` has been able to generate a stepped fit gauge since Phase 2
  and nothing has ever printed one. `profiles/calibration.json` still carries three published
  defaults with `"measured": null`. 3B prints the gauge per material, captures caliper readings,
  and replaces those defaults with values measured on *this* printer.

**This phase inherits the repository's founding problem in a new location.** Phases 1 and 2 exist
because an agent produces confident, plausible, wrong *geometry*. Spike [S16](#s16) found the same
failure already present in the AMS layer, shipped, and undetected: `slicer.ams_mapping` returns a
confident, plausible, wrong *slot*. Asked for ABS it answers slot 3; slot 3 physically holds green
PETG. Phase 3 is the first phase that can read the truth from the printer, so it is the phase that
has to close that gap.

## User Story

As **someone who has just verified a part**
I want to **send it to the printer and get back a real object whose dimensions match the model**
So that **the verification loop terminates in a physical part rather than a file, and the
compensation numbers it relies on are measured from my printer instead of borrowed from a blog
post.**

## Problem Statement

Four concrete gaps, each measured this session rather than assumed:

1. **There is no send path.** `--export-3mf` produces a file a human transfers by hand. That was
   the correct Phase 2 boundary and it is now the thing blocking the loop from closing.
2. **The AMS inventory is a hand-maintained claim that has silently drifted** ([S16](#s16)).
   `profiles/filaments.json` disagrees with the physical AMS in **4 of 5 slots**. Nothing detects
   this, and `ams_mapping()` converts the drift into a wrong slot with no error.
3. **Compensation is unvalidated.** All three calibration records are published defaults.
   `Resolved.stale` and `CalibrationStaleWarning` already exist to say so on every compensated
   export — the machinery to *report* the gap shipped in Phase 1; the gap itself is still open.
4. **The printer profile is wrong about the hardware** ([S17](#s17)).
   `printer-p1s.json` claims `"nozzle_material": "hardened-steel"` with `"source": "vendor-spec"`.
   The printer reports `stainless_steel`, and tray 1 currently holds abrasive **PLA-CF**.

## Solution Statement

A thin `printer.py` on `paho-mqtt` + stdlib `ftplib` ([ADR-13](#adr-13)), which:

- uploads over implicit FTPS using the `sock`-property override, TLS session reuse and a
  `storbinary` that does **not** call `conn.unwrap()` — all three measured necessary in [S14](#s14);
- **reconciles `filaments.json` against live AMS telemetry and refuses on mismatch**
  ([ADR-16](#adr-16)) before any dispatch is even attempted;
- accepts a dispatch on **four independent conditions** ([ADR-14](#adr-14)), reading the printer's
  `err_code` echo ([S18](#s18)) rather than waiting on a timeout, and recognising `0502-4007` as the
  authorization refusal it measurably is ([S19](#s19));
- merges delta telemetry into local state, treating "no full push seen yet" as **UNKNOWN**, never
  as idle ([ADR-17](#adr-17)).

Then `lril3d-print` for the human gate, and a calibration workflow that turns caliper readings into
`calibration.json` entries carrying a measurement **date** and the gauge that produced them.

## Feature Metadata

**Feature Type**: New Capability
**Estimated Complexity**: **High** — a new I/O boundary, real hardware, irreversible physical
actions, and a refusal channel ([S18](#s18)) that defeats the obvious listener.
**Primary Systems Affected**: new `src/threedp/printer.py`, new `src/threedp/calibrate.py`,
`profiles/filaments.json`, `profiles/calibration.json`, `profiles/printer-p1s.json`,
`.claude/settings.json`, `tests/test_no_printer_path.py`, new `.claude/skills/lril3d-print/`
**Dependencies**: `paho-mqtt>=2.1` (resolves clean on 3.13, [S24](#s24)). Nothing else.

---

## CONTEXT REFERENCES

### Relevant Codebase Files — YOU MUST READ THESE BEFORE IMPLEMENTING

| File | Why |
|---|---|
| `src/threedp/slicer.py` (lines 1–35) | The module docstring is the template for `printer.py`'s: it opens by naming the measured ways the subsystem *reports a lie*. Mirror that structure. |
| `src/threedp/slicer.py` (lines 302–430, `accept_slice`) | **The pattern [ADR-14](#adr-14) copies.** Four independent conditions, and an exception naming which one failed and what to do. |
| `src/threedp/slicer.py` (lines 539–590, `ams_mapping`) | Inherited by 3A. Its docstring says "reverse-indexed" — see [C5](#c5). Behaviour is correct; the word and the missing reconciliation are not. |
| `src/threedp/slicer.py` (lines 234–272, `SliceResult`) | The dataclass shape `PrintJob` should mirror, incl. `__str__` reporting numbers with units. |
| `src/threedp/compensate.py` (lines 37–66, `Resolved`) | `stale`, `staleness_warning`. 3B's whole job is making `stale` false honestly. |
| `src/threedp/compensate.py` (lines 92–180) | `load_calibration` / `_entry`. 3B extends the record; do not break this reader. |
| `src/threedp/io.py` (lines 42, 160–178) | `CalibrationStaleWarning` and where it fires. |
| `src/threedp/coupon.py` (entire, 242 lines) | 3B's input. `write_gauge` **refuses a calibration** — read that docstring before touching 3B. |
| `src/threedp/dfm.py` (lines 159–232, `load_rules`) | The "**every threshold carries a `source`**" enforcement pattern. 3B's calibration records follow it. |
| `src/threedp/parts.py` (lines 130–147) | `_assert_keys_are_globally_unique` — import-time structural validation of a data file. `printer.py` validates `filaments.json` the same way. |
| `tests/test_no_printer_path.py` (entire, 200 lines) | **The file this phase must carefully narrow, not delete.** See [ADR-15](#adr-15). |
| `tests/test_one_ruler.py` (lines 1–60) | Provides `REPO` and `strip_strings_and_comments`, which the above imports rather than copies. |
| `tests/test_slicer.py` (lines 1–60) | The `@pytest.mark.slicer` pattern for hardware-gated tests. `printer` marker mirrors it exactly. |
| `.claude/PRINT-GATE.md` | Contains the **exact** post-conversion `settings.json` block. Task 3A-9 is a transcription, not a design. |
| `.claude/skills/lril3d-slice/SKILL.md` | The sibling skill `lril3d-print` mirrors — including "no thresholds in this file". |
| `profiles/slicer.json` | The config-with-`source` shape `printer.json` follows. |

### New Files to Create

| Path | Purpose |
|---|---|
| `src/threedp/printer.py` | FTPS upload, MQTT dispatch/telemetry, AMS reconciliation, `accept_dispatch`. |
| `src/threedp/calibrate.py` | Caliper readings → calibration record. Pure, no I/O to the printer. |
| `profiles/printer-conn.json` | Ports, timeouts, url-scheme candidates, retry policy — **with `source`**. |
| `.claude/skills/lril3d-print/SKILL.md` | The approval gate and pre-send summary. |
| `.claude/skills/lril3d-calibrate/SKILL.md` | Gauge → print → measure → record workflow. |
| `tests/test_printer.py` | Against a **fake** broker/FTPS server; runs with no hardware. |
| `tests/test_printer_live.py` | `@pytest.mark.printer`; requires the real P1S. |
| `tests/test_calibrate.py` | Pure-function tests for the calibration maths. |
| `tests/fixtures/push_status_full.json` | Real `msg:0` capture from [S15](#s15) (redact `net`/serial). |
| `tests/fixtures/push_status_delta.json` | Real delta capture — proves the merge is needed. |
| `.env.example` | **Requires a `!.env.example` negation in `.gitignore`** — see [C9](#c9). |

### Relevant Documentation — READ BEFORE IMPLEMENTING

- [Bambu wiki — Third-party Integration](https://wiki.bambulab.com/en/software/third-party-integration)
  — the authoritative list of what Authorization Control blocks. Note telemetry is **explicitly
  exempt**, which is why [S15](#s15) worked while [S18](#s18) did not.
- [Bambu wiki — Enable Developer Mode](https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode)
  — *the access code changes when you toggle it.*
- [Bambu wiki — HMS 0500-0500-0001-0007](https://wiki.bambulab.com/en/x1/troubleshooting/hmscode/0500_0500_0001_0007)
  — the documented Dev-Mode-off code. **We did not receive it** ([S18](#s18)); do not key on it.
- [OpenBambuAPI — mqtt.md](https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md) — payload
  reference. ⚠ Its `ams_mapping` section is self-contradictory and wrong; see [C5](#c5). Its
  `bed_levelling` spelling is also wrong — Bambu Studio uses `bed_leveling`.
- [OpenBambuAPI — ftp.md](https://github.com/Doridian/OpenBambuAPI/blob/main/ftp.md) /
  [tls.md](https://github.com/Doridian/OpenBambuAPI/blob/main/tls.md) — the cert is issued by a
  Bambu CA with **CN = printer serial**, not self-signed.
- [bambulabs_api `ftp_client.py`](https://github.com/mchrisgm/bambulabs_api/blob/main/bambulabs_api/ftp_client.py)
  — **MIT.** The `ImplicitFTP_TLS` shape to vendor (~60 lines), not depend on.
- [BambuStudio `DevMapping.cpp`](https://github.com/bambulab/BambuStudio/blob/master/src/slic3r/GUI/DeviceCore/DevMapping.cpp)
  — decisive source for forward-indexed `ams_mapping` and `-1`.
- [cpython#63699](https://github.com/python/cpython/issues/63699) — ftplib has no data-channel TLS
  session reuse; open since 2013. This is why `ntransfercmd` must be overridden.
- [paho#734](https://github.com/eclipse-paho/paho.mqtt.python/issues/734#issuecomment-2256633060) —
  SNI override, needed only if you validate the certificate properly.

### Patterns to Follow

**Refuse rather than report a plausible number.** From `slicer._print_time`:

```python
if time_s <= 0.0:
    raise SliceRejected(
        "the slice reported no print time: ... Reporting 0s would be inventing a number "
        "nothing produced."
    )
```

`printer.py` does the same for `mc_remaining_time` — see [C10](#c10), it is **minutes**, and an
unknown must not become `0`.

**Config carries its own provenance.** Every `profiles/*.json` has a `source`. `dfm.load_rules`
*refuses* an uncited threshold. `printer-conn.json` and every new `calibration.json` record follow
this; 3B's records carry `"measured": "<ISO date>"` and the gauge that produced them.

**Hardware-gated tests use a marker and must actually run.** `pyproject.toml` already declares
`slicer`; add `printer` beside it, and `CLAUDE.md`'s existing rule applies unchanged — a green
suite with the layer skipped is not evidence the layer works.

> **Spike-snippet fidelity.** The `ImplicitFTP_TLS` snippet below is exactly what [S14](#s14) ran.
> Its three assertions: (a) the `sock` setter wraps *before* the greeting is read, so `AUTH TLS` is
> never sent; (b) `session=self.sock.session` is required — vsFTPd runs `require_ssl_reuse`;
> (c) `storbinary`'s stock `conn.unwrap()` must be dropped, but the `voidresp()` **must be kept**.
> If your transcription drops (c)'s second half, uploads silently truncate and the printer throws
> `0500-C010`.

```python
class ImplicitFTP_TLS(ftplib.FTP_TLS):
    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session)  # (b)
        return conn, size

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):                                                   # (a)
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value
```

---

<a id="prd-corrections"></a>
## PRD CORRECTIONS

Six. Each is backed by a spike below or by vendor source, and each contradicts a specific PRD claim.

<a id="c5"></a>
**C5 — `ams_mapping` is *forward*-indexed. "Reverse-indexed" is wrong in both PRD §9 and the
code's own docstring.** PRD §9 and `slicer.py:545` both say "reverse-indexed", then correctly
describe forward indexing in the next clause ("array *position* = filament index, array *value* =
AMS slot"). Bambu Studio's `DevMapping.cpp` settles it: the result vector is indexed by filament
source index (`result[picked_src_idx].tray_id`), unmapped entries are `-1`. **The behaviour of
`ams_mapping()` is correct and its tests pass; only the word is wrong.** Fix the docstring; do not
touch the logic. Two further facts PRD §9 omits: values are **not** capped at 0–3 (`ams_id * 4 +
tray_id`, so a second AMS gives 4–7), and the external spool is `254`/`255` — [S15](#s15) observed
`vt_tray.id == "254"` on this machine.

<a id="c6"></a>
**C6 — PRD §9's firmware attribution is wrong.** §9 says "Jan 2025 firmware; X-series first, then
P/A". January 2025 was the **X1**. The **P1-series** Authorization Control release is
`01.08.02.00`, 2025-06-03, which introduced ACS *and* Developer Mode together. This machine runs
`01.10.00.00` ([S20](#s20)). Consequence for the plan: `01.10.00.00` clamps task-identity fields to
2³¹−1, so a raw epoch-ms `task_id` collides and the printer treats a new dispatch as a continuation
of the previous FAILED job. We send `"0"` for local prints, which sidesteps it — **do not
"improve" that to a timestamp.**

<a id="c7"></a>
**C7 — Phase 2's correction C2 (blank P1S preview) does not apply to the transport Phase 3 uses,
and Phase 3 closes it for free.** C2 measured that CLI G-code carries no thumbnail block. True, and
still true. But `project_file` sends the **3MF**, and [S21](#s21) measured
`Metadata/plate_1.png` inside our own Phase 2 export at **512×512, 141 unique byte values,
std 58.27** — a real render. The P1S screen preview will not be blank. Update
`lril3d-slice/SKILL.md`, which currently documents this as an unfixable cosmetic defect.

<a id="c8"></a>
**C8 — PRD §9's "`use_ams` is silently ignored unless `filament_id` is set inside the 3MF" does not
apply to us.** [S22](#s22) measured our Bambu Studio CLI output carrying
`filament_ids: ['GFA00']` in `project_settings.config` and a populated `tray_info_idx` in
`slice_info.config`. The trap is real but traces to **OrcaSlicer's** CLI emitting empty IDs — a
slicer this repo does not use (Phase 2 correction C1). Keep an assertion for it anyway
(task 3A-6): it costs one check and it is the difference between "we believe it is fine" and "we
verified it on this file".

<a id="c9"></a>
**C9 — `.gitignore` will silently swallow `.env.example`.** PRD §9's config table lists `.env`, and
the natural companion is a committed `.env.example`. Measured: `git check-ignore -v .env.example`
→ matched by `.gitignore:3:.env.*`. **A plan that says "commit `.env.example`" without adding
`!.env.example` ships a file nobody receives** — the same class as a rule living in the gitignored
`settings.local.json`, which `test_no_printer_path.py` already guards against.

<a id="c10"></a>
**C10 — `mc_remaining_time` is in MINUTES.** No PRD claim, but a documented-nowhere unit that
produces a silent 60× error. pybambu's `get_end_time()` does `timedelta(minutes=remaining_time)`.
`printer.py` names the field `remaining_min` and converts at the boundary, per `CLAUDE.md`'s
suffix rule.

---

## PRE-FLIGHT SPIKE RESULTS

Run on this machine, 2026-08-02, against the real P1S. Every number was observed, not estimated.
Credentials were loaded in-process from `.env` and never entered the transcript.

### Environment — verified present

| Thing | Fact | How verified |
|---|---|---|
| `paho-mqtt` | **2.1.0**, resolves on 3.13 | `uv pip install --dry-run` <a id="s24"></a>(**S24**) |
| Printer firmware | ota `01.10.00.00`, esp32 `01.16.38.70`, mc `00.01.33.24` | MQTT `get_version` <a id="s20"></a>(**S20**) |
| Nozzle | `0.4`, **`stainless_steel`** | `push_status` |
| AMS | 1 unit, `tray_exist_bits: 'f'` (all 4 present) | `push_status` |

<a id="s13"></a>
### S13 — the printer is reachable and all three service ports are open

`192.168.x.x` (private). Ports **990** (FTPS implicit), **8883** (MQTT TLS) and **6000** (camera)
all OPEN. Access code is 8 characters, serial 15 — both the documented shapes.

<a id="s14"></a>
### S14 — implicit FTPS works, and all three workarounds are load-bearing

Login as `bblp` succeeded; negotiated **TLSv1.2**. Directories `/` (9 entries), `/cache` (102),
`/model` (20), `/timelapse` (66) all listable. A **135,726-byte** 3MF uploaded to **both** `/` and
`/cache`, each returning **`226`** in **~1.0 s**, and both were confirmed present at the correct
byte count on a follow-up `LIST`.

The welcome banner does **not** contain the string `vsFTPd` — do not fingerprint on it.

<a id="s15"></a>
### S15 — MQTT telemetry works, and the P1 really does send deltas

Connected, subscribed to `device/{serial}/report`, published `pushall`. Over 30 s: **exactly one**
full push (`msg == 0`), then deltas. Merged state reached **63 keys**.

```
gcode_state='IDLE'  mc_percent=0  mc_remaining_time=0  layer_num=0
print_error=0  nozzle_temper=22.3125  bed_temper=19.375  chamber_temper=5
print_type='idle'  stg_cur=0  wifi_signal='-41dBm'  sdcard=True
```

⚠ `mc_remaining_time` is `0` **because the printer is idle**, so this spike could not settle
[C10](#c10)'s units empirically — it is settled from pybambu source, not from this machine. The
first real print must confirm it (task 3B-7).

⚠ `chamber_temper=5` against `bed_temper=19.375` in the same push is unexplained and is **not**
believed to be °C. Do not surface a chamber temperature until it is understood.

<a id="s16"></a>
### S16 — ⚠ **THE HEADLINE: `filaments.json` has drifted, and `ams_mapping` converts that into a confidently wrong slot**

Live AMS versus the committed inventory:

| Slot | `filaments.json` claims | Printer reports | |
|---|---|---|---|
| 0 | PLA `#101010` | PLA `#FFF144` (`GFA00`) | colour only |
| 1 | PLA `#f5f5f5` | **PLA-CF** `#951E23` (`GFA50`) | **MISMATCH** |
| 2 | PETG `#1e6fd9` | **PLA** `#A03CF7` (`GFA00`) | **MISMATCH** |
| 3 | ABS `#b02020` | **PETG** `#057748` (`GFG00`) | **MISMATCH** |
| 4 | PC (external) | **PLA** (`vt_tray`, `GFL99`, id `254`) | **MISMATCH** |

And the consequence, run against the shipped function:

```
ams_mapping(['PLA'])  -> [0]
ams_mapping(['PETG']) -> [2]   *** slot 2 actually holds PLA  #A03CF7 ***
ams_mapping(['ABS'])  -> [3]   *** slot 3 actually holds PETG #057748 ***
```

**No exception. No warning.** Asking for ABS yields slot 3, and slot 3 is green PETG — so an ABS
process (255 °C nozzle, 100 °C bed) would be driven into PETG. This is `PRD` Risk 1 — "plausible,
confident, wrong" — relocated from geometry to the AMS, and it is already shipped. It is the
direct motivation for [ADR-16](#adr-16).

<a id="s17"></a>
### S17 — the printer profile is wrong about the nozzle, and there is abrasive filament loaded

`printer-p1s.json` says `"nozzle_material": "hardened-steel"`, `"source": "vendor-spec"`. The
printer reports `nozzle_type: "stainless_steel"`. Tray 1 currently holds **PLA-CF**, which is
abrasive and wears a stainless nozzle. Two consequences: correct the profile from telemetry
(task 3A-5), and note that a DFM rule about abrasive-filament/nozzle pairing is a **Phase 4**
candidate, not a Phase 3 scope creep.

<a id="s18"></a>
### S18 — ⚠ **a refused dispatch is reported by an `err_code` echo, not by silence or by HMS**

This spike was run three times and **the first two readings were wrong**. The correction is the
finding, so all three are recorded.

**Reading 1 (wrong).** `project_file` published with both candidate url schemes; no `gcode_state`
change after 12 s, and the listener reported no ack. Conclusion drawn: *"accepted in complete
silence"*.

**Reading 2 (wrong, and it explains reading 1).** A control probe sent a deliberately malformed
command (`"command": "not_a_real_command"`) and *that* produced no ack either — so "no ack" was
read as carrying no information at all.

**Reading 3 (correct).** Capturing **raw** payloads instead of filtering them showed the printer had
been answering the whole time. It **echoes the entire `project_file` command back with an
`err_code` field appended**:

```json
{"print":{"sequence_id":"500","command":"project_file", ...,
          "url":"ftp:///threedp-spike.3mf","md5":"", ..., "err_code":84033543}}
```

`84033543` = `0x05024007` = **`0502-4007`**.

**The listener in readings 1–2 filtered for `result` / `reason` / `errno` and `err_code` is none of
those.** The bug was in the spike, not the printer.

**Consequence for [ADR-14](#adr-14): condition 2 keys on `err_code`, and a refusal is detectable
in ~1 s rather than by timeout.** Do not write a listener that whitelists ack field names; capture
the echo whole and inspect it.

<a id="s19"></a>
### S19 — ⚠ `0502-4007` is an authorization refusal, and it is **not** the documented HMS code

Eight `project_file` variants were published, with the file confirmed present on the SD card:

| url | md5 | `err_code` |
|---|---|---|
| `ftp:///threedp-spike.3mf` | — | `0502-4007` |
| `ftp:///threedp-spike.3mf` | **set** | `0502-4007` |
| `ftp://threedp-spike.3mf` | — | `0502-4007` |
| `file:///sdcard/threedp-spike.3mf` | — | `0502-4007` |
| `file:///mnt/sdcard/threedp-spike.3mf` *(path does not exist)* | — | `0502-4007` |
| `ftp:///cache/threedp-spike.3mf` *(file genuinely there)* | — | `0502-4007` |
| `file:///sdcard/cache/threedp-spike.3mf` | — | `0502-4007` |
| `threedp-spike.3mf` *(bare filename)* | — | `0502-4007` |

**Identical for all eight — including a nonexistent path and a bare filename.** A file-or-path
error could not be invariant across those, so the rejection happens **before the url is parsed**.
The documented "unable to parse print file" code is `0500-4003`, and we never see it.

Corroborating, from the same session: `info/get_version` returned a full module list and
`system/ledctrl` returned `result: success` — so the channel and credentials are fine — while
`print/gcode_line` (authorization-gated) produced no ack at all.

**Conclusion: `0502-4007` is the P1S's LAN authorization refusal.** Bambu documents
HMS `0500-0500-0001-0007` for this; **this machine does not emit it**. Key on `0502-4007`, and
treat the HMS code as a documented-but-unobserved alternative.

**Still open, and it blocks task 3A-7 only:** which url scheme is correct. It is *unknowable* until
Developer Mode is on, because every form is rejected identically before parsing. See
[PRE-FLIGHT GATE](#pre-flight-gate).

<a id="s25"></a>
### S25 — a `project_file` ack can take longer than 15 s

Community-sourced ([bambuddy #1150](https://github.com/maziggy/bambuddy/issues/1150)), not measured
here: the P1 can exceed a 15 s acknowledgement window, and a client that reconnects mid-dispatch on
timeout induces a `0500-4003` parse error on the printer. `dispatch_settle_s` must be generous and
the client must **not** reconnect while waiting.

<a id="s21"></a>
### S21 — the 3MF carries a real thumbnail (PRD correction [C7](#c7))

`Metadata/plate_1.png`, **512×512**, 4998 bytes, PNG magic valid, **141 unique byte values,
std 58.27** across the decompressed IDAT — a render, not a flat fill. Also present:
`plate_1_small.png`, `top_1.png`, `pick_1.png`. The G-code *inside* the same 3MF still has no
thumbnail block, which is why Phase 2's measurement was right and its conclusion was scoped too
broadly.

<a id="s22"></a>
### S22 — the 3MF carries filament ids (PRD correction [C8](#c8))

`project_settings.config` → `filament_ids: ['GFA00']`;
`slice_info.config` → `<filament id="1" tray_info_idx="GFA00" type="PLA" ... />`.
Note `filament id` is **1-based** in `slice_info.config` while `ams_mapping` is 0-based — a real
indexing seam. `filament_sequence.json` is also 1-based (`{"sequence":[1]}`). Do not mix them.

<a id="s23"></a>
### S23 — the sliced bed type does not match the physical plate

The G-code carries `; curr_bed_type = Cool Plate`; the P1S ships a textured PEI plate, and
`textured_plate_temp = 55` sits unused in the same profile. `profiles/slicer.json` sets no bed type
at all. Send `bed_type: "auto"` (documented as always-auto for local prints) and let the printer
decide — but **also** fix the slicer profile, because the first-layer temperature is baked into the
G-code long before MQTT sees it. Task 3A-4.

---

<a id="pre-flight-gate"></a>
## PRE-FLIGHT GATE — resolve before writing dispatch code

**Exactly one question is open: the `url` scheme.** It is *unknowable* until Developer Mode is on,
because [S19](#s19) measured all eight candidate forms being rejected identically **before the url
is parsed**. Do not write `dispatch()` against a guess, and do not try to resolve this by
permutation while `0502-4007` is still being returned — that is what S19 already did, exhaustively,
to no effect.

1. **Enable Developer Mode on the printer** — `Settings → WLAN → LAN Only Mode → Yes`,
   power-cycle, then scroll to `Developer Mode → Enable`. It is not a Bambu Studio setting.
   **The access code changes when toggled** — update `.env` before retrying.
2. Confirm the block is gone: publish any `project_file` and check the echo's `err_code` is
   **absent or no longer `84033543`**. If it is still `0502-4007`, Developer Mode did not take —
   stop and report; do not proceed to step 3.
3. Re-run the url matrix (`scratchpad/matrix.py`, or its port into `tests/test_printer_live.py`)
   with an already-uploaded 3MF. Record which form produces a `gcode_state` transition out of
   `IDLE`, and which upload directory it agrees with (`/` and `/cache` are both writable —
   [S14](#s14)). **Stop the print immediately** once a form wins.
4. Write the winner into `profiles/printer-conn.json` **with a `source` naming this measurement**,
   and leave the losers in the file as documented, disabled candidates — the matrix result is
   evidence worth keeping.

**If no scheme works with Developer Mode confirmed ON and `0502-4007` gone, stop and report.**

---

## ARCHITECTURE DECISIONS

<a id="adr-13"></a>
### ADR-13 — `printer.py` is a thin in-repo module, not a wrapped library

**Decision** (maintainer, this session): vendor ~60 lines of MIT `ImplicitFTP_TLS` and drive
`paho-mqtt` directly. One new dependency.

**Rejected: `bambulabs_api` 2.6.6.** It is the only maintained library covering both halves and it
is MIT — a genuinely reasonable choice. Rejected because it drags in `pillow` for a preview feature
this repo already solves with `render.py`, and because it would own the single code path two phases
have deliberately refused to build. A bug in it becomes a silent print failure in a repository
whose entire thesis is that silent plausible failures are the enemy.

**Rejected: `pybambu`.** Structurally disqualified — no `STOR` anywhere in the package; its FTP is
download-only. Also vendored inside a Home Assistant integration with **no LICENSE file**, which is
a problem for a public repo. (The PyPI `pybambu` 1.0.1 is a different, dead package — a decoy.)

**Consequence:** the FTPS/MQTT semantics become *ours*, tested against fakes, and every byte on the
wire is reviewable. The cost is that protocol drift is our problem; `profiles/printer-conn.json`
exists so a payload change is a JSON edit, mirroring `profiles/slicer.json`'s role for the CLI.

<a id="adr-14"></a>
### ADR-14 — a dispatch is accepted on four independent conditions, or not at all

Directly parallel to ADR-10, and for a measured reason: [S18](#s18) observed conditions 1 and 2
satisfied by a dispatch that never started.

1. **The upload returned `226`** *and* a follow-up `LIST` shows the file at the **exact byte
   count** ([S14](#s14) confirms both are obtainable). The `226` alone is not enough — a skipped
   `voidresp()` produces a truncated file and `0500-C010`.
2. **The MQTT echo carries no `err_code`**, matching `sequence_id`. [S18](#s18) measured that
   `project_file` is answered by an **echo of the command with `err_code` appended** — not by a
   `result`/`reason` ack. A listener that whitelists ack field names sees nothing and reports a
   timeout; capture the echo whole. `err_code == 84033543` (`0502-4007`) is the authorization
   refusal ([S19](#s19)) and must produce a Developer-Mode message by name.
3. **`gcode_state` left `IDLE`** within a bounded window. This is the only positive evidence a job
   started, and it is the condition [S18](#s18) failed.
4. **`subtask_name` / `gcode_file` on the printer matches what we sent.** Guards against accepting
   a *pre-existing* job — the printer was already busy and we congratulated ourselves.

Each condition alone was measured or reasoned to be satisfiable by a failed dispatch. The raised
exception names **which** condition failed and what to do — copy `accept_slice`'s error prose
style, which is the best in the repository.

<a id="adr-15"></a>
### ADR-15 — `test_no_printer_path.py` narrows; it must not be deleted

The temptation on the day `printer.py` lands is to delete the file. That would remove the guarantee
for the **other thirteen modules**, which is most of its value.

Rewrite so that:
- the network-import ban still applies to every module **except** `printer.py` — a
  `render.py` that grew a socket must still fail;
- `printer.py` is the **single** allowed exception, asserted by name, so a second send path
  anywhere fails the suite;
- the `subprocess`-is-only-the-slicer assertion is **unchanged**;
- the settings assertions **invert**: the six printer entries must now be under `ask`, must
  **not** be under `deny`, `Read(.env)` must **remain** under `deny`, and the
  `settings.local.json` migration guard is unchanged.

Rename to `tests/test_printer_path_is_narrow.py` so the filename stops asserting something false.

<a id="adr-16"></a>
### ADR-16 — `filaments.json` is a claim, and it is verified against the printer before every dispatch

This is [S16](#s16) turned into a rule, and it is the same move `intent.json` makes for geometry:
**a hand-written claim is checked against a measurement taken from the real thing.**

- `printer.reconcile_ams(live, inventory)` compares material **per slot** and returns a report.
- A material mismatch in any slot the dispatch **uses** is a **BLOCKER** — refuse.
- A mismatch in an unused slot is a **WARNING** — report with both values, do not gate. (The
  `BLOCKER`/`WARNING` split is `dfm.py`'s, deliberately reused rather than reinvented.)
- Colour-only differences are a **NOTE**. [S16](#s16) slot 0 is exactly this case, and a verifier
  that refuses on colour would be refused-into-uselessness within a week.
- **`reconcile_ams` performs no I/O.** It takes already-fetched telemetry, exactly as `dfm.evaluate`
  takes already-taken measurements. This keeps it unit-testable against the [S15](#s15) fixture.

**`ams_mapping()` gains no printer knowledge.** It stays pure and Phase-2-tested; reconciliation is
a separate gate that runs before it. Mixing them would put I/O inside a pure function and give the
mutation suite nothing clean to bite on.

<a id="adr-17"></a>
### ADR-17 — absence of a full push is UNKNOWN, never IDLE

[S15](#s15) measured exactly one `msg == 0` full push followed by deltas. A fresh subscriber that
reads its first delta sees a near-empty object — which is indistinguishable from an idle printer to
any code that defaults missing fields.

`PrinterState` therefore starts as UNKNOWN and only becomes readable after a full push has been
merged. Any accessor called before that **raises**. This is `CircleFit.diameter` refusing without
`is_circular`, applied to telemetry: the plausible default is the whole danger.

Corollary: `pushall` is rate-limited. Bambu's own docs warn against intervals under 5 minutes on
the P1 — a fast poll to "make it reliable" degrades the printer.

<a id="adr-18"></a>
### ADR-18 — `"measured"` becomes an ISO date, and a calibration record names the gauge that produced it

Currently `"measured": null` marks unvalidated. 3B could set it `true`, which would satisfy
`Resolved.stale` and lose every fact worth keeping. PRD Risk 7 is explicitly *"calibration goes
stale — nozzle swap or filament change silently invalidates the profile"*, so the record must
carry enough to detect that.

```json
"PLA_generic": {
  "hole_delta_mm": 0.18, "outer_delta_mm": -0.05, "first_layer_squish": 0.12,
  "measured": "2026-08-09",
  "source": "coupon:hole-10mm-5step + coupon:pin-10mm-5step, digital caliper +/-0.01mm",
  "nozzle": "stainless_steel 0.4",
  "readings": { "...": "raw per-step caliper values, so the fit can be recomputed" }
}
```

**`compensate.load_calibration` must keep reading the old shape** — `stale` is
`record.get("measured") is None`, which stays correct for a date, a `null`, and (accidentally) a
`true`. Add an explicit rejection of `true`: it is the shape someone reaches for when cutting a
corner, and it discards the date.

---

## IMPLEMENTATION PLAN

### Milestone 3A — the send path and the gate

Foundation → transport → reconciliation → dispatch → skill → gate conversion. The gate conversion
is **last**: it is the only irreversible-ish step, and doing it first would leave the repo
guardrail-free while the code that needs guarding is still being written.

### Milestone 3B — calibration

Gauge → print → measure → record. 3B-1..4 can be built and tested before any physical print;
3B-5..8 need the printer and a caliper and are the human-in-the-loop half.

---

## STEP-BY-STEP TASKS

Execute in order. Each task is atomic and independently testable.

### 3A-1 — CREATE `profiles/printer-conn.json`

- **IMPLEMENT**: ports (990/8883), timeouts, `url_scheme_candidates` (both, with the winner marked
  once the [PRE-FLIGHT GATE](#pre-flight-gate) closes), `upload_dir`, `pushall_min_interval_s: 300`,
  `dispatch_settle_s`, and the fixed `project_file` field defaults.
- **PATTERN**: `profiles/slicer.json` — including its `notes` block explaining *why* a
  counter-intuitive value is correct.
- **GOTCHA**: `bed_leveling`, single `l`. OpenBambuAPI's `bed_levelling` is wrong; Bambu Studio's
  `bambu_networking.hpp` uses one. Put that in `notes`.
- **GOTCHA**: `task_id`/`project_id`/`subtask_id` are the **string** `"0"` — see [C6](#c6).
- **VALIDATE**: `uv run python -c "import json;d=json.load(open('profiles/printer-conn.json'));assert d['source'];print('OK')"`

### 3A-2 — UPDATE `.gitignore` and CREATE `.env.example`

- **IMPLEMENT**: add `!.env.example` **after** the `.env.*` line, then create `.env.example` with
  the three keys, empty, and a comment that the access code changes when Developer Mode is toggled.
- **GOTCHA**: [C9](#c9) — without the negation this file is invisible. Order matters; a negation
  before the pattern does nothing.
- **VALIDATE**: `git check-ignore -v .env.example` must exit **1** (not ignored), and
  `git check-ignore -v .env` must exit **0** (still ignored).

### 3A-3 — CREATE `src/threedp/printer.py` — config, credentials, FTPS

- **IMPLEMENT**: `load_conn_config`, `credentials()` reading `PRINTER_IP`/`PRINTER_SERIAL`/
  `PRINTER_ACCESS_CODE` from the environment, `ImplicitFTP_TLS`, `upload(path) -> UploadResult`.
- **IMPLEMENT**: `upload` waits for `voidresp()` and then re-`LIST`s to confirm the exact byte
  count. Both halves of ADR-14 condition 1 live here.
- **PATTERN**: the snippet in [Patterns to Follow](#patterns-to-follow); `slicer.load_config` for
  the config reader.
- **IMPORTS**: `ftplib`, `ssl`, `os`, `socket`. **No `requests`, no `httpx`.**
- **GOTCHA**: never log, repr or exception-message the access code. `credentials()` returns a
  dataclass whose `__repr__` redacts.
- **GOTCHA**: drop `conn.unwrap()`; **keep** `voidresp()`.
- **VALIDATE**: `uv run pytest tests/test_printer.py -k ftps -v`

### 3A-4 — UPDATE `profiles/slicer.json` for the physical plate

- **IMPLEMENT**: set the process preset's bed type to the textured plate so first-layer temperature
  is correct in the G-code.
- **GOTCHA**: [S23](#s23). `bed_type: "auto"` over MQTT does **not** fix this — the temperature is
  baked into the G-code at slice time.
- **GOTCHA**: changing a preset value risks `return_code -17` if it perturbs `compatible_printers`;
  re-run the slicer suite, do not assume.
- **VALIDATE**: `uv run pytest -m slicer -v` — must **run**, 0 skipped; then confirm
  `curr_bed_type` in a freshly sliced G-code.

### 3A-5 — UPDATE `profiles/printer-p1s.json` from telemetry

- **IMPLEMENT**: `"nozzle_material": "stainless-steel"`, and change `"source"` from
  `"vendor-spec"` to name the telemetry measurement and its date.
- **GOTCHA**: [S17](#s17). Do not silently correct a spec file — the `source` change *is* the
  point, and it is the same discipline `dfm.load_rules` enforces.
- **VALIDATE**: `uv run pytest tests/test_printer.py -k profile -v`

### 3A-6 — ADD `printer.assert_3mf_is_dispatchable(path)`

- **IMPLEMENT**: refuse a 3MF lacking `Metadata/plate_1.gcode`, a non-empty `filament_ids`, or a
  populated `tray_info_idx`. Return the parsed filament list in **3MF order** for `ams_mapping`.
- **GOTCHA**: [C8](#c8)/[S22](#s22). `slice_info.config`'s `filament id` is **1-based**;
  `ams_mapping` is 0-based. Convert once, here, and test the conversion.
- **VALIDATE**: `uv run pytest tests/test_printer.py -k dispatchable -v`

### 3A-7 — ADD `printer.dispatch()` and `accept_dispatch()`

- **BLOCKED BY**: [PRE-FLIGHT GATE](#pre-flight-gate). Do not start until the url scheme is measured.
- **IMPLEMENT**: publish `project_file`; then evaluate ADR-14's four conditions; raise
  `DispatchRejected` naming the failed condition.
- **PATTERN**: `slicer.accept_slice` (lines 302–430) — structure, and error-message voice.
- **GOTCHA**: [S18](#s18) — the refusal arrives as an **echo of your own command with `err_code`
  appended**, within ~1 s. Do **not** whitelist `result`/`reason`/`errno` when listening; that
  filter is what made the first two readings of S18 wrong.
- **GOTCHA**: `err_code == 84033543` (`0502-4007`) must map to a named message —
  *"the printer refused this: Developer Mode is not enabled"* — not to a generic timeout.
- **GOTCHA**: do **not** key on HMS `0500-0500-0001-0007`; this machine never emits it ([S19](#s19)).
- **GOTCHA**: do **not** reconnect while waiting for the echo — [S25](#s25); a mid-dispatch
  reconnect induces a `0500-4003` parse error on the printer.
- **VALIDATE**: `uv run pytest tests/test_printer.py -k dispatch -v` (fakes), then
  `uv run pytest -m printer -v`.

### 3A-8 — ADD `printer.reconcile_ams()` and `PrinterState`

- **IMPLEMENT**: `PrinterState` merges deltas, starts UNKNOWN, raises on access before the first
  `msg == 0` ([ADR-17](#adr-17)). `reconcile_ams` is pure ([ADR-16](#adr-16)) and returns
  BLOCKER/WARNING/NOTE findings.
- **PATTERN**: `dfm.Finding` / `dfm.DfmReport` for the finding shape and severity vocabulary.
- **GOTCHA**: [S16](#s16) is the regression test. Assert that the **exact** shipped drift produces
  a BLOCKER for ABS and PETG and at most a NOTE for slot 0.
- **GOTCHA**: external spool is `vt_tray`, id `254`, and is not an AMS slot.
- **VALIDATE**: `uv run pytest tests/test_printer.py -k reconcile -v`

### 3A-9 — UPDATE `slicer.py` docstring for [C5](#c5)

- **IMPLEMENT**: replace "reverse-indexed" with forward-indexed wording; note the 4–7 second-AMS
  range and 254/255 external. **Change no logic.**
- **VALIDATE**: `uv run pytest tests/test_slicer.py -v` — identical pass count before and after.

### 3A-10 — CREATE `.claude/skills/lril3d-print/SKILL.md`

- **IMPLEMENT**: PRD §9 layer 2. Pre-send summary — render, time, per-slot filament, purge waste,
  reconciliation report — then an explicit confirmation. Refuse to proceed on any BLOCKER.
- **PATTERN**: `lril3d-slice/SKILL.md`. **No thresholds, no payload literals in this file.**
- **VALIDATE**: `uv run pytest tests/test_printer.py -k skill -v` (asserts no numeric thresholds
  in the markdown, mirroring the DFM rule).

### 3A-11 — REWRITE `tests/test_no_printer_path.py` → `tests/test_printer_path_is_narrow.py`

- **IMPLEMENT**: [ADR-15](#adr-15) in full. **Do this before 3A-12**, so the moment the gate
  converts there is already a test asserting the new shape.
- **GOTCHA**: keep importing `REPO`/`strip_strings_and_comments` from `test_one_ruler`; do not copy.
- **GOTCHA**: keep `test_the_scan_actually_covers_something` — a broken glob passes everything
  silently, and this phase adds a module the glob must pick up.
- **VALIDATE**: `uv run pytest tests/test_printer_path_is_narrow.py -v`

### 3A-12 — UPDATE `.claude/settings.json` — the ADR-5 conversion

- **IMPLEMENT**: transcribe the block from `.claude/PRINT-GATE.md` verbatim. Six entries `deny` →
  `ask`; `Read(.env)`/`Read(.env.*)` stay `deny`.
- **GOTCHA**: **not** into `settings.local.json` — gitignored, and PRD §9 requires the guardrail
  committed. The existing migration guard will catch this.
- **GOTCHA**: update `.claude/PRINT-GATE.md` itself — it currently describes the conversion in the
  future tense.
- **VALIDATE**: `uv run pytest tests/test_printer_path_is_narrow.py -v` and full `uv run pytest -q`.

### 3B-1 — CREATE `src/threedp/calibrate.py`

- **IMPLEMENT**: `fit_delta(nominal_d, measured_d, role)` → the delta with its sign convention;
  `build_record(readings, material, gauge, nozzle, date)` → an [ADR-18](#adr-18)-shaped record.
- **GOTCHA**: hole and outer deltas have **opposite signs** and must not be averaged into one
  offset — that is `CLAUDE.md`'s central compensation rule and the reason `coupon` has two kinds.
- **GOTCHA**: pure functions only. No file I/O, no printer.
- **VALIDATE**: `uv run pytest tests/test_calibrate.py -v`

### 3B-2 — ADD rejection of `"measured": true`

- **IMPLEMENT**: in `compensate.load_calibration`, raise on a boolean `measured` with a message
  pointing at [ADR-18](#adr-18)'s date-plus-provenance shape.
- **PATTERN**: `dfm.load_rules` refusing an uncited threshold.
- **VALIDATE**: `uv run pytest tests/test_compensate.py -v`

### 3B-3 — ADD `calibrate.write_record()`

- **IMPLEMENT**: merge one material's record into `profiles/calibration.json`, preserving the other
  materials and the file's formatting.
- **GOTCHA**: never overwrite a measured record with a published default. Refuse and say so.
- **VALIDATE**: `uv run pytest tests/test_calibrate.py -k write -v`

### 3B-4 — CREATE `.claude/skills/lril3d-calibrate/SKILL.md`

- **IMPLEMENT**: the workflow — generate gauge, slice, print via `lril3d-print`, prompt for caliper
  readings **per step**, fit, write, re-export and confirm `stale` is now false.
- **GOTCHA**: `coupon.write_gauge` **refuses a calibration**. The skill must never pass one; the
  gauge is always nominal. Quote the reason, do not paraphrase it.
- **VALIDATE**: manual, per Level 4.

### 3B-5 — PRINT the hole gauge in PLA *(human-in-the-loop)*

- **IMPLEMENT**: `coupon.fit_gauge(kind="hole")` → slice → `lril3d-print` → print.
- **VALIDATE**: part completes; `gcode_state` reaches `FINISH`.

### 3B-6 — PRINT the pin gauge in PLA *(human-in-the-loop)*

- **GOTCHA**: both kinds are required — one gauge cannot measure an asymmetry.

### 3B-7 — MEASURE and record PLA; confirm [C10](#c10) *(human-in-the-loop)*

- **IMPLEMENT**: caliper each step, feed through `calibrate`, write the record.
- **IMPLEMENT**: during 3B-5/3B-6, capture `mc_remaining_time` against wall-clock and **settle
  whether it is minutes**. [S15](#s15) could not — the printer was idle.
- **GOTCHA**: measure each bore in two orientations; an out-of-round bore that reads correctly on
  one axis is exactly what `measure.py`'s circularity gate exists to refuse.
- **VALIDATE**: `uv run python -c "from threedp import compensate; r=compensate.resolve({'D':{'value':10,'role':'hole'}},'PLA_generic'); assert not r.stale; print(r)"`

### 3B-8 — REPEAT for PETG *(human-in-the-loop)*

- **GOTCHA**: ABS is **not loaded** ([S16](#s16)) — leave `ABS_generic` at its published default
  with `"measured": null`. A phase that fabricates the third record to look complete has
  reintroduced exactly the problem this repo exists to solve.

### 3B-9 — UPDATE `CLAUDE.md` and `lril3d-slice/SKILL.md`

- **IMPLEMENT**: Phase 3 status; the [C7](#c7) thumbnail correction; new environment gotchas
  (delta telemetry, `mc_remaining_time` in minutes, the `err_code` echo channel and `0502-4007`,
  `.env.example` negation); Phase 4 boundary.
- **GOTCHA**: link `PRD.md` sections, never copy their text.
- **VALIDATE**: `uv run ruff format --check .`

---

## TESTING STRATEGY

### Unit tests — no hardware

`tests/test_printer.py` runs against fakes and must be **fully green on a machine with no
printer**, mirroring `-m "not slicer"`.

- **Fake FTPS**: a stdlib `ssl`-wrapped socket server, or monkeypatched `ImplicitFTP_TLS`
  asserting `prot_p()` was called, that `unwrap()` was **not**, and that `voidresp()` **was**.
- **Fake broker**: an in-process publish/subscribe double. No real `paho` connection.
- **Real captures**: `tests/fixtures/push_status_full.json` and `push_status_delta.json` from
  [S15](#s15), redacted. The delta fixture is what proves [ADR-17](#adr-17) is necessary — a merge
  tested only against full pushes passes while being wrong.

### Integration tests — `@pytest.mark.printer`

`tests/test_printer_live.py` needs the real P1S and Developer Mode. **These must actually run
here**; report the count and expect 0 skipped. Covers: FTPS round-trip with byte-count
verification, `pushall` → full push, reconciliation against live AMS, and the dispatch path.

### Mutation coverage — the real gate

`printer.py` is not geometry, so it does not slot into the existing benchmarks directly. Two
mutations belong in the suite anyway, both **method** mutations in the sense of
[ADR-8](./phase-2-printability-and-preparation.md#adr-8--dfm-findings-are-scored-by-the-existing-mutation-harness-via-a-measure-kind):

- `method_stale_calibration` — flip a measured record back to `"measured": null` and assert the
  staleness warning fires. Expect **PASS** on the intent (a stale calibration is not a wrong part),
  with the warning asserted separately. This is a false-positive detector.
- `method_ams_drift` — apply [S16](#s16)'s exact drift to a fixture inventory and assert
  `reconcile_ams` produces a BLOCKER. Expect **FAIL**. Without this, [ADR-16](#adr-16) is a
  docstring.

### Edge cases that must be tested

- Dispatch with the printer already `RUNNING` — must refuse (ADR-14 condition 4).
- A delta arriving before any full push — must raise, not report `IDLE`.
- Access code wrong → clear auth error, and **the code must not appear** in the message or traceback.
- Upload interrupted mid-`STOR` → byte count mismatch → refuse.
- `ams_mapping` requesting a material in no slot — already refuses; keep the test.
- A 3MF with empty `filament_ids` → refuse ([C8](#c8)).
- `mc_remaining_time` absent → **UNKNOWN**, never `0`.

---

## VALIDATION COMMANDS

Every command runs from the repo root. Levels 1–3 are gates.

### Level 1 — syntax, style, and the root import gate

```bash
uv run ruff check . && uv run ruff format --check .
uv run python -c "import sys; assert sys.version_info[:2]==(3,13), sys.version; from threedp import measure, features, intent, render, compensate, parts, io, printability, dfm, repair, slicer, gcode, coupon, printer, calibrate; print('OK', sys.version)"
```
**Pass signal:** `All checks passed!`, `N files already formatted`, and `OK 3.13.x`.

### Level 2 — unit tests, no hardware

```bash
uv run pytest -m "not slicer and not printer" -q
```
**Pass signal:** exit 0, zero failures. This is the "someone cloned the repo" gate.

### Level 3 — the hardware layers, which must actually run

```bash
uv run pytest -m slicer -v      # expect the Phase 2 count, 0 skipped
uv run pytest -m printer -v     # expect > 0 collected, 0 skipped
uv run pytest -q                # full suite; baseline is 353 collected, 0 failures
```
**Pass signal:** `-m printer` reports a **non-zero** count with **0 skipped**. A skipped printer
layer wearing a green badge is the exact failure `CLAUDE.md` calls out for the slicer.

### Level 3b — the real gate, the mutation suite

```bash
uv run python benchmarks/run_mutations.py
```
**Pass signal:** current baseline is `caught 19/19 missed 0 false-positives 0 harness-errors 0`
over **28 mutations across 6 benchmarks**. After adding the two method mutations above, expect
`caught 20/20` over **30**. *Zero mutations found is a FAILURE, not a pass.*

> **Note:** `CLAUDE.md` currently says "27-mutation suite" and "over 27 mutations" in three places;
> the harness reports **28**. `dfm_slender_pin.py` was added after that text was written. Correct
> it in task 3B-9.

### Level 4 — manual validation

1. Developer Mode ON, `.env` updated with the **new** access code.
2. `lril3d-print` on a verified part: confirm the pre-send summary shows time, per-slot filament,
   purge waste and the reconciliation report **before** any confirmation prompt.
3. Decline once — confirm nothing is uploaded and nothing is published.
4. Accept — confirm `gcode_state` leaves `IDLE` and the **P1S screen shows a real preview**
   ([C7](#c7)).
5. Confirm `filaments.json` drift ([S16](#s16)) blocks a PETG or ABS dispatch until corrected.

### Level 5 — additional

`lril3d-viewer` alongside a live print for a visual cross-check. **Channel, not gate** — it never
contributes to a pass verdict.

---

## ACCEPTANCE CRITERIA

- [ ] `printer.py` uploads over implicit FTPS and verifies the byte count on the printer.
- [ ] A dispatch is accepted only on all four [ADR-14](#adr-14) conditions; the exception names
      which failed.
- [ ] The `err_code` echo is read whole ([S18](#s18)); `0502-4007` produces a named
      Developer-Mode message within seconds, not a generic timeout.
- [ ] A regression test asserts the listener does **not** whitelist `result`/`reason`/`errno` —
      the exact filter that made S18's first two readings wrong.
- [ ] `reconcile_ams` BLOCKS the exact [S16](#s16) drift for ABS and PETG; slot 0's colour-only
      difference is at most a NOTE.
- [ ] `PrinterState` raises rather than reporting `IDLE` before the first full push.
- [ ] The access code appears in no log, `repr`, exception or test output.
- [ ] `.claude/settings.json` has the six entries under `ask`, `Read(.env)` still under `deny`,
      and `test_printer_path_is_narrow.py` asserts exactly that.
- [ ] The network-import ban still holds for all modules except `printer.py`.
- [ ] `uv run pytest -m printer -v` runs with **0 skipped**.
- [ ] `PLA_generic` and `PETG_generic` carry an ISO `measured` date, a `source`, the nozzle, and
      raw readings. `ABS_generic` is **untouched** and still `null`.
- [ ] Mutation suite green at its new baseline with both new method mutations.
- [ ] `PRD.md` corrections [C5](#c5)–[C10](#c10) recorded in `CLAUDE.md`.

---

## COMPLETION CHECKLIST

- [ ] All tasks completed in order; the [PRE-FLIGHT GATE](#pre-flight-gate) closed before 3A-7
- [ ] Each task's validation passed immediately
- [ ] Levels 1, 2, 3, 3b all executed and reported with counts
- [ ] Manual Level 4 walkthrough done, including the decline path
- [ ] No linting or format errors
- [ ] `CLAUDE.md` updated — Phase 3 status, new gotchas, mutation count corrected
- [ ] Acceptance criteria all met, or explicitly listed as not met with reasons

---

## NOTES

**Why the gate conversion is task 3A-12 and not 3A-1.** ADR-5 says the `deny` → `ask` conversion
arrives *with* `lril3d-print`. "With" is doing real work: converting first leaves a window where the
guardrail is down and the capability is half-built. Converting last means the guardrail is only
relaxed once the thing it guards exists and is tested.

**Why [S16](#s16) is the most important finding in this phase.** It is not a bug in new code — it is
a defect in *shipped, tested, green* code, found only because the printer became readable. The
Phase 2 tests for `ams_mapping` are correct and pass; they test that the function maps its input
faithfully. Nothing tested that the input was true. That is precisely the gap `intent.json` closes
for geometry, and [ADR-16](#adr-16) closes the same gap for filament.

**Why [S18](#s18) records three readings instead of one.** The first two were wrong in the same
direction — the listener filtered for `result`/`reason`/`errno`, the printer answers with
`err_code`, and the missing field was read as *"the printer said nothing"*. A malformed-command
control probe then appeared to confirm it, because that too produced no *matching* field. Two
mutually reinforcing wrong readings from a single filtering bug, and both were plausible.

That is the repository's own thesis pointing back at its instrumentation: **a measurement apparatus
that silently drops what it was not expecting reports a confident, plausible, wrong result.** The
plan keeps all three readings because an executor who sees only the conclusion will rebuild the
same listener. It is also why `tests/test_printer.py` asserts the *absence* of a field whitelist
rather than merely testing the happy path.

**What Phase 3 deliberately does not do.** No cloud, no remote monitoring, no camera stream (port
6000 is open — [S13](#s13) — and it stays unused), no print queue, no multi-printer. `bed_type`
stays `"auto"`. The abrasive-nozzle DFM rule suggested by [S17](#s17) is Phase 4, and is noted here
only so it is not lost.

**A known limitation to state rather than paper over.** Reconciliation compares *material names*
reported by AMS RFID. A non-Bambu spool in an AMS slot reports `tray_info_idx` poorly or not at
all, so reconciliation degrades to "unknown material in this slot" — which must be a BLOCKER when
that slot is used, not a silent pass. This machine currently has all-Bambu spools, so the
degraded path is **untested against real hardware** and must be marked as such.

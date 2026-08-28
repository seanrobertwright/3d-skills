# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: Phase 3A done; Phase 3B is machinery-only until two coupons are printed

The `threedp` package, eight skills, the viewer, 6 benchmarks and a 30-mutation suite are in place.

**Phase 3A ships the send path, end to end, verified on the real printer.** `printer.py` (implicit
FTPS + MQTT), `lril3d-print`, AMS reconciliation, and ADR-5's `deny` → `ask` conversion in
`.claude/settings.json`. Measured 2026-08-02 with LAN Developer Mode on: a 135,820-byte 3MF
uploaded and byte-count-verified, `project_file` published as `ftp:///{name}`, the echo captured,
and `gcode_state` left `IDLE` for `PREPARE` in **5.8 s** — all four ADR-14 conditions satisfied —
then stopped before the first layer.

**Phase 3B ships the calibration machinery and none of the calibration.** `calibrate.py` is
complete and tested; all three records in `profiles/calibration.json` are still published defaults
with `"measured": null`, because replacing them requires printing two coupons and measuring them
with a caliper. `calibrate.stale_materials()` lists what is still owed. `ABS_generic` is not
merely outstanding — **no ABS is loaded**, so it cannot be measured here at all.

- **`PRD.md` is the source of truth.** Link to its sections; do not copy its text into new docs.
  `PRD.md` is excluded from `ruff format` on purpose — ruff formats fenced Python blocks and
  rewrote its API-specification snippet on first run.
- **`.agents/plans/phase-1-verification-loop.md`**,
  **`.agents/plans/phase-2-printability-and-preparation.md`** and
  **`.agents/plans/phase-3-printer-and-calibration.md`** are the implementation plans, each backed
  by a spike run on this machine. They contain measured numbers, PRD corrections, and ADRs 1–18.
  Read the relevant one before implementing anything.
- **The slicer is Bambu Studio, not OrcaSlicer** (Phase 2 correction C1). `PRD.md` §12 and §7 name
  OrcaSlicer; it is not installed on this machine and Bambu Studio is, with the complete BBL
  vendor profile tree. OrcaSlicer is a Bambu Studio fork sharing the CLI surface, so
  `profiles/slicer.json` holds the executable candidates and a second backend stays config rather
  than a rewrite.

## What this project is

Claude Code skills that take a plain-language description of a physical object to a printable part.
The differentiator is **not** the CAD binding — a dozen OpenSCAD/CadQuery wrappers already exist.
It is the **verification loop**: *understand → confirm → model → measure against intent → iterate*.

The founding observation: an agent that generates confident, plausible, **wrong** geometry is the
default, and bounding boxes, volumes, and renders all fail to detect it. Measurement against
intent recorded *before* the geometry existed is what catches it.

## Architecture

**Thin skills, thick library.** `SKILL.md` files handle intent recognition, user interaction, and
narration. All geometry, measurement, and rendering lives in the `threedp` Python package, which is
testable without an agent. Never put geometry or measurement logic in a `SKILL.md`.

### The artifact relationship (the thing worth understanding first)

```
intent.json      <- WRITTEN FIRST, before any geometry, from parts-DB citations
                    and explicit user confirmation
model.py         <- parametric build123d program
params.json      <- each dimension tagged with a semantic role: hole | outer | neutral
   |
   +-- resolve(nominal)      -> out/*.step   nominal geometry, valid CAD, portable
   +-- resolve(calibration)  -> out/*.stl    compensated for THIS printer + material
```

Three consequences that are easy to get wrong:

- **Nominal geometry is the truth.** The STEP describes the part, never the
  part-plus-this-printer's-error. Compensation must never leak into CAD output.
- **Compensation is applied to *parameters*, not geometry.** Hole and outer deltas have opposite
  signs and need not reconcile into a single offset — that is the whole point.
- **Models are programs.** Changing 40mm to 45mm is an edit, never a regeneration.

### The Phase 2 layers, and where each one refuses

```
printability.py   measures  ->  dfm.py       compares against profiles/dfm-rules.json (cited)
repair.py         fixes     ->  verify()     re-measures; a moved dimension is a FAILED repair
slicer.py         runs it   ->  accept_slice ADR-10's four conditions; a 0.00 g result is refused
gcode.py          parses    ->  viewer       a channel, never a gate
```

Three rules that are easy to erode:

- **`dfm.py` performs no measurement and holds no threshold.** New measurements go in
  `printability.py`; thresholds go in `profiles/dfm-rules.json` **with a `source`**. Separated,
  tuning a rule is a JSON edit that cannot touch a measurement.
- **DFM gates only where an `intent.json` asserts `dfm_violation_count`** (ADR-8). DFM is advice
  about a *process*; intent is a claim about a *part*.
- **Only BLOCKER gates.** A WARNING is reported with its number and does not fail a part.

### The Phase 3 layers, and where each one refuses

```
printer.upload        transfers ->  226 AND a byte count read back off the printer
printer.reconcile_ams compares  ->  profiles/filaments.json vs live AMS telemetry (ADR-16)
printer.PrinterLink   listens   ->  the whole echo, never a whitelist of ack field names
printer.accept_dispatch judges  ->  ADR-14's four conditions; a still-IDLE printer is refused
calibrate.fit_deltas  fits      ->  ONE offset per role, or a refusal naming the spread
```

Four rules that are easy to erode:

- **`reconcile_ams` performs no I/O and `ams_mapping` knows nothing about the printer.** The claim
  and the check are separate on purpose; mixing them would put I/O inside a pure function and give
  the mutation suite nothing clean to bite on.
- **UNKNOWN is never IDLE.** Telemetry arrives as one full push and then deltas — the smallest
  real delta captured here carries four keys and none of them is `gcode_state`. `PrinterState`
  raises until a full push lands rather than defaulting.
- **A refusal arrives as an echo of your own command, not as an ack.** Never filter the reply
  channel by field name. This one is not hypothetical: it produced two consecutive wrong readings
  during the spike, and a control probe appeared to confirm both.
- **Hole and outer deltas are fitted separately and never pooled.** One formula
  (`nominal - measured`) produces both, with opposite signs, which is the point.

### Verification tiers — by feature type, not representation

| Tier | Features | Guarantee |
|---|---|---|
| 1 | Axis-aligned regular features (bores, pockets, planes) | Dimensional, ±0.005mm. Full `intent.json` checking. |
| 2 | Freeform / organic surfaces | Topology + statistics only. Dimensional claims labelled **ESTIMATE**. |

A mesh-derived dimension is Tier 1 only if the circle fit passes the circularity gate **and** the
measured axis is within 1° of Z. Circularity alone is not enough: a Ø22 bore tilted 5° sections as
an ellipse whose residual is 0.042 mm — *inside* the 0.05 mm gate — while its diameter is inflated
by 0.084 mm. `features.py` measures the axis from centre drift between two sections to catch it.

BREP does *not* rescue freeform geometry, and mesh probing *is* Tier 1 for regular features. The
axis of difficulty is the kind of feature, not STEP-vs-STL.

### The mutation suite is the gate, not the benchmarks

Benchmarks passing proves nothing about the verifier if the verifier is only exercised by parts
that happen to be correct. `benchmarks/*/mutations/` inject known defects with declared expected
verdicts, and the verifier is scored on **caught / missed / false-positive**.

Two classes, both required: **geometry mutations** (a dimension is wrong) and **method mutations**
(the *ruler* is wrong). Geometry mutations structurally cannot catch a bad ruler.

## Non-negotiable rules

- **There is exactly one ruler.** All dimensional measurement flows through `src/threedp/measure.py`.
  Ad-hoc measurement elsewhere is prohibited and mechanically enforced by `tests/test_one_ruler.py`.
  Max-radius and bounding-box methods are banned for dimensional assertions — two improvised
  implementations once disagreed by 0.088mm, more than a press-fit tolerance.
- **A circle fit must never yield a diameter without a circularity check.** A square 20×20 pocket
  fits as a confident "24.4949mm circle". `CircleFit.diameter` raises unless `is_circular`.
- **There is exactly one way out to a printer, and it is `printer.py`.** The Phase 1–2 rule was
  "no module reaches a printer"; Phase 3 narrows it rather than lifting it (ADR-15). Every other
  module is still banned from importing a network module, a *second* send path anywhere fails the
  suite, and the one `subprocess` call is still the discovered slicer — all of it mechanical, in
  `tests/test_printer_path_is_narrow.py`, not agent discipline.
- **A print needs a human yes, in the conversation, for that part.** `.claude/settings.json`'s
  `ask` rules are the weaker half of the gate: they catch a shell command routing around the
  library and cannot see a Python call. `lril3d-print`'s pre-send summary is the half that matters.
- **The inventory is a claim and it is checked against the printer before every dispatch**
  (ADR-16). It shipped through two phases disagreeing with the AMS in four of five slots, green
  the whole way, because nothing had ever asked the printer.
- **A calibration record carries a date, not a boolean.** `"measured": true` satisfies the
  staleness check and discards the date, the nozzle and the gauge — the whole content of the
  claim — so `compensate.load_calibration` refuses it (ADR-18).
- **Every DFM threshold carries a `source`.** `dfm.load_rules` refuses an uncited one, exactly as
  `parts.get` refuses an unknown key. A threshold in Python or in a `SKILL.md` is a threshold
  outside the config and outside the tests.
- **A repair is not complete until it is re-measured.** `repair()` never returns a mesh alone, and
  "it is watertight now" is not a verdict — a bridged bore is watertight.
- **A slice result is accepted on four independent conditions or not at all.** Each one alone was
  measured being satisfied by a failed run.
- **Absent features FAIL with a reason — never skip.** A missing counterbore *is* the defect.
- **Renders are a channel, not a gate.** They never contribute to a pass verdict.
- **All dimensions are millimetres.** Suffix a variable only when it is *not* mm (`angle_deg`).
- **Report numbers, never impressions.** Every claim carries a measured value or an explicit
  ESTIMATE label.

## Environment gotchas (measured on this machine, 2026-07-30)

These each cost real debugging time. All were verified empirically.

- **Pin Python to `==3.13.*`, not `>=3.13`.** This machine's default is **3.14.6**; `bpy` ships
  cp313 wheels only. `>=3.13` lets uv resolve 3.14 and the install fails.
- **PyPI `sdf` is the wrong package** — it is "Scientific Data Format". fogleman's SDF library is
  git-only: `sdf = { git = "https://github.com/fogleman/sdf" }`.
- **Skills must live in `.claude/skills/<name>/SKILL.md`.** A root-level `skills/` directory is
  never discovered. (`PRD.md` §6 shows the wrong path.)
- **`lxml` is required to read 3MF** with trimesh and is not pulled in transitively.
- **`Path3D.to_planar()` is deprecated past its removal date** → use `to_2D()`. Likewise
  `Scene.dump(concatenate=True)` → `Scene.to_geometry()`. A `.3mf` loads as a `Scene`, not a `Trimesh`.
- **Never use `face.center()` for hole position.** It defaults to `CenterOf.GEOMETRY`, which for a
  cylindrical face is a point *on the surface* — wrong by exactly the radius, and wrong plausibly.
  Use the OCCT axis: `BRepAdaptor_Surface(f.wrapped).Cylinder().Axis()`.
- **Shapely closes rings by repeating the first vertex.** Strip it before any centroid. Including
  it inflates a fitted diameter by 0.088mm.
- **Overhang angles are measured from vertical** (0 = vertical wall, 90 = horizontal ceiling).
  Exclude build-plate-contact faces, and give the top histogram bin an inclusive upper bound or
  exactly-horizontal ceilings — the worst case — fall out entirely.
- **`sdf` writes a progress bar to stdout**; do not parse its stdout as data. It does *not* need a
  `__main__` guard despite forking workers. It also emits a **triangle soup** — the raw mesh reads
  as non-watertight until coincident vertices are merged (`merge_vertices`), after which it has
  zero broken faces. Merge, then *verify*; never export the raw output.
- **Least-squares is insensitive to Shapely's duplicate vertex; max-radius is not.** Measured on
  the same 253-point ring: LSQ 29.9973 with and without it, max-radius 30.1387 vs 30.0249. The
  0.088mm bug is specifically *centroid + max-radius*, which is why the duplicate-stripping line
  in `fit_circle` is belt-and-braces rather than load-bearing — and why a mutation asserts exactly
  that.
- **A parts-db citation names a key, not a category.** Heat-set keys are suffixed `-insert`
  (`parts-db:M3-insert.hole_d`) so they cannot collide with `parts-db:M3.clearance`. A shared key
  would resolve to whichever table came first — silently, to a plausible wrong number. Enforced at
  import by `parts._assert_keys_are_globally_unique`.
- **Two mesh-path traps that produce phantom features**, both found on real benchmarks:
  a Z-scan reports a cone as a stack of perfectly circular "cylinders" (fixed by measuring taper
  between two sections), and the crown strip of a bore drilled along Y is exactly flat and exactly
  horizontal without being a face (fixed by rejecting facets with shallow-angle neighbours).

### Phase 2 additions (measured 2026-07-31 / 2026-08-01)

Bambu Studio CLI — each of these was reproduced on this machine:

- **The CLI writes 0 bytes to stdout on every run.** `result.json` is the machine-readable
  channel and it is written even on failure. Never parse stdout as data.
- **The BBL system presets are not self-contained and the CLI does not walk `inherits`.** The leaf
  `Bambu PLA Basic @BBL P1S 0.4 nozzle.json` has 23 keys and no `filament_density`; the value 1.26
  lives two files up and `fdm_filament_common`'s **0** is what ships. Unflattened, the slice
  *succeeds* and reports `0.00 g`. `slicer.flatten_preset` resolves the chain, root first.
- **Flattening must keep the original preset `name`.** A process preset's `compatible_printers` is
  a list of printer *names*; renaming the machine gives `return_code -17`.
- **`--export-3mf` needs a relative filename with `cwd` set.** An absolute path returns `-13`
  *while still writing a perfectly good `plate_1.gcode`* — so never infer success from a file.
- **`return_code 0, "Success."` on a slice that produced nothing.** `--slice 3` on a single-plate
  model writes a `result.json` with no `sliced_plates` key and no G-code at all. Hence ADR-10's
  four independent acceptance conditions.
- **`total_predication` is not reliably a top-level key.** Slicing a `.3mf` puts it at the top
  level; slicing a `.stl` puts it only inside each `sliced_plates` entry. Read per-plate first,
  then top level, then the G-code header — and refuse rather than report `0s`.
- **The G-code header's volume unit label is wrong**: `; total filament volume [cm^3]` is mm³.
  3580.16 mm × π(1.75/2)² = 8611 mm³ = 8.611 cm³ × 1.26 = 10.85 g, which is the mass in the same
  header. The field is named `volume_mm3`; do not "fix" it back.
- **Bambu's markers are not PrusaSlicer's.** `; FEATURE:`, `; CHANGE_LAYER`, `; Z_HEIGHT:` — with
  a leading space. A parser written to `;TYPE:`/`;LAYER_CHANGE` finds *zero* of each and produces
  an empty preview that looks like an empty part. Bambu also uses **relative E** (`M83`).
- **CLI G-code contains no thumbnail block at all** — one `; thumbnail_size = 50x50` config line
  and nothing else (PRD correction C2). Still true, and **narrower than it was written**: the
  *3MF* from the same run carries `Metadata/plate_1.png` at 512×512 with 116 distinct byte values
  and std 55.87 — a real render, not a flat fill. Phase 3 sends the 3MF, so the screen preview is
  not blank (correction C7). A blank preview means the wrong artefact went across.

Repair:

- **`trimesh.repair.fill_holes` fills only tris and quads unless `use_fan=True`.** The fan is the
  hazard ADR-9 exists for, and declining it would make repair unable to close any real hole; the
  two passes are separate ops so the report says which one closed the mesh.
- **Fix inversion only *after* filling holes.** Inversion is detected from the sign of the
  enclosed volume, and an open surface does not enclose one — trimesh's own note is that
  `fix_normals` is "really only meaningful on watertight meshes". Run in the intuitive order the
  pipeline returned a **watertight mesh of −23065.76 mm³**: closed, plausible, and inside out,
  with every upward face reading as a 90° overhang to the DFM engine downstream.
- **An inverted mesh passes almost every check.** Watertight, winding-consistent, every bore
  sections as a perfect circle. Only the sign of the volume sees it, which is why
  `benchmarks/imported-mesh/intent.json` asserts `solid_volume: [1.0, null]` — a topology claim,
  open above so it cannot smuggle in a golden volume.

DFM:

- **A flared cone meets its own top face at a knife edge** — measured at 0.006 mm of material —
  which is a real `min_feature` BLOCKER and will mask whatever else you were testing. Give a test
  flare a collar.
- **`min_wall_mm` and `min_feature_mm` share one ray cast**, because a ray cannot tell a thin wall
  from a thin pin. They stay separate rules because the *fix* differs; expect them to fire
  together.

### Phase 3 additions (measured 2026-08-02 against the real P1S)

- **The refusal channel is an echo, not an ack.** `project_file` is answered by the whole command
  echoed back with an **`err_code`** field appended — no `result`, no `reason`, no `errno`. A
  listener that whitelists ack field names sees nothing and reports a timeout. This produced two
  consecutive wrong readings ("accepted in silence"), and a deliberately malformed control command
  appeared to confirm them, because that too produced no *matching* field. **Capture every
  non-status reply whole.**
- **`err_code 84033543` is `0x05024007` = `0502-4007`, the LAN authorization refusal.** Bambu
  document HMS `0500-0500-0001-0007` for this and **this machine never emits it**; do not key on
  the documented code. The refusal arrives in about a second, so a dispatch failure is detectable
  without waiting out a timeout.
- **The rejection happens before the url is parsed.** Eight `project_file` variants — including
  `file:///mnt/sdcard/...`, which does not exist, and a bare filename — returned *identical*
  `0502-4007`. A file-or-path error cannot be invariant across those.
- **The access code changes when you toggle Developer Mode.** A code that worked before the toggle
  is not evidence it is current.
- **`ftplib`'s `storbinary` calls `conn.unwrap()` and this firmware often never answers
  `close_notify`**, so the call hangs forever. Drop the unwrap; **keep the `voidresp()`** — without
  it the transfer truncates silently and the printer answers `0500-C010` on a file that is perfect
  locally. Data-channel TLS **session reuse** is also required (`require_ssl_reuse`), and `ftplib`
  has never supported it (cpython#63699), so `ntransfercmd` must be overridden.
- **The FTPS welcome banner does not contain `vsFTPd`.** Do not fingerprint on it.
- **Telemetry is one full push (`msg == 0`) and then deltas.** Measured: 1 full push and 10 deltas
  in 45 s, and the smallest delta carries **four keys** — `bed_temper`, `command`, `msg`,
  `sequence_id`. Nothing that identifies state. Code that defaults its missing fields reports a
  confident `IDLE` about a printer it knows nothing about.
- **A silent telemetry channel is not a broken one.** Deltas are emitted *when something changes*.
  A thermally settled idle printer sends **nothing at all** — measured 2026-08-04: 0 deltas in
  30 s, where the same test saw a steady stream an hour earlier while the bed was still cooling.
  A test that asserts "a delta arrives within N seconds" is inventing a cadence the protocol never
  promises, and one here did exactly that and failed. What *is* guaranteed, and what ADR-17 rests
  on, is that the full state arrives **once** and is never re-sent unprompted.
- **`mc_remaining_time` is in MINUTES** (correction C10) — **settled on hardware 2026-08-03**, not
  from source. On a part the slicer estimated at 8m46s the printer reported `8` and counted down
  `8 → 7 → … → 0` across the print. As seconds it would have read ~526. Reading it as seconds is a
  silent 60× error; pybambu's `timedelta(minutes=...)` agrees. An **absent** field is UNKNOWN,
  never `0`.
- **`task_id` / `project_id` / `subtask_id` are the string `"0"`** (correction C6). Firmware
  `01.10.00.00` clamps task-identity fields to 2³¹−1, so an epoch-ms id collides and the printer
  treats a new dispatch as a continuation of the previous FAILED job.
- **`bed_leveling`, one `l`.** OpenBambuAPI's `bed_levelling` is wrong; Bambu Studio's
  `bambu_networking.hpp` uses one — and a misspelled key is ignored, not rejected.
- **A `project_file` ack can exceed 15 s, and reconnecting while you wait induces `0500-4003` on
  the printer.** Wait generously; never tear the link down mid-dispatch.
- **`pushall` is rate-limited.** Bambu warn against polling the P1 under five minutes.
- **AMS slot numbers are `ams_id * 4 + tray_id`**, so a second unit occupies 4–7; the external
  spool is `vt_tray` at **254** and is not an AMS slot (correction C5). `ams_mapping` is
  **forward**-indexed — array *position* is the 3MF filament index, array *value* is the slot —
  and PRD §9 and the old docstring both called it "reverse-indexed" while describing forward
  indexing in the next clause. Bambu Studio's `DevMapping.cpp` settles it.
- **`.gitignore`'s `.env.*` swallows `.env.example`** (correction C9). It needs an explicit
  `!.env.example` **after** the pattern. Note that `git check-ignore -v` exits 0 on a negation
  match; use `git check-ignore -q`, which exits **1** for a file that is not ignored.
- **The CLI slices for the *Cool* plate unless told otherwise** (S23). `default_bed_type` lives in
  the printer-*model* json, which `--load-settings` does not walk, so `curr_bed_type` defaults to
  `Cool Plate` and a 35 °C first layer is baked into the G-code for a machine with a textured PEI
  plate. `profiles/slicer.json`'s `preset_overrides` fixes it; verified as `M190 S55`.
  **`bed_type: "auto"` over MQTT does not help** — the temperature is set at slice time.
- **Our own 3MF does carry filament ids** (correction C8): `filament_ids: ['GFA00']` in
  `project_settings.config` and a populated `tray_info_idx` in `slice_info.config`. The trap PRD §9
  records traces to *OrcaSlicer's* CLI, which this repo does not use — but `slice_info.config`'s
  `filament id` is **1-based** while `ams_mapping` is **0-based**, and that seam is real. Convert
  once, in `printer.assert_3mf_is_dispatchable`.
- **`chamber_temper` reads 5 beside `bed_temper` 19.375 in the same push.** Unexplained and not
  believed to be °C. Nothing surfaces a chamber temperature until it is understood.

Measured *after* Developer Mode was enabled, on 2026-08-02:

- **An echo with no `err_code` is not a started job.** `project_file` for a filename that is **not**
  on the SD card is echoed back with no `err_code` at all, sets `subtask_name` on the printer, and
  leaves `gcode_state` at `IDLE`. ADR-14 conditions 1 and 2 satisfied, no print. This is the case
  condition 3 exists for, and it is now a live regression test.
- **`print_error` is non-zero after a normal stop** — `83902467` = `0500-8003`. It is the record of
  the cancellation, not a fault, so nothing in `accept_dispatch` keys on `print_error`.
- **"not RUNNING" is not "stopped".** A job cancelled during `PREPARE` was never `RUNNING`, so a
  predicate waiting for `gcode_state != "RUNNING"` is satisfied instantly and returns while the
  machine is still heating. Wait for the *idle set* (`IDLE`/`FINISH`/`FAILED`). A stopped job
  reports `FAILED`.
- **A byte count is not the bytes.** ADR-14 condition 1 originally checked the `226` and the size
  the printer's `LIST` reported. That is the filesystem's *claim* about a file's length; on a card
  that is failing it and the contents diverge. The upload now downloads the file again and hashes
  it (`ftps.verify_md5`), and a file that cannot be read back counts as a mismatch rather than as
  "unverified". Measured 2026-08-04 on this machine's actual card: 62 files downloaded and hashed,
  every one at exactly its claimed size, **zero read failures** — so the FTPS read path was clean
  even while the printer was reporting an SD card error. That is the point: the check is cheap,
  and "it read back fine over FTP" does not clear a card either.
- **⚠⚠ THE PRINTER REPORTS `FINISH` AT 100% FOR A PART THAT DOES NOT EXIST.** Measured
  2026-08-03, and it is the most important thing in this phase. A job ran **30 of 30 layers**,
  `mc_percent 100`, `gcode_state FINISH`, `print_error 0`, `hms` empty — and produced nothing,
  because no filament was ever loaded. `hw_switch_state` (the toolhead's own filament sensor,
  pybambu's `extruder_filament_state`) stayed **0**, and `ams.tray_now` / `tray_tar` stayed
  **255**, for the entire run. The AMS never targeted a tray and the machine traced the toolpath
  through air for nine minutes.

  **Not one field the printer publishes dissents.** Return code, percentage, layer counter, error
  field, fault list — all agree the print succeeded. This is the repository's founding failure
  arriving at the last possible layer, and no amount of protocol correctness makes a machine's
  self-report into evidence about an object. So `PrintOutcome.finished` requires `FINISH` **and**
  filament seen at the extruder, and `watch()` says "NO PART" in as many words.

  **The root cause is open.** `ams_mapping2` was missing from the `project_file` payload —
  Bambu Studio sends it, `bambu_networking.hpp` declares it beside `ams_mapping`, and the
  firmware needs it to turn a global tray number into `{ams_id, slot_id}`. It has been added.
  **A re-run with it present still resolved no tray and still loaded nothing**, so it was *a*
  defect and is not *the* defect. Recorded as open rather than closed: a plausible cause standing
  in for a measured one is exactly what this project exists to refuse, and that does not change
  when the subject is our own code. Next step is the physical AMS path, not more payload fields.
- **⚠ `RUNNING` at 0% and layer 0 is normal for about nine minutes.** Measured on a completed
  print: `PREPARE → RUNNING` at t+6 s, then bed levelling and a 75 °C nozzle wipe, heat to 205 °C
  at t+520 s, and the **first extrusion at t+558 s**. So `mc_percent` and `layer_num` sit at zero
  for over nine minutes *while the printer is RUNNING and working correctly*. Anything that reads
  "0% after five minutes" as a stall is wrong, and a watcher whose timeout is shorter than the prep
  gives up on a healthy print.
- **`bed_target_temper` reaches 55 °C**, confirming the S23 textured-plate fix on hardware — the
  cool-plate default would have baked in 35 °C.
- **⚠ All four ADR-14 conditions can be satisfied by a job that prints nothing.** Measured: a
  dispatch was accepted — upload byte-verified, echo clean, `gcode_state` left `IDLE` for
  `PREPARE`, `subtask_name` ours — and the printer then returned to `IDLE` having laid **0 of 30
  layers**, `print_error 0500-8003`, `hms` empty. `PREPARE` is transient: the machine is heating,
  homing and levelling, and the job can be abandoned there or stopped by a human at the panel. So
  `accept_dispatch` claims only that *a dispatch landed*; `printer.watch()` is what reports whether
  a part exists, and `PrintJob.__str__` says so on its own second line. **This is the founding
  failure mode of the repository arriving in the newest layer** — a confident, plausible, wrong
  report of a successful print — and it was caught by watching the machine rather than the code.

## Commands

```bash
uv sync --extra dev                       # install; resolves on Python 3.13
uv run ruff check . && uv run ruff format --check .
uv run pytest -v                          # full suite
uv run pytest tests/test_measure.py -v    # one file
uv run pytest tests/test_measure.py::test_duplicate_vertex -v   # one test
uv run pytest -k circular -v              # by keyword
```

**Root import + interpreter gate** — the single check that catches a wrong interpreter and any
cross-module import breakage:

```bash
uv run python -c "import sys; assert sys.version_info[:2]==(3,13), sys.version; from threedp import measure, features, intent, render, compensate, parts, io, printability, dfm, repair, slicer, gcode, coupon, printer, calibrate; print('OK', sys.version)"
```

**The slicer layer is a gate, not a formality.** `slicer`-marked tests need Bambu Studio; a green
suite with them skipped is not evidence the wrapper works:

```bash
uv run pytest -m slicer -v        # must RUN here: report the count, expect 0 skipped
uv run pytest -m "not slicer" -q  # green on a machine with no slicer
```

**The printer layer is the same kind of gate**, and it needs the P1S on the LAN with `.env`
filled in. It has exactly **two** legitimate skips, and both **start a real print**, so both are
gated behind `THREEDP_APPROVE_A_REAL_PRINT=yes`: `test_the_url_scheme_matrix` and the full
dispatch round-trip. Those skips guard a physical action, not a missing dependency; every other
test in the file must run.

```bash
uv run pytest -m printer -v        # must RUN here; 10 pass, 2 skip (both physical-print gates)
uv run pytest -m "not printer" -q  # green on a machine with no printer
```

**The real gate** — the mutation suite. A green `pytest` with this skipped is *not* evidence the
verifier works:

```bash
uv run python benchmarks/run_mutations.py                      # all benchmarks
uv run python benchmarks/run_mutations.py --part bearing-holder
uv run python benchmarks/run_mutations.py -v                   # full report on any failure
```

Pass signal: `caught 20/20   missed 0   false-positives 0   harness-errors 0` over **30**
mutations across 6 benchmarks. (Earlier revisions of this file said 27; the harness has reported
28 since `dfm_slender_pin` was added, and Phase 3 brought it to 30.)
**If it reports zero mutations found, that is a FAILURE, not a pass** — a skipped layer wearing a
green badge. Mutations run against the **mesh** export: a BREP face query never fits a circle, so a
measurement-method mutation cannot bite there. The harness cross-checks STEP against STL on every
baseline build so the BREP path is not left unexercised.

Not every mutation expects FAIL. `cosmetic_*` mutations expect **PASS** and are the false-positive
detectors — a verifier that fails them cries wolf on every real part, which is a slower route to
the same place as no verifier at all.

**CI runs the three hardware-free lanes and nothing else** — `.github/workflows/verify.yml`, on
every push to `master` and every pull request: ruff, the interpreter/root-import gate,
`pytest -m "not printer and not slicer"`, and the mutation suite. `-m slicer` and `-m printer` stay
local and permanently so — **and CI asserts they were *deselected*, not skipped.** A hardware test
that skips itself for want of hardware produces a green check over nothing, which is the same
failure as no check at all wearing a better badge. The workflow itself is asserted by
`tests/test_ci_runs_the_gates.py`, for the reason `.claude/settings.json` is: a guardrail that
lives only in config is one edit from being gone.

- **A test needing the slicer escaped the `slicer` marker for two phases, and only a machine
  without Bambu Studio could see it.** `test_the_real_profile_tree_flattens_to_the_measured_density`
  reads the installed BBL profile tree and skips itself when it is absent — but carried no marker,
  so it lived in `-m "not slicer"`, the lane documented as *green on a machine with no slicer*.
  Every machine this repo had run on had Bambu Studio installed, so it passed everywhere and its
  conditionality was invisible. CI found it on the first clean runner. **A self-skipping test
  outside its marker is a gate that reports green for being absent**, which is why the workflow
  fails on any skip rather than printing one.

- **CI runs on ubuntu-latest under `xvfb-run`, and the reason is not portability.** `render.py`
  records VTK offscreen working natively on Windows with no OSMesa and no EGL, so the first
  workflow used `windows-latest` expecting to need no graphics setup at all. **That measurement
  came from a workstation with a discrete GPU and does not transfer**: on a hosted Windows runner
  the same code segfaulted — `Windows fatal exception: access violation` in `render.py:316`
  `_render_view`, an interpreter crash 76% of the way through the suite, not a test failure. The
  constraint was never the OS but whether a working **OpenGL implementation** exists, and no
  standard hosted runner has one on either OS. Xvfb + Mesa llvmpipe gives VTK's OpenGL2 backend a
  real GLX context on the CPU, which is why the apt step and the `xvfb-run` prefix are load-bearing
  rather than boilerplate. Deleting either turns the suite red with a segfault, not a message.

Viewer:

```bash
cd viewer && npm install && npm run dev    # Node >=20; v24.18.0 verified present
```

## Shipping a slice

**Every slice writes two files before its PR opens, whether or not it is a phase:**

```
.agents/code-reviews/<branch>.md        the working-tree review, pre-commit
.agents/execution-reports/<branch>.md   what was done, and what was measured
```

`<branch>` is the PR's head branch, with any `/` replaced by `-`. `.agents/plans/` is for phases
and is not required of a small slice. The paths come from `.claude/post-execute.json`, which is
the ship pipeline's profile for this repo; that file names the paths but states no obligation,
which is why the obligation is written here.

The PR body carries `## Review`, citing both files, and `## Validation`, naming the gate that ran
with its counts. **A phase deliberately skipped is stated in the body** — "no separate PR review
was run" is a fine thing to write and a bad thing to leave to inference.

This is mechanical, not a habit: `.github/workflows/verify.yml`'s `slice artifacts` job fails a
pull request whose branch has no matching pair, and `tests/test_ci_runs_the_gates.py` asserts that
job exists — the same two-layer arrangement `.claude/settings.json` gets from
`test_printer_path_is_narrow.py`, and for the same reason.

**The rule is here because it was measured missing.** The 2026-08-28 trajectory audit
(`.agents/audits/`) found all three phase PRs produced both artifacts and both non-phase PRs (#6,
#7) produced neither — 2 of 2. Not a discipline gradient: the phase PRs each had a
`.agents/plans/phase-N-*.md` naming their slice, so the convention was discoverable from inside the
repo, while a small slice had nothing to copy and this file said nothing. #6 is a careful PR that
retracts its own earlier measurement as non-transferable; care was never the variable.

A review that found nothing still gets a file saying so. A two-line artifact is cheap; the reason
the check has no escape hatch is that an escape hatch is what the last one had.

## Phase boundaries

Phase 3 ships the printer path, and **that is the whole of what it opens.** No cloud, no remote
monitoring, no camera stream (port 6000 is open and stays unused), no print queue, no
multi-printer. `bed_type` stays `"auto"`. The abrasive-nozzle DFM rule that PLA-CF in slot 1
suggests is Phase 4, noted here so it is not lost. When in doubt about scope, check `PRD.md` §12.

- **Phase 1** *(done)* — the verification loop: `measure` → `features` → `intent`, 5 benchmarks,
  19 mutations, 3 skills, viewer.
- **Phase 2** *(done)* — `lril3d-dfm`, `lril3d-repair`, `lril3d-slice` (**Bambu Studio**, not
  OrcaSlicer — correction C1), `coupon.py`, `gcode.py` + viewer preview, the `imported-mesh`
  benchmark, 28 mutations. `coupon.py` appears in the PRD §6 directory tree and is scheduled in
  §12 as Phase 2 — **§12 wins**, and it lives at `src/threedp/coupon.py`.
- **Phase 3A** *(done)* — `printer.py`, `lril3d-print`, `profiles/printer-conn.json`, AMS
  reconciliation, the ADR-5 `deny` → `ask` conversion, 30 mutations. **Except the url scheme**,
  which is measured, not chosen — see below.
- **Phase 3B** *(machinery done, measurements outstanding)* — `calibrate.py`,
  `lril3d-calibrate`, and `compensate`'s rejection of `"measured": true`. The three calibration
  records are still published defaults; replacing them needs two printed coupons and a caliper.
- **Phase 4** — multi-slicer abstraction, and the abrasive-filament/nozzle DFM rule.

### The pre-flight gate, closed — and why the shape of the answer matters

`dispatch.url_scheme` is **`ftp:///{name}`**, uploading to `/`, measured 2026-08-02 with Developer
Mode on. It won on the first attempt.

The part worth keeping is what came *before* that. With Developer Mode **off**, all seven
candidates returned an identical `err_code 0502-4007` — including `file:///mnt/sdcard/...`, a path
that does not exist, and a bare filename. A file-or-path error cannot be invariant across those,
which is what proves the rejection happened **before the url was parsed** — and therefore that no
amount of permuting url forms could ever have found the answer. Two hours of candidate-shuffling
would have looked like progress and produced nothing.

So the losers stay in `profiles/printer-conn.json` marked **untried**, not rejected: they were
never actually disproved, only refused for a different reason. And `resolve_url_scheme` still
raises `PreFlightGateOpen` on a `null` scheme, so pointing this at a printer whose accepted form
has not been measured says so instead of reaching for the one that worked here.

Both live-print tests are behind `THREEDP_APPROVE_A_REAL_PRINT=yes`:

```bash
THREEDP_APPROVE_A_REAL_PRINT=yes uv run pytest -m printer -k url_scheme -v -s
THREEDP_APPROVE_A_REAL_PRINT=yes uv run pytest -m printer -k end_to_end -v -s
```

## Known accepted gaps

Stated plainly rather than papered over — do not "fix" these by weakening a guarantee:

- **Z-only mesh probing**: angled features are invisible. Mitigated by *refusing Tier 1 status*, not
  by guessing.
- **Benchmark 5 (gyroid vase) is Tier 2 and largely unverifiable.** Do not write dimensional
  mutations for it — that scores the verifier against a promise it never made.
- **Imported meshes have no parametrization** and fall back to uniform geometric offset, where the
  hole/outer asymmetry is real and unresolvable. Press fits on imported meshes are unsupported.
- **`repair.verify` compares the file it was handed to the file it produced**, so damage that
  arrived *inside* the import is not repair's to catch — that is `intent.json`'s job. A PASS from
  `repair` says the repair changed nothing, never that the file is faithful to its designer.
- **A repair with no Tier 1 feature to compare reports UNVERIFIABLE**, not PASS. Organic geometry
  therefore never gets a green repair verdict, which is correct and is not a bug to fix.
- **Bridge spans are derived from face geometry, not from a slice**, and are labelled ESTIMATE. A
  slicer knows which perimeters actually land over air; this knows which faces point down.
- **The AMS has never successfully fed a print through this code path.** Three dispatches were
  accepted and none loaded filament; `tray_tar` never left 255. Until that is solved, `lril3d-print`
  can send a job and watch it, and cannot produce a part. **`watch()` will say so** rather than
  reporting the printer's own `FINISH`.
- **A dispatch is not a print, and nothing here can tell you a part is on the plate.** `watch`
  distinguishes finished / failed / returned-to-idle / finished-with-no-filament, but even
  "`FINISH` and filament was seen" is a claim about a machine, not a measurement of an object.
  Verifying the part is `lril3d-inspect`'s job, on something someone has taken off the plate.
- **Only one url form has been tried since Developer Mode was enabled.** `ftp:///{name}` won on
  the first attempt and the matrix stops as soon as one does, so the other six are *untried*
  rather than known-bad. If this ever needs re-measuring on different firmware, re-run the matrix
  rather than assuming the recorded winner generalises.
- **`ABS_generic` has no measured calibration and will not get one from this repository** until an
  ABS spool is loaded. It stays a published default with `"measured": null` and every compensated
  export against it warns. Do not "complete" the file.
- **`reconcile_ams` compares material *names* from AMS RFID.** A non-Bambu spool reports
  `tray_info_idx` poorly or not at all, so reconciliation degrades to "unknown material in this
  slot" — a BLOCKER when that slot is used, never a silent pass. Every spool on this machine is
  Bambu, so **the degraded path is untested against real hardware**.

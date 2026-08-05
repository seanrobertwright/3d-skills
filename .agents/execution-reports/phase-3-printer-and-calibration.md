# Execution report — Phase 3: The Printer and Calibration

> **Provenance.** This slice was implemented in earlier sessions; this report was reconstructed at
> ship time from `.agents/plans/phase-3-printer-and-calibration.md`, the `master...HEAD` diff, and
> the validation commands actually re-run at commit `57fb4ea`. It is evidence-based rather than a
> first-hand account of the implementation session — where the plan and the tree disagree, the tree
> was read, not remembered. Anything not verifiable from those three sources is marked as such.

## Meta

- **Plan file**: `.agents/plans/phase-3-printer-and-calibration.md` (976 lines, ADRs 13–18, spikes S13–S25)
- **Branch**: `phase-3-printer-and-calibration` · **commit**: `57fb4ea`
- **Lines changed**: +7022 −286 across 33 files

**Files added (18)**

| Path | Lines |
| --- | --- |
| `src/threedp/printer.py` | 1976 |
| `src/threedp/calibrate.py` | 326 |
| `tests/test_printer.py` | 1329 |
| `tests/test_printer_live.py` | 405 |
| `tests/test_printer_path_is_narrow.py` | 259 |
| `tests/test_calibrate.py` | 328 |
| `.agents/plans/phase-3-printer-and-calibration.md` | 976 |
| `profiles/printer-conn.json` | 119 |
| `.claude/skills/lril3d-print/SKILL.md` | 138 |
| `.claude/skills/lril3d-calibrate/SKILL.md` | 107 |
| `benchmarks/bearing-holder/mutations/method_stale_calibration.py` | 127 |
| `benchmarks/bearing-holder/mutations/method_ams_drift.py` | 71 |
| `tests/fixtures/push_status_full.json` | 269 |
| `tests/fixtures/push_status_delta.json` | 8 |
| `tests/fixtures/filaments_drifted_s16.json` | 10 |
| `tests/fixtures/filaments_reconciled.json` | 10 |
| `.env.example` | 13 |

**Files modified (14)**: `CLAUDE.md` (+280), `src/threedp/slicer.py`, `src/threedp/compensate.py`,
`src/threedp/intent.py`, `tests/test_slicer.py`, `tests/test_one_ruler.py`, `profiles/slicer.json`,
`profiles/filaments.json`, `profiles/printer-p1s.json`, `.claude/settings.json`,
`.claude/PRINT-GATE.md`, `.claude/skills/lril3d-slice/SKILL.md`, `.gitignore`, `pyproject.toml`,
`uv.lock`.

**Files deleted (1)**: `tests/test_no_printer_path.py` — replaced, not dropped (ADR-15).

## Validation results

Every command below was re-run at `57fb4ea`; these are observed outputs, not expectations.

| Level | Command | Result |
| --- | --- | --- |
| 1 | `ruff check .` | ✓ All checks passed |
| 1 | `ruff format --check .` | ✓ 73 files already formatted |
| 1 | root import + interpreter gate | ✓ `OK 3.13.14` |
| 2 | `pytest` (full) | ✓ **480 passed, 2 skipped**, 5 warnings, 92.5 s |
| 3 | `pytest -m slicer` | ✓ **6 passed, 0 skipped** |
| 3 | `pytest -m printer` | ✓ **10 passed, 2 skipped** (12 collected) |
| 3b | `benchmarks/run_mutations.py` | ✓ `caught 20/20  missed 0  false-positives 0  harness-errors 0` — **30** mutations / 6 benchmarks, **VERDICT: PASS** |
| — | `git check-ignore -q .env.example` | ✓ exit 1 (committed; correction C9 holds) |

There is **no type-checking step** in this project — `pyproject.toml` configures ruff and pytest
only, and no mypy/pyright config exists. Recorded as absent rather than reported as passing.

There is also **no CI** (`.github/workflows/` does not exist), so the runs above are the entire
verification surface for this PR.

## What went well

- **The four-condition dispatch gate holds against fixtures with no printer.** `accept_dispatch`
  takes a `DispatchEvidence` dataclass rather than a live link, which is the same split as
  `slicer.accept_slice`. Every one of ADR-14's conditions is exercised in `tests/test_printer.py`
  without hardware, and the hardware tests then confirm the same code path end to end.
- **The S18 regression is asserted as an absence, which is the hard direction.**
  `test_the_listener_captures_an_echo_that_has_none_of_result_reason_errno`
  (`tests/test_printer.py:713`) constructs an echo carrying none of `result`/`reason`/`errno` and
  asserts it is still captured. A happy-path test would have passed against the broken listener
  that caused the spike's two wrong readings.
- **The pre-flight gate closed cleanly once Developer Mode was on.** Seven candidate url forms had
  been rejected identically with `0502-4007`; with the authorization gate open, `ftp:///{name}` won
  on the first attempt, and `profiles/printer-conn.json` records it as `measured-winner` with the
  measurement quoted, leaving the six others in the file as documented, disabled candidates.
- **ADR-15's narrowing worked as designed.** Deleting `test_no_printer_path.py` on the day
  `printer.py` landed was the obvious move and would have discarded the guarantee for the other
  fourteen modules. The replacement asserts the exemption *positively* too — if `printer.py` ever
  stops importing a network module, the test fails and says the exemption is now dead.
- **The mutation suite absorbed the new work without a second verdict channel.** `ams_mismatch_count`
  became an ordinary `intent.py` measure kind, so `method_ams_drift` is scored by the same harness
  as every geometry mutation rather than by a parallel pass/fail path.

## Challenges encountered

Reconstructed from the plan's spike log and the code comments, which record them explicitly:

- **The refusal channel is an echo, not an ack** (S18). Two consecutive wrong readings, mutually
  reinforced by a control probe that appeared to confirm both. The fix is one line
  (`printer.py:1346-1349`, keep every non-status reply whole); finding it cost the spike three
  readings.
- **`ftplib` needed three separate deviations**, each independently load-bearing: implicit wrapping
  in the `sock` setter, `ntransfercmd` overridden for data-channel TLS session reuse
  (cpython#63699, open since 2013), and `storbinary`'s `conn.unwrap()` dropped while its
  `voidresp()` is kept. Dropping the wrong one of those two truncates the transfer silently.
- **A `FINISH` at 100% for a part that does not exist** (2026-08-03). Thirty of thirty layers,
  `mc_percent 100`, `print_error 0`, empty `hms` — and no object, because no filament was ever
  loaded. Not one field the printer publishes dissented. This is the single most consequential
  finding in the phase and it arrived at the last possible layer.
- **The root cause of that failure is still open.** `ams_mapping2` was missing and has been added;
  a re-run with it present still resolved no tray. The code records it as *a* defect and not *the*
  defect, and the detection does not depend on the cause.

## Divergences from plan

**1. `pytest -m printer` does not run with 0 skipped**

- **Planned**: acceptance criterion — "`uv run pytest -m printer -v` runs with **0 skipped**".
- **Actual**: 10 passed, **2 skipped**. Both skips are `test_printer_live.py`'s
  `THREEDP_APPROVE_A_REAL_PRINT` gates.
- **Reason**: the criterion was written to prevent a *dependency* skip wearing a green badge. Two
  of these tests start a physical print, and gating those behind an explicit environment variable
  is the correct reading of the project's standing "a print needs a human yes" rule. The criterion
  and the rule collide; the rule wins.
- **Type**: Plan assumption wrong (the criterion did not anticipate physical-action gates).
- **Follow-up**: `CLAUDE.md:426` still documents "9 pass, 1 skip", which matches neither the plan
  nor the tree. Raised as finding #2 in the code review.

**2. The url scheme was measured mid-phase rather than blocking it**

- **Planned**: the PRE-FLIGHT GATE was to be closed **before** task 3A-7 (`dispatch()`).
- **Actual**: `dispatch()` was written against `url_scheme: null` with `resolve_url_scheme()`
  refusing rather than guessing; the scheme was measured afterwards, on 2026-08-02, once Developer
  Mode was enabled at the machine.
- **Reason**: closing the gate required physical access to the printer's screen and a power-cycle.
  Building the refusal first and the measurement second kept the phase moving without a guessed
  default ever existing in the config.
- **Type**: Better approach found.

**3. `bed_type` fix landed in the slicer, not the dispatch**

- **Planned**: S23 recorded the plate mismatch; the natural fix looks like an MQTT `bed_type`.
- **Actual**: `profiles/slicer.json`'s `preset_overrides` sets `curr_bed_type` at slice time, and
  `slicer._write_presets` now raises on an override naming an unknown preset kind.
- **Reason**: measured — the bed temperature is baked into the G-code at slice time, so
  `bed_type: "auto"` over MQTT cannot change it.
- **Type**: Plan assumption wrong.

## Skipped items

**Tasks 3B-5 through 3B-8 — the calibration measurements themselves.**

- 3B-5 print the hole gauge in PLA · 3B-6 print the pin gauge in PLA · 3B-7 measure and record PLA ·
  3B-8 repeat for PETG.
- **Reason**: each requires printing a coupon and measuring it with a caliper. All three records in
  `profiles/calibration.json` remain `"measured": null` / `"source": "published-default"`.
  `calibrate.stale_materials()` lists exactly what is outstanding.
- **Consequence for acceptance**: the criterion "`PLA_generic` and `PETG_generic` carry an ISO
  `measured` date …" is **not met** and is not claimed to be. The machinery that would satisfy it
  is complete and tested; the measurements are owed.
- `ABS_generic` is a permanent exception, not a backlog item — no ABS is loaded, so it cannot be
  measured on this machine at all, and the plan explicitly forbids fabricating the third record.

**Confirmation of C10 from a live print** was listed under 3B-7 as pending; per `CLAUDE.md` it was
subsequently settled on hardware on 2026-08-03 (`8 → 7 → … → 0` across a print the slicer estimated
at 8m46s). Recorded here because the plan still shows it open.

**Level 4 manual walkthrough, including the decline path**: not re-run at ship time. Not verifiable
from the tree, so it is neither claimed nor denied here.

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| FTPS upload with byte-count verification | ✓ (and md5 readback, added beyond the plan) |
| Four ADR-14 conditions; exception names which failed | ✓ |
| `err_code` echo read whole; `0502-4007` named within seconds | ✓ |
| Regression test asserts no `result`/`reason`/`errno` whitelist | ✓ `tests/test_printer.py:713` |
| `reconcile_ams` blocks the S16 drift; colour-only is a NOTE | ✓ `method_ams_drift` caught |
| `PrinterState` raises rather than reporting IDLE | ✓ |
| Access code in no log, repr, exception or test output | ✓ |
| `settings.json` six entries under `ask`, `.env` still `deny` | ✓ asserted mechanically |
| Network-import ban holds for all modules but `printer.py` | ✓ (see review finding #1 on scan depth) |
| `pytest -m printer` with 0 skipped | ✗ 2 skipped — divergence 1 |
| PLA/PETG carry an ISO `measured` date | ✗ **outstanding** — skipped items |
| Mutation suite green at its new baseline | ✓ 30 mutations, both new ones present |
| PRD corrections C5–C10 in `CLAUDE.md` | ✓ all six present |

**11 of 13 met.** Both misses are named above rather than reworded into passes.

## Recommendations

- **Write `.claude/post-execute.json`.** `baseBranch: master`, `merge.strategy: merge`,
  `merge.deleteBranch: true`, `merge.admin: false`, and the gate commands from `CLAUDE.md`. The ship
  pipeline currently re-derives all of this from auto-detection plus recalled preferences on every
  run, and the merge strategy in particular is a stop-and-ask that a five-line file would retire.
- **Make the enforcement scanners recursive** before the package ever grows a subdirectory. Both
  non-negotiable rules are enforced by `glob("*.py")`; the fix is `rglob` and it is cheapest now,
  while the answer is provably unchanged.
- **Keep expected counts in `CLAUDE.md` in one place.** Three separate counts (printer tests,
  slicer tests, mutations) are quoted as acceptance signals, and one has already drifted. A single
  table, or a test that asserts the documented counts, would stop the next drift silently.
- **Consider a minimal CI workflow** for the hardware-free lanes (`ruff`, `pytest -m "not printer
  and not slicer"`, `run_mutations.py`). The hardware gates cannot run in CI, but three of the four
  levels can, and today a PR gets no automated signal at all.

# Code review — Phase 3: printer dispatch, AMS reconciliation and calibration

Reviewed at commit `57fb4ea`, against `master`. Working-tree pass (the PR-diff pass is separate).

## Stats

- Files modified: 14
- Files added: 18
- Files deleted: 1 (`tests/test_no_printer_path.py`, replaced by `tests/test_printer_path_is_narrow.py`)
- New lines: 7022
- Deleted lines: 286

## Gates, run rather than assumed

| Gate | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 73 files already formatted |
| Root import + interpreter gate | `OK 3.13.14` |
| `pytest` (full) | **480 passed, 2 skipped**, 5 warnings, 92.5 s |
| `pytest -m printer` | **10 passed, 2 skipped** (12 collected) |
| `pytest -m slicer` | **6 passed, 0 skipped** |
| `benchmarks/run_mutations.py` | `caught 20/20  missed 0  false-positives 0  harness-errors 0` over **30** mutations / 6 benchmarks — **VERDICT: PASS** |
| `git check-ignore -q .env.example` | exit **1** (not ignored — correction C9 holds) |
| `git check-ignore -q .env` | exit **0** (ignored) |

Both skips are the `THREEDP_APPROVE_A_REAL_PRINT` physical-print gates in `test_printer_live.py`.
Neither is a missing dependency. There is no CI in this repo, so this local run is the only gate.

## Findings

### 1. The two non-negotiable-rule scanners do not descend into subdirectories

```
severity: medium
file: tests/test_printer_path_is_narrow.py
line: 70
issue: package_files() uses glob("*.py"), so any future subpackage escapes the send-path ban
detail: `PACKAGE.glob("*.py")` is non-recursive. `tests/test_one_ruler.py:102` has the same
  pattern for the same package, while both files correctly use `rglob` for `benchmarks/`. Today
  `src/threedp` is flat, so nothing escapes and every test passes honestly — the hole is latent,
  not active. But a future `src/threedp/net/client.py` would import `socket` and reach a printer
  without failing either scan, and `test_the_scan_actually_covers_something` would not notice: it
  asserts `len(files) >= 8` and that six named files are present, both of which stay true.
  This matters more here than it would elsewhere. CLAUDE.md states both rules are "mechanically
  enforced ... not agent discipline", and a scanner with a blind spot is precisely the "skipped
  layer wearing a green badge" the mutation-suite guidance warns about.
suggestion: `glob("*.py")` -> `rglob("*.py")` in both files, and extend the skipped-layer guard to
  assert the walk found every `.py` under the package (e.g. compare against an independent count).
```

### 2. `CLAUDE.md`'s expected `-m printer` counts are stale

```
severity: medium
file: CLAUDE.md
line: 426
issue: documents "9 pass, 1 skip" for `pytest -m printer`; the actual result is 10 passed, 2 skipped
detail: The surrounding prose is stronger than a comment — it says the printer layer "is a gate,
  not a formality" and that it "has exactly one legitimate skip". Both numbers are now wrong (12
  tests collected, 2 physical-print skips). In a repo whose stated rule is "Report numbers, never
  impressions", the expected count IS the acceptance criterion: a future run that sees 2 skips
  cannot tell whether that is the documented state or a newly-broken dependency. The same section
  for the mutation suite is exactly right (`caught 20/20`, 30 mutations), which is what makes this
  one stand out.
suggestion: update to "10 pass, 2 skip (both physical-print gates)" and change "exactly one
  legitimate skip" to two, naming both.
```

### 3. A skip reason asserts a fact about its own file that is no longer true

```
severity: low
file: tests/test_printer_live.py
line: 317
issue: the skipif reason says "This is the only skip in this file"; there are two
detail: The other physical-print gate at line 270 skips under the same condition. Self-describing
  messages are load-bearing here — this one is what a reader consults to decide whether a skip is
  legitimate — so a claim that is false undermines the thing it exists to establish.
suggestion: reword to "both skips in this file guard a physical action, not a missing dependency".
```

### 4. `calibrate.__all__` omits the function CLAUDE.md names as the phase's status API

```
severity: low
file: src/threedp/calibrate.py
line: 43
issue: `stale_materials` and `WriteResult` are public and documented but absent from `__all__`
detail: CLAUDE.md cites `calibrate.stale_materials()` twice as the way to list outstanding
  calibration work, and `write_record` (which IS exported) returns a `WriteResult` that callers
  cannot name from a star-import. Nothing breaks — the attribute resolves — but `__all__` is the
  module's own statement of its surface, and it currently disagrees with the documentation.
suggestion: add both to `__all__`.
```

### 5. ADR-14 condition 4 matches the job name by substring

```
severity: low
file: src/threedp/printer.py
line: 1704
issue: `evidence.subtask_name not in reported` accepts any printer job whose name contains ours
detail: The loose match is deliberate and mostly right — `printer_gcode_file` arrives as a path
  with an extension, so an equality test would reject our own job. But the failure mode it admits
  is the exact one condition 4 exists to prevent: dispatching `bracket` while the printer is
  running `bracket-v2` passes, and we report someone else's print as ours. Narrow, because
  condition 4 also requires the printer to have been idle beforehand; a job started between the
  idle read and the settle window is the window.
suggestion: compare against the stem of `reported` rather than the whole string, or require the
  match to be anchored (`Path(reported).stem == subtask_name` with the raw-substring test as a
  fallback).
```

### 6. `upload()` holds the whole file in memory and then hashes it from disk a second time

```
severity: low
file: src/threedp/printer.py
line: 482
issue: `source.read_bytes()` buffers the entire 3MF, and `_md5(source)` re-reads it from disk
detail: `payload` is read whole at line 482 and sent with one `sendall`; line 539 then streams the
  same file through `_md5` again. Two full reads and a peak equal to the file size. For a 135 kB
  3MF this is invisible; for a large multi-plate export it is not, and there is a correctness edge
  too — if the file changes between the two reads, the md5 recorded does not describe the bytes
  that were sent, which is the one thing the md5 is there to establish.
suggestion: hash `payload` directly (`hashlib.md5(payload).hexdigest()`) so the digest provably
  covers the transmitted bytes, or stream the upload and hash in the same pass.
```

### 7. `PrinterLink.close()` latches, so a retried `connect()` can leak a paho loop thread

```
severity: low
file: src/threedp/printer.py
line: 1304
issue: `_closed` is set permanently, making the second `close()` a no-op after a re-`connect()`
detail: `connect()` calls `self.close()` on both of its failure paths. If a caller retries
  `connect()` on the same object, the retry reuses `self._client`, calls `loop_start()` again, and
  a second failure returns early from `close()` because `_closed` is already `True` — leaving that
  network thread running with nothing holding a reference to stop it. The class docstring is
  careful about exactly this ("a failure inside connect() must not leave a network thread running
  with nobody holding a reference to stop it"), so the intent is clear and the latch defeats it on
  the retry path. Not currently reachable: nothing in the tree retries `connect()`.
suggestion: clear `_closed` at the top of `connect()`, or refuse to reconnect a closed link with an
  explicit error rather than silently half-working.
```

## What was checked and found correct

Recording this so a later reader knows these were examined rather than skipped:

- **`_merge` replaces lists wholesale and recurses into dicts** — correct for this protocol; merging
  tray arrays element-wise would synthesise a state that existed at no single moment.
- **`PrinterState` accessors all route through `_require()`**, including `snapshot`, `get` and every
  property. There is no defaulted read path. `remaining_min` returns `None` for an absent field
  rather than `0`, and `remaining_s` derives from it (correction C10 held correctly).
- **`upload()` re-issues `TYPE I` before `STOR`** because `remote_sizes`' `retrlines` leaves the
  session in ASCII — a genuine trap, and the comment explains it.
- **An unreadable readback is recorded as `"unreadable: <type>"`, not `None`**, so both
  `UploadResult.complete` and `accept_dispatch` condition 1 treat it as a mismatch. "Unverified"
  cannot masquerade as "verified" here.
- **`accept_dispatch` evaluates condition 4 before condition 3**, with a comment saying why. An
  already-busy printer satisfies 3 for free; checking 4 first is what stops that.
- **`_check_measured` is applied in three places** (whole-file load, single-material load, and a
  record handed straight to `resolve()`), which closes the direct-to-`resolve` path that would
  otherwise bypass the loader.
- **`write_record` cannot downgrade a measurement**: `_iso_date` runs before the read-modify-write,
  so no record lacking a real ISO date reaches the file at all.
- **`fit_deltas` derives its spread limit from the gauge's own step pitch** rather than a chosen
  constant, and raises with the per-step detail instead of reporting a mean.
- **`ams_mapping_fields` emits `-1` plus `{"ams_id": 255}` for the external spool** and rejects
  slots >= 16 rather than guessing AMS-HT conventions.
- **`project_file_command` refuses `use_ams` with no mapping**, which is the nine-minute
  print-of-nothing measured on 2026-08-03.
- **`resolve_url_scheme` still refuses a scheme with no `{name}` placeholder**, and
  `profiles/printer-conn.json` carries the winner with a `source` naming the measurement plus all
  seven losers as disabled, documented candidates.
- **`.claude/settings.json`'s ADR-5 conversion is complete and correctly scoped**: the six send
  entries moved to `ask`, `Read(.env)` / `Read(.env.*)` stayed under `deny`, and nothing appears in
  both buckets.
- **No secret reaches an error message.** `Credentials` uses `slots=True` plus a redacting
  `__repr__`, and every auth failure reports the access code's *length* only.

## Verdict

Seven findings, none critical, none blocking. All gates pass, including the mutation suite, which is
the gate that actually scores the verifier.

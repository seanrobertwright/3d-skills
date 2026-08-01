# Code review — Phase 2: printability, repair, slicing and preview

Reviewed: `master..phase-2-printability-and-preparation` @ `5d7a3fc`
Reviewer: working-tree pass (pre-PR), against `CLAUDE.md` conventions and
`.agents/plans/phase-2-printability-and-preparation.md`.

**Stats**

- Files Modified: 13
- Files Added: 31
- Files Deleted: 0
- New lines: 7,350
- Deleted lines: 42

**Gate state at review time:** `ruff` clean · `pytest` 324 passed · `pytest -m slicer` 6 passed,
0 skipped · `run_mutations.py` 27 mutations, caught 19/19, missed 0, false-positives 0,
harness-errors 0.

---

## Findings

### 1. A requested `--export-3mf` that was never written is silently reported as absent

```
severity: high
file: src/threedp/slicer.py
line: 378
issue: accept_slice() maps a missing 3MF to `export_3mf=None` instead of refusing the result.
detail: The caller explicitly asked for a 3MF. If the file is not there, `SliceResult.export_3mf`
        is None and `__str__` simply omits the line — so a partial success renders identically to
        a run where no 3MF was requested at all. This is the exact failure class the module's own
        docstring is built around, and the pattern the plan names to follow lives two modules
        away: `io.py:88` raises `"{fmt} export reported success but wrote no file at {path}"`.
        S5 measured `--export-3mf` failing (rc -13) while the G-code was written correctly; that
        specific case is caught by condition 1, but any rc-0 path that drops the 3MF is not.
suggestion: When `export_3mf` was requested and `(outdir / export_3mf)` does not exist, raise
        SliceRejected naming the file and the relative-path requirement, rather than returning a
        result with the field nulled.
```

### 2. `bridge_spans` is never exercised with a non-empty result

```
severity: high
file: src/threedp/printability.py
line: 300
issue: No test and no mutation ever makes bridge_spans return a span, so max_bridge_mm is a rule
       that has never fired.
detail: Every current caller feeds it geometry with no near-horizontal downward faces — the
        `imported-mesh` baseline, both overhang variants (75 deg and 40 deg are outside the 80 deg
        bridging band by construction), and the conftest fixtures. The function therefore runs on
        every DFM evaluation and returns an empty report every time, so line coverage is green
        while the interesting half — connected-component grouping, the span/long assignment, the
        area sum — has never executed under test.
        Verified by hand during this review: a 24 mm slot bridged by a slab returns
        `1 span, max 20.000 mm, area 480.00 mm2` and `flag=True`, i.e. the code is correct. That
        is precisely the problem — it is correct and unverified, and the next edit to it would be
        unguarded. This is the "skipped layer wearing a green badge" the mutation suite exists to
        prevent, one level down.
suggestion: Add a `tests/test_printability.py` case asserting the measured 20.000 mm span on
        analytically known geometry (the shorter extent, not the longer), plus a `dfm` case
        asserting max_bridge_mm produces a WARNING. Consider a bridged variant on `imported-mesh`
        so the mutation suite scores it too.
```

### 3. Filament mass is summed across every plate while the G-code is one plate

```
severity: medium
file: src/threedp/slicer.py
line: 327
issue: `grams` accumulates over all entries of `sliced_plates`, but `gcode` is `plate_N.gcode`.
detail: With `--slice 0` on a multi-plate 3MF, `sliced_plates` holds one entry per plate and the
        loop sums them all, while `expected_gcode()` resolves to `plate_1.gcode`. The result then
        reports one plate's toolpath next to every plate's filament — a number that does not
        describe the artifact beside it. `filament_id` has the same shape of bug: it takes the
        first non-empty id across all plates.
        Not reproduced at runtime — every model exercised here is single-plate, and I did not
        construct a multi-plate 3MF to confirm. The mismatch is visible in the code path.
suggestion: Either select the plate entry matching the G-code being reported, or carry per-plate
        results and make the single-plate case an explicit selection. If multi-plate is out of
        scope, refuse `len(sliced_plates) > 1` with a message saying so — consistent with the
        module's habit of refusing rather than reporting an ambiguous number.
```

### 4. One global debounce timer now serves three watched files

```
severity: medium
file: viewer/server/watch.mjs
line: 78
issue: `timer` and `lastSize` are module-level singletons; `schedule()` clears any pending
       announcement, so two files changing inside the debounce window announce only the last.
detail: Pre-existing (part.stl and part.3mf could already collide), but Phase 2 makes it
        materially more likely: the natural slice workflow writes the mesh and then
        `part.preview.json` moments later, which is exactly the collision. The dropped
        announcement is silent — the page keeps showing stale geometry and nothing says so.
suggestion: Key the timer and the settle state per file (a `Map<file, {timer, lastSize}>`), so
        each watched path debounces independently.
```

### 5. Toggling the preview off with no mesh loaded leaves stale status text

```
severity: low
file: viewer/src/main.js
line: 247
issue: `if (part) status.textContent = modelStatus` — when `part` is null the text is left as the
       preview's description while `status.className` is cleared unconditionally on the next line.
detail: Reachable when a `part.preview.json` exists and no `part.stl`/`part.3mf` does. The panel
        then describes a preview that is no longer drawn, in the neutral colour.
suggestion: In the else branch, fall back to the "no part.stl or part.3mf yet" message when
        `part` is null, and set the class alongside the text rather than after it.
```

### 6. `read_meta` scans the whole file when there is no `HEADER_BLOCK_END`

```
severity: low
file: src/threedp/gcode.py
line: 156
issue: The header loop only breaks on `; HEADER_BLOCK_END`; a file without one is scanned to EOF
       against ten regexes per comment line.
detail: A PrusaSlicer or hand-written file has no such marker. The file is already read whole by
        `_read_lines`, so this is constant-factor rather than complexity — ~310k regex calls on a
        31k-line file — but it is work done to find nothing.
suggestion: Also break once a non-comment, non-blank line is seen; the header block is always at
        the top of the file, and the first G-code command is a reliable terminator.
```

---

## What was checked and found clean

- **Security.** No network imports anywhere in `src/threedp/` (mechanically asserted by
  `tests/test_no_printer_path.py`). The single `subprocess.run` passes an argv **list**, not a
  shell string, and its element zero is asserted to be the executable `find_slicer()` returned.
  No secrets, no credentials, no SQL, no user-supplied HTML. `.claude/settings.json` is byte-identical
  to `master`.
- **The one-ruler rule.** Every new module is scanned by `tests/test_one_ruler.py`, and the five
  new names are asserted present so a module in the wrong directory cannot pass unnoticed.
  `repair.py` and `printability.bore_diameters` both take diameters from `features`, never from a
  fresh fit.
- **Units.** Every new measure kind has a `MEASURE_UNITS` entry, and a new test fails the build if
  a future kind silently inherits `mm`.
- **Error handling.** The refusal paths are the point of this phase and they are dense with tests:
  four ADR-10 conditions, `UNVERIFIABLE` never collapsing to PASS, `grams=None` rather than 0.0,
  uncited thresholds refused at load, unknown materials listing the valid set.
- **Parser edge cases.** Inline `;` inside a config value, `=` inside a value, `;` inside the
  printing-time field, and an inline comment on a motion line are each covered by a named test —
  the last of these was a real bug found and fixed during implementation.
- **Performance.** `dfm.evaluate` re-runs a Z-scan that `intent.check` has usually already done,
  and `showUpTo` is a linear scan per slider event. Both are small at current sizes (12,837
  segments, ~1 s scans) and neither is on a hot path; noted, not filed.

## Verdict

No critical issues. Two high findings, both of the same species and both about *coverage of a
refusal* rather than a wrong number: one path can report a partial success as a success (#1), and
one measurement has never been observed producing a value (#2).

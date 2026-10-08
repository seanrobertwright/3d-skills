---
slice: chore-p1s-nozzle-reading
title: "chore(profiles): record the P1S nozzle reading of 2026-10-07"
author: "seanrobertwright"
reviewed: 2026-10-07
recommendation: approve
---

# Code review — `chore-p1s-nozzle-reading`

Working-tree review, run before the PR was opened. The slice records a fresh nozzle reading from
the printer for seanrobertwright/fpv #5.

| File | Change |
|---|---|
| `profiles/printer-p1s.json` | new `nozzle_reading` block with the date; a note; `source` names the new reading |
| `tests/test_printer.py` | one test: the profile carries a dated reading that agrees with `nozzle_material` |

## Findings

No blocking findings.

1. **Fixed before commit.** A draft of the new note stated as fact that the P1S has no sensor for
   the nozzle type. That was not verified in this repository, so the note now gives an
   instruction instead: after a nozzle swap, check the configured type and read it again.
2. **Accepted.** The new test calls `date.fromisoformat` only to validate the date string. That is
   intentional: a malformed date raises and fails the test.
3. **Not changed, reported.** `nozzle_material` stays `stainless-steel` because the printer still
   reports `stainless_steel`. Nothing in this slice loosens the block on printing PAHT-CF.

## Out of scope, noted

- `tests/test_printer_live.py::test_the_captured_fixture_still_describes_this_printers_ams` fails
  on the live printer: AMS slots 2 and 3 were swapped since the fixture was captured. That is a
  physical change, not this slice. Re-capturing the fixture is left to the owner.
- PA-CF's "Internal solid infill" layers next to the skins alternate X and Y (zig-zag pattern).
  The 100% sparse infill holds X on every layer. Whether arms want the solid layers aligned too is
  a design decision for fpv, not made here.

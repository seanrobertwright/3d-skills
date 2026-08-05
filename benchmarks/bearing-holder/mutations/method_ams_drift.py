"""The inventory drifts away from the AMS, and the mapping stays confidently, silently wrong.

**This is not a hypothetical defect.** The drift injected here is the one that was *already
shipped*: on 2026-08-02 the printer was asked what it was holding and ``profiles/filaments.json``
disagreed in four of five slots. Asked for PETG, ``slicer.ams_mapping`` answered slot 2; slot 2
held purple PLA. Asked for ABS it answered slot 3, and slot 3 held green PETG -- so an ABS process
at 255 C would have been driven into PETG. No exception, no warning, and the Phase 2 tests for
``ams_mapping`` all passed, because they test that the function maps its input faithfully and
nothing tested that the input was true.

That is precisely the gap ``intent.json`` closes for geometry, so it is closed the same way here
(ADR-16): the claim is checked against a measurement of the real thing before it is used.

The baseline asserts against ``tests/fixtures/filaments_reconciled.json``, which is what the AMS
actually held, and reads **zero** blockers against the captured telemetry. The mutation swaps in
the shipped, drifted inventory -- the real file, unmodified -- and the assertion must fail.

``KIND = "method"``: no geometry moves. The part is identical in both runs and the only thing that
changes is which claim the verifier is handed, which is the correct shape for scoring a *ruler*
rather than a *part*. Without this mutation, ADR-16 is a docstring.
"""

import contextlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "tests" / "fixtures"

EXPECT = "FAIL"
REASON = "the shipped inventory maps PETG onto a slot that physically holds PLA"
KIND = "method"
SOURCE = "stl"

EXTRA_ASSERTS = [
    {
        "ams_mismatch_count": [0, 0],
        "source": "user-confirmed",
        "measure": {
            "kind": "ams_mismatch_count",
            "severity": "BLOCKER",
            "materials": ["PETG"],
            "live": str(FIXTURES / "push_status_full.json"),
            "inventory": str(FIXTURES / "filaments_reconciled.json"),
        },
        "note": (
            "the filament this part will be printed in is the filament the inventory claims is "
            "in that slot"
        ),
    }
]


@contextlib.contextmanager
def method_patch():
    """Hand the verifier the drifted inventory that shipped, in place of the true one."""
    from threedp import slicer

    canonical = slicer.load_inventory

    def drifted(path=None):
        # The FROZEN capture of profiles/filaments.json as it shipped, not the live file. The
        # live file has been corrected from telemetry; pointing the mutation at it would make the
        # mutation stop biting on the day the defect was fixed, which is the wrong way round --
        # a regression test exists to keep a fixed defect fixed.
        return canonical(FIXTURES / "filaments_drifted_s16.json")

    slicer.load_inventory = drifted
    try:
        yield
    finally:
        slicer.load_inventory = canonical

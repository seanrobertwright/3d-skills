"""An unsupported flare at 75 degrees from vertical is added on top of the pin.

Nothing dimensional changes: the plate is still 60mm wide and 10mm thick, both bores are still
Ø8, and the mesh is still watertight and still the right way out. The part is *correct* and it
will not print. That gap is the whole reason Phase 2 exists.

Measured: ``max_overhang_deg`` = 75.10 against a 45.0 threshold in PLA, one BLOCKER, so
``dfm_blockers`` measures 1 against an asserted 0.

The flare carries a 2.5mm collar at its rim. Without it the cone meets its own top face at a
knife edge -- thousandths of a millimetre of material -- and ``min_feature_mm`` would fire too,
which would make this mutation pass for a reason that has nothing to do with overhangs.
"""

EXPECT = "FAIL"
REASON = "a 75-degree flare droops into the nozzle without support; unprintable as posed"
BUILD_OPTIONS = {"overhang": True}

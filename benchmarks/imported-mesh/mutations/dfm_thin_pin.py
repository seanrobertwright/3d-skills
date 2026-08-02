"""The pin shrinks from Ø3.0 to Ø0.5 -- below one extrusion bead.

**This is the mutation that scores the DFM engine, and it only works because nothing else
constrains ``PIN_D``.** Every other dimension on this benchmark is asserted in ``intent.json``,
so changing one of those fails a dimensional assertion and the run says nothing about whether
``dfm.py` works -- it would be caught with the DFM engine deleted. The pin exists precisely so
that there is one parameter whose only guardian is a printability rule.

Measured: ``min_feature_mm`` and ``min_wall_mm`` both fire at 0.500mm against a 0.800mm
threshold. Both are BLOCKERs, so ``dfm_blockers`` measures 2 against an asserted 0.

Read the report on a failing run: the failing line must be ``dfm_blockers``. If a dimensional
line fails instead, the pin has started interfering with something and this mutation has stopped
testing the DFM engine.
"""

EXPECT = "FAIL"
REASON = "a 0.5mm pin is thinner than one bead; the nozzle never lays it down"
PARAMS_OVERRIDE = {"PIN_D": 0.5}

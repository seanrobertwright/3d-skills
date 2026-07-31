"""Counterbore 4.2 -> 5.5 in a 6mm plate, leaving 0.5mm of material under the screw head.

The PRD 15.1 trap, injected. The part still builds, still renders, and its volume moves by under
half a percent -- but the bracket tears out around the screw on first load.
"""

EXPECT = "FAIL"
REASON = "0.5mm of material under an M4 head is not a bolted joint"
PARAMS_OVERRIDE = {"CBORE_DEPTH": 5.5}

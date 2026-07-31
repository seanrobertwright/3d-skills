"""Clearance hole 4.5 -> 3.4: an M3 clearance drill used for an M4 screw.

The kind of defect that is invisible in a render and obvious with a screw in your hand.
"""

EXPECT = "FAIL"
REASON = "an M4 screw does not pass through a 3.4mm hole"
PARAMS_OVERRIDE = {"HOLE_D": 3.4}

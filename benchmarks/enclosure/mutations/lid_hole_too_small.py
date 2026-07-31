"""Lid screw hole 3.4 -> 3.0: the M3 *tap* drill used where a clearance hole belongs.

The lid then threads onto the screw instead of floating on it, so it cannot pull down onto the
bosses -- the mating tolerance is gone.
"""

EXPECT = "FAIL"
REASON = "a 3.0mm hole binds on an M3 shank; the lid cannot pull down onto the bosses"
PARAMS_OVERRIDE = {"LID_HOLE_D": 3.0}

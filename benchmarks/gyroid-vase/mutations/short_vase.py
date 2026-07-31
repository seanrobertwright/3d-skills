"""Height 40 -> 35. A bounding-box defect, which is exactly what Tier 2 *can* see.

Tier 2 cannot tell you a wall is 0.3mm thin. It can tell you the part is the wrong size, and
that is worth having.
"""

EXPECT = "FAIL"
REASON = "the vase is 5mm shorter than asserted"
PARAMS_OVERRIDE = {"HEIGHT": 35.0}

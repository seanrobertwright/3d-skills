"""Flare 60 deg -> 75 deg from vertical.

Past 45 deg every additional degree costs surface quality, and at 75 deg the underside is nearly
a ceiling. A verifier that only checks "is there an overhang at all" passes this happily.
"""

EXPECT = "FAIL"
REASON = "a 75 deg flare droops without support; it is a worse overhang, not the asserted one"
PARAMS_OVERRIDE = {"ANGLE_DEG": 75.0}

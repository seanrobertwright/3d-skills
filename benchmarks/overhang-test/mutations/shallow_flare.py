"""Flare 60 deg -> 30 deg from vertical: the part stops being an overhang test.

This mutation is aimed squarely at the histogram's two traps. Under a ``< 90`` top bin, or with
build-plate contact faces left in, the measured overhang barely moves between a 30 deg and a
60 deg flare -- and the detector silently stops detecting.
"""

EXPECT = "FAIL"
REASON = "a 30 deg flare needs no support; the part no longer tests what it claims to test"
PARAMS_OVERRIDE = {"ANGLE_DEG": 30.0}

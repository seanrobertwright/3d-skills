"""Gyroid band half-width 0.55 -> 0.30: the struts thin out across the whole lattice.

A defect with no location. There is no bore to measure and no plane to probe -- the only signal
is that the part contains materially less material than it should. Volume is a blunt instrument,
and here it is the right one.
"""

EXPECT = "FAIL"
REASON = "the lattice loses roughly a fifth of its material; struts thin toward unprintable"
PARAMS_OVERRIDE = {"GYROID_T": 0.30}

"""Cosmetic fillet 0.5 -> 0.6. Nothing functional changes.

**The false-positive detector.** If this fails, the verifier is over-tight and would cry wolf on
every real part -- which makes its reports ignorable, a slower route to the same place as having
no verifier at all. It is as important as the three genuine defects.
"""

EXPECT = "PASS"
REASON = (
    "a base-corner fillet touches no asserted dimension; volume drift alone must not fail a part"
)
PARAMS_OVERRIDE = {"FILLET": 0.6}

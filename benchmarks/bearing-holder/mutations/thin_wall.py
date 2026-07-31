"""Wall 4.0 -> 1.1, by shrinking the boss OD from 30.0 to 24.2.

The bore is unchanged, so every diameter assertion still passes. Only the wall between the bore
and the outside is wrong -- which is the point: a defect that no single diameter can see.
"""

EXPECT = "FAIL"
REASON = "a 1.1mm boss wall splits under 608 press-fit hoop stress"
PARAMS_OVERRIDE = {"BODY_OD": 24.2}

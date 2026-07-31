"""Boss height 12.0 -> 13.0. Every asserted dimension is unchanged.

The false-positive detector for this benchmark. A taller boss moves two plane positions and the
part volume, and touches none of the fits: the insert hole, its depth below the boss top, the
boss wall, and the floor and lid thicknesses are all still exactly what was asserted.

It is a real check that ``plane_gap`` selects planes *structurally* rather than by value -- an
implementation that matched planes against expected heights would fail here.
"""

EXPECT = "PASS"
REASON = "a taller boss changes no fit; volume drift alone must not fail a part"
PARAMS_OVERRIDE = {"BOSS_H": 13.0}

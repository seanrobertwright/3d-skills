"""Boss OD 8.0 -> 6.0, leaving 1.0mm of wall around a 4.0mm insert.

``parts-db:M3-insert.min_boss_od`` is 8.0 for exactly this reason. A 1mm boss wall survives the
render, the volume check and the bounding box, and splits the first time an insert is pressed in.
"""

EXPECT = "FAIL"
REASON = "a 1.0mm boss wall splits when the heat-set insert goes in"
PARAMS_OVERRIDE = {"BOSS_OD": 6.0}

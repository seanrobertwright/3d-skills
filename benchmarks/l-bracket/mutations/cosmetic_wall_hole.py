"""Wall-hole height 35.0 -> 36.0. Nothing this part's intent asserts changes.

The false-positive detector for this benchmark. The wall holes run along Y, and a Z-scan cannot
measure a Y-axis bore -- so ``intent.json`` deliberately makes no dimensional claim about them
(ADR-4). A verifier that fails this mutation is failing a part over something it never promised
to check, which is how a report becomes noise.
"""

EXPECT = "PASS"
REASON = "moving an unasserted, deliberately unverified feature must not fail the part"
PARAMS_OVERRIDE = {"WALL_HOLE_Z": 36.0}

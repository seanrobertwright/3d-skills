"""Every face wound backwards, nothing deleted, and the repair skipped.

This is the nastiest shape a broken import takes, because almost nothing notices it. The mesh is
**watertight**. Its winding is **consistent**. Every bore sections as a perfect circle and
measures Ø7.999. The plate is 10mm thick and 60mm wide. The only tell is the sign of the
enclosed volume, which for this part measures **-23065.76 mm3** -- a negative number that
``intent.check``'s ``volume`` kind will compare against a range without comment.

So this mutation exists to score exactly one assertion: ``solid_volume``, whose lower bound of
1.0 with no upper bound is a claim about topology rather than size. Delete that assertion and
this mutation goes from caught to missed while every other line of the report stays green.

It also guards the repair op ordering, which was measured getting this wrong: fixing inversion
*before* filling holes reads the sign of the volume of an open surface, which does not have one.
"""

EXPECT = "FAIL"
REASON = "an inside-out mesh is watertight, consistent, and measures every dimension correctly"
PARAMS_OVERRIDE = {"FLIP_FACES": 100000.0, "BREAK_FACES": 0.0}
BUILD_OPTIONS = {"repair_it": False}

"""A flare at 40 degrees from vertical: inside PLA's 45-degree threshold, and it prints.

**The false-positive detector for the DFM engine**, and specifically for the severity levels. The
40-degree flare produces a real finding -- ``warn_unsupported_mm2`` measures 197.63 mm2 of
surface past the 30-degree reporting angle, against a 50 mm2 threshold -- but that finding is a
WARNING, and a WARNING is not a gate (ADR-8).

If this flips to FAIL, one of two things happened, and both are bad in the same way: either every
severity has quietly become a blocker, or somebody tightened ``max_overhang_deg`` past what PLA
actually needs. Either way the engine now refuses parts that print, and refusing parts that print
is a slower route to the same place as having no engine at all.

Note what this also proves: the report is *not* silent on this part. It says 197.63 mm2 will show
sag. Advice and refusal are different acts, and the severity is what separates them.
"""

EXPECT = "PASS"
REASON = "a 40-degree flare in PLA is a warning about surface finish, not a refusal to print"
BUILD_OPTIONS = {"overhang": "mild"}

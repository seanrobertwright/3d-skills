"""Pocket 7.0 -> 6.5. A real defect from the PRD spike (15.2, defect 1).

A 0.5mm fillet consumed the pocket depth. The part rendered cleanly, had a plausible volume, and
passed its bounding box.
"""

EXPECT = "FAIL"
REASON = "a 7mm-wide 608 in a 6.5mm pocket stands proud and will not retain"
PARAMS_OVERRIDE = {"POCKET_DEPTH": 6.5}

"""Stem height 4.0 -> 5.0. The flare angle, its area, and the stem diameter are all unchanged.

The false-positive detector for this benchmark. Raising the flare by 1mm moves the whole part's
height and volume and changes nothing this part exists to measure. It also checks that
build-plate exclusion keys off the *lowest* face rather than a fixed Z.
"""

EXPECT = "PASS"
REASON = "a taller stem changes no asserted angle, area or diameter"
PARAMS_OVERRIDE = {"STEM_H": 5.0}

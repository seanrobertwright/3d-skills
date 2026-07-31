"""Counterbore removed. A real defect from the PRD spike (15.2, defect 2).

The spike's ``CounterBoreHole`` call silently produced plain bores: **no 4.5mm cylinder existed
anywhere**. No parameter value expresses that, which is why this mutation is structural.

An absent feature is the defect. A checker that skipped absent features would score this green.
"""

EXPECT = "FAIL"
REASON = "M4 socket heads stand 4mm proud of the base; nothing sits flat"
KIND = "geometry"


def patch(model, params):
    """Build the holder with the counterbore step omitted entirely."""
    return model.build(params, counterbore=False)

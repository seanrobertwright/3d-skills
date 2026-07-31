"""Marching-cubes step 0.3 -> 0.35. The geometry is unchanged; only its sampling is.

The false-positive detector for this benchmark, and a pointed one: a *meshing* parameter must not
change a *geometric* verdict. The spike measured that tessellation tolerance had no effect on fit
accuracy at 0.1, 0.01 and 0.001 -- the method dominates, not the mesh (PRD 15.5). If this
mutation fails, some assertion is really measuring the mesh rather than the part.
"""

EXPECT = "PASS"
REASON = "a resolution change is not a geometry change; a verdict must not turn on it"
PARAMS_OVERRIDE = {"STEP": 0.35}

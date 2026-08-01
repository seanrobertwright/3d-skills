"""The same geometry, tessellated five times finer. Nothing about the part changes.

**The false-positive detector for the repair path.** Every triangle in the mesh is different,
every face index is different, the break lands on different faces and the repair fills a
different boundary -- and the part is the part. A verifier that fails this cries wolf on every
remesh, every re-export, and every file that arrived from a different CAD package, which makes
its reports ignorable.

It is also the assertion that tessellation tolerance does not buy accuracy: the spike measured
identical fit accuracy at 0.1, 0.01 and 0.001, and this mutation is that claim, scored.
"""

EXPECT = "PASS"
REASON = "a finer tessellation of identical geometry is not a defect"
BUILD_OPTIONS = {"tess_tol": 0.002}

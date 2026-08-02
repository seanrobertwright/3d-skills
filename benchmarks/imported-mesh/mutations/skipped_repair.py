"""The repair step is skipped: the mesh is verified exactly as it arrived.

The simplest way a repair pipeline reports green is by not running. Three faces are missing from
the plate's top surface and 200 faces are wound backwards, so the mesh is not watertight and
never was.

A verifier that only checked dimensions would pass this happily: every bore is still Ø8 and the
plate is still 60mm wide. Being closed is a separate claim, and the intent makes it.
"""

EXPECT = "FAIL"
REASON = "a mesh with three faces missing is not a repaired part, whatever its bores measure"
BUILD_OPTIONS = {"repair_it": False}

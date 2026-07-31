"""``threedp`` -- the thick library behind the thin ``lril3d-*`` skills.

Geometry, measurement, and rendering live here so they are testable without an agent. The
public surface is the PRD 10 import line and is kept stable::

    from threedp import measure, features, intent, render, compensate, parts, io

All dimensions are millimetres.
"""

__version__ = "0.1.0"

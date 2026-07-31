"""Shared fixtures.

The canonical test part is the spike's: **OD30 cylinder, Ø22 bore 7 deep, Ø10 through-hole**,
20mm tall and centred on the origin. Its truth is known by construction, and it is exported to
both ``.step`` and ``.stl`` from the *same* build so the BREP and mesh paths are measured
against identical ground truth. A disagreement between them is then a real bug in one path,
not a difference in the part.

Spike 2 measured, on exactly this geometry: radii {15.0, 11.0, 5.0}; planes at z = {+10, -10,
+3}; pocket depth 10.0 - 3.0 = 7.000 exact.
"""

from pathlib import Path

import pytest

CANONICAL = {
    "outer_d": 30.0,
    "bore_d": 22.0,
    "hole_d": 10.0,
    "height": 20.0,
    "pocket_depth": 7.0,
    "top_z": 10.0,
    "bottom_z": -10.0,
    "pocket_floor_z": 3.0,
}

# Spike 3 / spike 7 geometry: a 60-wide plate 10 thick with Ø8 holes at x = +/-21.
# True thinnest wall is 5.0mm, and face.center() reported those holes at x = -25/+17.
PLATE = {"size_x": 60.0, "size_y": 40.0, "thick": 10.0, "hole_d": 8.0, "hole_x": 21.0}


def build_canonical():
    from build123d import Align, BuildPart, Cylinder, Locations, Mode

    with BuildPart() as p:
        Cylinder(radius=CANONICAL["outer_d"] / 2, height=CANONICAL["height"])
        with Locations((0, 0, CANONICAL["top_z"])):
            Cylinder(
                radius=CANONICAL["bore_d"] / 2,
                height=CANONICAL["pocket_depth"],
                align=(Align.CENTER, Align.CENTER, Align.MAX),
                mode=Mode.SUBTRACT,
            )
        Cylinder(radius=CANONICAL["hole_d"] / 2, height=CANONICAL["height"], mode=Mode.SUBTRACT)
    return p.part


def build_plate():
    from build123d import Box, BuildPart, Cylinder, Locations, Mode

    with BuildPart() as p:
        Box(PLATE["size_x"], PLATE["size_y"], PLATE["thick"])
        with Locations((-PLATE["hole_x"], 0, 0), (PLATE["hole_x"], 0, 0)):
            Cylinder(
                radius=PLATE["hole_d"] / 2,
                height=PLATE["thick"] * 2,
                mode=Mode.SUBTRACT,
            )
    return p.part


def build_square_pocket():
    """A 20x20 square pocket -- the adversarial case a circle fit lies about (spike 5)."""
    from build123d import Align, Box, BuildPart, Locations, Mode

    with BuildPart() as p:
        Box(40.0, 40.0, 20.0)
        with Locations((0, 0, 10.0)):
            Box(20.0, 20.0, 7.0, align=(Align.CENTER, Align.CENTER, Align.MAX), mode=Mode.SUBTRACT)
    return p.part


def build_overhang_cone(rise: float = 10.0, bottom_radius: float = 2.0, angle_deg: float = 60.0):
    """A cone flaring outward whose underside sits at exactly ``angle_deg`` from vertical.

    These are the spike-6 dimensions: the lateral surface is pi*(r1+r2)*slant = 1339.6 mm2
    analytically, against a measured 1339.09 mm2 unsupported area once tessellated.
    """
    import math

    from build123d import BuildPart, Cone

    run = rise * math.tan(math.radians(angle_deg))
    with BuildPart() as p:
        Cone(bottom_radius=bottom_radius, top_radius=bottom_radius + run, height=rise)
    return p.part


@pytest.fixture(scope="session")
def artifacts_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("threedp-artifacts")


@pytest.fixture(scope="session")
def canonical_part():
    return build_canonical()


@pytest.fixture(scope="session")
def canonical_step(canonical_part, artifacts_dir) -> Path:
    from build123d import export_step

    out = artifacts_dir / "canonical.step"
    export_step(canonical_part, str(out))
    return out


@pytest.fixture(scope="session")
def canonical_stl(canonical_part, artifacts_dir) -> Path:
    from build123d import export_stl

    out = artifacts_dir / "canonical.stl"
    export_stl(canonical_part, str(out), tolerance=0.01, angular_tolerance=0.1)
    return out


@pytest.fixture(scope="session")
def canonical_3mf(canonical_part, artifacts_dir) -> Path:
    from build123d import Mesher

    out = artifacts_dir / "canonical.3mf"
    m = Mesher()
    m.add_shape(canonical_part, linear_deflection=0.01, angular_deflection=0.1)
    m.write(str(out))
    return out


@pytest.fixture(scope="session")
def plate_part():
    return build_plate()


@pytest.fixture(scope="session")
def plate_mesh(plate_part):
    from threedp.features import _tessellate

    return _tessellate(plate_part)


@pytest.fixture(scope="session")
def square_pocket_stl(artifacts_dir) -> Path:
    from build123d import export_stl

    out = artifacts_dir / "square-pocket.stl"
    export_stl(build_square_pocket(), str(out), tolerance=0.01, angular_tolerance=0.1)
    return out


def build_tilted_bore(tilt_deg: float = 5.0):
    """A block with a Ø22 bore tilted off Z.

    At 5deg the Z-scan section is an ellipse whose max residual is ~0.042mm -- *inside* the
    0.05mm circularity gate -- while the reported diameter is inflated by ~0.084mm. Circularity
    alone cannot catch this; only measuring the axis can (ADR-4).
    """
    from build123d import Box, BuildPart, Cylinder, Mode

    with BuildPart() as p:
        Box(60.0, 60.0, 40.0)
        Cylinder(radius=11.0, height=120.0, rotation=(tilt_deg, 0, 0), mode=Mode.SUBTRACT)
    return p.part


@pytest.fixture(scope="session")
def tilted_bore_stl(artifacts_dir) -> Path:
    from build123d import export_stl

    out = artifacts_dir / "tilted-bore.stl"
    export_stl(build_tilted_bore(), str(out), tolerance=0.01, angular_tolerance=0.1)
    return out


@pytest.fixture(scope="session")
def overhang_mesh():
    from threedp.features import _tessellate

    return _tessellate(build_overhang_cone())

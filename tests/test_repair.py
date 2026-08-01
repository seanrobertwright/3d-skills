"""Repair, and the thing that makes repair trustworthy: re-measuring afterwards.

Written before ``repair.py`` existed. The spike (S10) measured that a correct repair is
**dimensionally free** -- delete three faces, fill the holes, and the largest bore comes back at
Ø6.9989 before and Ø6.9989 after, delta 0.000000 mm. That is precisely why "it looks fine after
repair" is not a verdict: the good case and the bad case are indistinguishable without a
measurement, and ``trimesh.repair.fill_holes`` documents that it fills holes "using fans, which
may result in bad answers if the holes are non-convex" -- which is exactly the shape of a bore
breaking a surface.

Every break here is deterministic: fixed face indices, fixed counts. A randomly broken mesh makes
a failing test unreproducible, which is a slower route to no test at all.
"""

from __future__ import annotations

import numpy as np
import pytest
import trimesh
from conftest import PLATE

from threedp import features, repair

# --- helpers ---------------------------------------------------------------------------------


def _drop_faces(mesh: trimesh.Trimesh, indices) -> trimesh.Trimesh:
    keep = np.ones(len(mesh.faces), dtype=bool)
    keep[np.asarray(indices, dtype=np.int64)] = False
    broken = mesh.copy()
    broken.update_faces(keep)
    return broken


def _flip_windings(mesh: trimesh.Trimesh, count: int) -> trimesh.Trimesh:
    flipped = mesh.copy()
    faces = np.array(flipped.faces)
    faces[:count] = faces[:count][:, ::-1]
    return trimesh.Trimesh(vertices=flipped.vertices, faces=faces, process=False)


def _bore_wall_faces(mesh: trimesh.Trimesh, cx: float, cy: float, radius: float) -> np.ndarray:
    """Every face lying on the wall of the bore at (cx, cy). Deterministic, no sampling."""
    tri = mesh.triangles
    offset = np.hypot(tri[:, :, 0] - cx, tri[:, :, 1] - cy)
    on_wall = (np.abs(offset - radius) <= 0.05).all(axis=1)
    return np.flatnonzero(on_wall)


# --- diagnosis -------------------------------------------------------------------------------


def test_a_healthy_mesh_diagnoses_as_healthy(plate_mesh):
    d = repair.diagnose(plate_mesh)
    assert d.watertight
    assert d.winding_consistent
    assert not d.inverted
    assert d.broken_faces == 0
    assert d.healthy
    assert d.volume > 0


def test_deleted_faces_are_diagnosed_as_broken(plate_mesh):
    broken = _drop_faces(plate_mesh, [10, 11, 12])
    d = repair.diagnose(broken)
    assert not d.watertight
    assert d.broken_faces > 0
    assert not d.healthy


def test_reversed_winding_is_diagnosed_as_inversion_not_as_a_volume(plate_mesh):
    """Measured in the spike: an inverted mesh reports volume -571.14 mm3.

    A *negative* number that ``intent.check``'s volume kind will happily compare against a
    range -- correctly failing, but for the wrong reason and with a useless message. Inversion is
    named first so the message points at the winding, not at the size.
    """
    broken = _flip_windings(plate_mesh, 200)
    d = repair.diagnose(broken)
    assert not d.winding_consistent
    assert d.volume < 0
    assert d.inverted
    assert "INVERT" in str(d).upper()


def test_a_fully_inverted_mesh_is_caught_even_though_its_winding_is_consistent(plate_mesh):
    """All faces flipped: winding is perfectly consistent and the volume is negative."""
    flipped = _flip_windings(plate_mesh, len(plate_mesh.faces))
    d = repair.diagnose(flipped)
    assert d.winding_consistent
    assert d.inverted
    assert not d.healthy


# --- repair ----------------------------------------------------------------------------------


def test_repairing_deleted_faces_restores_the_geometry_exactly(plate_mesh):
    """S10: fill_holes on this break restored the volume to 0.000000 mm3 of the original."""
    broken = _drop_faces(plate_mesh, [10, 11, 12])
    result = repair.repair(broken)
    assert result.passed, str(result)
    assert result.after.watertight
    assert result.mesh is not None
    assert result.mesh.volume == pytest.approx(plate_mesh.volume, abs=1e-6)
    assert "fill_holes" in result.ops
    assert result.holes_filled >= 1


def test_repairing_inverted_winding_restores_the_geometry_exactly(plate_mesh):
    broken = _flip_windings(plate_mesh, 200)
    result = repair.repair(broken)
    assert result.passed, str(result)
    assert not result.after.inverted
    assert result.after.winding_consistent
    assert result.mesh.volume == pytest.approx(plate_mesh.volume, abs=1e-6)


def test_a_correct_repair_leaves_every_bore_diameter_untouched(plate_mesh):
    broken = _drop_faces(plate_mesh, [10, 11, 12])
    result = repair.repair(broken)
    assert result.dimensions, "nothing was compared; the verdict would mean nothing"
    for d in result.dimensions:
        assert abs(d.delta) <= repair.DEFAULT_DIM_TOL
    measured = sorted(d.after for d in result.dimensions)
    assert measured == pytest.approx([PLATE["hole_d"], PLATE["hole_d"]], abs=0.05)


def test_repair_is_a_no_op_on_an_already_healthy_mesh(plate_mesh):
    result = repair.repair(plate_mesh.copy())
    assert result.passed
    assert result.before.healthy and result.after.healthy
    assert result.faces_added == 0


# --- the verification contract (ADR-9) --------------------------------------------------------


def _one_hole_mesh():
    """conftest's plate with the right-hand bore never drilled: the after-state of a bad repair."""
    from build123d import Box, BuildPart, Cylinder, Locations, Mode

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(PLATE["size_x"], PLATE["size_y"], PLATE["thick"])
        with Locations((-PLATE["hole_x"], 0, 0)):
            Cylinder(radius=PLATE["hole_d"] / 2, height=PLATE["thick"] * 2, mode=Mode.SUBTRACT)
    return _tessellate(p.part)


def test_a_repair_that_consumes_a_bore_is_a_failed_repair(plate_mesh):
    """The whole reason ``verify`` exists.

    ``fill_holes`` fanning a non-convex boundary shut is how a bore disappears during a repair.
    The result is watertight -- which is what a naive repair reports as success -- and one
    feature short. An absent feature IS the defect, the same rule as ``intent.py``.
    """
    result = repair.verify(plate_mesh, _one_hole_mesh())

    assert result.after.watertight, "the premise is that the mesh ends up closed"
    assert not result.passed, "a watertight mesh with a bore missing is not a repaired part"
    assert result.status == repair.FAIL
    assert result.lost_features, "the absent bore was not named"
    lost_x = [x for x, _y in result.lost_features]
    assert any(abs(x - PLATE["hole_x"]) < 0.5 for x in lost_x)
    assert "21" in str(result), "the report does not say which feature went missing"
    assert "ABSENT" in str(result)


def test_repair_scores_the_file_it_was_handed_not_a_pristine_original(plate_mesh):
    """A limitation worth stating rather than discovering.

    Removing a whole bore wall and fanning the two circular boundaries shut produces a watertight
    plate with one bore instead of two -- and ``repair`` reports PASS, correctly: the bore was
    already unmeasurable in the *input*, so nothing about it moved during the repair. Damage that
    arrives inside the imported file is ``intent.json``'s job, not ``verify``'s. Conflating the
    two would mean blaming a repair for a defect it did not cause and, worse, implying that a
    PASS here says anything about the file's fidelity to its designer's intent.
    """
    wall = _bore_wall_faces(plate_mesh, PLATE["hole_x"], 0.0, PLATE["hole_d"] / 2)
    assert len(wall) > 0, "the fixture changed; this test is no longer breaking a bore"
    result = repair.repair(_drop_faces(plate_mesh, wall))

    assert result.after.watertight
    assert "fill_holes_fan" in result.ops, "the safe pass cannot close a boundary this large"
    assert result.passed
    assert len(result.dimensions) == 1, "the second bore was never measurable in the input"
    # ...and the mesh that comes out really has lost it, which the intent check will catch.
    assert len(features.from_mesh(result.mesh).cylinders) == 1


def test_a_dimension_that_moves_beyond_tolerance_fails_with_both_numbers(plate_mesh):
    """A silent dimension change is the failure ADR-9 is aimed at. Both numbers get printed."""
    after = plate_mesh.copy()
    after.apply_scale(1.01)  # Ø8 -> Ø8.08: 0.08mm, eight times the tolerance
    result = repair.verify(plate_mesh, after)
    assert not result.passed
    assert result.status == repair.FAIL
    moved = [d for d in result.dimensions if abs(d.delta) > repair.DEFAULT_DIM_TOL]
    assert moved
    text = str(result)
    assert f"{moved[0].before:.4f}" in text
    assert f"{moved[0].after:.4f}" in text


def test_a_dimension_inside_tolerance_passes(plate_mesh):
    result = repair.verify(plate_mesh, plate_mesh.copy())
    assert result.passed
    assert result.status == repair.PASS
    assert result.dimensions


def test_the_tolerance_is_twice_the_tier_1_guarantee():
    """0.01mm, stated rather than tuned: 2x the +/-0.005mm Tier 1 promise."""
    assert repair.DEFAULT_DIM_TOL == 0.01


def test_a_tighter_tolerance_is_honoured(plate_mesh):
    after = plate_mesh.copy()
    after.apply_scale(1.0005)  # Ø8 -> Ø8.004
    assert repair.verify(plate_mesh, after, tol=0.01).passed
    assert not repair.verify(plate_mesh, after, tol=0.001).passed


def test_a_mesh_too_broken_to_section_never_passes():
    """It does not report success on the grounds that it could not look.

    This one is *also* still open after the repair, so the status is the sharper of the two
    verdicts -- FAIL, a known defect, rather than UNVERIFIABLE, the absence of one. Both are
    non-pass; the report still states that nothing could be probed.
    """
    flat = trimesh.Trimesh(
        vertices=np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]]),
        faces=np.array([[0, 1, 2]]),
        process=False,
    )
    result = repair.repair(flat)
    assert not result.passed
    assert result.status != repair.PASS
    assert "could not be probed" in str(result)


def test_a_part_with_no_tier_1_feature_is_unverifiable_not_a_pass():
    """A plain block carries nothing a Z-scan can compare, and the report says so."""
    from build123d import Box, BuildPart

    from threedp.features import _tessellate

    with BuildPart() as p:
        Box(20.0, 20.0, 10.0)
    result = repair.repair(_tessellate(p.part))
    assert result.after.watertight, "the block is fine; the point is that it is uncheckable"
    assert result.status == repair.UNVERIFIABLE
    assert not result.passed
    assert "no Tier 1 feature" in str(result)


def test_a_repair_that_leaves_the_mesh_open_fails(plate_mesh):
    """Watertight-after is necessary, just nowhere near sufficient."""
    broken = _drop_faces(plate_mesh, [10, 11, 12])
    result = repair.repair(broken, ops=("merge_vertices",))  # deliberately no fill_holes
    assert not result.after.watertight
    assert not result.passed
    assert "watertight" in str(result).lower()


def test_repair_never_mutates_the_mesh_it_was_given(plate_mesh):
    """The caller's mesh is the before-state of the comparison; repairing it in place erases it."""
    broken = _drop_faces(plate_mesh, [10, 11, 12])
    before_faces = len(broken.faces)
    repair.repair(broken)
    assert len(broken.faces) == before_faces


def test_an_unknown_op_is_refused_rather_than_ignored(plate_mesh):
    with pytest.raises(repair.RepairError) as exc:
        repair.repair(plate_mesh.copy(), ops=("polish_it",))
    assert "polish_it" in str(exc.value)
    assert "fill_holes" in str(exc.value)


def test_the_report_carries_the_ops_that_were_applied(plate_mesh):
    broken = _flip_windings(plate_mesh, 200)
    result = repair.repair(broken)
    text = str(result)
    for op in result.ops:
        assert op in text


def test_verify_uses_the_one_ruler(plate_mesh):
    """Diameters must come from features/measure, not from a second fit invented here."""
    result = repair.verify(plate_mesh, plate_mesh.copy())
    found = features.from_mesh(plate_mesh)
    ruler = sorted(c.diameter for c in found.cylinders)
    assert sorted(d.before for d in result.dimensions) == pytest.approx(ruler, abs=1e-9)

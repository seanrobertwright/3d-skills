"""Contact sheets: legible, and never a gate.

A render that "succeeds" while showing a white part on a white background is worse than no
render, because it looks like evidence. These tests check legibility, not just exit status.
"""

import numpy as np
import pytest
import vtk
from vtkmodules.util import numpy_support

from threedp import render
from threedp.render import RenderError


def read_png(path):
    reader = vtk.vtkPNGReader()
    reader.SetFileName(str(path))
    reader.Update()
    image = reader.GetOutput()
    w, h, _ = image.GetDimensions()
    arr = numpy_support.vtk_to_numpy(image.GetPointData().GetScalars())
    return arr.reshape(h, w, -1)


@pytest.fixture(scope="module")
def sheet(canonical_stl, artifacts_dir):
    return render.contact_sheet(canonical_stl, artifacts_dir / "sheet.png", size=320)


def test_contact_sheet_is_written(sheet):
    assert sheet.path.exists()
    assert sheet.path.stat().st_size > 10_000


def test_contact_sheet_is_not_a_single_flat_colour(sheet):
    """The white-on-white failure: technically successful, completely useless."""
    px = read_png(sheet.path).astype(float)
    assert px.std() > 10.0, f"image is nearly flat (std {px.std():.2f})"


def test_contact_sheet_tiles_four_views(sheet, artifacts_dir):
    assert sheet.views == ("iso", "top", "front", "right")
    px = read_png(sheet.path)
    assert px.shape[0] == 640 and px.shape[1] == 640  # 2x2 grid of 320px views


def test_background_is_a_gradient(sheet):
    """Top and bottom of the sheet must differ, or the background is flat."""
    px = read_png(sheet.path).astype(float)
    top_strip = px[2:8, :, :].mean()
    mid_strip = px[px.shape[0] // 2 - 3 : px.shape[0] // 2 + 3, :, :].mean()
    assert abs(top_strip - mid_strip) > 3.0


def test_part_is_visible_against_the_background(sheet):
    """The part is rendered in a colour; a monochrome sheet means it never drew."""
    px = read_png(sheet.path).astype(float)
    channel_spread = np.abs(px[:, :, 0] - px[:, :, 2])
    assert channel_spread.max() > 30, "no coloured material anywhere in the sheet"


def test_orthographic_views_get_a_real_mm_scale_bar(sheet):
    """PRD 6.6 mandates parallel projection on the ortho views; the bar is derived from it."""
    assert set(sheet.scale_bar_mm) == {"top", "front", "right"}
    assert "iso" not in sheet.scale_bar_mm, "a perspective view has no single scale to bar"
    for value in sheet.scale_bar_mm.values():
        assert value in (1, 2, 5, 10, 20, 50, 100, 200)


def test_scale_bar_can_be_turned_off(canonical_stl, artifacts_dir):
    s = render.contact_sheet(canonical_stl, artifacts_dir / "nobar.png", scale_bar=False, size=200)
    assert s.scale_bar_mm == {}


def test_a_single_view_still_renders(canonical_stl, artifacts_dir):
    s = render.contact_sheet(canonical_stl, artifacts_dir / "one.png", views=("top",), size=240)
    assert s.width == 240 and s.height == 240


def test_render_reads_a_3mf(canonical_3mf, artifacts_dir):
    s = render.contact_sheet(canonical_3mf, artifacts_dir / "from3mf.png", size=200)
    assert s.path.exists()


def test_output_directory_is_created(canonical_stl, artifacts_dir):
    out = artifacts_dir / "nested" / "deeper" / "sheet.png"
    render.contact_sheet(canonical_stl, out, views=("top",), size=160)
    assert out.exists()


def test_unknown_view_is_refused(canonical_stl, artifacts_dir):
    with pytest.raises(RenderError, match="unknown view"):
        render.contact_sheet(canonical_stl, artifacts_dir / "x.png", views=("underneath",))


def test_no_views_is_refused(canonical_stl, artifacts_dir):
    with pytest.raises(RenderError):
        render.contact_sheet(canonical_stl, artifacts_dir / "x.png", views=())


def test_unknown_projection_is_refused(canonical_stl, artifacts_dir):
    with pytest.raises(RenderError, match="projection"):
        render.contact_sheet(canonical_stl, artifacts_dir / "x.png", projection="isometric")


def test_unknown_plate_profile_is_refused(canonical_stl, artifacts_dir):
    with pytest.raises(RenderError, match="printer profile"):
        render.contact_sheet(canonical_stl, artifacts_dir / "x.png", plate="ender3", size=160)


def test_render_is_a_channel_not_a_gate():
    """There is no code path by which a render can contribute to a verdict.

    ``intent.check`` takes a ``FeatureSet`` and an intent, full stop. It neither imports the
    render module nor accepts an image, so render success cannot become evidence of correctness
    (PRD Principle 1).
    """
    import inspect

    from threedp import features, intent

    assert not hasattr(intent, "render")
    assert not hasattr(intent, "contact_sheet")
    assert "threedp.render" not in inspect.getsource(intent)
    assert "threedp.render" not in inspect.getsource(features)

    params = inspect.signature(intent.check).parameters
    assert list(params) == ["features", "intent"]
    assert set(intent.MEASURE_KINDS) & {"render", "contact_sheet", "image"} == set()

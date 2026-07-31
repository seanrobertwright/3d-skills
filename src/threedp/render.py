"""VTK offscreen contact sheet.

**Renders are a channel, not a gate** (PRD Principle 1). Nothing in this module ever contributes
to a pass verdict -- the founding anecdote is a part with three real defects that rendered
cleanly. What a render is for is gross-error detection and the human's understanding.

Which makes legibility a requirement rather than styling. A naive VTK render produces **a white
part on a white background**: technically successful, completely useless. PRD 6.6 therefore
mandates all of gradient background, Phong-shaded coloured material, silhouette and feature
edges at 20-25 deg, three-point lighting, **parallel projection on the orthographic views**, a mm
scale bar, and a build-plate reference.

Offscreen rendering works natively on Windows -- no OSMesa, no EGL.

All dimensions are millimetres.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import vtk
from vtkmodules.util import numpy_support

__all__ = ["RenderError", "ContactSheet", "contact_sheet", "VIEWS", "FEATURE_ANGLE_DEG"]

# PRD 6.6 mandates feature edges at 20-25 deg. 22 sits mid-band: low enough to draw the edges
# that describe a part's form, high enough not to outline every tessellation facet.
FEATURE_ANGLE_DEG = 22.0

VIEWS = ("iso", "top", "front", "right")

# camera direction (from the part toward the camera) and up vector, per view
_VIEW_VECTORS = {
    "iso": ((1.0, -1.0, 0.8), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
}

_PART_COLOR = (0.29, 0.56, 0.85)
_EDGE_COLOR = (0.06, 0.09, 0.14)
_BG_BOTTOM = (0.11, 0.13, 0.18)
_BG_TOP = (0.30, 0.35, 0.44)
_GRID_COLOR = (0.42, 0.47, 0.55)
_PLATE_COLOR = (0.85, 0.55, 0.25)
_NICE_BARS = (1, 2, 5, 10, 20, 50, 100, 200)
_GRID_PITCH = 10.0


class RenderError(Exception):
    """A contact sheet could not be produced. Never silently swallowed -- but never a gate."""


@dataclass(frozen=True)
class ContactSheet:
    path: Path
    views: tuple[str, ...]
    width: int
    height: int
    scale_bar_mm: dict[str, float]

    def __str__(self) -> str:
        return (
            f"contact sheet {self.path}  {self.width}x{self.height}px  "
            f"views {', '.join(self.views)}  (channel, not a gate)"
        )


# --- geometry plumbing ------------------------------------------------------------------------


def _load_polydata(path: str | Path) -> vtk.vtkPolyData:
    from threedp.features import load_mesh

    mesh = load_mesh(path)
    points = vtk.vtkPoints()
    points.SetData(numpy_support.numpy_to_vtk(np.ascontiguousarray(mesh.vertices), deep=True))

    faces = np.asarray(mesh.faces, dtype=np.int64)
    array = vtk.vtkCellArray()
    array.SetData(
        numpy_support.numpy_to_vtkIdTypeArray(
            np.arange(0, 3 * len(faces) + 1, 3, dtype=np.int64), deep=True
        ),
        numpy_support.numpy_to_vtkIdTypeArray(np.ascontiguousarray(faces.ravel()), deep=True),
    )

    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(array)

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(FEATURE_ANGLE_DEG)
    normals.SplittingOn()
    normals.ConsistencyOn()
    normals.Update()
    return normals.GetOutput()


def _plate_size(plate: str | None) -> tuple[float, float]:
    if not plate:
        return (0.0, 0.0)
    from threedp.compensate import profiles_dir

    try:
        data = json.loads((profiles_dir() / f"printer-{plate}.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise RenderError(f"could not read the printer profile for plate {plate!r}: {exc}") from exc
    build = data.get("plate") or data.get("build_volume") or {}
    return (
        float(build.get("width", build.get("x", 0))),
        float(build.get("depth", build.get("y", 0))),
    )


def _lines_actor(segments: np.ndarray, color, width: float, opacity: float = 1.0) -> vtk.vtkActor:
    """Build a line actor from an (N, 2, 3) array of segment endpoints."""
    flat = segments.reshape(-1, 3)
    points = vtk.vtkPoints()
    points.SetData(numpy_support.numpy_to_vtk(np.ascontiguousarray(flat), deep=True))
    cells = vtk.vtkCellArray()
    for i in range(len(segments)):
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, 2 * i)
        line.GetPointIds().SetId(1, 2 * i + 1)
        cells.InsertNextCell(line)
    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetLines(cells)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*color)
    actor.GetProperty().SetLineWidth(width)
    actor.GetProperty().SetOpacity(opacity)
    actor.GetProperty().LightingOff()
    return actor


def _ground_reference(bounds, plate: tuple[float, float]) -> list[vtk.vtkActor]:
    """A 10mm ground grid under the part, plus the build-plate outline when it is in view.

    The grid is what makes a render size-legible at a glance; the plate outline answers "does
    this fit?" -- and for a 30mm part on a 256mm plate the outline is off-view, which is why
    both exist rather than only the outline.
    """
    x0, x1, y0, y1, z0, _z1 = bounds
    span = max(x1 - x0, y1 - y0, 1.0) * 1.6
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = max(span / 2, _GRID_PITCH)
    lo_x = math.floor((cx - half) / _GRID_PITCH) * _GRID_PITCH
    hi_x = math.ceil((cx + half) / _GRID_PITCH) * _GRID_PITCH
    lo_y = math.floor((cy - half) / _GRID_PITCH) * _GRID_PITCH
    hi_y = math.ceil((cy + half) / _GRID_PITCH) * _GRID_PITCH

    segs = []
    for x in np.arange(lo_x, hi_x + _GRID_PITCH / 2, _GRID_PITCH):
        segs.append([[x, lo_y, z0], [x, hi_y, z0]])
    for y in np.arange(lo_y, hi_y + _GRID_PITCH / 2, _GRID_PITCH):
        segs.append([[lo_x, y, z0], [hi_x, y, z0]])
    actors = [_lines_actor(np.array(segs, dtype=float), _GRID_COLOR, 1.0, opacity=0.45)]

    pw, pd = plate
    if pw > 0 and pd > 0:
        hx, hy = pw / 2, pd / 2
        corners = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
        outline = np.array(
            [[[*corners[i], z0], [*corners[(i + 1) % 4], z0]] for i in range(4)],
            dtype=float,
        )
        actors.append(_lines_actor(outline, _PLATE_COLOR, 2.5))
    return actors


def _text(label: str, x: int, y: int, size: int = 16, color=(0.93, 0.95, 0.98)) -> vtk.vtkTextActor:
    actor = vtk.vtkTextActor()
    actor.SetInput(label)
    prop = actor.GetTextProperty()
    prop.SetFontSize(size)
    prop.SetColor(*color)
    prop.SetFontFamilyToCourier()
    actor.SetDisplayPosition(x, y)
    return actor


def _scale_bar(pixels_per_mm: float, width_px: int) -> tuple[list, float]:
    """A real mm scale bar, sized from the camera's own parallel scale."""
    target_px = width_px * 0.22
    best = _NICE_BARS[0]
    for candidate in _NICE_BARS:
        if candidate * pixels_per_mm <= target_px:
            best = candidate
    length_px = best * pixels_per_mm
    x0, y0 = 18, 18
    x1 = x0 + length_px

    points = vtk.vtkPoints()
    for px, py in ((x0, y0), (x1, y0), (x0, y0 - 5), (x0, y0 + 5), (x1, y0 - 5), (x1, y0 + 5)):
        points.InsertNextPoint(px, py, 0)
    cells = vtk.vtkCellArray()
    for a, b in ((0, 1), (2, 3), (4, 5)):
        line = vtk.vtkLine()
        line.GetPointIds().SetId(0, a)
        line.GetPointIds().SetId(1, b)
        cells.InsertNextCell(line)
    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetLines(cells)

    mapper = vtk.vtkPolyDataMapper2D()
    mapper.SetInputData(poly)
    actor = vtk.vtkActor2D()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(0.95, 0.95, 0.95)
    actor.GetProperty().SetLineWidth(2.0)
    return [actor, _text(f"{best} mm", int(x0), int(y0) + 10, size=14)], float(best)


# --- one view ---------------------------------------------------------------------------------


def _render_view(
    poly: vtk.vtkPolyData,
    view: str,
    size: int,
    projection: str,
    scale_bar: bool,
    plate: tuple[float, float],
) -> tuple[vtk.vtkImageData, float]:
    renderer = vtk.vtkRenderer()
    # Gradient background. Without it a light part on a light background is invisible, which is
    # the exact failure the spike reproduced.
    renderer.GradientBackgroundOn()
    renderer.SetBackground(*_BG_BOTTOM)
    renderer.SetBackground2(*_BG_TOP)

    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(poly)
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetInterpolationToPhong()
    prop.SetColor(*_PART_COLOR)
    prop.SetDiffuse(0.75)
    prop.SetAmbient(0.22)
    prop.SetSpecular(0.35)
    prop.SetSpecularPower(28)
    renderer.AddActor(actor)

    edges = vtk.vtkFeatureEdges()
    edges.SetInputData(poly)
    edges.BoundaryEdgesOn()
    edges.FeatureEdgesOn()
    edges.SetFeatureAngle(FEATURE_ANGLE_DEG)
    edges.ManifoldEdgesOff()
    edges.NonManifoldEdgesOff()
    edge_mapper = vtk.vtkPolyDataMapper()
    edge_mapper.SetInputConnection(edges.GetOutputPort())
    # vtkFeatureEdges tags its output with an edge-type scalar. Left visible, the mapper colours
    # the edges through a lookup table and ignores SetColor entirely -- they come out red.
    edge_mapper.ScalarVisibilityOff()
    edge_actor = vtk.vtkActor()
    edge_actor.SetMapper(edge_mapper)
    edge_actor.GetProperty().SetColor(*_EDGE_COLOR)
    edge_actor.GetProperty().SetLineWidth(1.6)
    edge_actor.GetProperty().LightingOff()
    renderer.AddActor(edge_actor)

    for ground in _ground_reference(poly.GetBounds(), plate):
        renderer.AddActor(ground)

    # three-point lighting
    light_kit = vtk.vtkLightKit()
    light_kit.SetKeyLightIntensity(1.05)
    light_kit.SetKeyToFillRatio(2.6)
    light_kit.SetKeyToHeadRatio(3.2)
    light_kit.SetKeyToBackRatio(3.0)
    light_kit.AddLightsToRenderer(renderer)

    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(size, size)
    window.AddRenderer(renderer)

    direction, up = _VIEW_VECTORS[view]
    camera = renderer.GetActiveCamera()
    # Parallel projection on the orthographic views: a perspective "top" view is not a top view,
    # and measuring anything off one is wrong (PRD 6.6). Iso keeps perspective for readability.
    ortho = view != "iso"
    camera.SetParallelProjection(bool(ortho and projection == "parallel"))
    camera.SetPosition(*direction)
    camera.SetFocalPoint(0.0, 0.0, 0.0)
    camera.SetViewUp(*up)
    renderer.ResetCamera(poly.GetBounds())
    camera.Zoom(0.82)

    bar_mm = 0.0
    if scale_bar and camera.GetParallelProjection():
        pixels_per_mm = (size / 2.0) / camera.GetParallelScale()
        actors, bar_mm = _scale_bar(pixels_per_mm, size)
        for a in actors:
            renderer.AddViewProp(a)
        renderer.AddViewProp(_text(view, 14, size - 26, size=18))
    else:
        renderer.AddViewProp(_text(f"{view} (perspective - not to scale)", 14, size - 26, size=18))

    window.Render()

    grabber = vtk.vtkWindowToImageFilter()
    grabber.SetInput(window)
    grabber.SetInputBufferTypeToRGB()
    grabber.ReadFrontBufferOff()
    grabber.Update()
    image = vtk.vtkImageData()
    image.DeepCopy(grabber.GetOutput())
    window.Finalize()
    return image, bar_mm


# --- the sheet --------------------------------------------------------------------------------


def contact_sheet(
    path: str | Path,
    out: str | Path,
    views: tuple[str, ...] = VIEWS,
    projection: str = "parallel",
    scale_bar: bool = True,
    plate: str | None = "p1s",
    size: int = 640,
) -> ContactSheet:
    """Render one annotated PNG tiling several views of a part.

    Four views tile into a single image so that inspecting a part is cheap enough to do on every
    iteration -- which is the only way a render earns its place in the loop at all.
    """
    for view in views:
        if view not in _VIEW_VECTORS:
            raise RenderError(f"unknown view {view!r}; expected some of {sorted(_VIEW_VECTORS)}")
    if not views:
        raise RenderError("a contact sheet with no views shows nothing")
    if projection not in ("parallel", "perspective"):
        raise RenderError(f"unknown projection {projection!r}; expected parallel or perspective")

    poly = _load_polydata(path)
    if poly.GetNumberOfPolys() == 0:
        raise RenderError(f"{path} tessellated to zero triangles; there is nothing to render")

    plate_size = _plate_size(plate)
    images, bars = [], {}
    for view in views:
        image, bar_mm = _render_view(poly, view, size, projection, scale_bar, plate_size)
        images.append(image)
        if bar_mm:
            bars[view] = bar_mm

    tiled = _tile(images)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(out))
    writer.SetInputData(tiled)
    writer.Write()
    if not out.exists():
        raise RenderError(f"the PNG writer reported success but wrote no file at {out}")

    dims = tiled.GetDimensions()
    return ContactSheet(out, tuple(views), dims[0], dims[1], bars)


def _tile(images: list[vtk.vtkImageData]) -> vtk.vtkImageData:
    """Tile view images into a grid, two per row."""
    if len(images) == 1:
        return images[0]
    per_row = 2
    rows = []
    for start in range(0, len(images), per_row):
        chunk = images[start : start + per_row]
        if len(chunk) == 1:
            rows.append(chunk[0])
            continue
        append = vtk.vtkImageAppend()
        append.SetAppendAxis(0)
        for image in chunk:
            append.AddInputData(image)
        append.Update()
        row = vtk.vtkImageData()
        row.DeepCopy(append.GetOutput())
        rows.append(row)
    if len(rows) == 1:
        return rows[0]
    append = vtk.vtkImageAppend()
    append.SetAppendAxis(1)
    for row in reversed(rows):  # first row on top
        append.AddInputData(row)
    append.Update()
    out = vtk.vtkImageData()
    out.DeepCopy(append.GetOutput())
    return out

"""Optional isometric PNG rendering for real STL artifacts."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)


class PreviewGenerationResult(TypedDict):
    status: Literal["CREATED", "BLOCKED"]
    artifact_path: str | None
    file_size_bytes: int | None
    width_px: int | None
    height_px: int | None
    message: str


def _blocked(message: str) -> PreviewGenerationResult:
    return {
        "status": "BLOCKED",
        "artifact_path": None,
        "file_size_bytes": None,
        "width_px": None,
        "height_px": None,
        "message": message,
    }


def generate_stl_preview(
    stl_path: Path,
    output_path: Path,
) -> PreviewGenerationResult:
    """Render an actual STL mesh to an isometric PNG without a display server."""
    if not stl_path.is_file() or stl_path.stat().st_size == 0:
        return _blocked("The STL file is missing or empty. No preview was created.")

    try:
        import trimesh
    except ImportError:
        return _blocked(
            "The optional trimesh preview dependency is unavailable. "
            "No preview image was created."
        )

    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError:
        return _blocked(
            "The optional Matplotlib headless renderer is unavailable. "
            "No preview image was created."
        )

    temporary_path = output_path.with_name(f"{output_path.stem}.tmp.png")
    try:
        mesh: Any = trimesh.load(
            str(stl_path),
            file_type="stl",
            force="mesh",
            process=False,
        )
        faces = mesh.vertices[mesh.faces]
        bounds = mesh.bounds
        extents = mesh.extents
        if (
            mesh.is_empty
            or len(mesh.faces) == 0
            or faces.ndim != 3
            or faces.shape[1:] != (3, 3)
            or not all(math.isfinite(float(value)) for value in faces.flat)
            or not all(float(value) > 0 for value in extents)
        ):
            return _blocked(
                "The STL does not contain a renderable finite triangle mesh. "
                "No preview image was created."
            )

        figure = Figure(figsize=(8, 6), dpi=140, facecolor="#f7f8fa")
        canvas = FigureCanvasAgg(figure)
        axes = figure.add_subplot(111, projection="3d")
        collection = Poly3DCollection(
            faces,
            facecolor="#5f8fc7",
            edgecolor="#26374a",
            linewidth=0.08,
            alpha=1.0,
        )
        axes.add_collection3d(collection)
        axes.set_xlim(float(bounds[0][0]), float(bounds[1][0]))
        axes.set_ylim(float(bounds[0][1]), float(bounds[1][1]))
        axes.set_zlim(float(bounds[0][2]), float(bounds[1][2]))
        axes.set_box_aspect([float(value) for value in extents])
        axes.view_init(elev=30, azim=45)
        axes.set_axis_off()
        figure.subplots_adjust(left=0, right=1, bottom=0, top=1)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.print_png(str(temporary_path))
        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise OSError("Renderer completed without producing a non-empty PNG.")
        temporary_path.replace(output_path)
        return {
            "status": "CREATED",
            "artifact_path": str(output_path),
            "file_size_bytes": output_path.stat().st_size,
            "width_px": int(figure.get_figwidth() * figure.dpi),
            "height_px": int(figure.get_figheight() * figure.dpi),
            "message": (
                "Isometric PNG rendered from the existing STL mesh. "
                "It is a visualization of reference concept geometry, not validation."
            ),
        }
    except Exception as exc:
        logger.exception("STL preview rendering failed for %s", stl_path)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove incomplete preview file %s", temporary_path)
        return _blocked(
            f"Headless STL preview rendering failed ({type(exc).__name__}). "
            "No usable preview image is available."
        )

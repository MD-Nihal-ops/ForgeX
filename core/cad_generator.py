"""Optional CadQuery export for reference-concept geometry."""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Literal, TypedDict

logger = logging.getLogger(__name__)


class CadGenerationResult(TypedDict):
    status: Literal["CREATED", "BLOCKED"]
    artifact_path: str | None
    message: str


def _blocked(message: str) -> CadGenerationResult:
    return {"status": "BLOCKED", "artifact_path": None, "message": message}


def _export_stl(model: Any, output_path: Path) -> None:
    import cadquery as cq

    temporary_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cq.exporters.export(model, str(temporary_path), exportType="STL")
        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise OSError("CadQuery completed without producing a non-empty STL file.")
        temporary_path.replace(output_path)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove incomplete CAD output %s", temporary_path)
        raise


def generate_reference_gripper_stl(
    alternative: dict[str, Any],
    output_path: Path,
) -> CadGenerationResult:
    """Export the existing two-finger reference gripper concept."""
    try:
        import cadquery as cq
    except ImportError:
        return _blocked(
            "CadQuery or one of its required dependencies is unavailable in this "
            "environment. No STL file was created."
        )

    parameters = alternative.get("key_parameters", {})
    try:
        finger_count = parameters.get("finger_count")
        finger_length = float(parameters["finger_length_mm"])
        finger_width = float(parameters["finger_width_mm"])
        finger_thickness = float(parameters["finger_thickness_mm"])
        diameter_m = float(parameters["object_diameter_m"])
        if finger_count != 2:
            raise ValueError("The reference CAD generator requires exactly two fingers.")
        dimensions = (finger_length, finger_width, finger_thickness, diameter_m)
        if any(not math.isfinite(value) or value <= 0 for value in dimensions):
            raise ValueError("CAD dimensions must be finite positive reference values.")

        diameter_mm = diameter_m * 1000
        base_depth = finger_width
        base_width = diameter_mm + 2 * finger_width
        base = (
            cq.Workplane("XY")
            .box(base_width, base_depth, finger_thickness)
            .translate((0, -base_depth / 2, finger_thickness / 2))
        )
        model = base
        positions = (
            -(diameter_mm / 2 + finger_width / 2),
            diameter_mm / 2 + finger_width / 2,
        )
        for x_position in positions:
            finger = (
                cq.Workplane("XY")
                .box(finger_width, finger_length, finger_thickness)
                .translate(
                    (x_position, finger_length / 2, finger_thickness / 2)
                )
            )
            model = model.union(finger)
            if "roller" in str(alternative.get("id", "")).casefold():
                roller_radius = finger_width / 2
                roller = (
                    cq.Workplane("XY")
                    .circle(roller_radius)
                    .extrude(finger_thickness)
                    .translate((x_position, finger_length - roller_radius, 0))
                )
                model = model.union(roller)
        _export_stl(model, output_path)
    except Exception as exc:
        logger.exception(
            "Reference-concept STL generation failed for %s",
            alternative.get("id"),
        )
        return _blocked(
            f"CadQuery STL generation failed ({type(exc).__name__}): {exc}. "
            "No usable STL file is available."
        )
    return {
        "status": "CREATED",
        "artifact_path": str(output_path),
        "message": (
            "Reference concept model STL created from the selected alternative's "
            "reference parameters. It is not optimized, validated, simulation-backed, "
            "or manufacturing-ready geometry."
        ),
    }


def generate_reference_product_stl(
    alternative: dict[str, Any],
    output_path: Path,
    product_type: str,
) -> CadGenerationResult:
    """Export a parametric product-family concept when a generator is registered."""
    if product_type == "servo_driven_gripper":
        return generate_reference_gripper_stl(alternative, output_path)
    if product_type == "civil_concept_assistant":
        return _blocked(
            "Civil concept advisory does not generate CAD or construction geometry. "
            "No file was created."
        )
    try:
        import cadquery as cq
    except ImportError:
        return _blocked("CadQuery is unavailable. No CAD file was created.")

    parameters = alternative.get("key_parameters", {})
    design_id = str(alternative.get("id", ""))
    try:
        if product_type == "electronics_enclosure":
            length = float(parameters["internal_length_mm"])
            width = float(parameters["internal_width_mm"])
            height = float(parameters["internal_height_mm"])
            wall = float(parameters["wall_thickness_mm"])
            outer = cq.Workplane("XY").box(
                length + 2 * wall,
                width + 2 * wall,
                height + wall,
                centered=(True, True, False),
            )
            cavity = (
                cq.Workplane("XY")
                .box(length, width, height + 1, centered=(True, True, False))
                .translate((0, 0, wall))
            )
            model = outer.cut(cavity)
            if design_id == "vented_rectangular_enclosure":
                slot_width = min(length / 3, 15.0)
                slot_height = min(height / 3, 15.0)
                for x_position in (-length / 4, length / 4):
                    slot = (
                        cq.Workplane("XY")
                        .box(slot_width, width + 2 * wall + 2, slot_height)
                        .translate((x_position, 0, wall + height / 2))
                    )
                    model = model.cut(slot)
            count = int(parameters.get("cable_port_count", 0))
            diameter = float(parameters.get("cable_port_diameter_mm", 0))
            if count and diameter > 0:
                for index in range(count):
                    x_position = (index - (count - 1) / 2) * length / count
                    port = (
                        cq.Workplane("XZ")
                        .circle(diameter / 2)
                        .extrude(wall + 2)
                        .translate((x_position, -width / 2, height / 2))
                    )
                    model = model.cut(port)
            lid = (
                cq.Workplane("XY")
                .box(length + 2 * wall, width + 2 * wall, wall)
                .translate((0, 0, height + wall + wall / 2))
            )
            model = model.union(lid)
            if design_id == "wall_mount_enclosure":
                lug = cq.Workplane("XY").box(12, 6, wall, centered=(True, True, False))
                lug_offset = length / 2 + wall + 6
                model = model.union(lug.translate((-lug_offset, 0, 0)))
                model = model.union(lug.translate((lug_offset, 0, 0)))
        elif product_type == "mounting_bracket":
            width = float(parameters["base_width_mm"])
            arm = float(parameters["arm_length_mm"])
            thickness = float(parameters["reference_thickness_mm"])
            base = (
                cq.Workplane("XY")
                .box(width, arm, thickness)
                .translate((0, arm / 2, thickness / 2))
            )
            upright = (
                cq.Workplane("XY")
                .box(width, thickness, arm)
                .translate((0, -thickness / 2, arm / 2))
            )
            model = base.union(upright)
            if design_id == "reinforced_triangular_bracket":
                brace = (
                    cq.Workplane("YZ")
                    .polyline([(0, 0), (arm, 0), (0, arm)])
                    .close()
                    .extrude(thickness)
                    .translate((-thickness / 2, 0, 0))
                )
                model = model.union(brace)
            if design_id == "t_shaped_bracket":
                crossbar = cq.Workplane("XY").box(
                    width * 1.4, thickness, thickness
                ).translate((0, -thickness / 2, arm + thickness / 2))
                model = model.union(crossbar)
            diameter = float(parameters["fastener_diameter_mm"])
            for x_position in (-width / 4, width / 4):
                hole = (
                    cq.Workplane("XY")
                    .circle(diameter / 2)
                    .extrude(thickness * 2)
                    .translate((x_position, arm / 2, -thickness))
                )
                model = model.cut(hole)
        elif product_type in {
            "simple_house_model",
            "residential_building_concept",
        }:
            residential = product_type == "residential_building_concept"
            length = float(parameters["footprint_length_mm"])
            width = float(parameters["footprint_width_mm"])
            height = float(parameters["reference_wall_height_mm"])
            wall = float(parameters["wall_thickness_mm"])
            foundation = (
                float(parameters["foundation_thickness_mm"]) if residential else 0.0
            )
            roof_angle = math.radians(float(parameters["roof_pitch_degrees"]))
            roof_rise = (width / 2) * math.tan(roof_angle)
            walls = cq.Workplane("XY").box(
                length, width, height, centered=(True, True, False)
            ).translate((0, 0, foundation))
            interior = (
                cq.Workplane("XY")
                .box(
                    length - 2 * wall,
                    width - 2 * wall,
                    height + 1,
                    centered=(True, True, False),
                )
                .translate((0, 0, foundation))
            )
            model = walls.cut(interior)
            if residential:
                slab = cq.Workplane("XY").box(
                    length,
                    width,
                    foundation,
                    centered=(True, True, False),
                )
                model = slab.union(model)
            if float(parameters.get("door_width_mm", 0)) > 0:
                door = (
                    cq.Workplane("XY")
                    .box(
                        float(parameters["door_width_mm"]),
                        wall * 3,
                        float(parameters["door_height_mm"]),
                    )
                    .translate(
                        (
                            0,
                            -width / 2,
                            foundation + float(parameters["door_height_mm"]) / 2,
                        )
                    )
                )
                model = model.cut(door)
            roof = (
                cq.Workplane("YZ")
                .polyline(
                    [
                        (-width / 2, foundation + height),
                        (width / 2, foundation + height),
                        (0, foundation + height + roof_rise),
                    ]
                )
                .close()
                .extrude(length / 2, both=True)
            )
            model = model.union(roof)
        else:
            raise ValueError(f"No CAD generator is registered for {product_type!r}.")
        _export_stl(model, output_path)
    except Exception as exc:
        logger.exception(
            "Reference-concept STL generation failed for product family %s",
            product_type,
        )
        return _blocked(
            f"Reference CAD generation failed ({type(exc).__name__}). "
            "No usable STL file is available."
        )
    message = (
        "A parametric reference concept STL was created from user inputs and "
        "reference parameters. It is not optimized, simulation-validated, "
        "certified, or manufacturing-ready."
    )
    if product_type == "simple_house_model" and int(parameters.get("window_count", 0)) > 0:
        message += (
            " Window openings were omitted because window dimensions and spacing "
            "were not provided."
        )
    return {
        "status": "CREATED",
        "artifact_path": str(output_path),
        "message": message,
    }

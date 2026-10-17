"""Product-family registry and deterministic non-gripper concept screening."""

from __future__ import annotations

import math
import json
from dataclasses import dataclass
from typing import Any

from core.calculations import (
    calculate_beam_bending_stress,
    calculate_safety_factor,
    check_minimum_wall_thickness,
    estimate_mass,
    estimate_material_cost,
    estimate_print_time,
)
from core.data_loader import CatalogError, get_material
from core.models import CalculationResult, DesignAlternative
from core.requirements import DesignStatus, EvidenceStatus, ProductType
from core.residential_concept import (
    RESIDENTIAL_REQUIRED_FIELDS,
    calculate_residential_panel,
    validate_residential_inputs,
)

PRINT_SPEED_CM3_PER_HOUR = 10.0


@dataclass(frozen=True)
class ProductFamily:
    product_type: ProductType
    title: str
    required_fields: tuple[tuple[str, str, str], ...]
    alternatives: tuple[tuple[str, str], ...]
    disclaimer: str
    cad_supported: bool
    report_template_id: str

    @property
    def report_template(self) -> str:
        return (
            f"# {self.title} — ForgeX preliminary concept report\n\n"
            f"> {self.disclaimer}\n\n"
            "## Brief and user-provided inputs\n\n"
            "## Reference alternatives and comparison\n\n"
            "## Deterministic calculations and evidence\n\n"
            "## Limitations and required professional review\n"
        )

    @property
    def calculation_strategy(self) -> str:
        return {
            ProductType.SERVO_DRIVEN_GRIPPER: "core.design_engine.generate_gripper_designs",
            ProductType.ELECTRONICS_ENCLOSURE: "enclosure_volume_and_clearance_screen",
            ProductType.MOUNTING_BRACKET: "cantilever_bending_and_fastener_screen",
            ProductType.SIMPLE_HOUSE_MODEL: "wall_roof_volume_and_opening_screen",
            ProductType.RESIDENTIAL_BUILDING_CONCEPT: "residential_area_wall_roof_catalog_screen",
            ProductType.CIVIL_CONCEPT_ASSISTANT: "advisory_only_no_engineering_calculations",
        }[self.product_type]

    @property
    def evidence_strategy(self) -> str:
        return (
            "calculation results and explicit constraints; estimates are ESTIMATED, "
            "missing values are BLOCKED, advisory comparisons remain UNVERIFIED"
        )

    @property
    def cad_generator_id(self) -> str:
        return (
            f"core.cad_generator:{self.product_type.value}"
            if self.cad_supported
            else "disabled_advisory_only"
        )


FAMILIES: dict[str, ProductFamily] = {
    ProductType.SERVO_DRIVEN_GRIPPER.value: ProductFamily(
        ProductType.SERVO_DRIVEN_GRIPPER,
        "Servo-driven gripper",
        (),
        (
            ("two_finger_rigid_gripper", "Two-finger rigid gripper"),
            ("compliant_finger_gripper", "Compliant finger gripper"),
            ("wrap_around_roller_gripper", "Wrap-around roller gripper"),
        ),
        "Reference concept only; not optimized, validated, certified, or manufacturing-ready.",
        True,
        "gripper-engineering-report",
    ),
    ProductType.ELECTRONICS_ENCLOSURE.value: ProductFamily(
        ProductType.ELECTRONICS_ENCLOSURE,
        "Electronics enclosure",
        (
            ("internal_length_mm", "Internal length (mm)", "What internal length is required?"),
            ("internal_width_mm", "Internal width (mm)", "What internal width is required?"),
            ("internal_height_mm", "Internal height (mm)", "What internal height is required?"),
            ("wall_thickness_mm", "Wall thickness (mm)", "What wall thickness should be used?"),
            ("lid_type", "Lid type", "Choose snap-fit or screw-mounted."),
            ("cable_port_count", "Cable port count", "How many cable ports are required?"),
            ("cable_port_diameter_mm", "Cable port diameter (mm)", "What is the cable port diameter?"),
            ("material", "Material", "Which catalog material should be used?"),
            ("minimum_wall_thickness_mm", "Minimum wall thickness (mm)", "What is the minimum acceptable wall thickness?"),
        ),
        (
            ("compact_rectangular_enclosure", "Compact rectangular enclosure"),
            ("vented_rectangular_enclosure", "Vented rectangular enclosure"),
            ("wall_mount_enclosure", "Wall-mount enclosure"),
        ),
        "Reference enclosure concepts and estimates only. Fit, ingress protection, heat dissipation, and printability are not validated.",
        True,
        "electronics-enclosure-report",
    ),
    ProductType.MOUNTING_BRACKET.value: ProductFamily(
        ProductType.MOUNTING_BRACKET,
        "Mounting bracket",
        (
            ("load_mass_kg", "Load mass (kg)", "What mass will the bracket support?"),
            ("load_distance_mm", "Load distance from mounting surface (mm)", "How far from the mounting surface is the load applied?"),
            ("base_width_mm", "Base width (mm)", "What base width is available?"),
            ("arm_length_mm", "Arm length (mm)", "What arm length is required?"),
            ("material", "Material", "Which catalog material should be used?"),
            ("minimum_safety_factor", "Minimum safety factor", "What minimum safety factor do you require?"),
            ("fastener_diameter_mm", "Fastener diameter (mm)", "What fastener diameter will be used?"),
        ),
        (
            ("l_shaped_bracket", "L-shaped bracket"),
            ("t_shaped_bracket", "T-shaped bracket"),
            ("reinforced_triangular_bracket", "Reinforced triangular bracket"),
        ),
        "Reference bracket concept only. Closed-form screening is not validation, FEA, fatigue analysis, or certification.",
        True,
        "mounting-bracket-report",
    ),
    ProductType.SIMPLE_HOUSE_MODEL.value: ProductFamily(
        ProductType.SIMPLE_HOUSE_MODEL,
        "Simple house model",
        (
            ("footprint_length_mm", "Footprint length (mm)", "What is the footprint length?"),
            ("footprint_width_mm", "Footprint width (mm)", "What is the footprint width?"),
            ("wall_height_mm", "Wall height (mm)", "What is the wall height?"),
            ("wall_thickness_mm", "Wall thickness (mm)", "What is the wall thickness?"),
            ("roof_pitch_degrees", "Roof pitch (degrees)", "What roof pitch is intended?"),
            ("door_width_mm", "Door width (mm)", "What door width is required?"),
            ("door_height_mm", "Door height (mm)", "What door height is required?"),
            ("window_count", "Number of windows", "How many windows are required?"),
            ("material", "Material", "Which catalog material should be used?"),
            ("minimum_wall_thickness_mm", "Minimum wall thickness (mm)", "What is the minimum acceptable wall thickness?"),
        ),
        (
            ("compact_gabled_house", "Compact gabled house"),
            ("wide_gabled_house", "Wide gabled house"),
            ("tall_gabled_house", "Tall gabled house"),
        ),
        "Scale model concept only; not architectural, structural, code-compliant, or construction-ready.",
        True,
        "simple-house-model-report",
    ),
    ProductType.RESIDENTIAL_BUILDING_CONCEPT.value: ProductFamily(
        ProductType.RESIDENTIAL_BUILDING_CONCEPT,
        "Residential building concept",
        RESIDENTIAL_REQUIRED_FIELDS,
        (
            ("residential_gabled_concept", "Residential gabled concept"),
            ("residential_compact_plan", "Compact residential plan concept"),
            ("residential_wide_plan", "Wide residential plan concept"),
        ),
        "Illustrative residential concept only; not architectural, structural, code-compliant, permitted, or construction-ready.",
        True,
        "residential-building-concept-report",
    ),
    ProductType.CIVIL_CONCEPT_ASSISTANT.value: ProductFamily(
        ProductType.CIVIL_CONCEPT_ASSISTANT,
        "Civil concept assistant",
        (),
        (
            ("site_constraints", "Site and constraints framing"),
            ("system_options", "Preliminary system options"),
            ("professional_review", "Required professional review"),
        ),
        "Preliminary advisory concepts only. Final structural, geotechnical, architectural, and code-compliance decisions require qualified professionals and local regulations.",
        False,
        "civil-advisory-report",
    ),
}


def get_product_family(product_type: str) -> ProductFamily:
    try:
        return FAMILIES[product_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported ForgeX product family: {product_type}") from exc


def missing_product_fields(product_type: str, values: dict[str, Any]) -> list[dict[str, str]]:
    family = get_product_family(product_type)
    return [
        {"name": name, "label": label, "question": question}
        for name, label, question in family.required_fields
        if values.get(name) is None or values.get(name) == ""
    ]


def validate_product_inputs(product_type: str, values: dict[str, Any]) -> dict[str, Any]:
    if product_type == ProductType.RESIDENTIAL_BUILDING_CONCEPT.value:
        return validate_residential_inputs(values)
    missing = missing_product_fields(product_type, values)
    if missing:
        raise ValueError(
            "Missing required inputs: " + ", ".join(row["name"] for row in missing)
        )
    clean = dict(values)
    for key, value in clean.items():
        if key in {"material", "lid_type"}:
            continue
        if isinstance(value, bool) or not isinstance(value, (float, int)):
            raise ValueError(f"{key} must be numeric.")
        if not math.isfinite(float(value)) or float(value) <= 0:
            if key in {"cable_port_count", "window_count"} and value == 0:
                continue
            if (
                product_type == ProductType.ELECTRONICS_ENCLOSURE.value
                and key == "cable_port_diameter_mm"
                and value == 0
                and clean.get("cable_port_count") == 0
            ):
                continue
            raise ValueError(f"{key} must be a finite positive value.")
    if product_type == ProductType.ELECTRONICS_ENCLOSURE.value:
        if clean["cable_port_count"] > 0 and clean["cable_port_diameter_mm"] <= 0:
            raise ValueError("cable_port_diameter_mm must be positive when cable ports are requested.")
        if clean["lid_type"] not in {"snap-fit", "screw-mounted"}:
            raise ValueError("lid_type must be 'snap-fit' or 'screw-mounted'.")
        if int(clean["cable_port_count"]) != clean["cable_port_count"]:
            raise ValueError("cable_port_count must be a whole number.")
        clean["cable_port_count"] = int(clean["cable_port_count"])
    if product_type == ProductType.SIMPLE_HOUSE_MODEL.value:
        if int(clean["window_count"]) != clean["window_count"]:
            raise ValueError("window_count must be a whole number.")
        clean["window_count"] = int(clean["window_count"])
        if clean["roof_pitch_degrees"] >= 90:
            raise ValueError("roof_pitch_degrees must be less than 90.")
        if clean["footprint_length_mm"] <= 2 * clean["wall_thickness_mm"]:
            raise ValueError("footprint_length_mm must exceed twice the wall thickness.")
        if clean["footprint_width_mm"] <= 2 * clean["wall_thickness_mm"]:
            raise ValueError("footprint_width_mm must exceed twice the wall thickness.")
    if product_type == ProductType.MOUNTING_BRACKET.value:
        if clean["minimum_safety_factor"] < 1:
            raise ValueError("minimum_safety_factor must be at least 1.")
    if product_type in {
        ProductType.ELECTRONICS_ENCLOSURE.value,
        ProductType.MOUNTING_BRACKET.value,
        ProductType.SIMPLE_HOUSE_MODEL.value,
    }:
        try:
            get_material(str(clean["material"]))
        except CatalogError as exc:
            raise ValueError(str(exc)) from exc
    return clean


def _calc_row(
    alternative_id: str,
    calculation: CalculationResult,
    evidence_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = calculation.model_dump(mode="json")
    evidence_rows.append(
        {
            "alternative_id": alternative_id,
            "source": calculation.name,
            "statement": (
                f"{calculation.equation}; result={calculation.output_value:g} "
                f"{calculation.unit}. {calculation.notes}"
            ),
            "status": calculation.evidence_status.value,
            "result": calculation.output_value,
            "unit": calculation.unit,
        }
    )
    return payload


def _check_result(
    name: str,
    equation: str,
    inputs: dict[str, Any],
    passed: bool,
    explanation: str,
) -> CalculationResult:
    return CalculationResult(
        name=name,
        equation=equation,
        inputs=inputs,
        output_value=1.0 if passed else 0.0,
        unit="1",
        evidence_status=EvidenceStatus.VERIFIED,
        notes=explanation,
    )


def _unverified_evidence(
    alternative_id: str,
    source: str,
    statement: str,
    evidence_rows: list[dict[str, Any]],
) -> None:
    evidence_rows.append(
        {
            "alternative_id": alternative_id,
            "source": source,
            "statement": statement,
            "status": EvidenceStatus.UNVERIFIED.value,
            "result": None,
            "unit": None,
        }
    )


def _estimated_result(
    name: str,
    equation: str,
    inputs: dict[str, Any],
    output_value: float,
    unit: str,
) -> CalculationResult:
    return CalculationResult(
        name=name,
        equation=equation,
        inputs=inputs,
        output_value=output_value,
        unit=unit,
        evidence_status=EvidenceStatus.ESTIMATED,
        notes="Deterministic arithmetic on user inputs and labeled reference geometry; not validation.",
    )


def _combine_checks(checks: list[bool | None]) -> bool | None:
    if False in checks:
        return False
    if None in checks:
        return None
    return True


def _volume_calculations(
    alternative_id: str,
    volume_cm3: float,
    material: str,
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    record = get_material(material)
    volume_m3 = volume_cm3 * 1e-6
    mass = estimate_mass(volume_m3, record.density_kg_m3)
    cost = estimate_material_cost(mass.output_value, record.cost_per_kg_usd)
    time = estimate_print_time(volume_cm3, PRINT_SPEED_CM3_PER_HOUR)
    calculations = [
        _calc_row(alternative_id, mass, evidence_rows),
        _calc_row(alternative_id, cost, evidence_rows),
        _calc_row(alternative_id, time, evidence_rows),
    ]
    return calculations, {
        "estimated_volume_cm3": volume_cm3,
        "estimated_mass_kg": mass.output_value,
        "estimated_material_cost_usd": cost.output_value,
        "estimated_print_time_hours": time.output_value,
    }


def _enclosure(
    alternative_id: str,
    values: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    length = float(values["internal_length_mm"])
    width = float(values["internal_width_mm"])
    height = float(values["internal_height_mm"])
    wall = float(values["wall_thickness_mm"])
    outer = (length + 2 * wall) * (width + 2 * wall) * (height + wall)
    inner = length * width * height
    wall_volume = outer - inner
    lid_volume = (length + 2 * wall) * (width + 2 * wall) * wall
    hole_area = math.pi * (float(values["cable_port_diameter_mm"]) / 2) ** 2
    port_cut = hole_area * wall * int(values["cable_port_count"])
    if alternative_id == "vented_rectangular_enclosure":
        slot_width = min(length / 3, 15.0)
        slot_height = min(height / 3, 15.0)
        vent_cut = 4 * slot_width * slot_height * wall
    else:
        vent_cut = 0.0
    lug_volume = (
        2 * 12.0 * 6.0 * wall
        if alternative_id == "wall_mount_enclosure"
        else 0.0
    )
    printed = max(0.0, wall_volume + lid_volume - port_cut - vent_cut + lug_volume)
    internal_calc = _estimated_result(
        f"{alternative_id}/internal_volume",
        "V_internal_mm3 = L_internal * W_internal * H_internal",
        {
            "internal_length_mm": length,
            "internal_width_mm": width,
            "internal_height_mm": height,
        },
        inner,
        "mm3",
    )
    wall_calc = _estimated_result(
        f"{alternative_id}/wall_volume",
        "V_wall_mm3 = V_outer_mm3 - V_open_cavity_mm3",
        {
            "outer_volume_mm3": outer,
            "internal_cavity_volume_mm3": inner,
            "reference_wall_thickness_mm": wall,
        },
        wall_volume,
        "mm3",
    )
    printed_calc = _estimated_result(
        f"{alternative_id}/estimated_printed_volume",
        "V_print_mm3 = V_wall + V_lid - V_ports - V_vents + V_mount_lugs",
        {
            "wall_volume_mm3": wall_volume,
            "lid_volume_mm3": lid_volume,
            "cable_port_removed_volume_mm3": port_cut,
            "vent_removed_volume_mm3": vent_cut,
            "mount_lug_volume_mm3": lug_volume,
        },
        printed,
        "mm3",
    )
    calculations, metrics = _volume_calculations(
        alternative_id, printed / 1000, str(values["material"]), evidence_rows
    )
    geometry_calculations = [
        _calc_row(alternative_id, calculation, evidence_rows)
        for calculation in (internal_calc, wall_calc, printed_calc)
    ]
    calculations.extend(geometry_calculations)
    wall_check = check_minimum_wall_thickness(
        wall, float(values["minimum_wall_thickness_mm"])
    )
    port_clear = _check_result(
        f"{alternative_id}/cable_port_clearance",
        "port diameter <= minimum internal enclosure span",
        {
            "cable_port_diameter_mm": values["cable_port_diameter_mm"],
            "minimum_internal_span_mm": min(length, width, height),
        },
        float(values["cable_port_diameter_mm"]) <= min(length, width, height),
        "Geometric size check only; connector body, strain relief, and routing clearance are not assessed.",
    )
    _unverified_evidence(
        alternative_id,
        f"{alternative_id}/lid_fit_reference_check",
        f"Lid type is {values['lid_type']}; mating clearance and retention requirements "
        "were not provided, so fit is not verified.",
        evidence_rows,
    )
    calculations.extend(
        _calc_row(alternative_id, item, evidence_rows)
        for item in (wall_check, port_clear)
    )
    if alternative_id == "vented_rectangular_enclosure":
        metrics_vent = {
            "reference_vent_slot_count": 4,
            "reference_vent_slot_width_mm": min(length / 3, 15.0),
            "reference_vent_slot_height_mm": min(height / 3, 15.0),
        }
    else:
        metrics_vent = {}
    metrics.update(
        {
            "internal_volume_mm3": length * width * height,
            "wall_volume_mm3": wall_volume,
            "minimum_wall_thickness_pass": wall_check.output_value == 1,
            "cable_port_clearance_pass": port_clear.output_value == 1,
            "lid_fit_reference_pass": None,
            "lid_type": values["lid_type"],
            "cable_port_count": values["cable_port_count"],
            **metrics_vent,
        }
    )
    return calculations, metrics


def _bracket(
    alternative_id: str,
    values: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mass_kg = float(values["load_mass_kg"])
    distance_m = float(values["load_distance_mm"]) / 1000
    width_m = float(values["base_width_mm"]) / 1000
    load_n = mass_kg * 9.80665
    moment_nm = load_n * distance_m
    variant_scale = {
        "l_shaped_bracket": 0.08,
        "t_shaped_bracket": 0.10,
        "reinforced_triangular_bracket": 0.12,
    }[alternative_id]
    # Thickness ratios are explicit reference geometry parameters, not optimized sizing.
    thickness_m = float(values["base_width_mm"]) * variant_scale / 1000
    section_modulus_m3 = width_m * thickness_m**2 / 6
    stress = calculate_beam_bending_stress(
        load_n, distance_m, section_modulus_m3
    )
    record = get_material(str(values["material"]))
    safety = calculate_safety_factor(record.yield_strength_mpa, stress.output_value)
    base_width_mm = float(values["base_width_mm"])
    arm_length_mm = float(values["arm_length_mm"])
    thickness_mm = thickness_m * 1000
    volume_mm3 = 2 * base_width_mm * arm_length_mm * thickness_mm
    fastener_holes_mm3 = (
        2
        * math.pi
        * (float(values["fastener_diameter_mm"]) / 2) ** 2
        * thickness_mm
    )
    if alternative_id == "t_shaped_bracket":
        volume_mm3 += 1.4 * base_width_mm * thickness_mm**2
    elif alternative_id == "reinforced_triangular_bracket":
        volume_mm3 += arm_length_mm**2 * thickness_mm / 2
    volume_mm3 = max(0.0, volume_mm3 - fastener_holes_mm3)
    volume_cm3 = volume_mm3 / 1000
    calculations, metrics = _volume_calculations(
        alternative_id, volume_cm3, str(values["material"]), evidence_rows
    )
    applied_load = _estimated_result(
        f"{alternative_id}/applied_load",
        "F_N = m_kg * g",
        {"load_mass_kg": mass_kg, "g_m_s2": 9.80665},
        load_n,
        "N",
    )
    moment = _estimated_result(
        f"{alternative_id}/bending_moment",
        "M_Nm = F_N * load_distance_m",
        {"applied_load_n": load_n, "load_distance_m": distance_m},
        moment_nm,
        "N*m",
    )
    calculations.extend(
        _calc_row(alternative_id, item, evidence_rows)
        for item in (applied_load, moment, stress, safety)
    )
    fastener = _check_result(
        f"{alternative_id}/fastener_clearance_check",
        "base width >= 2 * fastener diameter",
        {
            "base_width_mm": values["base_width_mm"],
            "fastener_diameter_mm": values["fastener_diameter_mm"],
        },
        float(values["base_width_mm"]) >= 2 * float(values["fastener_diameter_mm"]),
        "Reference edge-spacing screen only; fastener standard, edge distance, and joint strength require design review.",
    )
    calculations.append(_calc_row(alternative_id, fastener, evidence_rows))
    metrics.update(
        {
            "applied_load_n": load_n,
            "bending_moment_nm": moment_nm,
            "reference_bending_stress_mpa": stress.output_value,
            "safety_factor": safety.output_value,
            "minimum_safety_factor": values["minimum_safety_factor"],
            "reference_thickness_mm": thickness_m * 1000,
            "fastener_clearance_pass": fastener.output_value == 1,
        }
    )
    return calculations, metrics


def _house(
    alternative_id: str,
    values: dict[str, Any],
    evidence_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    length = float(values["footprint_length_mm"])
    width = float(values["footprint_width_mm"])
    height = float(values["wall_height_mm"])
    wall = float(values["wall_thickness_mm"])
    pitch = math.radians(float(values["roof_pitch_degrees"]))
    height_scale = {
        "compact_gabled_house": 0.9,
        "wide_gabled_house": 1.0,
        "tall_gabled_house": 1.15,
    }[alternative_id]
    adjusted_height = height * height_scale
    wall_volume = (
        length * width - (length - 2 * wall) * (width - 2 * wall)
    ) * adjusted_height
    roof_rise = (width / 2) * math.tan(pitch)
    roof_volume = length * width * roof_rise / 2
    printed_volume = max(0.0, wall_volume + roof_volume - float(values["door_width_mm"]) * float(values["door_height_mm"]) * wall)
    volume_calculations = [
        _estimated_result(
            f"{alternative_id}/wall_volume",
            "V_wall_mm3 = (L*W - (L-2t)*(W-2t)) * H",
            {
                "footprint_length_mm": length,
                "footprint_width_mm": width,
                "reference_wall_height_mm": adjusted_height,
                "wall_thickness_mm": wall,
            },
            wall_volume,
            "mm3",
        ),
        _estimated_result(
            f"{alternative_id}/roof_volume",
            "V_roof_mm3 = length_mm * footprint_width_mm * roof_rise_mm / 2",
            {
                "footprint_length_mm": length,
                "footprint_width_mm": width,
                "roof_rise_mm": roof_rise,
                "roof_pitch_degrees": values["roof_pitch_degrees"],
            },
            roof_volume,
            "mm3",
        ),
        _estimated_result(
            f"{alternative_id}/estimated_printed_volume",
            "V_print_mm3 = V_wall_mm3 + V_roof_mm3 - V_door_opening_mm3",
            {
                "wall_volume_mm3": wall_volume,
                "roof_volume_mm3": roof_volume,
                "door_opening_volume_mm3": float(values["door_width_mm"]) * float(values["door_height_mm"]) * wall,
            },
            printed_volume,
            "mm3",
        ),
    ]
    calculations, metrics = _volume_calculations(
        alternative_id, printed_volume / 1000, str(values["material"]), evidence_rows
    )
    calculations.extend(
        _calc_row(alternative_id, calculation, evidence_rows)
        for calculation in volume_calculations
    )
    wall_check = check_minimum_wall_thickness(
        wall, float(values["minimum_wall_thickness_mm"])
    )
    door_clear = _check_result(
        f"{alternative_id}/door_clearance_check",
        "door dimensions fit within footprint and wall height",
        {
            "door_width_mm": values["door_width_mm"],
            "door_height_mm": values["door_height_mm"],
            "footprint_width_mm": width,
            "wall_height_mm": adjusted_height,
        },
        float(values["door_width_mm"]) < width
        and float(values["door_height_mm"]) < adjusted_height,
        "Door opening envelope screen only; no lintels, egress, or code rules are assessed.",
    )
    calculations.extend(
        _calc_row(alternative_id, item, evidence_rows)
        for item in (wall_check, door_clear)
    )
    if values["window_count"]:
        _unverified_evidence(
            alternative_id,
            f"{alternative_id}/window_clearance_check",
            "Window count was provided but window dimensions and spacing were not; "
            "window clearance is unverified.",
            evidence_rows,
        )
    metrics.update(
        {
            "wall_volume_mm3": wall_volume,
            "reference_wall_height_mm": adjusted_height,
            "roof_volume_mm3": roof_volume,
            "minimum_wall_thickness_pass": wall_check.output_value == 1,
            "door_window_clearance_pass": (
                door_clear.output_value == 1
                if values["window_count"] == 0
                else None
            ),
            "door_clearance_pass": door_clear.output_value == 1,
            "window_count": values["window_count"],
            "roof_pitch_degrees": values["roof_pitch_degrees"],
        }
    )
    return calculations, metrics


def _civil_advisory(values: dict[str, Any]) -> dict[str, Any]:
    requested = str(values.get("question", "")).strip()
    caveat = get_product_family(ProductType.CIVIL_CONCEPT_ASSISTANT.value).disclaimer
    alternatives = [
        DesignAlternative(
            id=ident,
            name=name,
            description=(
                f"Preliminary discussion topic related to the request: {requested or 'not provided'}. "
                f"{caveat}"
            ),
            key_parameters={"concept_class": ident, "value_class": "advisory_only"},
            status=DesignStatus.DRAFT,
        )
        for ident, name in get_product_family(
            ProductType.CIVIL_CONCEPT_ASSISTANT.value
        ).alternatives
    ]
    comparisons = [
        {
            "design_id": alternative.id,
            "name": alternative.name,
            "evidence_status": EvidenceStatus.UNVERIFIED.value,
            "recommendation_score": None,
            "constraints_pass": None,
        }
        for alternative in alternatives
    ]
    return {
        "alternatives": alternatives,
        "calculations": [],
        "evidence_rows": [],
        "comparison_table": comparisons,
        "recommended_design_id": None,
        "status": "REVIEW",
        "explanation": (
            "Advisory discussion topics only; ForgeX does not generate civil engineering "
            "designs, final member sizes, construction drawings, or safety approvals. "
            + caveat
        ),
        "missing_inputs": [],
        "disclaimer": caveat,
    }


def _residential_concept(
    values: dict[str, Any],
    family: ProductFamily,
) -> dict[str, Any]:
    panel = calculate_residential_panel(values)
    calculations: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    calculation_specs = [
        (
            "total_floor_area",
            "A = footprint_length_m * footprint_width_m",
            {
                "footprint_length_m": values["footprint_length_m"],
                "footprint_width_m": values["footprint_width_m"],
            },
            panel["floor_area_m2"],
            "m2",
        ),
        (
            "estimated_wall_volume",
            "V_wall = (L*W - (L-2t)*(W-2t)) * wall_height",
            {
                "footprint_length_m": values["footprint_length_m"],
                "footprint_width_m": values["footprint_width_m"],
                "wall_thickness_m": values["wall_thickness_m"],
                "wall_height_m": values["wall_height_m"],
            },
            panel["wall_volume_m3"],
            "m3",
        ),
        (
            "estimated_gabled_roof_volume",
            "V_roof = footprint_length * footprint_width * roof_rise / 2",
            {
                "footprint_length_m": values["footprint_length_m"],
                "footprint_width_m": values["footprint_width_m"],
                "roof_rise_m": panel["roof_rise_m"],
            },
            panel["roof_volume_m3"],
            "m3",
        ),
        (
            "estimated_foundation_slab_volume",
            "V_foundation = footprint_length_m * footprint_width_m * foundation_thickness_m",
            {
                "footprint_length_m": values["footprint_length_m"],
                "footprint_width_m": values["footprint_width_m"],
                "foundation_thickness_m": values["foundation_thickness_m"],
            },
            panel["foundation_volume_m3"],
            "m3",
        ),
    ]
    for name, equation, inputs, output, unit in calculation_specs:
        calculations.append(
            _calc_row(
                "residential_gabled_concept",
                _estimated_result(
                    f"residential_building_concept/{name}",
                    equation,
                    inputs,
                    float(output),
                    unit,
                ),
                evidence,
            )
        )

    for name, key, unit, equation in (
        (
            "estimated_material_mass",
            "material_mass_kg",
            "kg",
            "mass_kg = total_concept_volume_m3 * catalog_density_kg_m3",
        ),
        (
            "estimated_material_cost",
            "estimated_material_cost_usd",
            "USD",
            "cost_USD = material_mass_kg * catalog_cost_USD_per_kg",
        ),
        (
            "estimated_extrusion_time",
            "estimated_print_time_hours",
            "hours",
            "time_h = total_concept_volume_cm3 * 1e6 / catalog_deposition_rate_cm3_per_hour",
        ),
    ):
        output_value = panel[key]
        if output_value is not None:
            calculations.append(
                _calc_row(
                    "residential_gabled_concept",
                    _estimated_result(
                        f"residential_building_concept/{name}",
                        equation,
                        {
                            "total_concept_volume_m3": panel[
                                "total_concept_volume_m3"
                            ],
                            "material": values["material"],
                        },
                        float(output_value),
                        unit,
                    ),
                    evidence,
                )
            )
        else:
            evidence.append(
                {
                    "alternative_id": "residential_gabled_concept",
                    "source": f"residential_building_concept/{name}",
                    "statement": (
                        f"Not calculated because required catalog data is unavailable. "
                        f"Equation would be {equation}."
                    ),
                    "status": EvidenceStatus.BLOCKED.value,
                    "result": None,
                    "unit": unit,
                }
            )

    alternatives: list[DesignAlternative] = []
    comparison: list[dict[str, Any]] = []
    for identifier, name in family.alternatives:
        parameters = {
            **values,
            **panel,
            "footprint_length_mm": float(values["footprint_length_m"]) * 1000,
            "footprint_width_mm": float(values["footprint_width_m"]) * 1000,
            "wall_height_mm": float(values["wall_height_m"]) * 1000,
            "wall_thickness_mm": float(values["wall_thickness_m"]) * 1000,
            "foundation_thickness_mm": float(values["foundation_thickness_m"]) * 1000,
            "reference_wall_height_mm": float(values["wall_height_m"]) * 1000,
            "window_count": 0,
            "door_width_mm": 0,
            "door_height_mm": 0,
            "calculated_metrics": dict(panel),
            "value_class": "reference_estimate",
        }
        alternative = DesignAlternative(
            id=identifier,
            name=name,
            description=(
                "Parametric illustrative residential concept using the user-provided "
                "footprint, wall height, wall thickness, and roof pitch. No structural "
                "or code validation is implied. This response keeps the existing "
                "three-item API shape; these entries share the same user-provided "
                "geometry and are not distinct optimized alternatives."
            ),
            key_parameters=parameters,
            estimated_mass_kg=panel["material_mass_kg"],
            estimated_cost_usd=panel["estimated_material_cost_usd"],
            estimated_print_time_hours=panel["estimated_print_time_hours"],
            status=DesignStatus.DRAFT,
        )
        alternatives.append(alternative)
        comparison.append(
            {
                "design_id": identifier,
                "name": name,
                "evidence_status": EvidenceStatus.ESTIMATED.value,
                "floor_area_m2": panel["floor_area_m2"],
                "total_wall_roof_volume_m3": panel["total_wall_roof_volume_m3"],
                "foundation_volume_m3": panel["foundation_volume_m3"],
                "constraints_pass": None,
                "recommendation_score": None,
            }
        )

    return {
        "alternatives": alternatives,
        "calculations": calculations,
        "evidence_rows": evidence,
        "comparison_table": comparison,
        "recommended_design_id": None,
        "status": "REVIEW",
        "explanation": (
            "Residential concept estimates are ready for review. Soil capacity, "
            "seismic requirements, local codes, foundation design, and several catalog "
            "specifications remain unconfirmed."
        ),
        "missing_inputs": [],
        "disclaimer": family.disclaimer,
        "catalog_cards": panel["catalog_cards"],
        "calculation_panel": panel,
    }


def generate_product_designs(
    product_type: str,
    raw_values: dict[str, Any],
) -> dict[str, Any]:
    """Generate deterministic, explicitly estimated non-gripper concept screens."""
    family = get_product_family(product_type)
    if product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
        raise ValueError("Use the existing gripper design engine for this product family.")
    if product_type == ProductType.CIVIL_CONCEPT_ASSISTANT.value:
        return _civil_advisory(raw_values)

    values = validate_product_inputs(product_type, raw_values)
    if product_type == ProductType.RESIDENTIAL_BUILDING_CONCEPT.value:
        return _residential_concept(values, family)
    alternatives: list[DesignAlternative] = []
    calculations: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    comparison: list[dict[str, Any]] = []
    all_constraints: list[bool | None] = []
    for alternative_id, name in family.alternatives:
        if product_type == ProductType.ELECTRONICS_ENCLOSURE.value:
            design_calculations, metrics = _enclosure(alternative_id, values, evidence)
            constraints = _combine_checks(
                [
                    metrics["minimum_wall_thickness_pass"],
                    metrics["cable_port_clearance_pass"],
                    metrics["lid_fit_reference_pass"],
                ]
            )
        elif product_type == ProductType.MOUNTING_BRACKET.value:
            design_calculations, metrics = _bracket(alternative_id, values, evidence)
            constraints = (
                metrics["safety_factor"] >= float(values["minimum_safety_factor"])
                and metrics["fastener_clearance_pass"]
            )
        else:
            design_calculations, metrics = _house(alternative_id, values, evidence)
            constraints = _combine_checks(
                [
                    metrics["minimum_wall_thickness_pass"],
                    metrics["door_window_clearance_pass"],
                ]
            )
        metrics["constraints_pass"] = constraints
        all_constraints.append(constraints)
        calculations.extend(design_calculations)
        alternative = DesignAlternative(
            id=alternative_id,
            name=name,
            description=(
                f"{family.disclaimer} All geometry parameters are caller inputs or "
                "explicitly labeled deterministic reference derivations."
            ),
            key_parameters={
                **values,
                **metrics,
                "calculated_metrics": dict(metrics),
                "value_class": "reference_estimate",
                "disclaimer": family.disclaimer,
            },
            estimated_mass_kg=metrics.get("estimated_mass_kg"),
            estimated_cost_usd=metrics.get("estimated_material_cost_usd"),
            estimated_print_time_hours=metrics.get("estimated_print_time_hours"),
            status=DesignStatus.DRAFT,
        )
        alternatives.append(alternative)
        comparison.append(
            {
                "design_id": alternative_id,
                "name": name,
                "evidence_status": EvidenceStatus.ESTIMATED.value,
                **metrics,
                "constraints_pass": constraints,
                "recommendation_score": None,
            }
        )

    failed = [index for index, passed in enumerate(all_constraints) if passed is False]
    unverified = [
        index for index, passed in enumerate(all_constraints) if passed is None
    ]
    if failed:
        status = "REVIEW"
        explanation = (
            f"Reference checks failed for {len(failed)} alternative(s). "
            "No design is recommended; review the calculation and evidence rows."
        )
    elif unverified:
        status = "REVIEW"
        explanation = (
            f"Some required fit/opening checks remain unverified for "
            f"{len(unverified)} alternative(s). No design is recommended."
        )
    else:
        status = "READY"
        explanation = (
            "Three reference alternatives were screened using deterministic calculations. "
            "No alternative is recommended or presented as optimized; geometry and all "
            "estimated properties require independent review."
        )
    return {
        "alternatives": alternatives,
        "calculations": calculations,
        "evidence_rows": evidence,
        "comparison_table": comparison,
        "recommended_design_id": None,
        "status": status,
        "explanation": explanation,
        "missing_inputs": [],
        "disclaimer": family.disclaimer,
    }


def blocked_product_designs(
    product_type: str,
    missing: list[dict[str, str]],
) -> dict[str, Any]:
    family = get_product_family(product_type)
    alternatives = [
        DesignAlternative(
            id=ident,
            name=name,
            description=f"Reference concept blocked pending required inputs. {family.disclaimer}",
            key_parameters={"missing_inputs": [row["name"] for row in missing]},
            status=DesignStatus.DRAFT,
        )
        for ident, name in family.alternatives
    ]
    evidence = [
        {
            "alternative_id": alternative.id,
            "source": field["name"],
            "statement": f"Required user input was not supplied: {field['label']}.",
            "status": EvidenceStatus.BLOCKED.value,
            "result": None,
            "unit": None,
        }
        for alternative in alternatives
        for field in missing
    ]
    return {
        "alternatives": alternatives,
        "calculations": [],
        "evidence_rows": evidence,
        "comparison_table": [
            {
                "design_id": alternative.id,
                "name": alternative.name,
                "evidence_status": EvidenceStatus.BLOCKED.value,
                "constraints_pass": None,
                "recommendation_score": None,
            }
            for alternative in alternatives
        ],
        "recommended_design_id": None,
        "status": "BLOCKED",
        "explanation": "Generation is blocked until required inputs are provided: "
        + ", ".join(field["name"] for field in missing),
        "missing_inputs": [field["name"] for field in missing],
        "disclaimer": family.disclaimer,
    }


def generate_product_report(
    product_type: str,
    confirmed_brief: dict[str, Any],
    design_result: dict[str, Any],
) -> str:
    family = get_product_family(product_type)
    lines = [
        family.report_template,
        f"**Template:** `{family.report_template_id}`",
        "",
        f"**Project:** {confirmed_brief.get('project_name', 'Not specified')}",
        "",
        f"**Purpose:** {confirmed_brief.get('purpose', 'Not specified')}",
        "",
        "```json",
        json.dumps(confirmed_brief.get("product_inputs", {}), indent=2, sort_keys=True),
        "```",
        "",
        f"Generation status: **{design_result.get('status', 'Not returned')}**",
        "",
        str(design_result.get("explanation", "No explanation was returned.")),
        "",
        "### Alternatives",
        "",
        "| ID | Name | Status |",
        "|---|---|---|",
    ]
    lines.extend(
        f"| {item.get('id', '')} | {item.get('name', '')} | {item.get('status', 'Not returned')} |"
        for item in design_result.get("alternatives", [])
    )
    lines.extend(["", "### Comparison", "", "```json"])
    lines.append(
        json.dumps(design_result.get("comparison_table", []), indent=2, sort_keys=True)
    )
    lines.extend(["```", "", "### Calculations", ""])
    for calculation in design_result.get("calculations", []):
        lines.append(
            f"- `{calculation.get('name')}` = {calculation.get('output_value')} "
            f"{calculation.get('unit')} — {calculation.get('equation')} "
            f"({calculation.get('evidence_status')})."
        )
    lines.extend(["", "### Evidence rows", "", "```json"])
    lines.append(
        json.dumps(design_result.get("evidence_rows", []), indent=2, sort_keys=True)
    )
    lines.extend(
        [
            "```",
            "",
            "## Limitations and required professional review",
            "",
            family.disclaimer,
            "",
            "ForgeX is engineering decision support, not certification. "
            "Reference concepts are not validated or manufacturing-ready.",
        ]
    )
    return "\n".join(lines) + "\n"

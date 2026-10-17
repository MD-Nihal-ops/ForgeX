"""Deterministic reference-estimate screening for servo-driven grippers."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.calculations import (
    STANDARD_GRAVITY_M_S2,
    calculate_beam_bending_stress,
    calculate_required_grip_force,
    calculate_safety_factor,
    calculate_servo_torque_required,
    compare_design_alternatives,
    estimate_mass,
    estimate_material_cost,
    estimate_print_time,
)
from core.data_loader import DATA_DIR, CatalogError, get_component, get_material
from core.models import CalculationResult, DesignAlternative, EngineeringBrief
from core.requirements import DesignStatus, EvidenceStatus, ProductType

_TEMPLATE_FILES = (
    "two_finger_rigid_gripper.json",
    "compliant_finger_gripper.json",
    "wrap_around_roller_gripper.json",
)
_MASS_PATTERN = re.compile(
    r"(?:payload mass|filled weight|payload weight)[^\d]{0,32}"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kg|g)\b",
    re.IGNORECASE,
)
_SERVO_PATTERN = re.compile(r"\b(SG90|MG996R)\b", re.IGNORECASE)
_REQUIRED_TEMPLATE_PARAMETERS = {
    "finger_count",
    "finger_length_mm",
    "finger_width_mm",
    "finger_thickness_mm",
    "contact_area_mm2",
    "friction_coefficient",
    "material",
    "servo_mount_type",
    "estimated_volume_cm3",
    "servo_lever_arm_mm",
    "print_speed_cm3_per_hour",
}


class GripperTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1)
    template_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value_class: str
    disclaimer: str = Field(min_length=1)
    parameters: dict[str, Any]
    parameter_sources: dict[str, str]


def _load_templates() -> list[GripperTemplate]:
    templates: list[GripperTemplate] = []
    for filename in _TEMPLATE_FILES:
        path = DATA_DIR / "design_templates" / filename
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Could not read design template {filename}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in design template {filename}: {exc}") from exc
        try:
            template = GripperTemplate.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid design template {filename}: {exc}") from exc
        if template.value_class != "reference_estimate":
            raise ValueError(f"Template {filename} must be labeled reference_estimate.")
        missing_parameters = _REQUIRED_TEMPLATE_PARAMETERS - template.parameters.keys()
        missing_sources = _REQUIRED_TEMPLATE_PARAMETERS - template.parameter_sources.keys()
        if missing_parameters or missing_sources:
            missing = sorted(missing_parameters | missing_sources)
            raise ValueError(
                f"Template {filename} is missing values or provenance for {missing}."
            )
        templates.append(template)
    return templates


def _payload_mass_kg(brief: EngineeringBrief) -> float | None:
    for load in brief.load_conditions:
        match = _MASS_PATTERN.search(load.description)
        if match:
            value = float(match.group("value"))
            return value / 1000 if match.group("unit").lower() == "g" else value
    return None


def _servo_for_brief(brief: EngineeringBrief):
    source = " ".join([brief.purpose, *brief.assumptions])
    match = _SERVO_PATTERN.search(source)
    if not match:
        return None, "A supported servo (SG90 or MG996R) is not specified in the brief."
    name = "SG90 servo" if match.group(1).upper() == "SG90" else "MG996R servo"
    try:
        return get_component(name), None
    except CatalogError as exc:
        return None, str(exc)


def _required_inputs(brief: EngineeringBrief, servo: Any) -> tuple[dict[str, Any], list[str]]:
    mass = _payload_mass_kg(brief)
    diameter_m = brief.dimensions.width_m
    safety_factor = (
        brief.safety_constraints[0].min_safety_factor
        if brief.safety_constraints
        else None
    )
    missing = []
    if mass is None or mass <= 0 or not math.isfinite(mass):
        missing.append("positive filled payload mass")
    if diameter_m is None or diameter_m <= 0 or not math.isfinite(diameter_m):
        missing.append("positive object diameter (stored as dimensions.width_m)")
    if safety_factor is None:
        missing.append("minimum safety factor")
    if servo is None:
        missing.append("supported servo catalog selection")
    return {
        "payload_mass_kg": mass if mass and mass > 0 and math.isfinite(mass) else None,
        "object_diameter_m": diameter_m,
        "minimum_safety_factor": safety_factor,
        "servo": servo,
    }, missing


def _calculation_row(
    calculation: CalculationResult,
    alternative_id: str,
) -> dict[str, Any]:
    payload = calculation.model_dump(mode="json")
    payload["name"] = f"{alternative_id}/{calculation.name}"
    return payload


def _evidence(
    alternative_id: str | None,
    source: str,
    statement: str,
    status: EvidenceStatus,
    *,
    result: float | bool | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    return {
        "alternative_id": alternative_id,
        "source": source,
        "statement": statement,
        "status": status.value,
        "result": result,
        "unit": unit,
    }


def _screen_one(
    template: GripperTemplate,
    brief: EngineeringBrief,
    inputs: dict[str, Any],
    missing: list[str],
) -> tuple[DesignAlternative, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    params = template.parameters
    alternative_id = template.template_id
    evidence: list[dict[str, Any]] = [
        _evidence(
            alternative_id,
            f"data/design_templates/{template.template_id}.json",
            template.disclaimer,
            EvidenceStatus.ESTIMATED,
        )
    ]
    calculations: list[dict[str, Any]] = []
    values: dict[str, Any] = {
        "required_grip_force_n": None,
        "required_servo_torque_nm": None,
        "servo_torque_capacity_nm": None,
        "grip_force_capacity_n": None,
        "estimated_mass_kg": None,
        "estimated_cost_usd": None,
        "estimated_print_time_hours": None,
        "bending_stress_mpa": None,
        "safety_factor": None,
        "grip_force_margin": None,
        "servo_torque_margin": None,
        "recommendation_score": None,
        "constraints_pass": None,
    }

    template_material = str(params["material"])
    try:
        material = get_material(template_material)
    except CatalogError as exc:
        material = None
        evidence.append(
            _evidence(
                alternative_id,
                "materials catalog",
                str(exc),
                EvidenceStatus.BLOCKED,
            )
        )
    else:
        evidence.append(
            _evidence(
                alternative_id,
                "materials catalog",
                f"{material.name}: {material.source_note}",
                EvidenceStatus.ESTIMATED,
            )
        )

    calculations_to_add: list[CalculationResult] = []
    grip: CalculationResult | None = None
    torque: CalculationResult | None = None
    bending: CalculationResult | None = None
    safety: CalculationResult | None = None
    mass_calc: CalculationResult | None = None
    cost_calc: CalculationResult | None = None
    print_calc: CalculationResult | None = None
    servo = inputs["servo"]
    payload_mass = inputs["payload_mass_kg"]
    safety_target = inputs["minimum_safety_factor"]

    if not missing and payload_mass is not None and safety_target is not None:
        grip = calculate_required_grip_force(
            payload_mass,
            float(params["friction_coefficient"]),
            safety_target,
        )
        torque = calculate_servo_torque_required(
            grip.output_value,
            float(params["servo_lever_arm_mm"]) / 1000,
            1.0,
        )
        calculations_to_add.extend((grip, torque))
        values["required_grip_force_n"] = grip.output_value
        values["required_servo_torque_nm"] = torque.output_value

        beam_load_n = grip.output_value / int(params["finger_count"])
        section_modulus_m3 = (
            float(params["finger_width_mm"])
            * 1e-3
            * (float(params["finger_thickness_mm"]) * 1e-3) ** 2
            / 6
        )
        bending = calculate_beam_bending_stress(
            beam_load_n,
            float(params["finger_length_mm"]) / 1000,
            section_modulus_m3,
        )
        calculations_to_add.append(bending)
        values["bending_stress_mpa"] = bending.output_value
        if material is not None:
            safety = calculate_safety_factor(
                material.yield_strength_mpa,
                bending.output_value,
            )
            calculations_to_add.append(safety)
            values["safety_factor"] = safety.output_value

        volume_m3 = float(params["estimated_volume_cm3"]) * 1e-6
        mass_calc = estimate_mass(volume_m3, material.density_kg_m3) if material else None
        if mass_calc:
            cost_calc = estimate_material_cost(
                mass_calc.output_value,
                material.cost_per_kg_usd,
            )
            print_calc = estimate_print_time(
                float(params["estimated_volume_cm3"]),
                float(params["print_speed_cm3_per_hour"]),
            )
            calculations_to_add.extend((mass_calc, cost_calc, print_calc))
            values["estimated_mass_kg"] = mass_calc.output_value
            values["estimated_cost_usd"] = cost_calc.output_value
            values["estimated_print_time_hours"] = print_calc.output_value

        available_torque_nm = (
            float(servo.torque_kg_cm) * STANDARD_GRAVITY_M_S2 * 0.01
        )
        lever_arm_m = float(params["servo_lever_arm_mm"]) / 1000
        grip_capacity_n = available_torque_nm / lever_arm_m
        grip_margin = grip_capacity_n / grip.output_value
        torque_margin = available_torque_nm / torque.output_value
        values["servo_torque_capacity_nm"] = available_torque_nm
        values["grip_force_capacity_n"] = grip_capacity_n
        values["grip_force_margin"] = grip_margin
        values["servo_torque_margin"] = torque_margin

        derived = (
            CalculationResult(
                name="servo_torque_capacity",
                equation="UNIT-SRV-01: T_Nm = torque_kg_cm * g_m_s2 * 0.01",
                inputs={
                    "catalog_torque_kg_cm": servo.torque_kg_cm,
                    "g_m_s2": STANDARD_GRAVITY_M_S2,
                    "servo": servo.name,
                },
                output_value=available_torque_nm,
                unit="N*m",
                evidence_status=EvidenceStatus.ESTIMATED,
                notes=(
                    f"Converted from catalog reference estimate. {servo.source_note} "
                    "No additional servo derating or mechanism efficiency is applied."
                ),
            ),
            CalculationResult(
                name="grip_force_margin",
                equation="MARGIN-GRIP-01: (T_available / lever_arm) / F_required",
                inputs={
                    "available_servo_torque_nm": available_torque_nm,
                    "lever_arm_m": lever_arm_m,
                    "required_grip_force_n": grip.output_value,
                    "assumed_ideal_mechanism": True,
                },
                output_value=grip_margin,
                unit="1",
                evidence_status=EvidenceStatus.ESTIMATED,
                notes=(
                    "Ideal lever capacity divided by GRIP-01 demand; excludes linkage "
                    "losses and must not be treated as a tested grip rating."
                ),
            ),
            CalculationResult(
                name="servo_torque_margin",
                equation="MARGIN-SRV-01: T_available / T_required",
                inputs={
                    "available_servo_torque_nm": available_torque_nm,
                    "required_servo_torque_nm": torque.output_value,
                    "servo": servo.name,
                },
                output_value=torque_margin,
                unit="1",
                evidence_status=EvidenceStatus.ESTIMATED,
                notes=(
                    f"Catalog reference estimate comparison. {servo.source_note} "
                    "No torque derating or actuator dynamics are included."
                ),
            ),
        )
        calculations_to_add.extend(derived)
        calculations.extend(
            _calculation_row(calc, alternative_id) for calc in calculations_to_add
        )
        minimum_safety_pass = (
            safety is not None and safety.output_value >= safety_target
        )
        torque_pass = torque_margin >= 1
        grip_pass = grip_margin >= 1
        values["constraints_pass"] = grip_pass and torque_pass and minimum_safety_pass
        margins = {
            "grip_force_margin": grip_margin,
            "servo_torque_margin": torque_margin,
            "safety_factor_margin": (
                safety.output_value / safety_target if safety else None
            ),
        }
        values["recommendation_score"] = (
            min(value for value in margins.values() if value is not None)
            if all(value is not None for value in margins.values())
            else None
        )
        for name, result, unit, passed in (
            ("grip_force_margin", grip_margin, "1", grip_pass),
            ("servo_torque_margin", torque_margin, "1", torque_pass),
            (
                "minimum_safety_factor",
                safety.output_value if safety else None,
                "1",
                minimum_safety_pass,
            ),
        ):
            evidence.append(
                _evidence(
                    alternative_id,
                    f"constraint:{name}",
                    (
                        f"{name} {'passes' if passed else 'fails'} the required threshold; "
                        f"calculated value={result:g} {unit}. "
                        f"Requirement is a reference-estimate screening check, not certification."
                    ),
                    EvidenceStatus.ESTIMATED,
                    result=result,
                    unit=unit,
                )
            )
    else:
        for item in missing:
            evidence.append(
                _evidence(
                    alternative_id,
                    "confirmed EngineeringBrief",
                    f"Calculation blocked: missing {item}.",
                    EvidenceStatus.BLOCKED,
                )
            )
        if material and payload_mass is not None:
            volume_m3 = float(params["estimated_volume_cm3"]) * 1e-6
            mass_calc = estimate_mass(volume_m3, material.density_kg_m3)
            cost_calc = estimate_material_cost(
                mass_calc.output_value,
                material.cost_per_kg_usd,
            )
            print_calc = estimate_print_time(
                float(params["estimated_volume_cm3"]),
                float(params["print_speed_cm3_per_hour"]),
            )
            calculations_to_add.extend((mass_calc, cost_calc, print_calc))
            values["estimated_mass_kg"] = mass_calc.output_value
            values["estimated_cost_usd"] = cost_calc.output_value
            values["estimated_print_time_hours"] = print_calc.output_value
        calculations.extend(
            _calculation_row(calc, alternative_id) for calc in calculations_to_add
        )

    for calculation in calculations_to_add:
        evidence.append(
            _evidence(
                alternative_id,
                calculation.equation,
                (
                    f"{calculation.name}: {calculation.output_value:g} "
                    f"{calculation.unit}. {calculation.notes}"
                ),
                calculation.evidence_status,
                result=calculation.output_value,
                unit=calculation.unit,
            )
        )
    for parameter, source in template.parameter_sources.items():
        evidence.append(
            _evidence(
                alternative_id,
                f"template:{parameter}",
                f"{parameter}={params[parameter]!r}. {source}",
                EvidenceStatus.ESTIMATED,
            )
        )

    status = (
        DesignStatus.PROPOSED
        if values["constraints_pass"] is True
        else DesignStatus.INFEASIBLE
        if values["constraints_pass"] is False
        else DesignStatus.DRAFT
    )
    key_parameters = {
        **params,
        "template_id": template.template_id,
        "template_value_class": template.value_class,
        "template_disclaimer": template.disclaimer,
        "object_diameter_m": inputs["object_diameter_m"],
        "user_selected_servo": servo.name if servo else None,
        "calculated_metrics": values,
    }
    alternative = DesignAlternative(
        id=alternative_id,
        name=template.name,
        description=(
            f"{template.disclaimer} These are reference screening parameters only; "
            "this is not optimized geometry or a simulation."
        ),
        key_parameters=key_parameters,
        pros=["Screened with explicit deterministic calculations."],
        cons=[
            "Template values are reference estimates; actual printed-part and mechanism "
            "performance require physical validation."
        ],
        estimated_mass_kg=values["estimated_mass_kg"],
        estimated_cost_usd=values["estimated_cost_usd"],
        estimated_print_time_hours=values["estimated_print_time_hours"],
        status=status,
    )
    comparison = {
        "design_id": alternative_id,
        "name": template.name,
        "evidence_status": (
            EvidenceStatus.ESTIMATED.value
            if values["constraints_pass"] is not None
            else EvidenceStatus.BLOCKED.value
        ),
        **values,
        "score_formula": (
            "minimum of grip_force_margin, servo_torque_margin, "
            "and calculated_safety_factor / requested_minimum_safety_factor"
        ),
    }
    return alternative, calculations, evidence, comparison


def generate_gripper_designs(brief: EngineeringBrief) -> dict[str, Any]:
    """Generate and screen the three reference gripper concepts deterministically."""
    if brief.product_type != ProductType.SERVO_DRIVEN_GRIPPER:
        raise ValueError("Design generation currently supports servo-driven gripper briefs only.")
    templates = _load_templates()
    servo, servo_error = _servo_for_brief(brief)
    inputs, missing = _required_inputs(brief, servo)
    if servo_error and servo_error not in missing:
        missing.append(servo_error)

    alternatives: list[DesignAlternative] = []
    calculations: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    comparison_table: list[dict[str, Any]] = []
    for template in templates:
        alternative, design_calculations, evidence, comparison = _screen_one(
            template,
            brief,
            inputs,
            missing,
        )
        alternatives.append(alternative)
        calculations.extend(design_calculations)
        evidence_rows.extend(evidence)
        comparison_table.append(comparison)

    comparison_calc: CalculationResult | None = None
    if all(row["estimated_mass_kg"] is not None for row in comparison_table):
        comparison_calc = compare_design_alternatives(
            [
                {
                    "id": row["design_id"],
                    "estimated_mass_kg": row["estimated_mass_kg"],
                    "estimated_cost_usd": row["estimated_cost_usd"],
                    "estimated_print_time_hours": row["estimated_print_time_hours"],
                    "safety_factor": row["safety_factor"],
                }
                for row in comparison_table
            ]
        )
        calculations.append(comparison_calc.model_dump(mode="json"))
        evidence_rows.append(
            _evidence(
                None,
                comparison_calc.equation,
                comparison_calc.notes,
                comparison_calc.evidence_status,
                result=comparison_calc.output_value,
                unit=comparison_calc.unit,
            )
        )

    eligible = [
        row for row in comparison_table
        if row["constraints_pass"] is True and row["recommendation_score"] is not None
    ]
    recommended_id: str | None = None
    if not missing and eligible:
        eligible.sort(
            key=lambda row: (
                -row["recommendation_score"],
                -row["safety_factor"],
                row["estimated_cost_usd"],
                row["estimated_mass_kg"],
                row["estimated_print_time_hours"],
                row["design_id"],
            )
        )
        recommended_id = eligible[0]["design_id"]
        selected_index = next(
            index for index, alternative in enumerate(alternatives)
            if alternative.id == recommended_id
        )
        alternatives[selected_index] = alternatives[selected_index].model_copy(
            update={"status": DesignStatus.SELECTED}
        )

    if missing:
        status = "BLOCKED"
        explanation = "Generation is blocked from recommendation: " + "; ".join(missing) + "."
    elif recommended_id:
        failed_designs = [
            row["name"]
            for row in comparison_table
            if row["constraints_pass"] is False
        ]
        if failed_designs:
            status = "REVIEW"
            explanation = (
                f"{recommended_id} is the highest-scoring alternative that passed all "
                "three reference-estimate screening constraints. Review is required because "
                f"other alternatives failed: {', '.join(failed_designs)}. "
                "This is not optimized geometry, simulation, testing, or certification."
            )
        else:
            status = "READY"
            explanation = (
                f"{recommended_id} is recommended by the transparent minimum-margin score. "
                "All alternatives pass the three reference-estimate screening constraints. "
                "This is not optimized geometry, simulation, testing, or certification."
            )
    else:
        status = "REVIEW"
        explanation = (
            "All required inputs are present, but no alternative passes every grip-force, "
            "servo-torque, and material safety-factor screening constraint. No design is recommended."
        )

    return {
        "alternatives": alternatives,
        "calculations": calculations,
        "evidence_rows": evidence_rows,
        "comparison_table": comparison_table,
        "recommended_design_id": recommended_id,
        "status": status,
        "explanation": explanation,
        "missing_inputs": missing,
    }

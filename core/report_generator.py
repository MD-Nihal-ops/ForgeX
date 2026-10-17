"""Markdown engineering report generation from stored ForgeX facts."""

from __future__ import annotations

from typing import Any

from core.data_loader import CatalogError, get_component, get_material
from core.models import CalculationResult, EngineeringBrief


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _number(value: Any, unit: str = "") -> str:
    if value is None:
        return "Not available"
    if isinstance(value, (int, float)):
        return f"{value:g}{f' {unit}' if unit else ''}"
    return _cell(value)


def _calculation_for_requirement(
    requirement_name: str,
    requirement_statement: str,
    calculations: list[CalculationResult],
    design_id: str,
) -> CalculationResult | None:
    text = f"{requirement_name} {requirement_statement}".casefold()
    terms_by_calculation = {
        "required_grip_force": ("grip", "hold", "retention"),
        "servo_torque_required": ("torque", "servo"),
        "estimated_mass": ("mass", "weight"),
        "estimated_material_cost": ("cost", "budget"),
        "estimated_print_time": ("print time", "manufacturing time"),
    }
    for calculation in calculations:
        if not calculation.name.startswith(f"{design_id}/"):
            continue
        short_name = calculation.name.split("/")[-1]
        if any(term in text for term in terms_by_calculation.get(short_name, ())):
            return calculation
    return None


def _evaluate_requirement(value: float, comparator: str, target: float) -> bool | None:
    if comparator == "ge":
        return value >= target
    if comparator == "le":
        return value <= target
    if comparator == "eq":
        return value == target
    return None


def generate_engineering_report(
    brief: EngineeringBrief,
    design_result: dict[str, Any],
    design_id: str,
) -> str:
    """Build a traceable report without adding unrecorded engineering results."""
    alternatives = design_result.get("alternatives", [])
    selected = next(
        (alternative for alternative in alternatives if alternative.get("id") == design_id),
        None,
    )
    if selected is None:
        raise ValueError(f"Design {design_id!r} is not in the generated alternatives.")

    calculations = [
        CalculationResult.model_validate(item)
        for item in design_result.get("calculations", [])
    ]
    comparison_rows = design_result.get("comparison_table", [])
    selected_parameters = selected.get("key_parameters", {})
    recommended_id = design_result.get("recommended_design_id")
    selected_is_recommended = recommended_id == design_id
    lines = [
        "# ForgeX Engineering Report",
        "",
        (
            "> **Reference concept package.** ForgeX is engineering decision support, not "
            "certification. This report is not an FEA or simulation result, and the listed "
            "reference dimensions and catalog properties require independent verification."
        ),
        "",
        "## Project overview",
        "",
        f"- **Project:** {_cell(brief.project_name)}",
        f"- **Product type:** {_cell(brief.product_type.value)}",
        f"- **Purpose:** {_cell(brief.purpose)}",
        f"- **Manufacturing method:** {_cell(brief.manufacturing_method.value)}",
        f"- **Design generation status:** {_cell(design_result.get('status', 'Unknown'))}",
        f"- **Generation explanation:** {_cell(design_result.get('explanation', 'Not recorded.'))}",
        "",
        "## Engineering brief",
        "",
        f"- **Operating environment:** {_cell(brief.operating_environment)}",
        f"- **Material preference:** {_cell(brief.material_preference or 'Not specified')}",
        f"- **Dimensions:** {_cell(brief.dimensions.model_dump_json(exclude_none=True))}",
        "- **Performance requirements:**",
    ]
    lines.extend(
        f"  - {_cell(item.name)}: {_cell(item.statement)}"
        + (
            f" (target {_number(item.quantity, item.unit or '')}, comparator "
            f"{_cell(item.comparator)})"
            if item.quantity is not None
            else " (no numeric target recorded)"
        )
        for item in brief.performance_requirements
    )
    lines.append("- **Load conditions:**")
    lines.extend(
        f"  - {_cell(item.name)}: {_cell(item.description or 'No description recorded.')}"
        + (f"; force {_number(item.force_n, 'N')}" if item.force_n is not None else "")
        for item in brief.load_conditions
    )
    lines.append("- **Safety constraints:**")
    lines.extend(
        f"  - {_cell(item.name)}: {_cell(item.statement)}"
        + (
            f" (minimum safety factor {_number(item.min_safety_factor)})"
            if item.min_safety_factor is not None
            else ""
        )
        for item in brief.safety_constraints
    )
    lines.extend(["", "## Assumptions", ""])
    lines.extend(f"- {_cell(item)}" for item in brief.assumptions)
    lines.extend(
        [
            "- Design-template dimensions, friction, lever arms, and volume are reference estimates.",
            "- No geometry optimization, tolerance analysis, FEA, physical test, or certification is represented.",
            "",
            "## Selected/recommended design",
            "",
            f"- **Design:** {_cell(selected.get('name', design_id))} (`{_cell(design_id)}`)",
            "- **User-selected for this report:** Yes",
            f"- **ForgeX recommendation:** {'Yes' if selected_is_recommended else 'No'}",
            (
                "- **Selection note:** This selected alternative is the current ForgeX recommendation."
                if selected_is_recommended
                else "- **Selection note:** The requested alternative is reported as selected by the caller; "
                "it is not the ForgeX recommendation or no recommendation is available."
            ),
            f"- **Description:** {_cell(selected.get('description', 'Not recorded.'))}",
            f"- **Reference parameters:** `{_cell(selected_parameters)}`",
            "",
            "## Design alternatives comparison",
            "",
            "| Alternative | Grip force margin | Servo torque margin | Safety factor | Estimated mass (kg) | Estimated cost (USD) | Estimated print time (h) | Constraints pass | Evidence status |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in comparison_rows:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    row.get("name", row.get("design_id", "Unknown")),
                    _number(row.get("grip_force_margin")),
                    _number(row.get("servo_torque_margin")),
                    _number(row.get("safety_factor")),
                    _number(row.get("estimated_mass_kg")),
                    _number(row.get("estimated_cost_usd")),
                    _number(row.get("estimated_print_time_hours")),
                    row.get("constraints_pass", "Unknown"),
                    row.get("evidence_status", "Unknown"),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Calculations",
            "",
            "| Name | Equation | Inputs | Result | Evidence status | Notes |",
            "|---|---|---|---:|---|---|",
        ]
    )
    for calculation in calculations:
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    calculation.name,
                    calculation.equation,
                    calculation.inputs,
                    _number(calculation.output_value, calculation.unit),
                    calculation.evidence_status.value,
                    calculation.notes,
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Requirement–Evidence Ledger",
            "",
            "| Requirement / screening check | Evidence | Result | Status |",
            "|---|---|---|---|",
        ]
    )
    for requirement in brief.performance_requirements:
        calculation = _calculation_for_requirement(
            requirement.name,
            requirement.statement,
            calculations,
            design_id,
        )
        if calculation is None:
            evidence = "No directly linked calculation or test is recorded."
            result = "Not verified"
            status = "UNVERIFIED"
        else:
            status = calculation.evidence_status.value
            evidence = f"{calculation.name}; {calculation.equation}"
            if requirement.quantity is None or requirement.unit != calculation.unit:
                result = (
                    f"Screening value {_number(calculation.output_value, calculation.unit)}; "
                    "no compatible numeric target to compare"
                )
                status = "UNVERIFIED"
            else:
                passed = _evaluate_requirement(
                    calculation.output_value,
                    requirement.comparator,
                    requirement.quantity,
                )
                if passed is None:
                    result = (
                        f"Screening value {_number(calculation.output_value, calculation.unit)} "
                        f"vs target {_number(requirement.quantity, requirement.unit)}; "
                        "the comparator requires an undefined tolerance"
                    )
                    status = "UNVERIFIED"
                else:
                    result = (
                        f"Screening value {_number(calculation.output_value, calculation.unit)} "
                        f"vs target {_number(requirement.quantity, requirement.unit)}: "
                        f"{'passes' if passed else 'fails'} calculation comparison; "
                        "physical performance remains unverified"
                    )
        lines.append(
            f"| {_cell(requirement.statement)} | {_cell(evidence)} | "
            f"{_cell(result)} | {_cell(status)} |"
        )
    for row in comparison_rows:
        if row.get("constraints_pass") is None:
            status = "BLOCKED"
            result = "Screening unavailable because required inputs are missing."
        else:
            status = row.get("evidence_status", "UNVERIFIED")
            result = (
                f"Calculated score={_number(row.get('recommendation_score'))}; "
                f"constraints_pass={row.get('constraints_pass')}"
            )
        lines.append(
            f"| Reference screening for {_cell(row.get('name', row.get('design_id')))} "
            f"| Design calculations and constraint rows | {_cell(result)} | {_cell(status)} |"
        )
        for constraint in brief.safety_constraints:
            if constraint.min_safety_factor is None:
                continue
            safety_factor = row.get("safety_factor")
            if safety_factor is None:
                constraint_result = "Blocked: safety factor is unavailable."
                constraint_status = "BLOCKED"
            else:
                passes = safety_factor >= constraint.min_safety_factor
                constraint_result = (
                    f"Reference safety factor {_number(safety_factor)} vs minimum "
                    f"{_number(constraint.min_safety_factor)}: "
                    f"{'passes' if passes else 'fails'} screening; physical verification required"
                )
                constraint_status = row.get("evidence_status", "UNVERIFIED")
            lines.append(
                f"| {_cell(constraint.statement)} for {_cell(row.get('name', row.get('design_id')))} "
                f"| Calculated reference safety factor | {_cell(constraint_result)} "
                f"| {_cell(constraint_status)} |"
            )
    evidence_rows = design_result.get("evidence_rows", [])
    lines.extend(
        [
            "",
            "### Detailed evidence rows",
            "",
            "| Alternative | Source | Statement | Status | Result | Unit |",
            "|---|---|---|---|---:|---|",
        ]
    )
    for row in evidence_rows:
        lines.append(
            "| "
            + " | ".join(
                _cell(value if value is not None else "Not available")
                for value in (
                    row.get("alternative_id"),
                    row.get("source"),
                    row.get("statement"),
                    row.get("status"),
                    row.get("result"),
                    row.get("unit"),
                )
            )
            + " |"
        )

    volume = selected_parameters.get("estimated_volume_cm3")
    mass = selected.get("estimated_mass_kg")
    printed_cost = selected.get("estimated_cost_usd")
    servo_name = selected_parameters.get("user_selected_servo")
    bom_rows = [
        (
            f"Printed reference gripper ({selected.get('name', design_id)})",
            "1",
            "estimated",
            _number(mass, "kg"),
            _number(printed_cost, "USD"),
            f"Template reference volume: {_number(volume, 'cm3')}; not CAD-derived.",
        )
    ]
    if servo_name:
        try:
            servo = get_component(str(servo_name))
        except CatalogError:
            bom_rows.append(
                (
                    _cell(servo_name),
                    "1",
                    "unverified",
                    "Not available",
                    "Not available",
                    "Named in the brief; no matching catalog record was available.",
                )
            )
        else:
            bom_rows.append(
                (
                    servo.name,
                    "1",
                    "reference estimate",
                    _number(servo.mass_kg, "kg"),
                    _number(servo.approximate_cost_usd, "USD"),
                    servo.source_note,
                )
            )
    lines.extend(
        [
            "",
            "## Bill of materials",
            "",
            "| Item | Quantity | Basis | Estimated mass | Estimated cost | Notes |",
            "|---|---:|---|---:|---:|---|",
        ]
    )
    lines.extend(
        "| " + " | ".join(_cell(value) for value in row) + " |"
        for row in bom_rows
    )
    lines.extend(["", "## Material recommendation", ""])
    material_name = selected_parameters.get("material")
    if material_name:
        try:
            material = get_material(str(material_name))
        except CatalogError as exc:
            lines.append(
                f"- Template material: {_cell(material_name)}. Catalog evidence is unavailable: "
                f"{_cell(exc)}. No material properties are inferred."
            )
        else:
            matches_preference = (
                brief.material_preference is not None
                and brief.material_preference.casefold() == material.name.casefold()
            )
            lines.extend(
                [
                    f"- **Reference material:** {material.name}.",
                    f"- **Brief preference match:** {'Yes' if matches_preference else 'No or not specified'}.",
                    f"- **Reference density:** {_number(material.density_kg_m3, 'kg/m3')}.",
                    f"- **Reference yield strength:** {_number(material.yield_strength_mpa, 'MPa')}.",
                    f"- **Catalog notes:** {_cell(material.printability_notes)}",
                    f"- **Evidence:** {_cell(material.source_note)}",
                    "- These are catalog reference estimates, not verified printed-part properties.",
                ]
            )
    else:
        lines.append("- No material is recorded for the selected template; no recommendation is made.")

    lines.extend(
        [
            "",
            "## Dimensions and tolerances",
            "",
            f"- Reference finger count: {_cell(selected_parameters.get('finger_count', 'Not available'))}.",
            f"- Reference finger length: {_number(selected_parameters.get('finger_length_mm'), 'mm')}.",
            f"- Reference finger width: {_number(selected_parameters.get('finger_width_mm'), 'mm')}.",
            f"- Reference finger thickness: {_number(selected_parameters.get('finger_thickness_mm'), 'mm')}.",
            f"- Reference contact area: {_number(selected_parameters.get('contact_area_mm2'), 'mm2')}.",
            f"- User-stated object diameter: {_number(selected_parameters.get('object_diameter_m'), 'm')}.",
            "- No tolerances are specified or inferred. Fit and tolerances must be established from actual CAD and physical measurements.",
            "",
            "## Assembly notes",
            "",
            "- The CAD export, if generated, is a simple reference concept model and does not define a complete actuator or linkage assembly.",
            "- Verify the actual servo, horn, mounting interface, travel, clearances, and fasteners before fabrication.",
            "- Do not treat the conceptual fingers or mount label as validated geometry.",
            "",
            "## Known limitations",
            "",
            "- Template dimensions, friction coefficient, lever arm, volume, and catalog values are estimates.",
            "- Closed-form screening does not account for print orientation, infill, anisotropy, local stress concentrations, creep, wear, or mechanism losses unless explicitly stated in the calculation notes.",
            "- No simulation, FEA, fatigue test, certification, or manufacturing-readiness assessment is included.",
            "- A non-empty STL is only a generated concept artifact; it is not evidence of printability, fit, or safe operation.",
            "",
            "## Required physical tests",
            "",
            "- Measure the printed part and confirm fit against the actual bottle and actuator.",
            "- Run a controlled grip and retention test using the confirmed payload and the user-defined acceptance criteria; secure the test setup against dropped loads.",
            "- Verify servo travel, current/temperature behavior, linkage clearances, and repeatability under the intended duty cycle.",
            "- Inspect printed layers and interfaces after loading; repeat tests after material, orientation, or geometry changes.",
            "- Establish and document tolerances and acceptance criteria before claiming the design meets the brief.",
            "",
            "## Disclaimer",
            "",
            "ForgeX is engineering decision support, not certification. Reference calculations and generated concept files are not a substitute for qualified engineering review, applicable standards, or physical validation.",
            "",
        ]
    )
    return "\n".join(lines)

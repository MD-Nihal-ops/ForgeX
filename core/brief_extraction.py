"""Offline extraction and completion helpers for an Engineering Brief."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.models import Budget, EngineeringBrief
from core.requirements import (
    EnvelopeDimensions,
    LoadCondition,
    ManufacturingMethod,
    PerformanceRequirement,
    ProductType,
    SafetyConstraint,
)

_NUMBER = r"\d+(?:[.,]\d+)?"
_LENGTH_UNIT = r"(?:mm|cm|m)\b"
_PERFORMANCE_LABEL = (
    r"(?:grip(?:ping)? force|holding force|payload capacity|"
    r"maximum mass|minimum mass)"
)


class BriefExtraction(BaseModel):
    """A partial, user-editable extraction; absent values remain unknown."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    original_text: str = Field(min_length=1)
    project_name: str | None = None
    product_type: ProductType | None = None
    purpose: str | None = None
    performance_requirement: PerformanceRequirement | None = None
    load_condition: LoadCondition | None = None
    dimensions: EnvelopeDimensions | None = None
    payload_mass_kg: float | None = None
    payload_description: str | None = None
    nominal_volume_ml: float | None = None
    component_preferences: list[str] = Field(default_factory=list)
    material_preference: str | None = None
    budget: Budget | None = None
    operating_environment: str | None = None
    safety_constraints: list[SafetyConstraint] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def missing_questions(self) -> list[str]:
        questions: list[str] = []
        if not self.project_name:
            questions.append("What should this project be called?")
        if self.product_type is None:
            questions.append("Is this a servo-driven gripper or a simple structural bracket?")
        if not self.purpose:
            questions.append("What should the product do?")
        if self.performance_requirement is None:
            questions.append(
                "What performance target should it meet? Include a value and unit if known."
            )
        if self.load_condition is None:
            questions.append(
                "What load or payload will it experience? Describe the magnitude and direction if known."
            )
        if self.dimensions is None:
            questions.append("What is the maximum envelope? Provide at least one dimension in metres.")
        if not self.operating_environment:
            questions.append("Where and under what conditions will it operate?")
        return questions

    def brief_payload(self) -> dict[str, Any]:
        """Return known values in the shape expected by EngineeringBrief."""
        return {
            "project_name": self.project_name,
            "product_type": self.product_type,
            "purpose": self.purpose,
            "performance_requirements": (
                [self.performance_requirement] if self.performance_requirement else []
            ),
            "load_conditions": [self.load_condition] if self.load_condition else [],
            "dimensions": self.dimensions,
            "material_preference": self.material_preference,
            "manufacturing_method": ManufacturingMethod.FDM_3D_PRINT,
            "budget": self.budget,
            "operating_environment": self.operating_environment,
            "safety_constraints": self.safety_constraints,
            "assumptions": self.assumptions,
        }


def _number(value: str) -> float:
    return float(value.replace(",", "."))


def _to_metres(value: str, unit: str) -> float:
    scale = {"m": 1.0, "cm": 0.01, "mm": 0.001}[unit.lower()]
    return _number(value) * scale


def _extract_dimensions(text: str) -> EnvelopeDimensions | None:
    diameter = re.search(
        rf"\b(?:bottle\s+)?diameter\b\D{{0,12}}(?P<value>{_NUMBER})\s*"
        rf"(?P<unit>mm|cm|m)\b",
        text,
        re.IGNORECASE,
    )
    if diameter:
        diameter_m = _to_metres(diameter.group("value"), diameter.group("unit"))
        return EnvelopeDimensions(
            width_m=diameter_m,
            notes=f"User-stated bottle diameter: {diameter.group('value')} {diameter.group('unit')}.",
        )

    triplet = re.search(
        rf"(?P<number1>{_NUMBER})\s*(?P<unit1>mm|cm|m)?\s*[x×]\s*"
        rf"(?P<number2>{_NUMBER})\s*(?P<unit2>mm|cm|m)?\s*[x×]\s*"
        rf"(?P<number3>{_NUMBER})\s*(?P<unit3>mm|cm|m)\b",
        text,
        re.IGNORECASE,
    )
    if triplet:
        last_unit = triplet.group("unit3")
        first_unit = triplet.group("unit1") or last_unit
        second_unit = triplet.group("unit2") or first_unit
        return EnvelopeDimensions(
            length_m=_to_metres(triplet.group("number1"), first_unit),
            width_m=_to_metres(triplet.group("number2"), second_unit),
            height_m=_to_metres(triplet.group("number3"), last_unit),
        )

    axes: dict[str, float] = {}
    axis_patterns = {
        "length_m": r"(?:length|long)",
        "width_m": r"(?:width|wide)",
        "height_m": r"(?:height|tall)",
    }
    for field, label in axis_patterns.items():
        match = re.search(
            rf"\b{label}\b\D{{0,20}}(?P<number>{_NUMBER})\s*(?P<unit>{_LENGTH_UNIT})",
            text,
            re.IGNORECASE,
        )
        if match:
            axes[field] = _to_metres(match.group("number"), match.group("unit"))
    return EnvelopeDimensions(**axes) if axes else None


def _extract_payload_mass(text: str) -> float | None:
    match = re.search(
        rf"\b(?:filled\s+weight|payload\s+mass|mass|weighs?|weight)\b"
        rf"\D{{0,18}}(?P<value>{_NUMBER})\s*(?P<unit>kg|g)\b|"
        rf"\b(?P<value_after>{_NUMBER})\s*(?P<unit_after>kg|g)\s+"
        rf"(?:filled\s+)?(?:weight|mass|object|bottle|payload)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    value = _number(match.group("value") or match.group("value_after"))
    unit = match.group("unit") or match.group("unit_after")
    return value if unit.lower() == "kg" else value / 1000


def _extract_performance_requirement(text: str) -> PerformanceRequirement | None:
    comparator = r"(?P<comparator>at least|no less than|minimum|min|>=|at most|no more than|maximum|max|<=)?"
    patterns = (
        (
            rf"{comparator}\s*(?P<number>{_NUMBER})\s*(?P<unit>N|newtons?)\s*"
            rf"(?:of\s*)?{_PERFORMANCE_LABEL}\b"
        ),
        (
            rf"{_PERFORMANCE_LABEL}\b[^.!?\n]{{0,32}}?"
            rf"{comparator}\s*(?P<number>{_NUMBER})\s*(?P<unit>N|newtons?)\b"
        ),
    )
    match = next(
        (found for pattern in patterns if (found := re.search(pattern, text, re.IGNORECASE))),
        None,
    )
    if not match:
        return None

    quantity = match.group("number")
    comparator_text = match.group("comparator") or ""
    comparator = (
        "le"
        if comparator_text.lower() in {"at most", "no more than", "maximum", "max", "<="}
        else "ge"
    )
    label = match.group(0).lower()
    name = "min_grip_force" if "grip" in label or "holding force" in label else "performance_target"
    return PerformanceRequirement(
        name=name,
        statement=match.group(0).strip(),
        quantity=_number(quantity),
        unit="N",
        comparator=comparator,
    )


def _extract_load_condition(text: str) -> LoadCondition | None:
    load_context = re.search(
        r"\b(?:load|payload|hold|holds|holding|lift|support|carry|object|bottle)\b",
        text,
        re.IGNORECASE,
    )
    if not load_context:
        return None

    force_match = re.search(
        rf"\b(?:load|payload|force)\b[^.!?\n]{{0,24}}?"
        rf"(?P<number>{_NUMBER})\s*(?:N|newtons?)\b",
        text,
        re.IGNORECASE,
    )
    return LoadCondition(
        name="applied_load",
        force_n=_number(force_match.group("number")) if force_match else None,
        description=text.strip(),
    )


def extract_engineering_brief(description: str) -> BriefExtraction:
    """Extract only explicit information from a natural-language description."""
    text = description.strip()
    if not text:
        raise ValueError("A non-empty product description is required.")

    lowered = text.lower()
    product_type = None
    if re.search(r"\bgripper\b|\bservo[- ]driven grip", lowered):
        product_type = ProductType.SERVO_DRIVEN_GRIPPER
    elif re.search(r"\bbracket\b|\bmount(?:ing)? bracket\b", lowered):
        product_type = ProductType.STRUCTURAL_BRACKET

    name_match = re.search(
        r"\b(?:called|named|project name[:=])\s+"
        r"([^,.!?\n]+?)(?:\s+(?:to|for|that|which)\b|[,!.?\n]|$)",
        text,
        re.IGNORECASE,
    )
    material_match = re.search(r"\b(PETG|PLA|ABS|ASA|nylon)\b", text, re.IGNORECASE)
    servo_matches = re.findall(
        r"\b(?:SG90|MG90S|MG996R)\b",
        text,
        re.IGNORECASE,
    )
    volume_match = re.search(
        rf"\b(?P<value>{_NUMBER})\s*(?P<unit>ml|mL|lit(?:er|re)s?)\b",
        text,
        re.IGNORECASE,
    )
    budget_match = re.search(
        rf"\b(?:budget|cost limit|price limit)\b[^$0-9]{{0,12}}\$?\s*(?P<amount>{_NUMBER})",
        text,
        re.IGNORECASE,
    ) or re.search(rf"\$\s*(?P<amount>{_NUMBER})\b", text, re.IGNORECASE)
    environment_match = re.search(
        r"\b(?:indoors?|outdoors?|underwater|humid|wet|dry|"
        r"workshop|benchtop|industrial)\b[^.!?\n,;]{0,45}",
        text,
        re.IGNORECASE,
    )
    safety_match = re.search(
        rf"\b(?:minimum|min|desired)?\s*safety factor(?: of)?\s*"
        rf"(?P<value>{_NUMBER})",
        text,
        re.IGNORECASE,
    )

    safety_constraints = (
        [
            SafetyConstraint(
                name="minimum_safety_factor",
                statement=f"Minimum closed-form safety factor of {safety_match.group(1)}.",
                min_safety_factor=_number(safety_match.group(1)),
            )
        ]
        if safety_match and _number(safety_match.group("value")) >= 1
        else []
    )
    notes = (
        ["The stated minimum safety factor is below 1.0 and needs correction."]
        if safety_match and _number(safety_match.group("value")) < 1
        else []
    )
    payload_description = text.strip() if _extract_load_condition(text) else None
    mass_kg = _extract_payload_mass(text)
    if mass_kg is not None:
        payload_description = (
            f"User-stated payload mass: {mass_kg:g} kg."
            if payload_description is None
            else f"{payload_description} User-stated payload mass: {mass_kg:g} kg."
        )

    budget = (
        Budget(amount_usd=_number(budget_match.group("amount")))
        if budget_match
        else None
    )

    return BriefExtraction(
        original_text=text,
        project_name=name_match.group(1).strip() if name_match else None,
        product_type=product_type,
        purpose=text,
        performance_requirement=_extract_performance_requirement(text),
        load_condition=_extract_load_condition(text),
        dimensions=_extract_dimensions(text),
        payload_mass_kg=mass_kg,
        payload_description=payload_description,
        nominal_volume_ml=(
            _number(volume_match.group("value"))
            if volume_match and volume_match.group("unit").lower() == "ml"
            else _number(volume_match.group("value")) * 1000
            if volume_match
            else None
        ),
        component_preferences=[value.upper() for value in servo_matches],
        material_preference=material_match.group(1).upper() if material_match else None,
        budget=budget,
        operating_environment=environment_match.group(0).strip() if environment_match else None,
        safety_constraints=safety_constraints,
        notes=notes,
    )


def build_engineering_brief(
    extraction: BriefExtraction,
    answers: Mapping[str, Any],
) -> EngineeringBrief:
    """Validate user-confirmed form values together with extracted candidates."""
    payload = extraction.brief_payload()
    payload.update(answers)
    return EngineeringBrief.model_validate(payload)

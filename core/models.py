"""Primary engineering data models for ForgeX."""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.requirements import (
    DesignStatus,
    EnvelopeDimensions,
    EvidenceStatus,
    LoadCondition,
    ManufacturingMethod,
    NonEmptyStr,
    PerformanceRequirement,
    ProductType,
    RequirementEvidence,
    SafetyConstraint,
)

PositiveFinite = Annotated[float, Field(gt=0)]
NonNegativeFinite = Annotated[float, Field(ge=0)]


class _ForgeXModel(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        use_enum_values=False,
        validate_assignment=True,
    )


def _require_finite(value: float, field_name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number, not {value!r}.")
    return value


class Budget(_ForgeXModel):
    """Project budget. Currency is USD for the MVP."""

    amount_usd: NonNegativeFinite = Field(..., description="Budget ceiling in US dollars.")
    notes: str = ""

    @field_validator("amount_usd")
    @classmethod
    def amount_is_finite(cls, value: float) -> float:
        return _require_finite(value, "amount_usd")


class EngineeringBrief(_ForgeXModel):
    """Structured intake for a mechanical product idea."""

    project_name: NonEmptyStr = Field(..., description="Human-readable project name.")
    product_type: ProductType = Field(
        ...,
        description=(
            "Supported families: servo-driven gripper, electronics enclosure, "
            "mounting bracket, simple house model, and civil concept advisory."
        ),
    )
    purpose: NonEmptyStr = Field(..., description="What the product is for.")
    performance_requirements: list[PerformanceRequirement] = Field(
        min_length=1,
        description="At least one measurable performance requirement is required.",
    )
    load_conditions: list[LoadCondition] = Field(
        min_length=1,
        description="At least one load condition is required.",
    )
    dimensions: EnvelopeDimensions
    material_preference: str | None = Field(
        default=None,
        description="Preferred print material id or name, e.g. 'PETG'.",
    )
    manufacturing_method: ManufacturingMethod = Field(
        default=ManufacturingMethod.FDM_3D_PRINT,
        description="MVP supports fdm_3d_print only.",
    )
    budget: Budget | None = None
    operating_environment: NonEmptyStr = Field(
        ...,
        description="Intended environment, e.g. 'indoor benchtop, 20 C'.",
    )
    safety_constraints: list[SafetyConstraint] = Field(
        default_factory=list,
        description="Closed-form safety constraints. Not a certification basis.",
    )
    assumptions: list[NonEmptyStr] = Field(
        default_factory=list,
        description="Explicit modelling and usage assumptions.",
    )

    @field_validator("material_preference")
    @classmethod
    def material_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError(
                "material_preference cannot be blank; omit the field or provide a material name."
            )
        return value


class DesignAlternative(_ForgeXModel):
    """One parametric design option to compare."""

    id: NonEmptyStr = Field(..., description="Stable id, e.g. 'ALT-A'.")
    name: NonEmptyStr
    description: NonEmptyStr
    key_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parametric dimensions and catalog ids used by this alternative.",
    )
    pros: list[NonEmptyStr] = Field(default_factory=list)
    cons: list[NonEmptyStr] = Field(default_factory=list)
    estimated_mass_kg: NonNegativeFinite | None = Field(
        default=None,
        description="Estimated mass in kilograms.",
    )
    estimated_cost_usd: NonNegativeFinite | None = Field(
        default=None,
        description="Estimated total cost in US dollars.",
    )
    estimated_print_time_hours: NonNegativeFinite | None = Field(
        default=None,
        description="Heuristic FDM print time in hours.",
    )
    status: DesignStatus = DesignStatus.PROPOSED

    @field_validator("id")
    @classmethod
    def id_has_no_whitespace(cls, value: str) -> str:
        if any(ch.isspace() for ch in value):
            raise ValueError("id cannot contain whitespace.")
        return value

    @field_validator("estimated_mass_kg", "estimated_cost_usd", "estimated_print_time_hours")
    @classmethod
    def estimates_are_finite(cls, value: float | None) -> float | None:
        if value is None:
            return value
        return _require_finite(value, "estimate")

    @field_validator("key_parameters")
    @classmethod
    def parameter_keys_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if not str(key).strip():
                raise ValueError("key_parameters cannot include an empty key.")
        return value


class CalculationResult(_ForgeXModel):
    """A single closed-form calculation with evidence status."""

    name: NonEmptyStr = Field(..., description="Calculation name, e.g. 'grip_force_required'.")
    equation: NonEmptyStr = Field(..., description="Formula id or human-readable equation.")
    inputs: dict[str, Any] = Field(..., min_length=1, description="Numeric and catalog inputs used.")
    output_value: float = Field(..., description="Primary numeric result.")
    unit: NonEmptyStr = Field(..., description="SI unit of output_value, e.g. 'N' or 'MPa'.")
    evidence_status: EvidenceStatus
    notes: str = ""

    @field_validator("output_value")
    @classmethod
    def output_is_finite(cls, value: float) -> float:
        return _require_finite(value, "output_value")

    @field_validator("inputs")
    @classmethod
    def input_keys_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if not str(key).strip():
                raise ValueError("inputs cannot include an empty key.")
        return value

    @model_validator(mode="after")
    def blocked_requires_notes(self) -> CalculationResult:
        if self.evidence_status == EvidenceStatus.BLOCKED and not self.notes.strip():
            raise ValueError(
                "CalculationResult with evidence_status BLOCKED must include notes "
                "explaining why the calculation cannot be completed."
            )
        return self


class BillOfMaterialsItem(_ForgeXModel):
    """One line in the manufacturing bill of materials."""

    name: NonEmptyStr
    quantity: PositiveFinite
    unit: NonEmptyStr = Field(default="ea", description="Quantity unit, e.g. 'ea' or 'g'.")
    source: str = Field(..., description="'print' for fabricated parts or 'buy' for catalog items.")
    catalog_id: str | None = None
    unit_cost_usd: NonNegativeFinite | None = None

    @field_validator("source")
    @classmethod
    def source_must_be_print_or_buy(cls, value: str) -> str:
        allowed = {"print", "buy"}
        if value not in allowed:
            raise ValueError(f"source must be one of {sorted(allowed)}; got {value!r}.")
        return value

    @field_validator("quantity", "unit_cost_usd")
    @classmethod
    def money_and_qty_finite(cls, value: float | None) -> float | None:
        if value is None:
            return value
        return _require_finite(value, "quantity or unit_cost_usd")


class ToleranceSpec(_ForgeXModel):
    """A linear tolerance in metres."""

    feature: NonEmptyStr
    plus_m: NonNegativeFinite
    minus_m: NonNegativeFinite
    notes: str = ""

    @model_validator(mode="after")
    def not_both_zero_unless_noted(self) -> ToleranceSpec:
        if self.plus_m == 0 and self.minus_m == 0:
            raise ValueError(
                f"tolerance for '{self.feature}' cannot be +0 / -0; provide a non-zero band."
            )
        return self


class ExportFile(_ForgeXModel):
    """A file produced for manufacturing or documentation."""

    kind: str = Field(..., description="stl, markdown, or json.")
    path: NonEmptyStr = Field(..., description="Relative path under the project export directory.")

    @field_validator("kind")
    @classmethod
    def kind_allowed(cls, value: str) -> str:
        allowed = {"stl", "markdown", "json"}
        if value not in allowed:
            raise ValueError(f"export kind must be one of {sorted(allowed)}; got {value!r}.")
        return value

    @field_validator("path")
    @classmethod
    def path_is_relative(cls, value: str) -> str:
        if value.startswith("/") or (len(value) >= 2 and value[1] == ":"):
            raise ValueError("export path must be a relative path, not an absolute path.")
        if ".." in value.replace("\\", "/").split("/"):
            raise ValueError("export path cannot contain '..'.")
        return value.replace("\\", "/")


class ManufacturingPackage(_ForgeXModel):
    """Export package for a selected, 3D-printable design."""

    selected_design: DesignAlternative
    bill_of_materials: list[BillOfMaterialsItem] = Field(min_length=1)
    material_recommendation: NonEmptyStr
    dimensions: EnvelopeDimensions
    tolerances: list[ToleranceSpec] = Field(default_factory=list)
    assembly_instructions: list[NonEmptyStr] = Field(
        min_length=1,
        description="Ordered assembly steps. At least one step is required.",
    )
    export_files: list[ExportFile] = Field(default_factory=list)
    known_limitations: list[NonEmptyStr] = Field(
        min_length=1,
        description="At least one limitation must be stated (estimates are not certification).",
    )
    required_physical_tests: list[NonEmptyStr] = Field(
        min_length=1,
        description="Physical tests the builder must run; ForgeX does not certify products.",
    )

    @model_validator(mode="after")
    def selected_design_must_be_selected(self) -> ManufacturingPackage:
        if self.selected_design.status != DesignStatus.SELECTED:
            raise ValueError(
                "ManufacturingPackage.selected_design.status must be 'selected'; "
                f"got {self.selected_design.status!r}."
            )
        return self


__all__ = [
    "BillOfMaterialsItem",
    "Budget",
    "CalculationResult",
    "DesignAlternative",
    "EngineeringBrief",
    "ExportFile",
    "ManufacturingPackage",
    "RequirementEvidence",
    "ToleranceSpec",
]

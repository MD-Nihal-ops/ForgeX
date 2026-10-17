"""Requirement, evidence, and enumeration types for ForgeX."""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmptyStr = Annotated[str, Field(min_length=1)]


class EvidenceStatus(str, Enum):
    """Allowed evidence statuses. Do not add other values."""

    VERIFIED = "VERIFIED"
    ESTIMATED = "ESTIMATED"
    UNVERIFIED = "UNVERIFIED"
    BLOCKED = "BLOCKED"


class ProductType(str, Enum):
    """Supported product families for ForgeX reference workflows."""

    SERVO_DRIVEN_GRIPPER = "servo_driven_gripper"
    ELECTRONICS_ENCLOSURE = "electronics_enclosure"
    MOUNTING_BRACKET = "mounting_bracket"
    SIMPLE_HOUSE_MODEL = "simple_house_model"
    RESIDENTIAL_BUILDING_CONCEPT = "residential_building_concept"
    CIVIL_CONCEPT_ASSISTANT = "civil_concept_assistant"
    STRUCTURAL_BRACKET = "structural_bracket"
    SIMPLE_PRINTABLE_PART = "simple_printable_part"
    SIMPLE_ASSEMBLY = "simple_assembly"


class ManufacturingMethod(str, Enum):
    """MVP manufacturing methods."""

    FDM_3D_PRINT = "fdm_3d_print"


class DesignStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    SELECTED = "selected"
    INFEASIBLE = "infeasible"
    SUPERSEDED = "superseded"


class RequirementResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class _ForgeXModel(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        use_enum_values=False,
        validate_assignment=True,
    )


class PerformanceRequirement(_ForgeXModel):
    """A measurable performance target from the brief."""

    name: NonEmptyStr = Field(
        ...,
        description="Short name, e.g. 'min_grip_force' or 'max_mass'.",
    )
    statement: NonEmptyStr = Field(
        ...,
        description="Human-readable requirement statement.",
    )
    quantity: float | None = Field(
        default=None,
        description="Numeric target in SI units when applicable.",
    )
    unit: str | None = Field(
        default=None,
        description="SI unit symbol for quantity, e.g. 'N' or 'kg'.",
    )
    comparator: str = Field(
        default="ge",
        description="How the design is judged against quantity: ge, le, eq, or approx.",
    )

    @model_validator(mode="after")
    def validate_quantity_and_comparator(self) -> PerformanceRequirement:
        allowed = {"ge", "le", "eq", "approx"}
        if self.comparator not in allowed:
            raise ValueError(
                f"comparator must be one of {sorted(allowed)}; got {self.comparator!r}."
            )
        if self.quantity is not None and self.unit in (None, ""):
            raise ValueError(
                f"performance requirement '{self.name}' has a quantity but no unit."
            )
        if self.quantity is None and self.unit not in (None, ""):
            raise ValueError(
                f"performance requirement '{self.name}' has a unit but no quantity."
            )
        return self


class LoadCondition(_ForgeXModel):
    """A load case applied to the part or assembly."""

    name: NonEmptyStr
    force_n: float | None = Field(default=None, ge=0, description="Force magnitude in newtons.")
    moment_nm: float | None = Field(
        default=None,
        ge=0,
        description="Moment magnitude in newton-metres.",
    )
    direction: str | None = Field(
        default=None,
        description="Load direction, e.g. 'vertical lift' or 'side load'.",
    )
    description: str = Field(default="", description="Free-text load description.")

    @model_validator(mode="after")
    def require_load_definition(self) -> LoadCondition:
        if self.force_n is None and self.moment_nm is None and not self.description:
            raise ValueError(
                f"load condition '{self.name}' must include force_n, moment_nm, "
                "or a non-empty description."
            )
        return self


class EnvelopeDimensions(_ForgeXModel):
    """Maximum bounding envelope in metres (SI)."""

    length_m: float | None = Field(default=None, gt=0, description="Envelope length in metres.")
    width_m: float | None = Field(default=None, gt=0, description="Envelope width in metres.")
    height_m: float | None = Field(default=None, gt=0, description="Envelope height in metres.")
    notes: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_axis(self) -> EnvelopeDimensions:
        if self.length_m is None and self.width_m is None and self.height_m is None:
            raise ValueError(
                "dimensions must include at least one of length_m, width_m, or height_m."
            )
        return self


class SafetyConstraint(_ForgeXModel):
    """A safety-related constraint. Not a certification claim."""

    name: NonEmptyStr
    statement: NonEmptyStr
    min_safety_factor: float | None = Field(
        default=None,
        ge=1.0,
        description="Minimum closed-form safety factor when specified. Must be at least 1.0.",
    )


class RequirementEvidence(_ForgeXModel):
    """One row of the Requirement–Evidence Ledger."""

    requirement: NonEmptyStr = Field(
        ...,
        description="Requirement statement or requirement id being evidenced.",
    )
    design_decision: NonEmptyStr = Field(
        ...,
        description="Design choice that addresses the requirement.",
    )
    evidence: NonEmptyStr = Field(
        ...,
        description="Pointer to a calculation, parameter, catalog item, or assumption.",
    )
    result: RequirementResult = Field(
        ...,
        description="pass, fail, unknown, or not_applicable.",
    )
    status: EvidenceStatus = Field(
        ...,
        description="VERIFIED, ESTIMATED, UNVERIFIED, or BLOCKED.",
    )
    notes: str = Field(default="")

    @model_validator(mode="after")
    def validate_status_consistency(self) -> RequirementEvidence:
        if self.status == EvidenceStatus.BLOCKED and not self.notes.strip():
            raise ValueError(
                "RequirementEvidence with status BLOCKED must include notes "
                "explaining what is blocking verification."
            )
        if self.status == EvidenceStatus.VERIFIED and self.result == RequirementResult.UNKNOWN:
            raise ValueError(
                "RequirementEvidence cannot be VERIFIED while result is unknown."
            )
        if (
            self.result == RequirementResult.NOT_APPLICABLE
            and self.status == EvidenceStatus.VERIFIED
            and not self.notes.strip()
        ):
            raise ValueError(
                "not_applicable + VERIFIED requires notes explaining why the "
                "requirement does not apply."
            )
        return self

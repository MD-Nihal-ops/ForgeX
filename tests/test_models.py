"""Minimal import and validation tests for Stage 2 core models."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from core.models import (
    BillOfMaterialsItem,
    Budget,
    CalculationResult,
    DesignAlternative,
    EngineeringBrief,
    ExportFile,
    ManufacturingPackage,
    ToleranceSpec,
)
from core.requirements import (
    DesignStatus,
    EnvelopeDimensions,
    EvidenceStatus,
    LoadCondition,
    ManufacturingMethod,
    PerformanceRequirement,
    ProductType,
    RequirementEvidence,
    RequirementResult,
    SafetyConstraint,
)


def _brief_kwargs(**overrides):
    data = {
        "project_name": "Bench gripper",
        "product_type": ProductType.SERVO_DRIVEN_GRIPPER,
        "purpose": "Hold a small printed cube on a benchtop.",
        "performance_requirements": [
            {
                "name": "min_grip_force",
                "statement": "Grip force at least 8 N.",
                "quantity": 8.0,
                "unit": "N",
                "comparator": "ge",
            }
        ],
        "load_conditions": [
            {
                "name": "payload_weight",
                "force_n": 2.0,
                "direction": "vertical lift",
            }
        ],
        "dimensions": {"length_m": 0.12, "width_m": 0.08, "height_m": 0.06},
        "manufacturing_method": ManufacturingMethod.FDM_3D_PRINT,
        "operating_environment": "indoor benchtop, 20 C",
        "assumptions": ["Coefficient of friction is an estimate."],
    }
    data.update(overrides)
    return data


def test_core_modules_import():
    import core.models as models
    import core.requirements as requirements

    assert models.EngineeringBrief is EngineeringBrief
    assert requirements.EvidenceStatus.VERIFIED.value == "VERIFIED"


def test_evidence_status_values_are_fixed():
    assert {s.value for s in EvidenceStatus} == {
        "VERIFIED",
        "ESTIMATED",
        "UNVERIFIED",
        "BLOCKED",
    }


def test_engineering_brief_validates_gripper():
    brief = EngineeringBrief.model_validate(_brief_kwargs())
    assert brief.product_type is ProductType.SERVO_DRIVEN_GRIPPER
    assert brief.manufacturing_method is ManufacturingMethod.FDM_3D_PRINT
    assert len(brief.performance_requirements) == 1
    assert len(brief.load_conditions) == 1


def test_engineering_brief_rejects_empty_requirements():
    with pytest.raises(ValidationError):
        EngineeringBrief.model_validate(
            _brief_kwargs(performance_requirements=[])
        )


def test_performance_requirement_requires_unit_with_quantity():
    with pytest.raises(ValidationError):
        PerformanceRequirement.model_validate(
            {
                "name": "min_grip_force",
                "statement": "Need a number with no unit.",
                "quantity": 8.0,
            }
        )


def test_load_condition_requires_definition():
    with pytest.raises(ValidationError):
        LoadCondition.model_validate({"name": "empty"})


def test_envelope_requires_one_axis():
    env = EnvelopeDimensions.model_validate({"height_m": 0.05})
    assert env.height_m == 0.05
    with pytest.raises(ValidationError):
        EnvelopeDimensions.model_validate({})


def test_safety_constraint_min_factor():
    SafetyConstraint.model_validate(
        {"name": "sf", "statement": "Closed-form SF >= 2.", "min_safety_factor": 2.0}
    )
    with pytest.raises(ValidationError):
        SafetyConstraint.model_validate(
            {"name": "sf", "statement": "Too low.", "min_safety_factor": 0.5}
        )


def test_requirement_evidence_blocked_needs_notes():
    with pytest.raises(ValidationError):
        RequirementEvidence.model_validate(
            {
                "requirement": "min_grip_force",
                "design_decision": "Pending servo selection.",
                "evidence": "SRV-02 not run.",
                "result": RequirementResult.UNKNOWN,
                "status": EvidenceStatus.BLOCKED,
            }
        )


def test_requirement_evidence_verified_unknown_is_invalid():
    with pytest.raises(ValidationError):
        RequirementEvidence.model_validate(
            {
                "requirement": "min_grip_force",
                "design_decision": "TBD",
                "evidence": "none",
                "result": RequirementResult.UNKNOWN,
                "status": EvidenceStatus.VERIFIED,
            }
        )


def test_requirement_evidence_not_applicable_verified_needs_notes():
    row = RequirementEvidence.model_validate(
        {
            "requirement": "min_grip_force",
            "design_decision": "Bracket has no jaws.",
            "evidence": "product_type=structural_bracket",
            "result": RequirementResult.NOT_APPLICABLE,
            "status": EvidenceStatus.VERIFIED,
            "notes": "Grip force does not apply to L-brackets.",
        }
    )
    assert row.status is EvidenceStatus.VERIFIED
    with pytest.raises(ValidationError):
        RequirementEvidence.model_validate(
            {
                "requirement": "min_grip_force",
                "design_decision": "Bracket has no jaws.",
                "evidence": "product_type=structural_bracket",
                "result": RequirementResult.NOT_APPLICABLE,
                "status": EvidenceStatus.VERIFIED,
            }
        )


def test_calculation_result_blocked_needs_notes():
    with pytest.raises(ValidationError):
        CalculationResult.model_validate(
            {
                "name": "grip_force_required",
                "equation": "GRIP-01",
                "inputs": {"mass_kg": 0.2},
                "output_value": 0.0,
                "unit": "N",
                "evidence_status": EvidenceStatus.BLOCKED,
            }
        )


def test_calculation_result_rejects_non_finite_output():
    with pytest.raises(ValidationError):
        CalculationResult.model_validate(
            {
                "name": "grip_force_required",
                "equation": "GRIP-01",
                "inputs": {"mass_kg": 0.2},
                "output_value": math.inf,
                "unit": "N",
                "evidence_status": EvidenceStatus.ESTIMATED,
            }
        )


def test_design_alternative_id_no_whitespace():
    with pytest.raises(ValidationError):
        DesignAlternative.model_validate(
            {
                "id": "ALT A",
                "name": "Wide jaw",
                "description": "Parallel gripper.",
            }
        )


def test_manufacturing_package_requires_selected_status():
    design = DesignAlternative.model_validate(
        {
            "id": "ALT-A",
            "name": "Wide jaw",
            "description": "Parallel gripper.",
            "status": DesignStatus.PROPOSED,
        }
    )
    payload = {
        "selected_design": design,
        "bill_of_materials": [
            BillOfMaterialsItem.model_validate(
                {"name": "jaw", "quantity": 2, "source": "print"}
            )
        ],
        "material_recommendation": "PETG",
        "dimensions": {"length_m": 0.12},
        "assembly_instructions": ["Print jaws.", "Fit servo."],
        "known_limitations": ["Closed-form estimates are not certification."],
        "required_physical_tests": ["Hang 2 N payload for 60 s."],
    }
    with pytest.raises(ValidationError):
        ManufacturingPackage.model_validate(payload)

    payload["selected_design"] = design.model_copy(
        update={"status": DesignStatus.SELECTED}
    )
    pkg = ManufacturingPackage.model_validate(payload)
    assert pkg.selected_design.status is DesignStatus.SELECTED


def test_export_file_rejects_absolute_and_parent_paths():
    ExportFile.model_validate({"kind": "markdown", "path": "exports/report.md"})
    with pytest.raises(ValidationError):
        ExportFile.model_validate({"kind": "stl", "path": "C:/tmp/part.stl"})
    with pytest.raises(ValidationError):
        ExportFile.model_validate({"kind": "json", "path": "../secret.json"})


def test_tolerance_rejects_zero_band():
    with pytest.raises(ValidationError):
        ToleranceSpec.model_validate(
            {"feature": "bore", "plus_m": 0.0, "minus_m": 0.0}
        )


def test_budget_non_negative():
    Budget.model_validate({"amount_usd": 0})
    with pytest.raises(ValidationError):
        Budget.model_validate({"amount_usd": -1})

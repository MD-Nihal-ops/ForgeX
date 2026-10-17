"""Tests for deterministic reference-estimate gripper screening."""

from __future__ import annotations

import pytest

from core.design_engine import generate_gripper_designs
from core.models import EngineeringBrief
from core.requirements import EvidenceStatus


def _brief(**overrides) -> EngineeringBrief:
    values = {
        "project_name": "Bottle Gripper",
        "product_type": "servo_driven_gripper",
        "purpose": "Hold a filled 500 ml bottle using an SG90 servo.",
        "performance_requirements": [
            {"name": "hold_bottle", "statement": "Hold the stated bottle."}
        ],
        "load_conditions": [
            {
                "name": "bottle",
                "description": "User-confirmed payload mass: 0.5 kg.",
            }
        ],
        "dimensions": {"width_m": 0.07},
        "material_preference": "PETG",
        "operating_environment": "Indoor bench.",
        "safety_constraints": [
            {
                "name": "minimum_safety_factor",
                "statement": "Minimum closed-form safety factor of 2.",
                "min_safety_factor": 2,
            }
        ],
        "assumptions": [
            "User-specified component preference: SG90; reference rating only."
        ],
    }
    values.update(overrides)
    return EngineeringBrief.model_validate(values)


def _calculation(result, alternative_id: str, name: str):
    return next(
        item
        for item in result["calculations"]
        if item["name"] == f"{alternative_id}/{name}"
    )


def test_generates_three_reference_gripper_alternatives():
    result = generate_gripper_designs(_brief())

    assert [alternative.name for alternative in result["alternatives"]] == [
        "Two-finger rigid gripper",
        "Compliant finger gripper",
        "Wrap-around roller gripper",
    ]
    assert len(result["alternatives"]) == 3
    for alternative in result["alternatives"]:
        parameters = alternative.key_parameters
        assert parameters["finger_count"] == 2
        assert parameters["finger_length_mm"] > 0
        assert parameters["finger_width_mm"] > 0
        assert parameters["finger_thickness_mm"] > 0
        assert parameters["contact_area_mm2"] > 0
        assert 0 < parameters["friction_coefficient"] < 1
        assert parameters["material"] == "PETG"
        assert parameters["servo_mount_type"]
        assert parameters["estimated_volume_cm3"] > 0
        assert parameters["template_value_class"] == "reference_estimate"


def test_calculates_force_torque_mass_cost_print_time_and_strength_per_design():
    result = generate_gripper_designs(_brief())

    assert result["status"] == "REVIEW"
    for alternative in result["alternatives"]:
        ident = alternative.id
        names = {
            calculation["name"].split("/")[-1]
            for calculation in result["calculations"]
            if calculation["name"].startswith(f"{ident}/")
        }
        assert {
            "required_grip_force",
            "servo_torque_required",
            "estimated_mass",
            "estimated_material_cost",
            "estimated_print_time",
            "beam_bending_stress",
            "safety_factor",
            "servo_torque_capacity",
            "grip_force_margin",
            "servo_torque_margin",
        } <= names


def test_missing_required_inputs_block_generation_and_recommendation():
    brief = _brief(
        dimensions={"length_m": 0.1},
        safety_constraints=[],
        load_conditions=[{"name": "payload", "description": "Bottle payload."}],
    )
    result = generate_gripper_designs(brief)

    assert len(result["alternatives"]) == 3
    assert result["status"] == "BLOCKED"
    assert result["recommended_design_id"] is None
    assert "positive filled payload mass" in result["missing_inputs"]
    assert "positive object diameter (stored as dimensions.width_m)" in result["missing_inputs"]
    assert "minimum safety factor" in result["missing_inputs"]
    assert all(item.status.value == "draft" for item in result["alternatives"])
    assert any(
        row["status"] == EvidenceStatus.BLOCKED.value
        for row in result["evidence_rows"]
    )


def test_recommendation_requires_passing_candidate_and_flags_other_failures():
    passing = generate_gripper_designs(_brief())
    assert passing["recommended_design_id"] is not None
    assert passing["status"] == "REVIEW"
    assert all(
        row["constraints_pass"] is True
        for row in passing["comparison_table"]
        if row["design_id"] == passing["recommended_design_id"]
    )
    assert any(
        row["constraints_pass"] is False for row in passing["comparison_table"]
    )
    assert "failed" in passing["explanation"]

    failing = generate_gripper_designs(
        _brief(
            safety_constraints=[
                {
                    "name": "minimum_safety_factor",
                    "statement": "Minimum closed-form safety factor of 100.",
                    "min_safety_factor": 100,
                }
            ]
        )
    )
    assert failing["status"] == "REVIEW"
    assert failing["recommended_design_id"] is None
    assert all(row["constraints_pass"] is False for row in failing["comparison_table"])
    assert failing["recommended_design_id"] is None


def test_calculation_and_evidence_statuses_are_estimated_or_blocked():
    complete = generate_gripper_designs(_brief())
    assert all(
        calculation["evidence_status"] == EvidenceStatus.ESTIMATED.value
        for calculation in complete["calculations"]
    )
    assert all(
        row["status"] == EvidenceStatus.ESTIMATED.value
        for row in complete["evidence_rows"]
    )

    blocked = generate_gripper_designs(
        _brief(
            assumptions=[],
            load_conditions=[{"name": "payload", "description": "Bottle payload."}],
        )
    )
    assert blocked["status"] == "BLOCKED"
    assert all(
        calculation["evidence_status"] in {
            EvidenceStatus.ESTIMATED.value,
            EvidenceStatus.BLOCKED.value,
        }
        for calculation in blocked["calculations"]
    )
    assert any(
        row["status"] == EvidenceStatus.BLOCKED.value
        for row in blocked["evidence_rows"]
    )


def test_generation_rejects_non_gripper_brief():
    with pytest.raises(ValueError, match="servo-driven gripper"):
        generate_gripper_designs(
            _brief(product_type="structural_bracket")
        )


def test_no_fake_cad_simulation_certification_or_evidence_hash_fields():
    result = generate_gripper_designs(_brief())

    def all_keys(value):
        if isinstance(value, dict):
            yield from value
            for child in value.values():
                yield from all_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from all_keys(child)

    keys = {key.casefold() for key in all_keys({
        **result,
        "alternatives": [
            alternative.model_dump(mode="json")
            for alternative in result["alternatives"]
        ],
    })}
    assert not any(
        "evidence_hash" in key or key in {"cad", "simulation", "certification"}
        for key in keys
    )
    assert all(
        "not optimized geometry" in alternative.description
        for alternative in result["alternatives"]
    )

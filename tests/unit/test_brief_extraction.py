"""Tests for offline Stage 5 Engineering Brief extraction."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.brief_extraction import (
    build_engineering_brief,
    extract_engineering_brief,
)
from core.requirements import ProductType


def test_extracts_explicit_gripper_brief_values_in_si_units():
    extraction = extract_engineering_brief(
        "A servo-driven gripper called Bench Gripper to hold a 200 g object, "
        "at least 10 N grip force, envelope 100 x 50 x 20 mm, indoors, PETG, "
        "budget $40."
    )

    assert extraction.project_name == "Bench Gripper"
    assert extraction.product_type is ProductType.SERVO_DRIVEN_GRIPPER
    assert extraction.performance_requirement is not None
    assert extraction.performance_requirement.quantity == 10
    assert extraction.performance_requirement.unit == "N"
    assert extraction.performance_requirement.comparator == "ge"
    assert extraction.load_condition is not None
    assert "200 g object" in extraction.load_condition.description
    assert extraction.dimensions is not None
    assert extraction.dimensions.length_m == pytest.approx(0.1)
    assert extraction.dimensions.width_m == pytest.approx(0.05)
    assert extraction.dimensions.height_m == pytest.approx(0.02)
    assert extraction.operating_environment == "indoors"
    assert extraction.material_preference == "PETG"
    assert extraction.budget is not None
    assert extraction.budget.amount_usd == 40
    assert not extraction.missing_questions


def test_extracts_labeled_bracket_dimensions_and_maximum_comparator():
    extraction = extract_engineering_brief(
        "A structural bracket for a wall mount, maximum 25 N holding force, "
        "length 12 cm and width 50 mm, outdoors."
    )

    assert extraction.product_type is ProductType.STRUCTURAL_BRACKET
    assert extraction.performance_requirement is not None
    assert extraction.performance_requirement.quantity == 25
    assert extraction.performance_requirement.comparator == "le"
    assert extraction.dimensions is not None
    assert extraction.dimensions.length_m == pytest.approx(0.12)
    assert extraction.dimensions.width_m == pytest.approx(0.05)
    assert extraction.dimensions.height_m is None


def test_missing_fields_are_questions_not_guessed_values():
    extraction = extract_engineering_brief("I need a mechanical product.")

    assert extraction.project_name is None
    assert extraction.product_type is None
    assert extraction.performance_requirement is None
    assert extraction.load_condition is None
    assert extraction.dimensions is None
    assert extraction.operating_environment is None
    assert len(extraction.missing_questions) == 6


def test_build_engineering_brief_validates_form_confirmed_values():
    extraction = extract_engineering_brief("A servo-driven gripper to lift a payload indoors.")
    brief = build_engineering_brief(
        extraction,
        {
            "project_name": "Bench Gripper",
            "product_type": ProductType.SERVO_DRIVEN_GRIPPER,
            "purpose": "Hold a small object.",
            "performance_requirements": [
                {
                    "name": "min_grip_force",
                    "statement": "Provide a minimum grip force.",
                    "quantity": 10,
                    "unit": "N",
                    "comparator": "ge",
                }
            ],
            "load_conditions": [
                {
                    "name": "payload",
                    "force_n": 2,
                    "direction": "vertical lift",
                    "description": "Lift a 200 g object.",
                }
            ],
            "dimensions": {"length_m": 0.1, "width_m": 0.05},
            "operating_environment": "Indoor benchtop.",
        },
    )

    assert brief.project_name == "Bench Gripper"
    assert brief.performance_requirements[0].quantity == 10
    assert brief.load_conditions[0].force_n == 2
    assert brief.dimensions.length_m == pytest.approx(0.1)


def test_build_rejects_incomplete_form_answers():
    extraction = extract_engineering_brief("A servo-driven gripper.")

    with pytest.raises(ValidationError):
        build_engineering_brief(extraction, {"project_name": "Incomplete"})


def test_empty_description_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        extract_engineering_brief("  ")


def test_invalid_safety_factor_is_flagged_for_user_correction():
    extraction = extract_engineering_brief(
        "A bracket with a minimum safety factor of 0.5."
    )

    assert not extraction.safety_constraints
    assert extraction.notes == [
        "The stated minimum safety factor is below 1.0 and needs correction."
    ]

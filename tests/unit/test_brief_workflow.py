"""Tests for the Streamlit-independent conversational brief workflow."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import brief_workflow
from core.brief_workflow import (
    clarify_brief_session,
    classify_product_type,
    confirm_brief,
    get_missing_fields,
    start_brief_session,
)
from core.models import EngineeringBrief

INITIAL_REQUEST = (
    "Design a 3D-printable gripper that holds a 500 ml bottle using an SG90 servo."
)
FOLLOW_UP = "Diameter 70 mm, filled weight 500 g, safety factor 2."


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("I want a house", "simple_house_model"),
        ("Plan a building", "simple_house_model"),
        ("What roof should it use?", "simple_house_model"),
        ("Create a gabled model", "simple_house_model"),
        ("Make a scale model", "simple_house_model"),
        ("Design an enclosure", "electronics_enclosure"),
        ("I need a box", "electronics_enclosure"),
        ("Design a case", "electronics_enclosure"),
        ("Create a housing", "electronics_enclosure"),
        ("The product needs a lid", "electronics_enclosure"),
        ("I need a bracket", "mounting_bracket"),
        ("Support a shelf", "mounting_bracket"),
        ("mount this component", "mounting_bracket"),
        ("Design a cantilever", "mounting_bracket"),
        ("Build a gripper", "servo_driven_gripper"),
        ("Design a jaw", "servo_driven_gripper"),
        ("Use a servo", "servo_driven_gripper"),
        ("Pick up a bottle", "servo_driven_gripper"),
        ("Discuss concrete", "civil_concept_assistant"),
        ("Use M20 concrete", "civil_concept_assistant"),
        ("Compare M25", "civil_concept_assistant"),
        ("Design a foundation", "civil_concept_assistant"),
    ],
)
def test_classifier_recognizes_keywords_for_all_product_families(message, expected):
    assert classify_product_type(message).value == expected


def test_house_request_prompts_for_footprint_and_roof_not_bracket_loads():
    result = start_brief_session("Design a gabled house scale model.")
    extraction = result["session_state"]["extraction"]

    assert extraction["product_type"] == "simple_house_model"
    questions = [field["question"].lower() for field in result["missing_fields"]]
    assert any("footprint" in question for question in questions)
    assert any("roof" in question for question in questions)
    assert all("bracket" not in question and "load" not in question for question in questions)


def test_first_message_extracts_known_values_and_reports_missing_inputs():
    result = start_brief_session(INITIAL_REQUEST)
    extraction = result["session_state"]["extraction"]

    assert extraction["product_type"] == "servo_driven_gripper"
    assert extraction["nominal_volume_ml"] == 500
    assert extraction["component_preferences"] == ["SG90"]
    assert "500 ml bottle" in result["assistant_message"]
    assert "SG90 servo" in result["assistant_message"]
    assert {item["name"] for item in get_missing_fields(result["session_state"])} == {
        "payload_diameter",
        "payload_mass",
        "minimum_safety_factor",
    }
    assert not result["ready_to_confirm"]
    json.dumps(result)


def test_follow_up_updates_dimension_mass_and_safety_factor():
    started = start_brief_session(INITIAL_REQUEST)
    result = clarify_brief_session(started["session_state"], FOLLOW_UP)
    extraction = result["session_state"]["extraction"]

    assert extraction["dimensions"]["width_m"] == pytest.approx(0.07)
    assert extraction["payload_mass_kg"] == pytest.approx(0.5)
    assert extraction["safety_constraints"][0]["min_safety_factor"] == 2
    assert result["missing_fields"] == []
    assert result["ready_to_confirm"]
    assert "critical inputs" in result["assistant_message"]


def test_conversation_asks_only_for_unresolved_inputs():
    started = start_brief_session(INITIAL_REQUEST)
    result = clarify_brief_session(
        started["session_state"],
        "Diameter 70 mm and filled weight 500 g.",
    )

    assert [item["name"] for item in result["missing_fields"]] == [
        "minimum_safety_factor"
    ]
    assert len(result["follow_up_questions"]) == 1
    assert "diameter" not in result["assistant_message"].lower().split(
        "to complete the critical inputs"
    )[-1]


def test_missing_values_are_not_fabricated():
    result = start_brief_session(INITIAL_REQUEST)
    extraction = result["session_state"]["extraction"]

    assert extraction["dimensions"] is None
    assert extraction["payload_mass_kg"] is None
    assert extraction["safety_constraints"] == []
    assert "diameter" in result["assistant_message"].lower()
    assert "filled" in result["assistant_message"].lower()
    assert "safety factor" in result["assistant_message"].lower()


def test_confirmation_is_blocked_until_critical_inputs_are_available():
    started = start_brief_session(INITIAL_REQUEST)

    with pytest.raises(ValueError, match="Cannot confirm"):
        confirm_brief(started["session_state"], {})

    clarified = clarify_brief_session(started["session_state"], FOLLOW_UP)
    result = confirm_brief(clarified["session_state"], {})
    brief = EngineeringBrief.model_validate(result["confirmed_brief"])

    assert result["session_state"]["phase"] == "confirmed"
    assert brief.dimensions.width_m == pytest.approx(0.07)
    assert brief.safety_constraints[0].min_safety_factor == 2
    assert "User-confirmed payload mass: 0.5 kg." in brief.load_conditions[0].description
    assert brief.operating_environment.startswith("Not specified by user")
    assert any("Operating environment was not provided" in item for item in brief.assumptions)


def test_confirmation_form_values_can_change_extracted_values():
    clarified = clarify_brief_session(
        start_brief_session(INITIAL_REQUEST)["session_state"],
        FOLLOW_UP,
    )
    result = confirm_brief(
        clarified["session_state"],
        {
            "payload_diameter_mm": "75",
            "payload_mass_g": "600",
            "minimum_safety_factor": "2.5",
        },
    )
    brief = EngineeringBrief.model_validate(result["confirmed_brief"])

    assert brief.dimensions.width_m == pytest.approx(0.075)
    assert "User-confirmed payload mass: 0.6 kg." in brief.load_conditions[0].description
    assert brief.safety_constraints[0].min_safety_factor == 2.5


def test_confirmed_user_environment_replaces_unspecified_marker():
    clarified = clarify_brief_session(
        start_brief_session(INITIAL_REQUEST)["session_state"],
        FOLLOW_UP,
    )
    result = confirm_brief(
        clarified["session_state"],
        {"operating_environment": "Indoor workshop."},
    )

    assert result["confirmed_brief"]["operating_environment"] == "Indoor workshop."
    assert not any(
        "Operating environment was not provided" in assumption
        for assumption in result["confirmed_brief"]["assumptions"]
    )


def test_workflow_module_has_no_streamlit_dependency():
    assert "streamlit" not in brief_workflow.__dict__
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import core.brief_workflow, sys; "
            "assert 'streamlit' not in sys.modules",
        ],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
    )


def test_invalid_minimum_safety_factor_is_not_accepted():
    started = start_brief_session(INITIAL_REQUEST)
    result = clarify_brief_session(
        started["session_state"],
        "Diameter 70 mm, filled weight 500 g, safety factor 0.5.",
    )
    extraction = result["session_state"]["extraction"]

    assert extraction["safety_constraints"] == []
    assert "minimum_safety_factor" in {
        item["name"] for item in result["missing_fields"]
    }
    assert any("below 1.0" in note for note in extraction["notes"])

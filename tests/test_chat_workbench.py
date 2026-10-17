from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from streamlit.testing.v1 import AppTest


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


def test_chat_workbench_completes_gripper_brief_and_generates_designs(monkeypatch):
    responses = [
        {
            "session_id": "chat-test-session",
            "product_type": "servo_driven_gripper",
            "phase": "clarifying",
            "agent_message": "What are the diameter, filled mass, and target safety factor?",
            "brief": {
                "product_type": "servo_driven_gripper",
                "purpose": "Design a gripper for a bottle using an SG90 servo.",
                "dimensions": None,
                "payload_mass_kg": None,
                "safety_constraints": [],
                "assumptions": [],
            },
            "missing_fields": [
                {"name": "payload_diameter", "question": "What is the bottle diameter?"},
                {"name": "payload_mass", "question": "What is the filled mass?"},
                {"name": "minimum_safety_factor", "question": "What safety factor?"},
            ],
        },
        {
            "session_id": "chat-test-session",
            "product_type": "servo_driven_gripper",
            "phase": "ready_to_confirm",
            "agent_message": "Critical inputs are available.",
            "brief": {
                "product_type": "servo_driven_gripper",
                "purpose": "Design a gripper for a bottle using an SG90 servo.",
                "dimensions": {"width_m": 0.07},
                "payload_mass_kg": 0.5,
                "payload_description": "500 ml bottle",
                "safety_constraints": [
                    {"min_safety_factor": 2.0, "statement": "Minimum factor 2."}
                ],
                "material_preference": "PETG",
                "operating_environment": None,
                "assumptions": [],
            },
            "missing_fields": [],
        },
        {
            "session_id": "chat-test-session",
            "product_type": "servo_driven_gripper",
            "phase": "confirmed",
            "agent_message": "Brief confirmed.",
            "brief": {"project_name": "Bottle gripper"},
            "confirmed_brief": {"project_name": "Bottle gripper"},
            "missing_fields": [],
        },
        {
            "status": "REVIEW",
            "recommended_design_id": "reference_gripper",
            "disclaimer": "Reference concept only.",
            "alternatives": [
                {
                    "id": "reference_gripper",
                    "name": "Reference gripper",
                    "status": "ESTIMATED",
                    "description": "Reference alternative.",
                    "key_parameters": {
                        "calculated_metrics": {
                            "recommendation_score": 1.1,
                            "constraints_pass": True,
                        }
                    },
                }
            ],
            "comparison_table": [],
            "calculations": [],
            "evidence_rows": [],
        },
    ]
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def fake_request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(requests.Session, "request", fake_request)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    ).run(timeout=15)

    assert not app.exception
    assert len(app.chat_input) == 1

    app.chat_input[0].set_value(
        "Design a 3D-printable gripper for a 500 ml bottle using an SG90 servo."
    ).run(timeout=15)
    assert not app.exception
    assert app.session_state["brief_response"]["phase"] == "clarifying"

    app.chat_input[0].set_value(
        "Diameter 70 mm, filled weight 500 g, safety factor 2, PETG."
    ).run(timeout=15)
    assert not app.exception
    assert app.session_state["confirmed_brief"] is not None
    assert app.session_state["design_response"]["recommended_design_id"] == "reference_gripper"
    assert len(app.session_state["messages"]) == 4
    assert [call[1].rsplit("/", 1)[-1] for call in calls] == [
        "start",
        "clarify",
        "confirm",
        "generate",
    ]
    confirmed_payload = calls[2][2]["json"]["confirmed_brief"]
    assert confirmed_payload["dimensions"]["width_m"] == 0.07
    assert "User-confirmed payload mass: 0.5 kg." in (
        confirmed_payload["load_conditions"][0]["description"]
    )

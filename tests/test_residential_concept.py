from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from api import routes_exports
from api.main import app
from api.session_store import session_store
from core.residential_concept import (
    calculate_residential_panel,
    extract_residential_inputs,
    missing_residential_fields,
)


class FakeResponse:
    status_code = 201

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload


def _complete_inputs(material: str = "PLA") -> dict:
    return {
        "floor_area_m2": 80,
        "room_count": 6,
        "bedroom_count": 2,
        "footprint_length_m": 10,
        "footprint_width_m": 8,
        "wall_height_m": 2.8,
        "wall_thickness_m": 0.2,
        "foundation_thickness_m": 0.15,
        "roof_pitch_degrees": 30,
        "material": material,
        "budget_amount": 25000,
        "budget_currency": "USD",
    }


def test_residential_request_extracts_known_values_and_only_asks_for_missing_values():
    extracted = extract_residential_inputs(
        "Design a 2-bedroom house model with 80 m\u00b2 area."
    )

    assert extracted == {"floor_area_m2": 80, "bedroom_count": 2}
    missing_names = {item["name"] for item in missing_residential_fields(extracted)}
    assert {"floor_area_m2", "bedroom_count"} & missing_names == set()
    assert "footprint_length_m" in missing_names
    assert "roof_pitch_degrees" in missing_names
    assert "material" in missing_names
    assert "budget_amount" in missing_names


def test_residential_panel_uses_material_catalog_and_flags_missing_machine_records():
    panel = calculate_residential_panel(_complete_inputs())

    assert panel["floor_area_m2"] == pytest.approx(80)
    assert panel["wall_volume_m3"] == pytest.approx(19.712)
    assert panel["roof_volume_m3"] == pytest.approx(92.376)
    assert panel["material_mass_kg"] is not None
    assert panel["estimated_material_cost_usd"] is not None
    assert panel["estimated_print_time_hours"] is None
    assert panel["catalog_cards"]["material"]["record"]["density_kg_m3"] == 1240
    assert panel["catalog_cards"]["printer"]["record"] is None
    assert panel["catalog_cards"]["robotic_arm"]["record"] is None
    assert any("deposition rate is unavailable" in flag for flag in panel["missing_data_flags"])
    assert any("Soil bearing capacity" in flag for flag in panel["missing_data_flags"])


def test_concrete_calculation_does_not_invent_density_or_price():
    panel = calculate_residential_panel(_complete_inputs("C25/30 Concrete"))
    material = panel["catalog_cards"]["material"]["record"]

    assert material["characteristic_strength_cylinder_mpa"] == 25
    assert material["characteristic_strength_cube_mpa"] == 30
    assert material["density_kg_m3"] is None
    assert material["cost_per_kg_usd"] is None
    assert panel["material_mass_kg"] is None
    assert panel["estimated_material_cost_usd"] is None


def test_brief_start_infers_residential_workflow_from_house_request():
    session_store.clear()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/brief/start",
                json={
                    "session_id": "residential-classification-test",
                    "message": "Design a 2-bedroom house model with 80 m\u00b2 area.",
                },
            )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["product_type"] == "residential_building_concept"
        assert data["brief"]["product_inputs"]["floor_area_m2"] == 80
        assert data["brief"]["product_inputs"]["bedroom_count"] == 2
        questions = " ".join(item["question"].lower() for item in data["missing_fields"])
        assert "bracket" not in questions
        assert "servo" not in questions
        assert "footprint" in questions
        assert "roof" in questions
    finally:
        session_store.clear()


def test_residential_design_response_contains_calculations_catalog_and_flags(
    monkeypatch, tmp_path
):
    session_store.clear()
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", tmp_path)
    with TestClient(app) as client:
        started = client.post(
            "/api/brief/start",
            json={
                "session_id": "residential-generation-test",
                "product_type": "residential_building_concept",
                "message": "Design a residential concept.",
            },
        )
        assert started.status_code == 201
        response = client.post(
            "/api/brief/clarify",
            json={
                "session_id": "residential-generation-test",
                "message": "Provide the specified inputs.",
                "product_inputs": _complete_inputs(),
            },
        )
        assert response.status_code == 200, response.text
        confirmed = client.post(
            "/api/brief/confirm",
            json={
                "session_id": "residential-generation-test",
                "confirmed_brief": {
                    "product_type": "residential_building_concept",
                    "project_name": "Two bedroom concept",
                    "purpose": "Illustrative residential concept",
                    "product_inputs": _complete_inputs(),
                },
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        generated = client.post(
            "/api/design/generate",
            json={"session_id": "residential-generation-test"},
        )
        assert generated.status_code == 200, generated.text
        design_id = generated.json()["alternatives"][0]["id"]
        report = client.post(
            f"/api/design/{design_id}/report",
            json={"session_id": "residential-generation-test"},
        )
        assert report.status_code == 200, report.text
        assert "estimated_wall_volume" in report.json()["report_markdown"]
        cad = client.post(
            f"/api/design/{design_id}/cad",
            json={"session_id": "residential-generation-test"},
        )
    session_store.clear()

    data = generated.json()
    assert data["calculation_panel"]["floor_area_m2"] == pytest.approx(80)
    assert data["catalog_cards"]["printer"]["record"] is None
    assert data["catalog_cards"]["robotic_arm"]["record"] is None
    assert "Flag: Soil bearing capacity unconfirmed." in data["calculation_panel"]["missing_data_flags"]
    assert len(data["alternatives"]) == 3
    cad_payload = cad.json()
    assert cad_payload["status"] in {"CREATED", "BLOCKED"}
    if cad_payload["status"] == "CREATED":
        cad_path = tmp_path / cad_payload["artifact_path"]
        assert cad_path.is_file() and cad_path.stat().st_size > 0
    else:
        assert cad_payload["artifact_path"] is None


def test_streamlit_shows_residential_three_panel_canvas_without_api():
    app_test = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    )
    app_test.session_state["product_type_input"] = "residential_building_concept"
    app_test.run(timeout=20)

    assert not app_test.exception
    markdown = "\n".join(item.value for item in app_test.markdown)
    assert "House concept" in markdown
    assert "Product records" in markdown
    assert "Deterministic calculation panel" in markdown
    assert len(app_test.chat_input) == 1


def test_house_chat_prompt_routes_to_residential_and_renders_three_panels(monkeypatch):
    requests_seen: list[dict[str, Any]] = []

    def fake_request(self, method, url, **kwargs):
        requests_seen.append(kwargs)
        return FakeResponse(
            {
                "session_id": "house-chat-ui-session",
                "product_type": "residential_building_concept",
                "phase": "clarifying",
                "agent_message": (
                    "I captured 80 m² and 2 bedrooms. I still need the footprint, "
                    "wall and roof inputs, material, and budget."
                ),
                "brief": {
                    "product_type": "residential_building_concept",
                    "product_inputs": {
                        "floor_area_m2": 80,
                        "bedroom_count": 2,
                    },
                    "catalog_cards": {
                        "material": {"status": "BLOCKED", "record": None},
                        "printer": {
                            "status": "BLOCKED",
                            "record": None,
                            "message": "No printer record.",
                        },
                        "robotic_arm": {
                            "status": "BLOCKED",
                            "record": None,
                            "message": "No robotic arm record.",
                        },
                    },
                },
                "missing_fields": [
                    {
                        "name": "footprint_length_m",
                        "label": "Footprint length (m)",
                        "question": "What footprint length should the concept use?",
                    },
                    {
                        "name": "roof_pitch_degrees",
                        "label": "Roof pitch (degrees)",
                        "question": "What roof pitch should it use?",
                    },
                ],
                "assumptions": [],
                "next_action": "clarify",
                "confirmed_brief": None,
            }
        )

    monkeypatch.setattr(requests.Session, "request", fake_request)
    app_test = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    ).run(timeout=20)
    prompt = "Design a 2-bedroom house model with 80 m\u00b2 area."
    app_test.chat_input[0].set_value(prompt).run(timeout=20)

    assert not app_test.exception
    assert requests_seen[0]["json"]["message"] == prompt
    assert "product_type" not in requests_seen[0]["json"]
    markdown = "\n".join(item.value for item in app_test.markdown)
    assert "House concept" in markdown
    assert "Product records" in markdown
    assert "Deterministic calculation panel" in markdown
    assert "80 m²" in markdown
    assert app_test.session_state["brief_response"]["product_type"] == (
        "residential_building_concept"
    )

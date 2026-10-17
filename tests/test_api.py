"""FastAPI integration tests for ForgeX backend endpoints."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import routes_exports
from api.main import app
from api.session_store import session_store
from core.calculations import calculate_required_grip_force
from core.models import EngineeringBrief


@pytest.fixture
def client():
    session_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    session_store.clear()


def _confirmed_brief(**overrides):
    brief = {
        "project_name": "Bottle Gripper",
        "product_type": "servo_driven_gripper",
        "purpose": "Hold a filled 500 ml bottle with an SG90 servo.",
        "performance_requirements": [
            {
                "name": "hold_bottle",
                "statement": "Hold the user-specified bottle.",
                "quantity": None,
                "unit": None,
                "comparator": "ge",
            }
        ],
        "load_conditions": [
            {
                "name": "bottle_payload",
                "force_n": None,
                "direction": "vertical lift",
                "description": "User-confirmed payload mass: 0.5 kg.",
            }
        ],
        "dimensions": {
            "length_m": None,
            "width_m": 0.07,
            "height_m": None,
            "notes": "User-stated bottle diameter: 70 mm.",
        },
        "material_preference": "PETG",
        "manufacturing_method": "fdm_3d_print",
        "budget": None,
        "operating_environment": "Indoor bench.",
        "safety_constraints": [
            {
                "name": "minimum_safety_factor",
                "statement": "Minimum closed-form safety factor of 2.",
                "min_safety_factor": 2,
            }
        ],
        "assumptions": [
            "User-specified component preference: SG90; catalog compatibility unverified."
        ],
    }
    brief.update(overrides)
    return brief


def test_brief_start_infers_house_family_and_requests_house_dimensions(client: TestClient):
    response = client.post(
        "/api/brief/start",
        json={
            "session_id": "house-classifier-session",
            "message": "Help me design a gabled scale model house.",
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["product_type"] == "residential_building_concept"
    questions = [field["question"].casefold() for field in payload["missing_fields"]]
    assert any("footprint" in question for question in questions)
    assert any("roof" in question for question in questions)
    assert all("bracket" not in question and "load" not in question for question in questions)


def _start_and_confirm(client: TestClient, brief=None) -> str:
    started = client.post(
        "/api/brief/start",
        json={
            "session_id": "design-session",
            "message": (
                "Design a 3D-printable gripper that holds a 500 ml bottle "
                "using an SG90 servo."
            ),
        },
    )
    assert started.status_code == 201
    confirmed = client.post(
        "/api/brief/confirm",
        json={
            "session_id": "design-session",
            "confirmed_brief": brief or _confirmed_brief(),
        },
    )
    assert confirmed.status_code == 200
    return "design-session"


def _generate_designs(client: TestClient, session_id: str = "design-session") -> dict:
    started = client.post(
        "/api/brief/start",
        json={
            "session_id": session_id,
            "message": "Design a 3D-printable gripper for a bottle using an SG90 servo.",
        },
    )
    assert started.status_code == 201
    confirmed = client.post(
        "/api/brief/confirm",
        json={
            "session_id": session_id,
            "confirmed_brief": _confirmed_brief(),
        },
    )
    assert confirmed.status_code == 200
    generated = client.post(
        "/api/design/generate",
        json={"session_id": session_id},
    )
    assert generated.status_code == 200
    return generated.json()


def test_health_reports_loaded_engine_and_cors(client: TestClient):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "engine_loaded": True}
    preflight = client.options(
        "/api/brief/start",
        headers={
            "Origin": "https://frontend.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.headers["access-control-allow-origin"] == "*"


def test_brief_start_returns_interpretation_missing_fields_and_next_action(
    client: TestClient,
):
    response = client.post(
        "/api/brief/start",
        json={
            "message": (
                "Design a 3D-printable gripper that holds a 500 ml bottle "
                "using an SG90 servo."
            )
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["session_id"]
    assert data["phase"] == "clarifying"
    assert data["next_action"] == "clarify"
    assert "500 ml bottle" in data["agent_message"]
    assert data["brief"]["component_preferences"] == ["SG90"]
    assert {field["name"] for field in data["missing_fields"]} == {
        "payload_diameter",
        "payload_mass",
        "minimum_safety_factor",
    }


def test_brief_clarify_updates_session_and_only_returns_remaining_questions(
    client: TestClient,
):
    started = client.post(
        "/api/brief/start",
        json={
            "session_id": "clarify-session",
            "message": "Design a gripper for a 500 ml bottle using SG90.",
        },
    )
    assert started.status_code == 201
    response = client.post(
        "/api/brief/clarify",
        json={
            "session_id": "clarify-session",
            "message": "Diameter 70 mm and filled weight 500 g.",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == "clarifying"
    assert data["next_action"] == "clarify"
    assert [field["name"] for field in data["missing_fields"]] == [
        "minimum_safety_factor"
    ]
    assert data["brief"]["dimensions"]["width_m"] == pytest.approx(0.07)
    assert data["brief"]["payload_mass_kg"] == pytest.approx(0.5)


def test_brief_confirm_validates_and_stores_engineering_brief(client: TestClient):
    started = client.post(
        "/api/brief/start",
        json={"session_id": "confirm-session", "message": "A bottle gripper."},
    )
    assert started.status_code == 201
    response = client.post(
        "/api/brief/confirm",
        json={
            "session_id": "confirm-session",
            "confirmed_brief": _confirmed_brief(),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == "confirmed"
    assert data["next_action"] == "generate_designs"
    assert data["confirmed_brief"]["project_name"] == "Bottle Gripper"
    stored = session_store.get("confirm-session")
    assert stored is not None
    assert EngineeringBrief.model_validate(stored["confirmed_brief"]).project_name == "Bottle Gripper"


def test_brief_confirmation_rejects_invalid_model(client: TestClient):
    client.post(
        "/api/brief/start",
        json={"session_id": "invalid-confirm", "message": "A bottle gripper."},
    )
    invalid = _confirmed_brief()
    invalid["safety_constraints"][0]["min_safety_factor"] = 0.5
    response = client.post(
        "/api/brief/confirm",
        json={"session_id": "invalid-confirm", "confirmed_brief": invalid},
    )

    assert response.status_code == 422


def test_design_generate_returns_three_calculation_backed_alternatives(
    client: TestClient,
):
    session_id = _start_and_confirm(client)
    response = client.post("/api/design/generate", json={"session_id": session_id})

    assert response.status_code == 200
    data = response.json()
    assert len(data["alternatives"]) == 3
    assert data["recommended_design_id"] == "two_finger_rigid_gripper"
    assert data["status"] == "REVIEW"
    assert len(data["comparison_table"]) == 3
    for alternative in data["alternatives"]:
        ident = alternative["id"]
        names = {
            calculation["name"].split("/")[-1]
            for calculation in data["calculations"]
            if calculation["name"].startswith(f"{ident}/")
        }
        assert "required_grip_force" in names
        assert "servo_torque_required" in names
    assert all(row["status"] == "ESTIMATED" for row in data["evidence_rows"])


def test_design_generation_and_qa_use_actual_stored_calculation_results(
    client: TestClient,
):
    brief = _confirmed_brief(
        assumptions=[
            "User-specified component preference: SG90.",
            "User assumption: friction coefficient = 0.4.",
        ]
    )
    session_id = _start_and_confirm(client, brief)
    response = client.post("/api/design/generate", json={"session_id": session_id})

    assert response.status_code == 200
    data = response.json()
    assert len(data["calculations"]) > 3
    grip_results = [
        calculation
        for calculation in data["calculations"]
        if calculation["name"].endswith("/required_grip_force")
    ]
    assert len(grip_results) == 3
    for calculation, alternative in zip(
        grip_results,
        data["alternatives"],
        strict=True,
    ):
        expected = calculate_required_grip_force(
            0.5,
            alternative["key_parameters"]["friction_coefficient"],
            2,
        )
        assert calculation["output_value"] == pytest.approx(expected.output_value)
        assert calculation["equation"].startswith("GRIP-01")

    answer = client.post(
        "/api/design/ask",
        json={
            "session_id": session_id,
            "question": "What grip force did ForgeX calculate?",
        },
    )
    assert answer.status_code == 200
    assert answer.json()["status"] == "answered"
    assert "required_grip_force" in answer.json()["answer"]
    assert "GRIP-01" in answer.json()["answer"]


def test_design_generation_blocks_incomplete_confirmed_brief(client: TestClient):
    brief = _confirmed_brief(
        dimensions={"length_m": 0.1, "width_m": None, "height_m": None, "notes": ""},
        load_conditions=[
            {
                "name": "bottle_payload",
                "force_n": None,
                "direction": "vertical lift",
                "description": "Bottle payload.",
            }
        ],
        safety_constraints=[],
    )
    session_id = _start_and_confirm(client, brief)
    response = client.post("/api/design/generate", json={"session_id": session_id})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"
    assert data["recommended_design_id"] is None
    assert len(data["alternatives"]) == 3
    assert len(data["missing_inputs"]) == 3
    assert any(row["status"] == "BLOCKED" for row in data["evidence_rows"])


def test_design_ask_answers_from_stored_brief_or_says_unavailable(
    client: TestClient,
):
    session_id = _start_and_confirm(client)
    known = client.post(
        "/api/design/ask",
        json={"session_id": session_id, "question": "What is the bottle diameter?"},
    )
    unknown = client.post(
        "/api/design/ask",
        json={"session_id": session_id, "question": "Will it pass a fatigue test?"},
    )

    assert known.status_code == 200
    assert known.json()["status"] == "answered"
    assert "0.07 m" in known.json()["answer"]
    assert unknown.status_code == 200
    assert unknown.json()["status"] == "unavailable"
    assert "will not estimate or invent" in unknown.json()["answer"]


@pytest.mark.parametrize(
    ("path", "body", "expected_status"),
    [
        (
            "/api/brief/clarify",
            {"session_id": "missing-session", "message": "70 mm"},
            404,
        ),
        (
            "/api/brief/confirm",
            {"session_id": "missing-session", "confirmed_brief": _confirmed_brief()},
            404,
        ),
        (
            "/api/design/generate",
            {"session_id": "missing-session"},
            404,
        ),
        (
            "/api/design/ask",
            {"session_id": "missing-session", "question": "What size is it?"},
            404,
        ),
    ],
)
def test_endpoints_reject_unknown_sessions(
    client: TestClient,
    path: str,
    body: dict,
    expected_status: int,
):
    assert client.post(path, json=body).status_code == expected_status


def test_design_generation_requires_confirmed_brief(client: TestClient):
    started = client.post(
        "/api/brief/start",
        json={"session_id": "not-confirmed", "message": "A bottle gripper."},
    )
    assert started.status_code == 201

    response = client.post(
        "/api/design/generate",
        json={"session_id": "not-confirmed"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("artifact", ["cad", "report"])
def test_artifact_endpoints_require_generated_design(
    client: TestClient,
    artifact: str,
):
    started = client.post(
        "/api/brief/start",
        json={"session_id": "artifact-session", "message": "A gripper."},
    )
    assert started.status_code == 201

    response = client.post(
        f"/api/design/two_finger_rigid_gripper/{artifact}",
        json={"session_id": "artifact-session"},
    )
    assert response.status_code == 409
    assert "Generate design alternatives" in response.json()["detail"]

    missing = client.post(
        f"/api/design/two_finger_rigid_gripper/{artifact}",
        json={"session_id": "unknown-artifact-session"},
    )
    assert missing.status_code == 404


def test_unknown_design_id_cannot_create_cad_or_report(
    client: TestClient,
):
    _generate_designs(client, "unknown-design-session")
    for artifact in ("cad", "preview", "report"):
        response = client.post(
            f"/api/design/not-a-generated-design/{artifact}",
            json={"session_id": "unknown-design-session"},
        )
        assert response.status_code == 404


def test_report_is_generated_stored_and_retrievable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _generate_designs(client, "report-session")
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/design/two_finger_rigid_gripper/report",
        json={"session_id": "report-session"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CREATED"
    report_path = tmp_path / data["artifact_path"]
    assert report_path.is_file()
    assert report_path.stat().st_size > 0
    assert data["report_markdown"] == report_path.read_text(encoding="utf-8")
    for heading in (
        "Project overview",
        "Engineering brief",
        "Assumptions",
        "Selected/recommended design",
        "Design alternatives comparison",
        "Calculations",
        "Requirement–Evidence Ledger",
        "Bill of materials",
        "Material recommendation",
        "Dimensions and tolerances",
        "Assembly notes",
        "Known limitations",
        "Required physical tests",
        "ForgeX is engineering decision support, not certification",
    ):
        assert heading in data["report_markdown"]

    fetched = client.get(
        "/api/design/two_finger_rigid_gripper/report",
        params={"session_id": "report-session"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["report_markdown"] == data["report_markdown"]
    assert fetched.json()["artifact_path"] == data["artifact_path"]

    assert "evidence_hash" not in data["report_markdown"].casefold()
    assert "simulation results: passed" not in data["report_markdown"].casefold()
    assert "certification: passed" not in data["report_markdown"].casefold()


def test_report_get_returns_404_when_report_has_not_been_generated(
    client: TestClient,
):
    _generate_designs(client, "no-report-session")
    response = client.get(
        "/api/design/two_finger_rigid_gripper/report",
        params={"session_id": "no-report-session"},
    )

    assert response.status_code == 404
    assert "No engineering report" in response.json()["detail"]


def test_cad_api_reports_real_file_or_explicit_blocked_status(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _generate_designs(client, "cad-session")
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/design/two_finger_rigid_gripper/cad",
        json={"session_id": "cad-session"},
    )
    assert response.status_code == 200
    data = response.json()
    if data["status"] == "CREATED":
        stl_path = tmp_path / data["artifact_path"]
        assert stl_path.is_file()
        assert stl_path.stat().st_size > 0
        assert "reference concept model" in data["message"].casefold()
    else:
        assert data["status"] == "BLOCKED"
        assert data["artifact_path"] is None
        assert "No STL file was created" in data["message"]
        assert not list(tmp_path.rglob("*.stl"))


def test_cad_export_failure_returns_blocked_without_publishing_partial_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    from core.cad_generator import generate_reference_gripper_stl
    from core.design_engine import generate_gripper_designs

    class FakeWorkplane:
        def __init__(self, *args, **kwargs):
            pass

        def box(self, *args, **kwargs):
            return self

        def translate(self, *args, **kwargs):
            return self

        def union(self, *args, **kwargs):
            return self

    class FailingExporter:
        @staticmethod
        def export(*args, **kwargs):
            raise RuntimeError("simulated CAD kernel export failure")

    class FakeCadQuery:
        Workplane = FakeWorkplane

        class exporters:
            export = FailingExporter.export

    monkeypatch.setitem(sys.modules, "cadquery", FakeCadQuery)
    generated = generate_gripper_designs(
        EngineeringBrief.model_validate(_confirmed_brief())
    )
    alternative = next(
        item.model_dump(mode="json")
        for item in generated["alternatives"]
        if item.id == "two_finger_rigid_gripper"
    )
    target = tmp_path / "reference_concept.stl"

    result = generate_reference_gripper_stl(alternative, target)

    assert result["status"] == "BLOCKED"
    assert result["artifact_path"] is None
    assert "simulated CAD kernel export failure" in result["message"]
    assert not target.exists()
    assert not list(tmp_path.glob("*.tmp.stl"))


def test_cad_generator_exports_nonempty_stl_when_cadquery_is_available(
    tmp_path,
):
    pytest.importorskip("cadquery")
    from core.cad_generator import generate_reference_gripper_stl
    from core.design_engine import generate_gripper_designs

    generated = generate_gripper_designs(
        EngineeringBrief.model_validate(_confirmed_brief())
    )
    alternative = next(
        item.model_dump(mode="json")
        for item in generated["alternatives"]
        if item.id == "two_finger_rigid_gripper"
    )
    target = tmp_path / "reference_concept.stl"
    result = generate_reference_gripper_stl(alternative, target)

    assert result["status"] == "CREATED"
    assert target.is_file()
    assert target.stat().st_size > 0


def _register_test_stl(
    client: TestClient,
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
    output_root,
    *,
    real_mesh: bool,
) -> Path:
    _generate_designs(client, session_id)
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", output_root)

    def create_stl(alternative, output_path, product_type):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if real_mesh:
            import trimesh

            trimesh.creation.box().export(str(output_path), file_type="stl")
        else:
            output_path.write_bytes(b"test STL artifact")
        return {
            "status": "CREATED",
            "artifact_path": str(output_path),
            "message": "Test STL artifact created.",
        }

    monkeypatch.setattr(routes_exports, "generate_reference_product_stl", create_stl)
    cad = client.post(
        "/api/design/two_finger_rigid_gripper/cad",
        json={"session_id": session_id},
    )
    assert cad.status_code == 200, cad.text
    assert cad.json()["status"] == "CREATED"
    return output_root / cad.json()["artifact_path"]


def test_preview_api_renders_png_from_existing_real_stl(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    pytest.importorskip("trimesh")
    pytest.importorskip("matplotlib")
    stl_path = _register_test_stl(
        client,
        "preview-success-session",
        monkeypatch,
        tmp_path,
        real_mesh=True,
    )
    assert stl_path.is_file() and stl_path.stat().st_size > 0

    response = client.post(
        "/api/design/two_finger_rigid_gripper/preview",
        json={"session_id": "preview-success-session"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "CREATED", data["message"]
    preview_path = tmp_path / data["artifact_path"]
    assert data["status"] == "CREATED"
    assert preview_path.is_file() and preview_path.stat().st_size > 0
    assert preview_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert data["file_size_bytes"] == preview_path.stat().st_size
    assert data["width_px"] > 0
    assert data["height_px"] > 0
    assert "rendered from the existing STL mesh" in data["message"]


def test_preview_api_blocks_when_stl_is_not_available(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _generate_designs(client, "preview-no-stl-session")
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/design/two_finger_rigid_gripper/preview",
        json={"session_id": "preview-no-stl-session"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"
    assert data["artifact_path"] is None
    assert data["file_size_bytes"] is None
    assert "No successfully generated STL" in data["message"]
    assert not list(tmp_path.rglob("*.png"))


def test_preview_api_blocks_when_recorded_stl_file_is_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    stl_path = _register_test_stl(
        client,
        "preview-deleted-stl-session",
        monkeypatch,
        tmp_path,
        real_mesh=False,
    )
    stl_path.unlink()

    response = client.post(
        "/api/design/two_finger_rigid_gripper/preview",
        json={"session_id": "preview-deleted-stl-session"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "BLOCKED"
    assert data["artifact_path"] is None
    assert data["file_size_bytes"] is None
    assert "recorded STL is missing, empty, or outside" in data["message"]
    assert not list(tmp_path.rglob("*.png"))


def test_preview_api_blocks_when_headless_renderer_is_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    stl_path = _register_test_stl(
        client,
        "preview-no-renderer-session",
        monkeypatch,
        tmp_path,
        real_mesh=False,
    )
    monkeypatch.setitem(sys.modules, "trimesh", None)

    response = client.post(
        "/api/design/two_finger_rigid_gripper/preview",
        json={"session_id": "preview-no-renderer-session"},
    )

    assert response.status_code == 200
    data = response.json()
    assert stl_path.is_file() and stl_path.stat().st_size > 0
    assert data["status"] == "BLOCKED"
    assert data["artifact_path"] is None
    assert data["file_size_bytes"] is None
    assert "trimesh preview dependency is unavailable" in data["message"]
    assert not list(tmp_path.rglob("*.png"))

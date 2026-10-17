"""Stage 10 product registry and optional persistence coverage."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import database
from api import routes_exports
from api.database import (
    ArtifactRecord,
    AnalysisJobRecord,
    Base,
    CalculationRecord,
    ClarificationRecord,
    ComparisonRecord,
    EvidenceRecord,
    GeneratedAlternativeRecord,
    SessionRecord,
)
from api.main import app
from api.session_store import session_store


PRODUCT_INPUTS = {
    "electronics_enclosure": {
        "internal_length_mm": 100,
        "internal_width_mm": 60,
        "internal_height_mm": 30,
        "wall_thickness_mm": 2,
        "lid_type": "screw-mounted",
        "cable_port_count": 2,
        "cable_port_diameter_mm": 8,
        "material": "PETG",
        "minimum_wall_thickness_mm": 1.2,
    },
    "mounting_bracket": {
        "load_mass_kg": 1.5,
        "load_distance_mm": 80,
        "base_width_mm": 50,
        "arm_length_mm": 80,
        "material": "PETG",
        "minimum_safety_factor": 2,
        "fastener_diameter_mm": 5,
    },
    "simple_house_model": {
        "footprint_length_mm": 120,
        "footprint_width_mm": 80,
        "wall_height_mm": 50,
        "wall_thickness_mm": 2,
        "roof_pitch_degrees": 30,
        "door_width_mm": 20,
        "door_height_mm": 35,
        "window_count": 4,
        "material": "PLA",
        "minimum_wall_thickness_mm": 1.2,
    },
}


def _new_session(
    client: TestClient,
    product_type: str,
    session_id: str,
    product_inputs: dict,
) -> dict:
    started = client.post(
        "/api/brief/start",
        json={
            "session_id": session_id,
            "message": f"Explore a {product_type.replace('_', ' ')} concept.",
            "product_type": product_type,
            "product_inputs": product_inputs,
        },
    )
    assert started.status_code == 201, started.text
    assert started.json()["phase"] == "ready_to_confirm"
    confirmed = client.post(
        "/api/brief/confirm",
        json={
            "session_id": session_id,
            "confirmed_brief": {
                "product_type": product_type,
                "project_name": f"Test {product_type}",
                "purpose": "Stage 10 integration coverage.",
                "product_inputs": product_inputs,
            },
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    generated = client.post(
        "/api/design/generate",
        json={"session_id": session_id},
    )
    assert generated.status_code == 200, generated.text
    return generated.json()


@pytest.fixture
def client():
    session_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    session_store.clear()


@pytest.mark.parametrize(
    ("product_type", "expected_names", "required_calculation"),
    [
        (
            "electronics_enclosure",
            [
                "Compact rectangular enclosure",
                "Vented rectangular enclosure",
                "Wall-mount enclosure",
            ],
            "estimated_mass",
        ),
        (
            "mounting_bracket",
            ["L-shaped bracket", "T-shaped bracket", "Reinforced triangular bracket"],
            "beam_bending_stress",
        ),
        (
            "simple_house_model",
            ["Compact gabled house", "Wide gabled house", "Tall gabled house"],
            "estimated_mass",
        ),
    ],
)
def test_registered_product_families_generate_real_calculations_and_evidence(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    product_type: str,
    expected_names: list[str],
    required_calculation: str,
):
    result = _new_session(
        client,
        product_type,
        f"stage10-{product_type}",
        PRODUCT_INPUTS[product_type],
    )

    assert [item["name"] for item in result["alternatives"]] == expected_names
    assert result["calculations"]
    assert "ESTIMATED" in {item["evidence_status"] for item in result["calculations"]}
    assert {item["evidence_status"] for item in result["calculations"]} <= {
        "ESTIMATED",
        "VERIFIED",
    }
    assert any(
        item["name"].endswith(required_calculation)
        for item in result["calculations"]
    )
    assert result["evidence_rows"]
    assert result["recommended_design_id"] is None
    assert result["disclaimer"]
    monkeypatch.setattr(routes_exports, "PROJECT_ROOT", tmp_path)
    report = client.post(
        f"/api/design/{result['alternatives'][0]['id']}/report",
        json={"session_id": f"stage10-{product_type}"},
    )
    assert report.status_code == 200, report.text
    assert result["disclaimer"] in report.json()["report_markdown"]
    assert (tmp_path / report.json()["artifact_path"]).is_file()


def test_product_registry_blocks_missing_values_without_fabrication(client: TestClient):
    started = client.post(
        "/api/brief/start",
        json={
            "session_id": "missing-enclosure",
            "message": "Build an electronics enclosure.",
            "product_type": "electronics_enclosure",
            "product_inputs": {"internal_length_mm": 100},
        },
    )
    assert started.status_code == 201
    assert started.json()["phase"] == "clarifying"
    assert {field["name"] for field in started.json()["missing_fields"]} >= {
        "internal_width_mm",
        "material",
        "minimum_wall_thickness_mm",
    }

    clarified = client.post(
        "/api/brief/clarify",
        json={
            "session_id": "missing-enclosure",
            "message": "I can provide more dimensions later.",
            "product_inputs": PRODUCT_INPUTS["electronics_enclosure"],
        },
    )
    assert clarified.status_code == 200
    assert clarified.json()["phase"] == "ready_to_confirm"


def test_civil_family_is_advisory_only_and_cannot_export_cad(client: TestClient):
    started = client.post(
        "/api/brief/start",
        json={
            "session_id": "civil-advisory",
            "message": "Compare preliminary approaches for a small retaining wall.",
            "product_type": "civil_concept_assistant",
        },
    )
    assert started.status_code == 201
    assert started.json()["phase"] == "ready_to_confirm"
    confirmed = client.post(
        "/api/brief/confirm",
        json={
            "session_id": "civil-advisory",
            "confirmed_brief": {"product_inputs": started.json()["brief"]["product_inputs"]},
        },
    )
    assert confirmed.status_code == 200
    generated = client.post(
        "/api/design/generate",
        json={"session_id": "civil-advisory"},
    )
    assert generated.status_code == 200
    data = generated.json()
    assert data["status"] == "REVIEW"
    assert data["recommended_design_id"] is None
    assert data["calculations"] == []
    assert "qualified professionals" in data["disclaimer"]
    cad = client.post(
        "/api/design/site_constraints/cad",
        json={"session_id": "civil-advisory"},
    )
    assert cad.status_code == 200
    assert cad.json()["status"] == "BLOCKED"
    assert cad.json()["artifact_path"] is None


def test_sqlite_dependency_override_persists_workflow_and_design_rows(tmp_path):
    database_file = tmp_path / "forgex-stage10.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_file}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def initialize() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(initialize())

    async def override_db():
        async with factory() as database_session:
            yield database_session

    session_store.clear()
    app.dependency_overrides[database.get_db_session] = override_db
    try:
        with TestClient(app) as test_client:
            brief = {
                "project_name": "Persistent gripper",
                "product_type": "servo_driven_gripper",
                "purpose": "Hold a user-specified bottle.",
                "performance_requirements": [
                    {
                        "name": "hold",
                        "statement": "Hold payload.",
                        "comparator": "ge",
                    }
                ],
                "load_conditions": [
                    {
                        "name": "payload",
                        "description": "User-confirmed payload mass: 0.5 kg.",
                    }
                ],
                "dimensions": {"width_m": 0.07},
                "material_preference": "PETG",
                "operating_environment": "Indoor bench.",
                "safety_constraints": [
                    {
                        "name": "minimum",
                        "statement": "Minimum safety factor 2.",
                        "min_safety_factor": 2,
                    }
                ],
            }
            started = test_client.post(
                "/api/brief/start",
                json={
                    "session_id": "sqlite-persistent-session",
                    "message": "A bottle gripper with an SG90 servo.",
                },
            )
            assert started.status_code == 201
            confirmed = test_client.post(
                "/api/brief/confirm",
                json={
                    "session_id": "sqlite-persistent-session",
                    "confirmed_brief": brief,
                },
            )
            assert confirmed.status_code == 200
            generated = test_client.post(
                "/api/design/generate",
                json={"session_id": "sqlite-persistent-session"},
            )
            assert generated.status_code == 200
            analysis = test_client.post(
                "/api/analysis/create",
                json={
                    "session_id": "sqlite-persistent-session",
                    "design_id": "two_finger_rigid_gripper",
                    "analysis_type": "structural",
                    "inputs": {},
                },
            )
            assert analysis.status_code == 201
            analysis_id = analysis.json()["analysis_id"]
            assert analysis.json()["status"] == "BLOCKED"
            session_store.clear()
            after_restart = test_client.post(
                "/api/design/ask",
                json={
                    "session_id": "sqlite-persistent-session",
                    "question": "What is the bottle diameter?",
                },
            )
            assert after_restart.status_code == 200
            assert "0.07 m" in after_restart.json()["answer"]
            session_store.clear()
            persisted_job = test_client.get(f"/api/analysis/{analysis_id}")
            assert persisted_job.status_code == 200
            assert persisted_job.json()["status"] == "BLOCKED"

        async def assert_rows() -> None:
            async with factory() as database_session:
                state = await database_session.get(
                    SessionRecord, "sqlite-persistent-session"
                )
                assert state is not None
                assert (
                    await database_session.get(AnalysisJobRecord, analysis_id)
                ) is not None
                assert len((await database_session.scalars(
                    select(GeneratedAlternativeRecord).where(
                        GeneratedAlternativeRecord.session_id
                        == "sqlite-persistent-session"
                    )
                )).all()) == 3
                for record_type in (
                    CalculationRecord,
                    EvidenceRecord,
                    ComparisonRecord,
                    ClarificationRecord,
                ):
                    count = len(
                        (
                            await database_session.scalars(
                                select(record_type).where(
                                    record_type.session_id
                                    == "sqlite-persistent-session"
                                )
                            )
                        ).all()
                    )
                    assert count > 0
                assert not (
                    await database_session.scalars(
                        select(ArtifactRecord).where(
                            ArtifactRecord.session_id == "sqlite-persistent-session"
                        )
                    )
                ).all()

        asyncio.run(assert_rows())
    finally:
        app.dependency_overrides.clear()
        session_store.clear()
        asyncio.run(engine.dispose())


def test_streamlit_product_selector_exposes_dynamic_inputs():
    from streamlit.testing.v1 import AppTest

    app_test = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    ).run(timeout=10)
    assert not app_test.exception
    selector = app_test.selectbox(key="product_family_selector")
    selector.set_value("Electronics enclosure")
    app_test.run(timeout=10)

    assert not app_test.exception
    assert any("Internal length" in item.label for item in app_test.number_input)

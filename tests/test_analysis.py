"""Opt-in analysis-job API coverage without requiring installed solvers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.session_store import session_store
from core import analysis_jobs


@pytest.fixture
def client():
    session_store.clear()
    with TestClient(app) as test_client:
        yield test_client
    session_store.clear()


def _ready_design(client: TestClient, session_id: str) -> None:
    start = client.post(
        "/api/brief/start",
        json={
            "session_id": session_id,
            "message": "Design a gripper for a bottle with a servo.",
        },
    )
    assert start.status_code == 201, start.text
    confirm = client.post(
        "/api/brief/confirm",
        json={
            "session_id": session_id,
            "confirmed_brief": {
                "project_name": "Analysis test gripper",
                "product_type": "servo_driven_gripper",
                "purpose": "Hold the user-provided bottle.",
                "performance_requirements": [
                    {
                        "name": "hold",
                        "statement": "Hold the user-specified payload.",
                        "comparator": "ge",
                    }
                ],
                "load_conditions": [
                    {
                        "name": "payload",
                        "description": "Payload conditions are user supplied.",
                    }
                ],
                "dimensions": {"width_m": 0.07},
                "material_preference": "PETG",
                "manufacturing_method": "fdm_3d_print",
                "operating_environment": "User supplied test conditions.",
                "safety_constraints": [],
                "assumptions": [],
            },
        },
    )
    assert confirm.status_code == 200, confirm.text
    generated = client.post(
        "/api/design/generate",
        json={"session_id": session_id},
    )
    assert generated.status_code == 200, generated.text


STRUCTURAL_INPUTS: dict[str, Any] = {
    "material_properties": {
        "density_kg_m3": 1200,
        "youngs_modulus_mpa": 1500,
        "poisson_ratio": 0.35,
        "yield_strength_mpa": 35,
    },
    "loads": [{"magnitude_n": 5, "direction": [0, 0, -1], "location": "user-defined"}],
    "supports": [{"type": "fixed", "location": "user-defined"}],
    "mesh_reference_assumptions": {
        "element_type": "C3D10",
        "mesh_size_mm": 2,
        "geometry_source": "user-supplied CalculiX deck mesh",
    },
    "solver_input": "*HEADING\nUser-supplied solver deck\n",
}


def _create_structural_job(
    client: TestClient,
    session_id: str,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/api/analysis/create",
        json={
            "session_id": session_id,
            "design_id": "two_finger_rigid_gripper",
            "analysis_type": "structural",
            "inputs": STRUCTURAL_INPUTS if inputs is None else inputs,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_analysis_create_is_explicit_and_does_not_start_solver(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    _ready_design(client, "analysis-create-session")

    def solver_must_not_be_checked(_):
        raise AssertionError("Creating a draft must not inspect or start a solver.")

    monkeypatch.setattr(analysis_jobs.shutil, "which", solver_must_not_be_checked)
    job = _create_structural_job(client, "analysis-create-session")

    assert job["status"] == "DRAFT"
    assert job["analysis_type"] == "structural"
    assert job["design_id"] == "two_finger_rigid_gripper"
    assert job["input_snapshot"]["inputs"] == STRUCTURAL_INPUTS
    assert job["created_at"]
    assert job["completed_at"] is None
    assert job["result_artifact_paths"] == []
    assert "qualified engineer" in job["disclaimer"]


def test_analysis_creation_blocks_with_precise_missing_inputs(client: TestClient):
    _ready_design(client, "analysis-missing-session")

    job = _create_structural_job(
        client,
        "analysis-missing-session",
        {"material_properties": {"density_kg_m3": 1200}},
    )

    assert job["status"] == "BLOCKED"
    assert job["result_artifact_paths"] == []
    assert {
        "material_properties.youngs_modulus_mpa",
        "material_properties.poisson_ratio",
        "material_properties.yield_strength_mpa",
        "loads",
        "supports",
        "mesh_reference_assumptions",
        "solver_input",
    } <= set(job["missing_fields"])
    assert "No solver was run" in job["message"]


def test_run_blocks_when_calculix_is_unavailable_and_creates_no_results(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _ready_design(client, "analysis-no-solver-session")
    job = _create_structural_job(client, "analysis-no-solver-session")
    monkeypatch.setattr(analysis_jobs.shutil, "which", lambda _: None)
    monkeypatch.setattr("api.routes_analysis.PROJECT_ROOT", tmp_path)

    response = client.post(f"/api/analysis/{job['analysis_id']}/run")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "BLOCKED"
    assert result["solver_name"] == "CalculiX (ccx)"
    assert result["solver_version"] is None
    assert result["result_artifact_paths"] == []
    assert "unavailable" in result["message"]
    assert not list(tmp_path.rglob("*"))


def test_cfd_job_blocks_when_selected_openfoam_solver_is_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _ready_design(client, "analysis-cfd-no-solver-session")
    case_files = {
        "system/controlDict": "user supplied control dictionary",
        "system/fvSchemes": "user supplied discretization schemes",
        "system/fvSolution": "user supplied solution controls",
        "constant/polyMesh/points": "user supplied mesh points",
        "constant/polyMesh/faces": "user supplied mesh faces",
        "constant/polyMesh/owner": "user supplied mesh owners",
        "constant/polyMesh/neighbour": "user supplied mesh neighbours",
        "constant/polyMesh/boundary": "user supplied mesh boundaries",
        "0/U": "user supplied velocity fields",
        "0/p": "user supplied pressure fields",
    }
    created = client.post(
        "/api/analysis/create",
        json={
            "session_id": "analysis-cfd-no-solver-session",
            "design_id": "two_finger_rigid_gripper",
            "analysis_type": "cfd",
            "inputs": {
                "fluid_domain": {"geometry_source": "user supplied"},
                "boundary_conditions": [{"patch": "inlet", "type": "velocity"}],
                "inlet_conditions": {"patch": "inlet", "velocity_m_s": 1},
                "outlet_conditions": {"patch": "outlet", "pressure_pa": 0},
                "solver": "simpleFoam",
                "solver_case_inputs": case_files,
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "DRAFT"
    monkeypatch.setattr(analysis_jobs.shutil, "which", lambda _: None)
    monkeypatch.setattr("api.routes_analysis.PROJECT_ROOT", tmp_path)

    run = client.post(f"/api/analysis/{created.json()['analysis_id']}/run")

    assert run.status_code == 200, run.text
    assert run.json()["status"] == "BLOCKED"
    assert run.json()["solver_name"] == "OpenFOAM (simpleFoam)"
    assert run.json()["result_artifact_paths"] == []
    assert "unavailable" in run.json()["message"]
    assert not list(tmp_path.rglob("*"))


def test_analysis_job_and_results_are_retrievable_without_fabricated_values(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _ready_design(client, "analysis-results-session")
    job = _create_structural_job(client, "analysis-results-session")
    monkeypatch.setattr(analysis_jobs.shutil, "which", lambda _: None)
    monkeypatch.setattr("api.routes_analysis.PROJECT_ROOT", tmp_path)
    run = client.post(f"/api/analysis/{job['analysis_id']}/run")
    assert run.status_code == 200

    fetched = client.get(f"/api/analysis/{job['analysis_id']}")
    results = client.get(f"/api/analysis/{job['analysis_id']}/results")

    assert fetched.status_code == results.status_code == 200
    assert fetched.json()["status"] == results.json()["status"] == "BLOCKED"
    assert results.json()["result_artifact_paths"] == []
    assert results.json()["solver_stdout"] is None
    assert results.json()["solver_stderr"] is None
    assert results.json()["solver_output_summary"] is None
    assert not {
        "stress_mpa",
        "displacement_mm",
        "factor_of_safety",
        "pressure_drop_pa",
        "velocity_m_s",
        "certification",
        "validated",
    } & results.json().keys()


def test_solver_results_endpoint_returns_only_files_created_by_solver_process(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    _ready_design(client, "analysis-completed-session")
    job = _create_structural_job(client, "analysis-completed-session")
    monkeypatch.setattr(analysis_jobs.shutil, "which", lambda _: "ccx")
    monkeypatch.setattr("api.routes_analysis.PROJECT_ROOT", tmp_path)

    def fake_solver(command, *, cwd, **kwargs):
        result_file = Path(cwd) / "model.frd"
        result_file.write_bytes(b"solver-created raw output")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="CalculiX Version 2.22\nSolver completed.",
            stderr="",
        )

    monkeypatch.setattr(analysis_jobs.subprocess, "run", fake_solver)
    run = client.post(f"/api/analysis/{job['analysis_id']}/run")

    assert run.status_code == 200, run.text
    assert run.json()["status"] == "COMPLETED"
    assert run.json()["solver_version"] == "2.22"
    results = client.get(f"/api/analysis/{job['analysis_id']}/results")
    assert results.status_code == 200
    data = results.json()
    assert data["solver_stdout"] == "CalculiX Version 2.22\nSolver completed."
    assert "Solver completed." == data["solver_output_summary"]
    assert any(path.endswith("model.frd") for path in data["result_artifact_paths"])
    for artifact in data["result_artifact_paths"]:
        assert (tmp_path / artifact).is_file()
    assert not {
        "stress_mpa",
        "displacement_mm",
        "factor_of_safety",
        "certification",
    } & data.keys()


def test_analysis_requires_a_generated_design_and_valid_design_id(client: TestClient):
    start = client.post(
        "/api/brief/start",
        json={"session_id": "analysis-before-design", "message": "A test brief"},
    )
    assert start.status_code == 201
    no_design = client.post(
        "/api/analysis/create",
        json={
            "session_id": "analysis-before-design",
            "design_id": "missing-design",
            "analysis_type": "cfd",
            "inputs": {},
        },
    )
    assert no_design.status_code == 409

    _ready_design(client, "analysis-invalid-design")
    invalid_design = client.post(
        "/api/analysis/create",
        json={
            "session_id": "analysis-invalid-design",
            "design_id": "missing-design",
            "analysis_type": "structural",
            "inputs": {},
        },
    )
    assert invalid_design.status_code == 404


def test_cfd_missing_inputs_are_reported_and_case_paths_are_confined(
    client: TestClient,
):
    _ready_design(client, "analysis-cfd-session")
    response = client.post(
        "/api/analysis/create",
        json={
            "session_id": "analysis-cfd-session",
            "design_id": "two_finger_rigid_gripper",
            "analysis_type": "cfd",
            "inputs": {"solver_case_inputs": {"../escape": "not allowed"}},
        },
    )
    assert response.status_code == 422


def test_streamlit_analysis_tab_shows_opt_in_analysis_controls():
    from streamlit.testing.v1 import AppTest

    app_path = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
    app = AppTest.from_file(app_path)
    brief = {
        "product_type": "servo_driven_gripper",
        "project_name": "UI smoke test",
        "purpose": "Render analysis controls.",
        "disclaimer": "Reference concept only.",
        "dimensions": {},
        "load_conditions": [],
        "safety_constraints": [],
        "assumptions": [],
    }
    app.session_state["brief_response"] = {
        "phase": "confirmed",
        "product_type": "servo_driven_gripper",
        "confirmed_brief": brief,
    }
    app.session_state["active_session_id"] = "analysis-ui-session"
    app.session_state["confirmed_brief"] = brief
    app.session_state["design_response"] = {
        "status": "REVIEW",
        "explanation": "UI test fixture.",
        "disclaimer": "Reference concepts only.",
        "recommended_design_id": None,
        "missing_inputs": [],
        "alternatives": [
            {
                "id": design_id,
                "name": design_id,
                "description": "UI test fixture.",
                "status": "DRAFT",
                "key_parameters": {"calculated_metrics": {}},
            }
            for design_id in (
                "two_finger_rigid_gripper",
                "compliant_finger_gripper",
                "wrap_around_roller_gripper",
            )
        ],
        "comparison_table": [],
        "calculations": [],
        "evidence_rows": [],
    }

    app.run(timeout=15)

    assert not app.exception
    assert any(tab.label == "Analysis" for tab in app.tabs)
    app.selectbox(key="analysis_choice_two_finger_rigid_gripper").set_value(
        "Structural analysis"
    )
    app.run(timeout=15)
    assert not app.exception
    assert any(button.label == "Create Analysis Job" for button in app.button)

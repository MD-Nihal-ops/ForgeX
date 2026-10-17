"""Explicit opt-in structural and CFD analysis jobs."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db_session
from api.schemas import (
    AnalysisCreateRequest,
    AnalysisJobResponse,
    AnalysisResultsResponse,
    AnalysisStatus,
    AnalysisType,
)
from api.session_store import (
    get_workflow_state,
    locate_analysis_job,
    remember_analysis_session,
    save_workflow_state,
)
from core.analysis_jobs import (
    ANALYSIS_DISCLAIMER,
    CFD_LIMITATIONS,
    STRUCTURAL_LIMITATIONS,
    _safe_case_path,
    execute_cfd_solver,
    execute_structural_solver,
    missing_analysis_inputs,
)
from core.data_loader import PROJECT_ROOT

router = APIRouter(prefix="/api/analysis", tags=["analysis jobs"])
_SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_SAFE_ANALYSIS_ID = re.compile(r"[0-9a-f]{32}\Z")


def _analysis_directory(session_id: str, analysis_id: str) -> Path:
    if not _SAFE_SESSION_ID.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id.")
    if not _SAFE_ANALYSIS_ID.fullmatch(analysis_id):
        raise HTTPException(status_code=400, detail="Invalid analysis_id.")
    export_root = (PROJECT_ROOT / "exports").resolve()
    session_directory = export_root / session_id
    analysis_directory = session_directory / "analysis" / analysis_id
    resolved = analysis_directory.resolve()
    if (
        session_directory.resolve().parent != export_root
        or session_directory.resolve() not in resolved.parents
    ):
        raise HTTPException(status_code=400, detail="Invalid analysis directory.")
    return resolved


def _response(job: dict[str, Any]) -> AnalysisJobResponse:
    return AnalysisJobResponse(
        analysis_id=job["analysis_id"],
        session_id=job["session_id"],
        design_id=job["design_id"],
        analysis_type=job["analysis_type"],
        status=job["status"],
        input_snapshot=job["input_snapshot"],
        solver_name=job.get("solver_name"),
        solver_version=job.get("solver_version"),
        created_at=job["created_at"],
        completed_at=job.get("completed_at"),
        result_artifact_paths=job.get("result_artifact_paths", []),
        missing_fields=job.get("missing_fields", []),
        limitations=job["limitations"],
        disclaimer=job["disclaimer"],
        message=job["message"],
    )


async def _load_job(
    analysis_id: str,
    database_session: AsyncSession | None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    found = await locate_analysis_job(analysis_id, database_session)
    if found is None:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    session_id, state = found
    job = next(
        (
            item
            for item in state.get("analysis_jobs", [])
            if item.get("analysis_id") == analysis_id
        ),
        None,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return session_id, state, job


def _validate_cfd_files(inputs: dict[str, Any], analysis_id: str) -> None:
    files = inputs.get("solver_case_inputs")
    if not isinstance(files, dict):
        return
    root = _analysis_directory("validation-session", analysis_id)
    for relative, contents in files.items():
        if not isinstance(relative, str) or not isinstance(contents, str):
            raise HTTPException(
                status_code=422,
                detail="solver_case_inputs must map relative file paths to text content.",
            )
        try:
            _safe_case_path(root, relative)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(contents.encode("utf-8")) > 5_000_000:
            raise HTTPException(
                status_code=422,
                detail=f"OpenFOAM input file {relative!r} exceeds the 5 MB size limit.",
            )


@router.post("/create", response_model=AnalysisJobResponse, status_code=201)
async def create_analysis(
    request: AnalysisCreateRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> AnalysisJobResponse:
    state = await get_workflow_state(request.session_id, database_session)
    if state is None or not state.get("design_result"):
        raise HTTPException(
            status_code=409,
            detail="Generate design alternatives before requesting analysis.",
        )
    selected = next(
        (
            alternative
            for alternative in state["design_result"].get("alternatives", [])
            if alternative.get("id") == request.design_id
        ),
        None,
    )
    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=f"Design {request.design_id!r} is not part of the generated alternatives.",
        )

    analysis_id = uuid4().hex
    analysis_type = request.analysis_type.value
    missing = missing_analysis_inputs(analysis_type, request.inputs)
    if analysis_type == AnalysisType.CFD.value:
        _validate_cfd_files(request.inputs, analysis_id)
    limitations = (
        STRUCTURAL_LIMITATIONS
        if analysis_type == AnalysisType.STRUCTURAL.value
        else CFD_LIMITATIONS
    )
    status = AnalysisStatus.BLOCKED.value if missing else AnalysisStatus.DRAFT.value
    snapshot = {
        "analysis_type": analysis_type,
        "design": selected,
        "inputs": request.inputs,
    }
    job = {
        "analysis_id": analysis_id,
        "session_id": request.session_id,
        "design_id": request.design_id,
        "analysis_type": analysis_type,
        "status": status,
        "input_snapshot": snapshot,
        "solver_name": None,
        "solver_version": None,
        "created_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "result_artifact_paths": [],
        "missing_fields": missing,
        "limitations": list(limitations),
        "disclaimer": ANALYSIS_DISCLAIMER,
        "message": (
            "Required analysis inputs are missing. No solver was run."
            if missing
            else "Analysis job created as a draft. Explicitly request execution to run a solver."
        ),
        "solver_stdout": None,
        "solver_stderr": None,
        "solver_output_summary": None,
    }
    updated = dict(state)
    jobs = list(updated.get("analysis_jobs", []))
    jobs.append(job)
    updated["analysis_jobs"] = jobs
    remember_analysis_session(analysis_id, request.session_id)
    await save_workflow_state(request.session_id, updated, database_session)
    return _response(job)


@router.get("/{analysis_id}", response_model=AnalysisJobResponse)
async def get_analysis(
    analysis_id: str,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> AnalysisJobResponse:
    _, _, job = await _load_job(analysis_id, database_session)
    return _response(job)


@router.get("/{analysis_id}/results", response_model=AnalysisResultsResponse)
async def get_analysis_results(
    analysis_id: str,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> AnalysisResultsResponse:
    session_id, _, job = await _load_job(analysis_id, database_session)
    stdout = job.get("solver_stdout")
    stderr = job.get("solver_stderr")
    if job["status"] not in {
        AnalysisStatus.COMPLETED.value,
        AnalysisStatus.FAILED.value,
    }:
        stdout = stderr = None
    work_directory = _analysis_directory(session_id, analysis_id)
    available_paths: list[str] = []
    for artifact_path in job.get("result_artifact_paths", []):
        candidate = (PROJECT_ROOT / Path(artifact_path)).resolve()
        if (
            work_directory in candidate.parents
            and candidate.is_file()
            and candidate.stat().st_size > 0
        ):
            available_paths.append(artifact_path)
    return AnalysisResultsResponse(
        analysis_id=analysis_id,
        status=job["status"],
        result_artifact_paths=available_paths,
        solver_stdout=stdout,
        solver_stderr=stderr,
        solver_output_summary=job.get("solver_output_summary"),
        limitations=job["limitations"],
        disclaimer=job["disclaimer"],
    )


@router.post("/{analysis_id}/run", response_model=AnalysisJobResponse)
async def run_analysis(
    analysis_id: str,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> AnalysisJobResponse:
    session_id, state, job = await _load_job(analysis_id, database_session)
    if job["status"] == AnalysisStatus.BLOCKED.value:
        return _response(job)
    if job["status"] in {
        AnalysisStatus.COMPLETED.value,
        AnalysisStatus.FAILED.value,
    }:
        raise HTTPException(status_code=409, detail="This analysis job has already run.")
    if job["status"] not in {AnalysisStatus.DRAFT.value, AnalysisStatus.QUEUED.value}:
        raise HTTPException(status_code=409, detail=f"Cannot run job in state {job['status']}.")

    inputs = job["input_snapshot"]["inputs"]
    missing = missing_analysis_inputs(job["analysis_type"], inputs)
    if missing:
        job["status"] = AnalysisStatus.BLOCKED.value
        job["missing_fields"] = missing
        job["message"] = "Required analysis inputs are missing. No solver was run."
        await save_workflow_state(session_id, state, database_session)
        return _response(job)

    job["status"] = AnalysisStatus.RUNNING.value
    job["message"] = "The explicitly requested solver process is running."
    await save_workflow_state(session_id, state, database_session)
    work_directory = _analysis_directory(session_id, analysis_id)
    if job["analysis_type"] == AnalysisType.STRUCTURAL.value:
        result = await run_in_threadpool(
            execute_structural_solver,
            inputs,
            work_directory,
        )
    else:
        result = await run_in_threadpool(
            execute_cfd_solver,
            inputs,
            work_directory,
        )

    artifact_paths: list[str] = []
    for raw_path in result.get("artifact_paths", []):
        path = Path(raw_path).resolve()
        if (
            work_directory.resolve() in path.parents
            and path.is_file()
            and path.stat().st_size > 0
        ):
            artifact_paths.append(
                path.relative_to(PROJECT_ROOT.resolve()).as_posix()
            )
    job["status"] = result["status"]
    job["solver_name"] = result["solver_name"]
    job["solver_version"] = result["solver_version"]
    job["result_artifact_paths"] = artifact_paths
    job["solver_stdout"] = result["stdout"]
    job["solver_stderr"] = result["stderr"]
    stdout_lines = [
        line.strip()
        for line in (result["stdout"] or "").splitlines()
        if line.strip()
    ]
    job["solver_output_summary"] = (
        stdout_lines[-1] if stdout_lines else None
    )
    job["completed_at"] = datetime.now(UTC).isoformat()
    job["missing_fields"] = []
    job["message"] = result["message"]
    await save_workflow_state(session_id, state, database_session)
    return _response(job)

"""CAD and Markdown report export endpoints for generated designs."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db_session
from api.schemas import (
    CadGenerationResponse,
    DesignArtifactRequest,
    PreviewGenerationResponse,
    ReportGenerationResponse,
    ReportGetResponse,
)
from api.session_store import get_workflow_state, save_workflow_state
from core.cad_generator import generate_reference_product_stl
from core.data_loader import PROJECT_ROOT
from core.models import EngineeringBrief
from core.preview_generator import generate_stl_preview
from core.product_registry import (
    generate_product_report,
    get_product_family,
)
from core.requirements import ProductType
from core.report_generator import generate_engineering_report

router = APIRouter(prefix="/api/design", tags=["design exports"])
_SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
logger = logging.getLogger(__name__)


def _export_directory(session_id: str) -> Path:
    if not _SAFE_SESSION_ID.fullmatch(session_id):
        raise HTTPException(
            status_code=400,
            detail="session_id must contain only letters, digits, underscores, or hyphens.",
        )
    export_root = (PROJECT_ROOT / "exports").resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    directory = export_root / session_id
    directory.mkdir(parents=True, exist_ok=True)
    resolved_directory = directory.resolve()
    if resolved_directory.parent != export_root:
        raise HTTPException(status_code=400, detail="Invalid export directory.")
    return resolved_directory


async def _get_generated_design(
    session_id: str,
    design_id: str,
    database_session: AsyncSession | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stored = await get_workflow_state(session_id, database_session)
    if stored is None:
        raise HTTPException(status_code=404, detail="Brief session not found.")
    generated = stored.get("design_result")
    if generated is None:
        raise HTTPException(
            status_code=409,
            detail="Generate design alternatives before creating CAD or reports.",
        )
    selected = next(
        (alternative for alternative in generated.get("alternatives", [])
         if alternative.get("id") == design_id),
        None,
    )
    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=f"Design {design_id!r} is not part of the generated alternatives.",
        )
    return stored, generated


@router.post("/{design_id}/cad", response_model=CadGenerationResponse)
async def generate_cad(
    design_id: str,
    request: DesignArtifactRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> CadGenerationResponse:
    return await _generate_cad(design_id, request, database_session)


async def _generate_cad(
    design_id: str,
    request: DesignArtifactRequest,
    database_session: AsyncSession | None,
) -> CadGenerationResponse:
    stored, generated = await _get_generated_design(
        request.session_id, design_id, database_session
    )
    selected = next(
        alternative
        for alternative in generated["alternatives"]
        if alternative["id"] == design_id
    )
    output_path = (
        _export_directory(request.session_id)
        / f"{design_id}_reference_concept.stl"
    )
    product_type = stored.get("product_type", ProductType.SERVO_DRIVEN_GRIPPER.value)
    result = generate_reference_product_stl(selected, output_path, product_type)
    artifact_path = result["artifact_path"]
    relative_path = (
        Path(str(artifact_path)).resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        if artifact_path and Path(str(artifact_path)).is_file()
        else None
    )
    artifact = {
        "design_id": design_id,
        "status": result["status"],
        "artifact_path": relative_path,
        "message": str(result["message"]),
    }
    updated = dict(stored)
    cad_artifacts = [
        item for item in updated.get("cad_artifacts", [])
        if item.get("design_id") != design_id
    ]
    cad_artifacts.append(artifact)
    updated["cad_artifacts"] = cad_artifacts
    await save_workflow_state(request.session_id, updated, database_session)
    return CadGenerationResponse(
        session_id=request.session_id,
        design_id=design_id,
        status=result["status"],
        artifact_path=relative_path,
        message=str(result["message"]),
    )


@router.get("/{design_id}/cad")
async def download_cad(
    design_id: str,
    session_id: str = Query(min_length=1),
    database_session: AsyncSession | None = Depends(get_db_session),
) -> FileResponse:
    stored, _ = await _get_generated_design(session_id, design_id, database_session)
    cad_artifact = next(
        (
            artifact
            for artifact in stored.get("cad_artifacts", [])
            if artifact.get("design_id") == design_id
        ),
        None,
    )
    if not cad_artifact or not cad_artifact.get("artifact_path"):
        raise HTTPException(
            status_code=404,
            detail="No STL artifact has been generated for this design.",
        )

    output_path = _export_directory(session_id) / f"{design_id}_reference_concept.stl"
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise HTTPException(
            status_code=404,
            detail="The previously generated STL file is no longer available.",
        )
    expected_path = output_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    if cad_artifact["artifact_path"] != expected_path:
        raise HTTPException(status_code=404, detail="The STL artifact path is invalid.")
    return FileResponse(
        output_path,
        media_type="model/stl",
        filename=output_path.name,
    )


@router.post("/{design_id}/preview", response_model=PreviewGenerationResponse)
async def generate_preview(
    design_id: str,
    request: DesignArtifactRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> PreviewGenerationResponse:
    stored, _ = await _get_generated_design(
        request.session_id, design_id, database_session
    )
    cad_artifact = next(
        (
            artifact
            for artifact in stored.get("cad_artifacts", [])
            if artifact.get("design_id") == design_id
        ),
        None,
    )
    result: dict[str, Any]
    if not cad_artifact or cad_artifact.get("status") != "CREATED":
        result = {
            "status": "BLOCKED",
            "artifact_path": None,
            "file_size_bytes": None,
            "width_px": None,
            "height_px": None,
            "message": (
                "No successfully generated STL is recorded for this design. "
                "Generate CAD before requesting a preview."
            ),
        }
    else:
        artifact_path = cad_artifact.get("artifact_path")
        relative_stl = Path(str(artifact_path)) if artifact_path else None
        export_directory = _export_directory(request.session_id)
        stl_path = (
            (PROJECT_ROOT / relative_stl).resolve()
            if relative_stl is not None and not relative_stl.is_absolute()
            else None
        )
        if (
            relative_stl is None
            or ".." in relative_stl.parts
            or relative_stl.parent != Path("exports") / request.session_id
            or stl_path is None
            or stl_path.parent != export_directory
            or stl_path.suffix.casefold() != ".stl"
            or not stl_path.is_file()
            or stl_path.stat().st_size == 0
        ):
            result = {
                "status": "BLOCKED",
                "artifact_path": None,
                "file_size_bytes": None,
                "width_px": None,
                "height_px": None,
                "message": (
                    "The recorded STL is missing, empty, or outside this session's "
                    "export directory. No preview was created."
                ),
            }
        else:
            output_path = export_directory / f"{stl_path.stem}_preview.png"
            result = generate_stl_preview(stl_path, output_path)

    preview_path = result["artifact_path"]
    relative_preview = None
    if preview_path:
        candidate_path = Path(str(preview_path)).resolve()
        expected_path = (
            export_directory
            / f"{Path(str(cad_artifact.get('artifact_path', ''))).stem}_preview.png"
            if cad_artifact and cad_artifact.get("artifact_path")
            else None
        )
        if (
            expected_path is not None
            and candidate_path == expected_path.resolve()
            and candidate_path.parent == export_directory
            and candidate_path.suffix.casefold() == ".png"
            and candidate_path.is_file()
            and candidate_path.stat().st_size > 0
        ):
            relative_preview = candidate_path.relative_to(
                PROJECT_ROOT.resolve()
            ).as_posix()
    if relative_preview is None and result["status"] == "CREATED":
        result = {
            "status": "BLOCKED",
            "artifact_path": None,
            "file_size_bytes": None,
            "width_px": None,
            "height_px": None,
            "message": "The preview renderer did not leave a usable PNG artifact.",
        }

    updated = dict(stored)
    preview_artifacts = [
        artifact
        for artifact in updated.get("preview_artifacts", [])
        if artifact.get("design_id") != design_id
    ]
    preview_artifacts.append(
        {
            "design_id": design_id,
            "status": result["status"],
            "artifact_path": relative_preview,
            "file_size_bytes": result["file_size_bytes"] if relative_preview else None,
            "width_px": result["width_px"] if relative_preview else None,
            "height_px": result["height_px"] if relative_preview else None,
            "message": result["message"],
        }
    )
    updated["preview_artifacts"] = preview_artifacts
    await save_workflow_state(request.session_id, updated, database_session)
    return PreviewGenerationResponse(
        session_id=request.session_id,
        design_id=design_id,
        status=result["status"],
        artifact_path=relative_preview,
        file_size_bytes=result["file_size_bytes"] if relative_preview else None,
        width_px=result["width_px"] if relative_preview else None,
        height_px=result["height_px"] if relative_preview else None,
        message=result["message"],
    )


@router.post("/{design_id}/report", response_model=ReportGenerationResponse)
async def generate_report(
    design_id: str,
    request: DesignArtifactRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> ReportGenerationResponse:
    stored, generated = await _get_generated_design(
        request.session_id, design_id, database_session
    )
    confirmed_brief = stored.get("confirmed_brief")
    if confirmed_brief is None:
        raise HTTPException(
            status_code=409,
            detail="Confirm an Engineering Brief before creating a report.",
        )
    try:
        product_type = stored.get(
            "product_type", ProductType.SERVO_DRIVEN_GRIPPER.value
        )
        if product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
            markdown = generate_engineering_report(
                EngineeringBrief.model_validate(confirmed_brief),
                generated,
                design_id,
            )
        else:
            markdown = generate_product_report(product_type, confirmed_brief, generated)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    output_directory = _export_directory(request.session_id)
    output_path = output_directory / f"{design_id}_engineering_report.md"
    temporary_path = output_path.with_suffix(".md.tmp")
    try:
        temporary_path.write_text(markdown, encoding="utf-8")
        temporary_path.replace(output_path)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise OSError("The report write completed without a non-empty output file.")
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove incomplete report file %s", temporary_path)
        raise HTTPException(
            status_code=500,
            detail=f"Could not write the engineering report: {exc}",
        ) from exc

    relative_path = output_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    updated = dict(stored)
    updated["report_artifact"] = {
        "design_id": design_id,
        "artifact_path": relative_path,
    }
    updated["report_artifact"]["status"] = "CREATED"
    updated["report_artifact"]["report_markdown"] = markdown
    await save_workflow_state(request.session_id, updated, database_session)
    return ReportGenerationResponse(
        session_id=request.session_id,
        design_id=design_id,
        status="CREATED",
        artifact_path=relative_path,
        report_markdown=markdown,
    )


@router.get("/{design_id}/report", response_model=ReportGetResponse)
async def get_report(
    design_id: str,
    session_id: str = Query(min_length=1),
    database_session: AsyncSession | None = Depends(get_db_session),
) -> ReportGetResponse:
    stored, _ = await _get_generated_design(session_id, design_id, database_session)
    report_artifact = stored.get("report_artifact")
    if not report_artifact or report_artifact.get("design_id") != design_id:
        raise HTTPException(
            status_code=404,
            detail="No engineering report has been generated for this design.",
        )

    output_directory = _export_directory(session_id)
    output_path = output_directory / f"{design_id}_engineering_report.md"
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise HTTPException(
            status_code=404,
            detail="The previously generated report file is no longer available.",
        )
    try:
        markdown = report_artifact.get("report_markdown") or output_path.read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read the engineering report: {exc}",
        ) from exc
    relative_path = output_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    return ReportGetResponse(
        session_id=session_id,
        design_id=design_id,
        artifact_path=relative_path,
        report_markdown=markdown,
    )

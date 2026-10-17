"""Pydantic request and response contracts for the ForgeX API."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from core.models import CalculationResult, DesignAlternative, EngineeringBrief
from core.requirements import EvidenceStatus, ProductType


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BriefStartRequest(ApiModel):
    session_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1)
    product_type: ProductType = ProductType.SERVO_DRIVEN_GRIPPER
    product_inputs: dict[str, Any] = Field(default_factory=dict)


class BriefClarifyRequest(ApiModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    product_inputs: dict[str, Any] = Field(default_factory=dict)


class BriefConfirmRequest(ApiModel):
    session_id: str = Field(min_length=1)
    confirmed_brief: dict[str, Any]


class MissingField(ApiModel):
    name: str
    label: str
    question: str


class BriefWorkflowResponse(ApiModel):
    session_id: str
    product_type: str = ProductType.SERVO_DRIVEN_GRIPPER.value
    phase: Literal["clarifying", "ready_to_confirm", "confirmed"]
    agent_message: str
    brief: dict[str, Any]
    missing_fields: list[MissingField]
    assumptions: list[str]
    next_action: Literal["clarify", "confirm", "generate_designs"]
    confirmed_brief: EngineeringBrief | None = None


class DesignGenerateRequest(ApiModel):
    session_id: str = Field(min_length=1)


class DesignEvidenceRow(ApiModel):
    alternative_id: str | None = None
    source: str
    statement: str
    status: EvidenceStatus
    result: float | bool | None = None
    unit: str | None = None


class DesignGenerateResponse(ApiModel):
    session_id: str
    alternatives: list[DesignAlternative] = Field(min_length=3, max_length=3)
    recommended_design_id: str | None
    calculations: list[CalculationResult]
    evidence_rows: list[DesignEvidenceRow]
    comparison_table: list[dict[str, Any]] = Field(min_length=3, max_length=3)
    status: Literal["READY", "REVIEW", "BLOCKED"]
    explanation: str
    missing_inputs: list[str]
    disclaimer: str | None = None
    catalog_cards: dict[str, Any] = Field(default_factory=dict)
    calculation_panel: dict[str, Any] = Field(default_factory=dict)


class DesignArtifactRequest(ApiModel):
    session_id: str = Field(min_length=1)


class AnalysisType(str, Enum):
    STRUCTURAL = "structural"
    CFD = "cfd"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class AnalysisCreateRequest(ApiModel):
    session_id: str = Field(min_length=1)
    design_id: str = Field(min_length=1)
    analysis_type: AnalysisType
    inputs: dict[str, Any] = Field(default_factory=dict)


class AnalysisJobResponse(ApiModel):
    analysis_id: str
    session_id: str
    design_id: str
    analysis_type: AnalysisType
    status: AnalysisStatus
    input_snapshot: dict[str, Any]
    solver_name: str | None = None
    solver_version: str | None = None
    created_at: str
    completed_at: str | None = None
    result_artifact_paths: list[str]
    missing_fields: list[str]
    limitations: list[str]
    disclaimer: str
    message: str


class AnalysisResultsResponse(ApiModel):
    analysis_id: str
    status: AnalysisStatus
    result_artifact_paths: list[str]
    solver_stdout: str | None = None
    solver_stderr: str | None = None
    solver_output_summary: str | None = None
    limitations: list[str]
    disclaimer: str


class CadGenerationResponse(ApiModel):
    session_id: str
    design_id: str
    status: Literal["CREATED", "BLOCKED"]
    artifact_path: str | None = None
    format: Literal["stl"] = "stl"
    message: str


class PreviewGenerationResponse(ApiModel):
    session_id: str
    design_id: str
    status: Literal["CREATED", "BLOCKED"]
    artifact_path: str | None = None
    format: Literal["png"] = "png"
    file_size_bytes: int | None = Field(default=None, ge=1)
    width_px: int | None = Field(default=None, ge=1)
    height_px: int | None = Field(default=None, ge=1)
    message: str


class ReportGenerationResponse(ApiModel):
    session_id: str
    design_id: str
    status: Literal["CREATED"]
    artifact_path: str
    report_markdown: Annotated[str, StringConstraints(strip_whitespace=False)]


class ReportGetResponse(ApiModel):
    session_id: str
    design_id: str
    artifact_path: str
    report_markdown: Annotated[str, StringConstraints(strip_whitespace=False)]


class DesignAskRequest(ApiModel):
    session_id: str = Field(min_length=1)
    question: str = Field(min_length=1)


class DesignAskResponse(ApiModel):
    session_id: str
    answer: str
    evidence: list[str]
    status: Literal["answered", "unavailable"]


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    engine_loaded: bool

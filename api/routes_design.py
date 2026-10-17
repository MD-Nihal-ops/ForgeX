"""Calculation-backed gripper design and evidence-grounded Q&A endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db_session
from api.schemas import (
    DesignAskRequest,
    DesignAskResponse,
    DesignGenerateRequest,
    DesignGenerateResponse,
)
from api.session_store import get_workflow_state, save_workflow_state
from core.design_engine import generate_gripper_designs
from core.models import CalculationResult, EngineeringBrief
from core.product_registry import (
    blocked_product_designs,
    generate_product_designs,
    get_product_family,
    missing_product_fields,
)
from core.requirements import ProductType

router = APIRouter(prefix="/api/design", tags=["design"])


@router.post("/generate", response_model=DesignGenerateResponse)
async def generate_designs(
    request: DesignGenerateRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> DesignGenerateResponse:
    stored = await get_workflow_state(request.session_id, database_session)
    if stored is None:
        raise HTTPException(status_code=404, detail="Brief session not found.")
    confirmed = stored.get("confirmed_brief")
    if confirmed is None:
        raise HTTPException(
            status_code=409,
            detail="Confirm an Engineering Brief before generating design alternatives.",
        )
    product_type = stored.get("product_type", ProductType.SERVO_DRIVEN_GRIPPER.value)
    try:
        if product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
            generated = generate_gripper_designs(EngineeringBrief.model_validate(confirmed))
        else:
            family = get_product_family(product_type)
            missing = missing_product_fields(
                product_type, dict(stored.get("product_inputs", {}))
            )
            generated = (
                blocked_product_designs(product_type, missing)
                if missing
                else generate_product_designs(
                    product_type, dict(stored.get("product_inputs", {}))
                )
            )
        response = DesignGenerateResponse(
            session_id=request.session_id,
            **generated,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    updated = dict(stored)
    updated["design_result"] = response.model_dump(mode="json")
    updated.pop("report_artifact", None)
    updated["cad_artifacts"] = []
    await save_workflow_state(request.session_id, updated, database_session)
    return response


def _generated_answer(
    request: DesignAskRequest,
    result: dict[str, Any],
) -> DesignAskResponse | None:
    question = request.question.casefold()
    calculations = [
        CalculationResult.model_validate(calculation)
        for calculation in result.get("calculations", [])
    ]
    alternatives = result.get("alternatives", [])
    evidence_rows = result.get("evidence_rows", [])
    matching_calculations = [
        calculation
        for calculation in calculations
        if any(
            term in question
            for term in (
                calculation.name.split("/")[-1].replace("_", " "),
                calculation.name.split("/")[-1],
                calculation.equation.split(":")[0].casefold(),
                *(
                    ("grip force", "grip force requirement")
                    if calculation.name.endswith("/required_grip_force")
                    else ()
                ),
                *(
                    ("servo torque", "required servo torque")
                    if calculation.name.endswith("/servo_torque_required")
                    else ()
                ),
            )
        )
    ]

    if any(term in question for term in ("recommend", "best", "pick", "winner")):
        recommended_id = result.get("recommended_design_id")
        if recommended_id is None:
            return DesignAskResponse(
                session_id=request.session_id,
                answer=(
                    f"No design is recommended. {result.get('explanation', '')}"
                ).strip(),
                evidence=[
                    row["source"]
                    for row in evidence_rows
                    if row.get("source", "").startswith("CMP-")
                ],
                status="unavailable",
            )
        selected = next(
            (
                alternative
                for alternative in alternatives
                if alternative["id"] == recommended_id
            ),
            None,
        )
        answer = (
            f"The calculated recommendation is {selected['name']} "
            f"({recommended_id}). {result.get('explanation', '')}"
            if selected
            else f"The recommended design id is {recommended_id}."
        )
        return DesignAskResponse(
            session_id=request.session_id,
            answer=answer,
            evidence=[
                row["source"]
                for row in evidence_rows
                if row.get("alternative_id") == recommended_id
            ],
            status="answered",
        )

    if matching_calculations:
        lines = [
            f"{calculation.name}: {calculation.output_value:g} {calculation.unit} "
            f"({calculation.equation}; {calculation.evidence_status.value})."
            for calculation in matching_calculations
        ]
        return DesignAskResponse(
            session_id=request.session_id,
            answer="Stored calculation results: " + " ".join(lines),
            evidence=[calculation.equation for calculation in matching_calculations],
            status="answered",
        )

    target_alternative = next(
        (
            alternative
            for alternative in alternatives
            if alternative["name"].casefold() in question
            or alternative["id"].casefold() in question
        ),
        None,
    )
    if target_alternative and any(
        term in question for term in ("parameter", "finger", "friction", "contact", "mount")
    ):
        values = target_alternative["key_parameters"]
        facts = [
            f"{key}={values[key]}"
            for key in (
                "finger_count",
                "finger_length_mm",
                "finger_width_mm",
                "finger_thickness_mm",
                "contact_area_mm2",
                "friction_coefficient",
                "material",
                "servo_mount_type",
            )
            if key in values
        ]
        sources = [
            row["source"]
            for row in evidence_rows
            if row.get("alternative_id") == target_alternative["id"]
            and row.get("source", "").startswith("template:")
        ]
        return DesignAskResponse(
            session_id=request.session_id,
            answer=(
                f"{target_alternative['name']} reference parameters: "
                + ", ".join(facts)
                + ". These are labeled template reference estimates, not optimized geometry."
            ),
            evidence=sources,
            status="answered",
        )

    if any(term in question for term in ("margin", "safety factor", "passes", "constraint")):
        matching_rows = [
            row
            for row in result.get("comparison_table", [])
            if any(term in question for term in (row["design_id"].casefold(), row["name"].casefold()))
        ]
        if matching_rows:
            return DesignAskResponse(
                session_id=request.session_id,
                answer="Calculated comparison: "
                + "; ".join(
                    f"{row['name']}: grip margin={row['grip_force_margin']}, "
                    f"servo torque margin={row['servo_torque_margin']}, "
                    f"safety factor={row['safety_factor']}, constraints_pass={row['constraints_pass']}"
                    for row in matching_rows
                ),
                evidence=[
                    row["source"]
                    for row in evidence_rows
                    if row.get("alternative_id") in {item["design_id"] for item in matching_rows}
                    and row.get("source", "").startswith("constraint:")
                ],
                status="answered",
            )
        if "comparison_table" in result:
            return DesignAskResponse(
                session_id=request.session_id,
                answer="Calculated comparison: "
                + "; ".join(
                    f"{row['name']}: score={row['recommendation_score']}, "
                    f"grip margin={row['grip_force_margin']}, "
                    f"torque margin={row['servo_torque_margin']}, "
                    f"safety factor={row['safety_factor']}, "
                    f"constraints_pass={row['constraints_pass']}"
                    for row in result["comparison_table"]
                ),
                evidence=[
                    row["source"]
                    for row in evidence_rows
                    if row.get("source", "").startswith("constraint:")
                ],
                status="answered",
            )
    return None


@router.post("/ask", response_model=DesignAskResponse)
async def ask_about_design(
    request: DesignAskRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> DesignAskResponse:
    stored = await get_workflow_state(request.session_id, database_session)
    if stored is None:
        raise HTTPException(status_code=404, detail="Brief session not found.")
    confirmed = stored.get("confirmed_brief")
    if confirmed is None:
        raise HTTPException(
            status_code=409,
            detail="Confirm an Engineering Brief before asking design questions.",
        )
    design_result = stored.get("design_result")
    product_type = stored.get("product_type", ProductType.SERVO_DRIVEN_GRIPPER.value)
    if product_type != ProductType.SERVO_DRIVEN_GRIPPER.value:
        question = request.question.casefold()
        if design_result:
            matched_rows = [
                row for row in design_result.get("comparison_table", [])
                if row.get("name", "").casefold() in question
                or row.get("design_id", "").casefold() in question
            ]
            if matched_rows:
                return DesignAskResponse(
                    session_id=request.session_id,
                    answer="Backend comparison values: "
                    + "; ".join(
                        ", ".join(
                            f"{key}={value}"
                            for key, value in row.items()
                            if key not in {"design_id", "name"} and value is not None
                        )
                        for row in matched_rows
                    ),
                    evidence=[
                        row["source"]
                        for row in design_result.get("evidence_rows", [])
                        if row.get("alternative_id") in {
                            item.get("design_id") for item in matched_rows
                        }
                    ],
                    status="answered",
                )
            if design_result.get("calculations") and any(
                word in question for word in ("calculation", "volume", "mass", "cost", "stress", "time", "safety")
            ):
                calculations = design_result["calculations"]
                return DesignAskResponse(
                    session_id=request.session_id,
                    answer="Stored deterministic calculations: "
                    + "; ".join(
                        f"{row['name']}={row['output_value']} {row['unit']}"
                        for row in calculations
                    ),
                    evidence=[row["equation"] for row in calculations],
                    status="answered",
                )
        if product_type == ProductType.CIVIL_CONCEPT_ASSISTANT.value:
            disclaimer = get_product_family(product_type).disclaimer
            return DesignAskResponse(
                session_id=request.session_id,
                answer=(
                    "ForgeX can provide only preliminary concept-level discussion. "
                    "It cannot determine final member sizes, approve safety, or provide "
                    f"construction documents. {disclaimer}"
                ),
                evidence=[],
                status="answered",
            )
        return DesignAskResponse(
            session_id=request.session_id,
            answer=(
                "The requested fact is not present in the confirmed brief or returned "
                "calculations. ForgeX will not invent an engineering result."
            ),
            evidence=[],
            status="unavailable",
        )
    if design_result:
        answer = _generated_answer(request, design_result)
        if answer is not None:
            return answer

    question = request.question.casefold()
    brief = EngineeringBrief.model_validate(confirmed)
    facts: list[str] = []
    evidence: list[str] = []
    if any(word in question for word in ("diameter", "dimension", "size", "envelope", "width")):
        facts.extend(
            f"{field}: {value:g} m"
            for field, value in brief.dimensions.model_dump(exclude_none=True).items()
            if field != "notes"
        )
        evidence.append("confirmed brief dimensions")
    if any(word in question for word in ("mass", "weight", "payload", "bottle", "load")):
        facts.extend(load.description for load in brief.load_conditions if load.description)
        facts.extend(
            f"force: {load.force_n:g} N"
            for load in brief.load_conditions
            if load.force_n is not None
        )
        evidence.append("confirmed brief load conditions")
    if any(word in question for word in ("safety", "factor")):
        facts.extend(constraint.statement for constraint in brief.safety_constraints)
        evidence.append("confirmed brief safety constraints")
    if not facts:
        return DesignAskResponse(
            session_id=request.session_id,
            answer=(
                "I cannot answer that from the confirmed brief or actual stored calculation "
                "results. Supporting evidence is unavailable, so I will not estimate or invent "
                "an answer."
            ),
            evidence=[],
            status="unavailable",
        )
    return DesignAskResponse(
        session_id=request.session_id,
        answer="According to the confirmed brief: " + " ".join(facts),
        evidence=evidence,
        status="answered",
    )

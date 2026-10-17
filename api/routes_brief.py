"""Brief conversation endpoints for registered ForgeX product families."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_db_session
from api.schemas import (
    BriefClarifyRequest,
    BriefConfirmRequest,
    BriefStartRequest,
    BriefWorkflowResponse,
)
from api.session_store import (
    create_workflow_session,
    get_workflow_state,
    save_workflow_state,
)
from core.brief_workflow import (
    clarify_brief_session,
    classify_product_type,
    confirm_brief,
    start_brief_session,
)
from core.models import EngineeringBrief
from core.product_registry import get_product_family, missing_product_fields, validate_product_inputs
from core.requirements import ProductType
from core.residential_concept import (
    extract_residential_inputs,
    residential_catalog_cards,
)

router = APIRouter(prefix="/api/brief", tags=["brief"])


def _response(session_id: str, state: dict[str, Any], message: str) -> BriefWorkflowResponse:
    phase = state["phase"]
    product_type = str(state.get("product_type", ProductType.SERVO_DRIVEN_GRIPPER.value))
    confirmed = state.get("confirmed_brief")
    if phase == "confirmed":
        brief_payload = confirmed or {}
    else:
        brief_payload = state.get("extraction", {})
    model_confirmed = None
    if phase == "confirmed" and product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
        model_confirmed = EngineeringBrief.model_validate(confirmed)
    return BriefWorkflowResponse(
        session_id=session_id,
        product_type=product_type,
        phase=phase,
        agent_message=message,
        brief=brief_payload,
        missing_fields=state.get("missing_fields", []) if phase != "confirmed" else [],
        assumptions=(
            confirmed.get("assumptions", [])
            if isinstance(confirmed, dict)
            else state.get("extraction", {}).get("assumptions", [])
        ),
        next_action=(
            "clarify"
            if phase == "clarifying"
            else "generate_designs"
            if phase == "confirmed"
            else "confirm"
        ),
        confirmed_brief=model_confirmed,
    )


@router.post("/start", response_model=BriefWorkflowResponse, status_code=status.HTTP_201_CREATED)
async def start_brief(
    request: BriefStartRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> BriefWorkflowResponse:
    inferred_product_type = classify_product_type(request.message)
    if "product_type" in request.model_fields_set:
        product_type = request.product_type.value
    elif inferred_product_type == ProductType.SIMPLE_HOUSE_MODEL:
        product_type = ProductType.RESIDENTIAL_BUILDING_CONCEPT.value
    else:
        product_type = (
            inferred_product_type.value
            if inferred_product_type is not None
            else request.product_type.value
        )
    session_id = await create_workflow_session(request.session_id, database_session)
    if product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
        result = start_brief_session(request.message)
        workflow_state = result["session_state"]
        workflow_state["product_type"] = product_type
        workflow_state["product_inputs"] = {}
        workflow_state["missing_fields"] = result["missing_fields"]
        message = result["assistant_message"]
    else:
        family = get_product_family(product_type)
        values = (
            extract_residential_inputs(request.message)
            if product_type == ProductType.RESIDENTIAL_BUILDING_CONCEPT.value
            else {}
        )
        values.update(request.product_inputs)
        if product_type == ProductType.CIVIL_CONCEPT_ASSISTANT.value:
            values.setdefault("question", request.message)
        missing = missing_product_fields(product_type, values)
        phase = "clarifying" if missing else "ready_to_confirm"
        workflow_state = {
            "product_type": product_type,
            "initial_message": request.message,
            "product_inputs": values,
            "extraction": {
                "product_type": product_type,
                "project_name": family.title,
                "purpose": request.message,
                "product_inputs": values,
                "disclaimer": family.disclaimer,
                **(
                    {"catalog_cards": residential_catalog_cards(str(values.get("material") or ""))}
                    if product_type == ProductType.RESIDENTIAL_BUILDING_CONCEPT.value
                    else {}
                ),
            },
            "missing_fields": missing,
            "phase": phase,
            "clarification_history": [],
        }
        message = (
            f"I understand you want to explore {family.title.lower()}. "
            + (
                "I still need: "
                + "; ".join(field["question"] for field in missing)
                if missing
                else "The provided inputs are ready for your review and confirmation."
            )
        )
    workflow_state.setdefault("clarification_history", []).extend(
        [
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": message},
        ]
    )
    await save_workflow_state(session_id, workflow_state, database_session)
    return _response(session_id, workflow_state, message)


@router.post("/clarify", response_model=BriefWorkflowResponse)
async def clarify_brief(
    request: BriefClarifyRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> BriefWorkflowResponse:
    stored = await get_workflow_state(request.session_id, database_session)
    if stored is None:
        raise HTTPException(status_code=404, detail="Brief session not found.")
    if stored.get("phase") == "confirmed":
        raise HTTPException(
            status_code=409,
            detail="This brief is already confirmed. Start a new brief session to revise it.",
        )
    product_type = stored.get("product_type", ProductType.SERVO_DRIVEN_GRIPPER.value)
    try:
        if product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
            result = clarify_brief_session(stored, request.message)
            workflow_state = result["session_state"]
            workflow_state["product_type"] = product_type
            workflow_state["product_inputs"] = stored.get("product_inputs", {})
            workflow_state["clarification_history"] = list(
                stored.get("clarification_history", [])
            )
            workflow_state["missing_fields"] = result["missing_fields"]
            message = result["assistant_message"]
        else:
            workflow_state = dict(stored)
            values = {
                **dict(stored.get("product_inputs", {})),
                **(
                    extract_residential_inputs(request.message)
                    if product_type == ProductType.RESIDENTIAL_BUILDING_CONCEPT.value
                    else {}
                ),
                **request.product_inputs,
            }
            workflow_state["product_inputs"] = values
            missing = missing_product_fields(product_type, values)
            workflow_state["missing_fields"] = missing
            workflow_state["phase"] = "clarifying" if missing else "ready_to_confirm"
            workflow_state["extraction"] = {
                **dict(stored.get("extraction", {})),
                "product_inputs": values,
                **(
                    {"catalog_cards": residential_catalog_cards(str(values.get("material") or ""))}
                    if product_type == ProductType.RESIDENTIAL_BUILDING_CONCEPT.value
                    else {}
                ),
            }
            message = (
                "I still need: " + "; ".join(field["question"] for field in missing)
                if missing
                else "The required values are present. Review and confirm the brief."
            )
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    workflow_state.setdefault("clarification_history", []).extend(
        [
            {"role": "user", "content": request.message},
            {"role": "assistant", "content": message},
        ]
    )
    await save_workflow_state(request.session_id, workflow_state, database_session)
    return _response(request.session_id, workflow_state, message)


@router.post("/confirm", response_model=BriefWorkflowResponse)
async def confirm_engineering_brief(
    request: BriefConfirmRequest,
    database_session: AsyncSession | None = Depends(get_db_session),
) -> BriefWorkflowResponse:
    stored = await get_workflow_state(request.session_id, database_session)
    if stored is None:
        raise HTTPException(status_code=404, detail="Brief session not found.")
    product_type = stored.get("product_type", ProductType.SERVO_DRIVEN_GRIPPER.value)
    if product_type == ProductType.SERVO_DRIVEN_GRIPPER.value:
        try:
            brief = EngineeringBrief.model_validate(request.confirmed_brief)
            result = confirm_brief(
                stored,
                {"confirmed_brief": brief.model_dump(mode="json")},
            )
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        workflow_state = result["session_state"]
        message = result["assistant_message"]
        workflow_state["product_type"] = product_type
        workflow_state["product_inputs"] = stored.get("product_inputs", {})
    else:
        if stored.get("phase") == "clarifying":
            raise HTTPException(
                status_code=409,
                detail="Provide all required product inputs before confirming this brief.",
            )
        confirmed = dict(request.confirmed_brief)
        values = confirmed.get("product_inputs", stored.get("product_inputs", {}))
        try:
            if product_type == ProductType.CIVIL_CONCEPT_ASSISTANT.value:
                validated_values = dict(values)
            else:
                validated_values = validate_product_inputs(product_type, values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        workflow_state = dict(stored)
        confirmed_payload = {
            "product_type": product_type,
            "project_name": str(confirmed.get("project_name") or stored.get("extraction", {}).get("project_name") or product_type),
            "purpose": str(confirmed.get("purpose") or stored.get("initial_message", "")),
            "product_inputs": validated_values,
            "disclaimer": get_product_family(product_type).disclaimer,
        }
        workflow_state["confirmed_brief"] = confirmed_payload
        workflow_state["product_inputs"] = validated_values
        workflow_state["phase"] = "confirmed"
        workflow_state["missing_fields"] = []
        workflow_state["design_result"] = None
        message = "Brief confirmed. " + get_product_family(product_type).disclaimer
    workflow_state["missing_fields"] = []
    workflow_state["design_result"] = None
    workflow_state["clarification_history"] = list(
        stored.get("clarification_history", [])
    )
    workflow_state["clarification_history"].append(
        {"role": "assistant", "content": message}
    )
    await save_workflow_state(request.session_id, workflow_state, database_session)
    return _response(request.session_id, workflow_state, message)

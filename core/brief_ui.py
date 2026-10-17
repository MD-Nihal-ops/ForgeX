"""Streamlit presentation for the backend-ready brief conversation."""

from __future__ import annotations

from typing import Any

import streamlit as st
from pydantic import ValidationError

from core.brief_extraction import BriefExtraction
from core.brief_workflow import (
    clarify_brief_session,
    confirm_brief,
    get_missing_fields,
    start_brief_session,
)
from core.models import EngineeringBrief
from core.requirements import ProductType

_SESSION_KEY = "forgex_brief_workflow"


def _show_engineering_brief(data: dict[str, Any]) -> None:
    brief = EngineeringBrief.model_validate(data)
    st.subheader("Confirmed Engineering Brief")
    st.markdown(f"**Project:** {brief.project_name}")
    st.markdown(f"**Product family:** {brief.product_type.value.replace('_', ' ').title()}")
    st.markdown(f"**Purpose:** {brief.purpose}")
    st.markdown("**Requirements**")
    for requirement in brief.performance_requirements:
        st.write(f"- {requirement.statement}")
    st.markdown("**Loads / payload**")
    for load in brief.load_conditions:
        details = load.description or load.direction or "No further details provided."
        if load.force_n is not None:
            details = f"{load.force_n:g} N; {details}"
        st.write(f"- {details}")
    st.markdown("**Envelope (m)**")
    st.write(brief.dimensions.model_dump(exclude_none=True))
    st.markdown(f"**Operating environment:** {brief.operating_environment}")
    if brief.safety_constraints:
        st.markdown("**Safety constraint (not certification)**")
        for constraint in brief.safety_constraints:
            st.write(f"- {constraint.statement}")
    if brief.assumptions:
        st.markdown("**Notes and assumptions to review**")
        for assumption in brief.assumptions:
            st.write(f"- {assumption}")
    with st.expander("Structured brief data"):
        st.json(brief.model_dump(mode="json"))


def _render_confirmation_form(workflow_state: dict[str, Any]) -> None:
    extraction = BriefExtraction.model_validate(workflow_state["extraction"])
    st.subheader("Review and confirm")
    st.caption(
        "The conversation has captured the critical inputs. Review these values; "
        "you can change them before saving."
    )

    dimensions = extraction.dimensions
    load = extraction.load_condition
    requirement = extraction.performance_requirement
    safety = extraction.safety_constraints[0] if extraction.safety_constraints else None
    product_options = {
        "Servo-driven gripper": ProductType.SERVO_DRIVEN_GRIPPER,
        "Structural bracket": ProductType.STRUCTURAL_BRACKET,
    }
    selected_product = next(
        label
        for label, value in product_options.items()
        if value == extraction.product_type
    )
    mass_g = (
        extraction.payload_mass_kg * 1000
        if extraction.payload_mass_kg is not None
        else None
    )
    component = ", ".join(extraction.component_preferences)

    with st.form("engineering_brief_confirmation"):
        project_name = st.text_input(
            "Project name",
            value=extraction.project_name or "",
        )
        product_label = st.selectbox(
            "Product family",
            list(product_options),
            index=list(product_options).index(selected_product),
        )
        purpose = st.text_area("Purpose", value=extraction.purpose or "", height=70)
        requirement_statement = st.text_input(
            "Engineering goal",
            value=requirement.statement if requirement else "",
        )
        diameter_mm = st.text_input(
            "Object diameter (mm)",
            value=(
                f"{dimensions.width_m * 1000:g}"
                if dimensions and dimensions.width_m is not None
                else ""
            ),
        )
        length_m = st.text_input(
            "Other envelope length (m, optional)",
            value=(
                f"{dimensions.length_m:g}"
                if dimensions and dimensions.length_m is not None
                else ""
            ),
        )
        height_m = st.text_input(
            "Other envelope height (m, optional)",
            value=(
                f"{dimensions.height_m:g}"
                if dimensions and dimensions.height_m is not None
                else ""
            ),
        )
        payload_mass_g = st.text_input(
            "Filled payload mass (g)",
            value=f"{mass_g:g}" if mass_g is not None else "",
        )
        load_description = st.text_area(
            "Load / payload description",
            value=load.description if load else "",
            height=60,
        )
        safety_factor = st.text_input(
            "Minimum safety factor",
            value=(
                f"{safety.min_safety_factor:g}"
                if safety and safety.min_safety_factor is not None
                else ""
            ),
        )
        operating_environment = st.text_input(
            "Operating environment",
            value=(
                extraction.operating_environment
                or "Not specified by user; confirm before engineering evaluation."
            ),
        )
        component_preference = st.text_input(
            "User-specified component preference (not compatibility-checked)",
            value=component,
        )
        assumptions = st.text_area(
            "Assumptions and notes",
            value="\n".join(extraction.assumptions),
            height=65,
        )
        submitted = st.form_submit_button("Confirm Engineering Brief")

    if not submitted:
        return

    confirmed_values: dict[str, Any] = {
        "project_name": project_name.strip(),
        "product_type": product_options[product_label],
        "purpose": purpose.strip(),
        "performance_requirements": [
            {
                "name": requirement.name if requirement else "user_stated_goal",
                "statement": requirement_statement.strip(),
                "quantity": requirement.quantity if requirement else None,
                "unit": requirement.unit if requirement else None,
                "comparator": requirement.comparator if requirement else "ge",
            }
        ],
        "payload_diameter_mm": diameter_mm.strip(),
        "length_m": length_m.strip(),
        "height_m": height_m.strip(),
        "payload_mass_g": payload_mass_g.strip(),
        "load_description": load_description.strip(),
        "minimum_safety_factor": safety_factor.strip(),
        "operating_environment": operating_environment.strip(),
        "assumptions": [
            item.strip() for item in assumptions.splitlines() if item.strip()
        ],
    }
    component_value = component_preference.strip()
    if component_value and component_value != component:
        confirmed_values["assumptions"].append(
            f"User-specified component preference: {component_value}; compatibility and "
            "catalog availability have not been checked."
        )
    try:
        result = confirm_brief(workflow_state, confirmed_values)
    except (ValidationError, ValueError) as exc:
        st.error(f"The Engineering Brief could not be confirmed: {exc}")
        return
    st.session_state[_SESSION_KEY] = result["session_state"]
    st.success(result["assistant_message"])


def render_brief_workflow() -> None:
    """Render chat first; show an editable confirmation form only when ready."""
    st.title("1 · Engineering Brief")
    st.caption(
        "Offline demo mode uses deterministic extraction and requires no API key. "
        "ForgeX never fills in missing engineering values."
    )
    st.caption(
        "Try: Design a 3D-printable gripper that holds a 500 ml bottle using an SG90 servo."
    )

    workflow_state = st.session_state.get(_SESSION_KEY)
    prompt = st.chat_input("Describe what you want to build", key="brief_conversation_input")
    if prompt:
        try:
            if not workflow_state or workflow_state.get("phase") == "confirmed":
                result = start_brief_session(prompt)
            else:
                result = clarify_brief_session(workflow_state, prompt)
        except (ValidationError, ValueError) as exc:
            st.error(f"I could not update the brief from that message: {exc}")
        else:
            workflow_state = result["session_state"]
            st.session_state[_SESSION_KEY] = workflow_state

    workflow_state = st.session_state.get(_SESSION_KEY)
    if not workflow_state:
        return

    for message in workflow_state.get("transcript", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if workflow_state.get("phase") == "confirmed":
        _show_engineering_brief(workflow_state["confirmed_brief"])
    elif workflow_state.get("phase") == "ready_to_confirm":
        _render_confirmation_form(workflow_state)
    else:
        questions = get_missing_fields(workflow_state)
        if questions:
            st.caption(
                "Still needed: " + " · ".join(item["label"] for item in questions)
            )

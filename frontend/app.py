"""Streamlit engineering workbench for the ForgeX FastAPI backend."""

from __future__ import annotations

import html
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

import streamlit as st

from api_client import DEFAULT_API_URL, ForgeXAPIClient, ForgeXAPIError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UNSPECIFIED_ENVIRONMENT = "Not specified by user; confirm before engineering evaluation."
STAGES = (
    "Describe Project",
    "Clarify Requirements",
    "Confirm Brief",
    "Review Designs",
    "Export Package",
)
DISCLAIMER = (
    "ForgeX outputs are engineering decision support and reference concepts. "
    "They are not optimized, validated, certified, or manufacturing-ready."
)
PRODUCT_OPTIONS = {
    "Servo-driven gripper": "servo_driven_gripper",
    "Electronics enclosure": "electronics_enclosure",
    "Mounting bracket": "mounting_bracket",
    "Simple house model": "simple_house_model",
    "Residential building concept": "residential_building_concept",
    "Civil concept assistant": "civil_concept_assistant",
}

st.set_page_config(
    page_title="ForgeX | Engineering Decision Support",
    page_icon="F",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _initialize_state() -> None:
    defaults = {
        "session_id_input": uuid.uuid4().hex,
        "product_type_input": "servo_driven_gripper",
        "api_url_input": os.getenv("FORGEX_API_URL", DEFAULT_API_URL),
        "active_session_id": None,
        "conversation": [],
        "messages": [],
        "brief_response": None,
        "confirmed_brief": None,
        "design_response": None,
        "selected_design_id": None,
        "report_response": None,
        "cad_response": None,
        "preview_response": None,
        "analysis_jobs": [],
        "selected_analysis_id": None,
        "api_health": None,
        "api_health_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if not st.session_state.messages and st.session_state.conversation:
        st.session_state.messages = list(st.session_state.conversation)


def _read_stylesheet() -> str:
    stylesheet = Path(__file__).resolve().parent / "styles.css"
    try:
        return stylesheet.read_text(encoding="utf-8")
    except OSError:
        return ""


def _status_badge(status: Any) -> str:
    label = str(status if status is not None else "Not returned")
    safe_label = html.escape(label)
    css_class = re.sub(r"[^a-z0-9_-]+", "-", label.casefold()).strip("-") or "unknown"
    return f'<span class="status-badge status-{css_class}">{safe_label}</span>'


def _show_api_error(error: ForgeXAPIError) -> None:
    if error.status_code == 422:
        st.error("The backend rejected one or more values. Review the validation details.")
        st.markdown("**422 validation details**")
        st.code(error.detail or str(error))
    elif error.status_code == 404:
        st.error("The requested session or design was not found.")
        st.markdown("**Backend response**")
        st.code(error.detail or str(error))
    elif error.status_code is None:
        st.error("ForgeX API could not be reached. Check the backend URL and network connection.")
        st.caption(str(error))
    else:
        st.error(str(error))
        if error.detail:
            st.code(error.detail)


def _api_client() -> ForgeXAPIClient:
    return ForgeXAPIClient(st.session_state.api_url_input)


def _clear_api_health() -> None:
    st.session_state.api_health = None
    st.session_state.api_health_error = None


def _reset_session() -> None:
    for key in (
        "active_session_id",
        "conversation",
        "messages",
        "brief_response",
        "confirmed_brief",
        "design_response",
        "selected_design_id",
        "report_response",
        "cad_response",
        "preview_response",
        "analysis_jobs",
        "selected_analysis_id",
        "api_health_error",
    ):
        st.session_state[key] = [] if key in {"conversation", "messages", "analysis_jobs"} else None
    st.session_state.session_id_input = uuid.uuid4().hex
    for key in ("initial_request", "clarification_input"):
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()


def _active_stage_index() -> int:
    if st.session_state.design_response is not None:
        if st.session_state.report_response or st.session_state.cad_response:
            return 4
        return 3
    if st.session_state.confirmed_brief is not None:
        return 3
    response = st.session_state.brief_response
    if response:
        if response.get("phase") == "ready_to_confirm":
            return 2
        if response.get("phase") == "confirmed":
            return 3
        return 1
    return 0


def _render_sidebar(client: ForgeXAPIClient) -> str:
    with st.sidebar:
        st.markdown(
            '<div class="brand-lockup"><div class="brand-mark">F</div>'
            '<div><div class="brand-title">ForgeX</div>'
            '<div class="brand-caption">ENGINEERING WORKBENCH</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown("#### Workspace connection")
        st.text_input(
            "FastAPI backend URL",
            key="api_url_input",
            on_change=_clear_api_health,
        )
        if st.button("Check connection", use_container_width=True, key="check_api"):
            try:
                st.session_state.api_health = client.get_health()
                st.session_state.api_health_error = None
            except ForgeXAPIError as error:
                st.session_state.api_health = None
                st.session_state.api_health_error = str(error)
                _show_api_error(error)

        health = st.session_state.api_health
        if health is None:
            st.markdown(
                '<div class="connection-state connection-unknown">'
                '<span class="connection-dot"></span>'
                f"{'Unavailable' if st.session_state.api_health_error else 'Not checked'}"
                "</div>",
                unsafe_allow_html=True,
            )
            if st.session_state.api_health_error:
                st.caption(st.session_state.api_health_error)
        elif health.get("status") == "ok" and health.get("engine_loaded") is True:
            st.markdown(
                '<div class="connection-state connection-online">'
                '<span class="connection-dot"></span>API online · engine loaded</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="connection-state connection-offline">'
                '<span class="connection-dot"></span>API degraded</div>',
                unsafe_allow_html=True,
            )

        st.markdown("#### Project session")
        st.text_input(
            "Session ID",
            key="session_id_input",
            help="This ID is used when starting a new API brief session.",
        )
        if st.session_state.active_session_id:
            st.caption(f"Active: `{st.session_state.active_session_id}`")
        st.button(
            "Reset session",
            use_container_width=True,
            on_click=_reset_session,
            key="reset_session",
        )

        st.markdown("#### Workflow")
        active = _active_stage_index()
        for index, label in enumerate(STAGES):
            if index < active:
                state, marker = "stage-complete", "✓"
            elif index == active:
                state, marker = "stage-current", f"{index + 1:02d}"
            else:
                state, marker = "stage-upcoming", f"{index + 1:02d}"
            st.markdown(
                f'<div class="workflow-stage {state}"><span class="stage-marker">'
                f"{marker}</span><span>{html.escape(label)}</span></div>",
                unsafe_allow_html=True,
            )
        st.markdown("---")
        st.caption(
            "Requests are made server-to-server from Streamlit to FastAPI. "
            "Browser CORS is not required."
        )
    return st.session_state.session_id_input.strip()


def _render_header(stage_index: int) -> None:
    st.markdown(
        '<div class="page-heading"><div class="eyebrow">ENGINEERING DECISION SUPPORT</div>'
        "<h1>ForgeX</h1>"
        '<div class="page-subtitle">Engineering Decision Support for 3D-Printable Designs</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.progress((stage_index + 1) / len(STAGES), text=f"Stage {stage_index + 1} of {len(STAGES)}")


def _render_disclaimer() -> None:
    st.markdown(
        f'<div class="engineering-disclaimer"><strong>Engineering use notice</strong>'
        f"<br>{html.escape(DISCLAIMER)}</div>",
        unsafe_allow_html=True,
    )


def _render_design_maturity(product_type: str) -> None:
    category = (
        "Preliminary advisory concept"
        if product_type == "civil_concept_assistant"
        else "Reference concept"
    )
    left, right = st.columns(2)
    with left:
        st.markdown(f"**ForgeX output category**  \n{category}")
        st.caption("Not a validated engineering design.")
    with right:
        st.markdown("**Certified / approved design**  \nNot provided by ForgeX.")
        st.caption("Qualified professional and regulatory review remain necessary.")


def _stage_heading(number: int, title: str, description: str) -> None:
    st.markdown(
        f'<div class="stage-heading"><span class="stage-number">{number:02d}</span>'
        f"<div><h2>{html.escape(title)}</h2><p>{html.escape(description)}</p></div></div>",
        unsafe_allow_html=True,
    )


def _product_input_controls(
    product_type: str,
    existing: dict[str, Any],
    prefix: str,
) -> dict[str, Any]:
    if product_type == "civil_concept_assistant":
        st.info(
            "Advisory questions only. No final member sizes, construction drawings, "
            "or safety approvals are produced."
        )
        return {"question": existing.get("question", "")}

    if product_type == "electronics_enclosure":
        fields = (
            ("internal_length_mm", "Internal length (mm)", "number"),
            ("internal_width_mm", "Internal width (mm)", "number"),
            ("internal_height_mm", "Internal height (mm)", "number"),
            ("wall_thickness_mm", "Wall thickness (mm)", "number"),
            ("lid_type", "Lid type", "lid"),
            ("cable_port_count", "Cable port count", "integer"),
            ("cable_port_diameter_mm", "Cable port diameter (mm)", "number"),
            ("material", "Material", "material"),
            ("minimum_wall_thickness_mm", "Minimum wall thickness (mm)", "number"),
        )
    elif product_type == "mounting_bracket":
        fields = (
            ("load_mass_kg", "Load mass (kg)", "number"),
            ("load_distance_mm", "Load distance from mounting surface (mm)", "number"),
            ("base_width_mm", "Base width (mm)", "number"),
            ("arm_length_mm", "Arm length (mm)", "number"),
            ("material", "Material", "material"),
            ("minimum_safety_factor", "Minimum safety factor", "number"),
            ("fastener_diameter_mm", "Fastener diameter (mm)", "number"),
        )
    elif product_type == "residential_building_concept":
        fields = (
            ("floor_area_m2", "Floor area (m²)", "number"),
            ("room_count", "Room count", "integer"),
            ("bedroom_count", "Bedroom count", "integer"),
            ("footprint_length_m", "Footprint length (m)", "number"),
            ("footprint_width_m", "Footprint width (m)", "number"),
            ("wall_height_m", "Wall height (m)", "number"),
            ("wall_thickness_m", "Wall thickness (m)", "number"),
            ("foundation_thickness_m", "Foundation thickness (m)", "number"),
            ("roof_pitch_degrees", "Roof pitch (degrees)", "number"),
            ("material", "Material", "house_material"),
            ("budget_amount", "Budget amount", "number"),
            ("budget_currency", "Budget currency", "currency"),
        )
    else:
        fields = (
            ("footprint_length_mm", "Footprint length (mm)", "number"),
            ("footprint_width_mm", "Footprint width (mm)", "number"),
            ("wall_height_mm", "Wall height (mm)", "number"),
            ("wall_thickness_mm", "Wall thickness (mm)", "number"),
            ("roof_pitch_degrees", "Roof pitch (degrees)", "number"),
            ("door_width_mm", "Door width (mm)", "number"),
            ("door_height_mm", "Door height (mm)", "number"),
            ("window_count", "Number of windows", "integer"),
            ("material", "Material", "material"),
            ("minimum_wall_thickness_mm", "Minimum wall thickness (mm)", "number"),
        )

    st.markdown("**Product-specific inputs**")
    columns = st.columns(2)
    values: dict[str, Any] = {}
    for index, (name, label, kind) in enumerate(fields):
        with columns[index % 2]:
            key = f"product_{prefix}_{product_type}_{name}"
            if kind == "lid":
                options = ["Select lid type", "snap-fit", "screw-mounted"]
                value = st.selectbox(
                    label,
                    options,
                    index=(
                        options.index(existing[name])
                        if existing.get(name) in {"snap-fit", "screw-mounted"}
                        else 0
                    ),
                    key=key,
                )
                if value != options[0]:
                    values[name] = value
            elif kind in {"material", "house_material"}:
                materials = (
                    ["Select material", "PLA", "PETG", "C25/30 Concrete", "Mortar"]
                    if kind == "house_material"
                    else ["Select material", "PLA", "PETG", "ABS", "Nylon"]
                )
                existing_material = existing.get(name)
                value = st.selectbox(
                    label,
                    materials,
                    index=(
                        materials.index(existing_material)
                        if existing_material in materials
                        else 0
                    ),
                    key=key,
                )
                if value != materials[0]:
                    values[name] = value
            elif kind == "currency":
                currencies = ["Select currency", "USD", "EUR"]
                value = st.selectbox(
                    label,
                    currencies,
                    index=(
                        currencies.index(existing[name])
                        if existing.get(name) in {"USD", "EUR"}
                        else 0
                    ),
                    key=key,
                )
                if value != currencies[0]:
                    values[name] = value
            elif kind == "integer":
                value = st.number_input(
                    label,
                    min_value=0,
                    step=1,
                    value=int(existing.get(name) or 0),
                    key=key,
                )
                if value > 0 or name in {"cable_port_count", "window_count"}:
                    values[name] = int(value)
            else:
                value = st.number_input(
                    label,
                    min_value=0.0,
                    step=1.0,
                    value=float(existing.get(name) or 0),
                    key=key,
                )
                if value > 0:
                    values[name] = float(value)
                elif (
                    name == "cable_port_diameter_mm"
                    and values.get("cable_port_count") == 0
                ):
                    values[name] = 0.0
    return values


def _render_start(client: ForgeXAPIClient, session_id: str) -> None:
    _stage_heading(
        1,
        "Describe Project",
        "Start with the intended function and any engineering details already known.",
    )
    with st.container(border=True):
        option_labels = list(PRODUCT_OPTIONS)
        selected_product = st.selectbox(
            "Product family",
            option_labels,
            index=list(PRODUCT_OPTIONS.values()).index(
                st.session_state.product_type_input
            ),
            key="product_family_selector",
        )
        product_type = PRODUCT_OPTIONS[selected_product]
        st.session_state.product_type_input = product_type
        request_text = st.text_area(
            "Project request",
            key="initial_request",
            placeholder="Describe the part or assembly you want ForgeX to evaluate.",
            height=180,
            label_visibility="collapsed",
        )
        st.caption(
            "Example: Design a 3D-printable gripper for a 500 ml bottle using an SG90 servo."
            if product_type == "servo_driven_gripper"
            else "Enter the goal, then provide any known product-specific values below. "
            "Unknown values remain missing; ForgeX will not fill them in."
        )
        product_inputs = _product_input_controls(product_type, {}, "setup")
        if st.button("Start Engineering Brief", type="primary", key="start_brief"):
            if not request_text.strip():
                st.warning("Enter a project request to start.")
                return
            if not session_id:
                st.warning("Enter a session ID in the sidebar.")
                return
            with st.spinner("Sending your request to ForgeX…"):
                try:
                    started = client.start_brief(
                        request_text.strip(),
                        session_id,
                        product_type=product_type,
                        product_inputs=(
                            product_inputs
                            if product_type != "servo_driven_gripper"
                            else None
                        ),
                    )
                except ForgeXAPIError as error:
                    _show_api_error(error)
                    return
            st.session_state.active_session_id = started["session_id"]
            st.session_state.product_type_input = product_type
            st.session_state.brief_response = started
            st.session_state.confirmed_brief = None
            st.session_state.design_response = None
            st.session_state.report_response = None
            st.session_state.cad_response = None
            st.session_state.preview_response = None
            st.session_state.analysis_jobs = []
            st.session_state.selected_analysis_id = None
            st.session_state.conversation = [
                {"role": "user", "content": request_text.strip()},
                {"role": "assistant", "content": started["agent_message"]},
            ]
            st.session_state.selected_design_id = None
            st.session_state.api_health = {"status": "ok", "engine_loaded": True}
            st.rerun()


def _render_clarification(client: ForgeXAPIClient, session_id: str) -> None:
    response = st.session_state.brief_response
    if response is None or response.get("phase") != "clarifying":
        return
    _stage_heading(
        2,
        "Clarify Requirements",
        "ForgeX asks for critical information it could not safely infer.",
    )
    conversation = st.container(border=True)
    with conversation:
        for message in st.session_state.conversation:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    missing = response.get("missing_fields", [])
    product_type = response.get("product_type", "servo_driven_gripper")
    if missing:
        st.markdown("**Open information requests**")
        question_columns = st.columns(min(3, len(missing)))
        for index, field in enumerate(missing):
            with question_columns[index % len(question_columns)]:
                st.markdown(
                    f'<div class="question-card"><div class="question-label">'
                    f"{html.escape(field.get('label', 'Information needed'))}</div>"
                    f"<div>{html.escape(field.get('question', ''))}</div></div>",
                    unsafe_allow_html=True,
                )
    with st.container(border=True):
        product_inputs = (
            _product_input_controls(
                product_type,
                (response.get("brief") or {}).get("product_inputs", {}),
                "clarify",
            )
            if product_type != "servo_driven_gripper"
            else None
        )
        clarification = st.text_area(
            "Your clarification",
            key="clarification_input",
            placeholder="For example: diameter 70 mm, filled weight 500 g, safety factor 2.",
            height=100,
        )
        if st.button("Send Clarification", type="primary", key="send_clarification"):
            if not clarification.strip():
                st.warning("Enter a clarification before sending.")
                return
            with st.spinner("Updating the engineering brief…"):
                try:
                    updated = client.clarify_brief(
                        session_id,
                        clarification.strip(),
                        product_inputs=product_inputs,
                    )
                except ForgeXAPIError as error:
                    _show_api_error(error)
                    return
            st.session_state.conversation.extend(
                [
                    {"role": "user", "content": clarification.strip()},
                    {"role": "assistant", "content": updated["agent_message"]},
                ]
            )
            st.session_state.brief_response = updated
            del st.session_state["clarification_input"]
            st.rerun()
    with st.expander("Inspect latest extracted brief", expanded=False):
        st.json(response.get("brief", {}))


def _build_confirmed_brief(
    extraction: dict[str, Any],
    *,
    project_name: str,
    product_type: str,
    purpose: str,
    performance_statement: str,
    diameter_mm: float,
    payload_mass_g: float,
    safety_factor: float,
    material_preference: str,
    operating_environment: str,
    assumptions_text: str,
) -> dict[str, Any]:
    """Map reviewed UI values to the existing EngineeringBrief API schema."""
    dimensions = dict(extraction.get("dimensions") or {})
    dimensions["width_m"] = diameter_mm / 1000
    if dimensions.get("notes") is None:
        dimensions["notes"] = f"User-confirmed object diameter: {diameter_mm:g} mm."

    load = extraction.get("load_condition") or {
        "name": "user_confirmed_payload",
        "force_n": None,
        "moment_nm": None,
        "direction": "vertical lift",
        "description": extraction.get("payload_description") or purpose,
    }
    load = dict(load)
    mass_kg = payload_mass_g / 1000
    mass_note = f"User-confirmed payload mass: {mass_kg:g} kg."
    prior_description = re.sub(
        r"\s*User-(?:stated|confirmed) payload mass: [\d.]+ kg\.?",
        "",
        str(load.get("description") or "").strip(),
    ).strip()
    load["description"] = f"{prior_description} {mass_note}".strip()

    performance = dict(
        extraction.get("performance_requirement")
        or {
            "name": "user_stated_goal",
            "statement": performance_statement,
            "quantity": None,
            "unit": None,
            "comparator": "ge",
        }
    )
    performance["statement"] = performance_statement

    source_assumptions = extraction.get("assumptions") or []
    reviewed_assumptions = [
        item.strip() for item in assumptions_text.splitlines() if item.strip()
    ]
    if operating_environment == UNSPECIFIED_ENVIRONMENT:
        marker = (
            "Operating environment was not provided; confirm it before engineering evaluation."
        )
        reviewed_assumptions = [item for item in reviewed_assumptions if item != marker]
        reviewed_assumptions.append(marker)

    return {
        "project_name": project_name.strip(),
        "product_type": product_type,
        "purpose": purpose.strip(),
        "performance_requirements": [performance],
        "load_conditions": [load],
        "dimensions": dimensions,
        "material_preference": material_preference.strip() or None,
        "manufacturing_method": "fdm_3d_print",
        "budget": extraction.get("budget"),
        "operating_environment": operating_environment.strip(),
        "safety_constraints": [
            {
                "name": "minimum_safety_factor",
                "statement": f"Minimum closed-form safety factor of {safety_factor:g}.",
                "min_safety_factor": safety_factor,
            }
        ],
        "assumptions": list(dict.fromkeys([*source_assumptions, *reviewed_assumptions])),
    }


def _render_brief_section(title: str, data: Any) -> None:
    with st.expander(title, expanded=False):
        if data:
            st.json(data)
        else:
            st.caption("No values were returned for this section.")


def _confirm_brief(client: ForgeXAPIClient, session_id: str) -> None:
    response = st.session_state.brief_response
    if response is None:
        return
    if response.get("phase") == "confirmed":
        product_type = response.get("product_type", "servo_driven_gripper")
        brief = (
            response.get("confirmed_brief")
            or response.get("brief")
            or st.session_state.confirmed_brief
        )
        if not brief:
            st.warning("The API marked this brief confirmed but returned no confirmed brief.")
            return
        _stage_heading(
            3,
            "Confirm Brief",
            "The API-confirmed brief is the source of inputs for design generation.",
        )
        with st.container(border=True):
            if product_type != "servo_driven_gripper":
                st.markdown(f"**Product family**  \n{product_type}")
                st.markdown(f"**Project**  \n{brief.get('project_name', 'Not returned')}")
                st.markdown(f"**Purpose**  \n{brief.get('purpose', 'Not returned')}")
                _render_brief_section(
                    "Confirmed product inputs", brief.get("product_inputs")
                )
                st.warning(brief.get("disclaimer", DISCLAIMER))
                if product_type == "civil_concept_assistant":
                    st.info(
                        "This is preliminary advisory content only—not a validated "
                        "engineering design or safety approval."
                    )
                else:
                    st.info(
                        "This is a reference concept—not a validated engineering design "
                        "or certified/approved design."
                    )
                _render_design_maturity(product_type)
            else:
                left, right = st.columns(2)
                with left:
                    st.markdown(f"**Project**  \n{brief.get('project_name', 'Not returned')}")
                    st.markdown(f"**Purpose**  \n{brief.get('purpose', 'Not returned')}")
                    _render_brief_section("Dimensions", brief.get("dimensions"))
                    _render_brief_section("Load conditions", brief.get("load_conditions"))
                with right:
                    st.markdown(f"**Product type**  \n{brief.get('product_type', 'Not returned')}")
                    st.markdown(
                        f"**Material preference**  \n"
                        f"{brief.get('material_preference') or 'Not specified'}"
                    )
                    _render_brief_section("Safety constraints", brief.get("safety_constraints"))
                    _render_brief_section("Assumptions", brief.get("assumptions"))
            with st.expander("Full confirmed brief JSON"):
                st.json(brief)
        st.success("Brief confirmed by the backend.")
        return

    if response.get("phase") != "ready_to_confirm":
        return

    extraction = response.get("brief", {})
    _stage_heading(
        3,
        "Confirm Brief",
        "Review and correct the extracted values before sending the final brief to the backend.",
    )
    product_type = extraction.get("product_type")
    if product_type != "servo_driven_gripper":
        existing_inputs = dict(extraction.get("product_inputs") or {})
        with st.form(f"confirm_{product_type}_brief", border=True):
            project_name = st.text_input(
                "Project name",
                value=extraction.get("project_name") or product_type.replace("_", " ").title(),
            )
            purpose = st.text_area(
                "Purpose",
                value=extraction.get("purpose") or "",
                height=90,
            )
            product_inputs = _product_input_controls(
                product_type, existing_inputs, "confirm"
            )
            submitted = st.form_submit_button("Confirm Brief", type="primary")
        with st.expander("Review extracted product brief"):
            st.json(extraction)
        if not submitted:
            return
        confirmed_payload = {
            "product_type": product_type,
            "project_name": project_name,
            "purpose": purpose,
            "product_inputs": product_inputs,
        }
        try:
            confirmed = client.confirm_brief(session_id, confirmed_payload)
        except ForgeXAPIError as error:
            _show_api_error(error)
            with st.expander("Submitted brief payload"):
                st.json(confirmed_payload)
            return
        st.session_state.brief_response = confirmed
        st.session_state.confirmed_brief = confirmed.get("brief")
        st.session_state.design_response = None
        st.session_state.report_response = None
        st.session_state.cad_response = None
        st.session_state.preview_response = None
        st.session_state.analysis_jobs = []
        st.session_state.selected_analysis_id = None
        st.session_state.conversation.append(
            {"role": "assistant", "content": confirmed.get("agent_message", "Brief confirmed.")}
        )
        st.rerun()
        return

    dimensions = extraction.get("dimensions") or {}
    diameter_default = (
        float(dimensions["width_m"]) * 1000
        if dimensions.get("width_m") is not None
        else 0.0
    )
    mass_default = float(extraction.get("payload_mass_kg") or 0) * 1000
    constraints = extraction.get("safety_constraints") or []
    factor_default = (
        float(constraints[0]["min_safety_factor"]) if constraints else 1.0
    )
    assumptions_default = "\n".join(extraction.get("assumptions") or [])

    with st.form("confirm_engineering_brief", border=True):
        top_left, top_right = st.columns(2)
        with top_left:
            project_name = st.text_input(
                "Project name", value=extraction.get("project_name") or ""
            )
            purpose = st.text_area(
                "Purpose", value=extraction.get("purpose") or "", height=100
            )
            performance = extraction.get("performance_requirement") or {}
            performance_statement = st.text_input(
                "Performance requirement",
                value=performance.get("statement") or "",
            )
        with top_right:
            diameter_mm = st.number_input(
                "Object diameter (mm)",
                min_value=0.0,
                value=diameter_default,
                step=1.0,
            )
            payload_mass_g = st.number_input(
                "Filled payload mass (g)",
                min_value=0.0,
                value=mass_default,
                step=10.0,
            )
            safety_factor = st.number_input(
                "Minimum safety factor",
                min_value=1.0,
                value=factor_default,
                step=0.5,
            )
            material = st.text_input(
                "Material preference (optional)",
                value=extraction.get("material_preference") or "",
            )
            environment = st.text_input(
                "Operating environment",
                value=extraction.get("operating_environment") or UNSPECIFIED_ENVIRONMENT,
            )
        assumptions_text = st.text_area(
            "Assumptions and notes (one per line)",
            value=assumptions_default,
        )
        submitted = st.form_submit_button("Confirm Brief", type="primary")

    with st.expander("Review raw extracted values"):
        st.json(extraction)

    if not submitted:
        return
    if not all(
        (
            project_name.strip(),
            purpose.strip(),
            performance_statement.strip(),
            environment.strip(),
        )
    ):
        st.error("Project name, purpose, performance requirement, and environment are required.")
        return
    if diameter_mm <= 0 or payload_mass_g <= 0 or safety_factor < 1:
        st.error(
            "Provide a positive object diameter, filled payload mass, and safety factor of at least 1."
        )
        return
    confirmed_payload = _build_confirmed_brief(
        extraction,
        project_name=project_name,
        product_type=product_type or "servo_driven_gripper",
        purpose=purpose,
        performance_statement=performance_statement,
        diameter_mm=diameter_mm,
        payload_mass_g=payload_mass_g,
        safety_factor=safety_factor,
        material_preference=material,
        operating_environment=environment,
        assumptions_text=assumptions_text,
    )
    with st.spinner("Validating the brief with the ForgeX API…"):
        try:
            confirmed = client.confirm_brief(session_id, confirmed_payload)
        except ForgeXAPIError as error:
            _show_api_error(error)
            with st.expander("Submitted brief payload"):
                st.json(confirmed_payload)
            return
    st.session_state.brief_response = confirmed
    st.session_state.confirmed_brief = confirmed.get("confirmed_brief")
    st.session_state.design_response = None
    st.session_state.report_response = None
    st.session_state.cad_response = None
    st.session_state.preview_response = None
    st.session_state.analysis_jobs = []
    st.session_state.selected_analysis_id = None
    st.session_state.conversation.append(
        {"role": "assistant", "content": confirmed.get("agent_message", "Brief confirmed.")}
    )
    st.rerun()


def _metric_value(value: Any, unit: str = "") -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3g}{f' {unit}' if unit else ''}"
    return "Not available"


def _format_design_metric(alternative: dict[str, Any], metric: str) -> Any:
    parameters = alternative.get("key_parameters", {})
    return (parameters.get("calculated_metrics") or {}).get(metric)


def _render_design_card(alternative: dict[str, Any], recommended_id: str | None) -> None:
    design_id = alternative.get("id", "unknown")
    metrics = alternative.get("key_parameters", {}).get("calculated_metrics") or {}
    with st.container(border=True):
        st.markdown(f"### {alternative.get('name', design_id)}")
        st.markdown(_status_badge(alternative.get("status")), unsafe_allow_html=True)
        if design_id == recommended_id:
            st.markdown('<div class="recommendation-label">Backend recommendation</div>', unsafe_allow_html=True)
        st.caption(f"Design ID · `{design_id}`")
        st.write(alternative.get("description", "No description returned by the API."))

        if "required_grip_force_n" not in metrics:
            labels = {
                "estimated_volume_cm3": ("Estimated printed volume", "cm³"),
                "estimated_mass_kg": ("Estimated mass", "kg"),
                "estimated_material_cost_usd": ("Estimated material cost", "USD"),
                "estimated_print_time_hours": ("Estimated print time", "h"),
                "internal_volume_mm3": ("Internal volume", "mm³"),
                "wall_volume_mm3": ("Wall volume", "mm³"),
                "applied_load_n": ("Applied load", "N"),
                "bending_moment_nm": ("Bending moment", "N·m"),
                "reference_bending_stress_mpa": ("Reference bending stress", "MPa"),
                "safety_factor": ("Reference safety factor", ""),
            }
            display_metrics = [
                (labels[key][0], value, labels[key][1])
                for key, value in metrics.items()
                if key in labels
            ]
            display_metrics.extend(
                (
                    (key.replace("_", " ").title(), "PASS" if value else "FAIL", "")
                    for key, value in metrics.items()
                    if key.endswith("_pass") and isinstance(value, bool)
                )
            )
            for start in range(0, len(display_metrics), 2):
                metric_columns = st.columns(2)
                for column, item in zip(
                    metric_columns, display_metrics[start : start + 2]
                ):
                    label, value, unit = item
                    column.metric(label, _metric_value(value, unit))
            with st.expander("Reference parameters"):
                st.json(alternative.get("key_parameters", {}))
            return

        primary_a, primary_b = st.columns(2)
        primary_a.metric(
            "Required grip force",
            _metric_value(metrics.get("required_grip_force_n"), "N"),
        )
        primary_b.metric(
            "Required servo torque",
            _metric_value(metrics.get("required_servo_torque_nm"), "N·m"),
        )
        secondary_a, secondary_b = st.columns(2)
        secondary_a.metric("Safety factor", _metric_value(metrics.get("safety_factor")))
        secondary_b.metric(
            "Grip force margin",
            _metric_value(metrics.get("grip_force_margin")),
        )
        margin_a, margin_b = st.columns(2)
        margin_a.metric(
            "Servo torque margin",
            _metric_value(metrics.get("servo_torque_margin")),
        )
        constraints = metrics.get("constraints_pass")
        margin_b.metric(
            "Constraints",
            "PASS" if constraints is True else "FAIL" if constraints is False else "BLOCKED",
        )
        with st.expander("Key parameters and estimates"):
            st.json(alternative.get("key_parameters", {}))
            st.caption(
                f"Mass estimate: {_metric_value(alternative.get('estimated_mass_kg'), 'kg')} · "
                f"Cost estimate: {_metric_value(alternative.get('estimated_cost_usd'), 'USD')} · "
                f"Print-time estimate: "
                f"{_metric_value(alternative.get('estimated_print_time_hours'), 'h')}"
            )


def _render_design_review(client: ForgeXAPIClient, session_id: str) -> None:
    if st.session_state.confirmed_brief is None:
        return
    _stage_heading(
        4,
        "Review Designs",
        "Request deterministic alternatives and inspect their calculations and evidence.",
    )
    if st.button("Generate Designs", type="primary", key="generate_designs"):
        with st.spinner("Requesting design screening from the ForgeX API…"):
            try:
                result = client.generate_designs(session_id)
            except ForgeXAPIError as error:
                _show_api_error(error)
                return
        st.session_state.design_response = result
        st.session_state.selected_design_id = result.get("recommended_design_id")
        st.session_state.report_response = None
        st.session_state.cad_response = None
        st.session_state.preview_response = None
        st.session_state.analysis_jobs = []
        st.session_state.selected_analysis_id = None
        st.rerun()

    result = st.session_state.design_response
    if result is None:
        st.info("The confirmed brief is ready. Generate designs to review backend results.")
        return

    status = result.get("status", "Not returned")
    if result.get("disclaimer"):
        st.warning(result["disclaimer"])
    _render_design_maturity(
        str(
            (st.session_state.confirmed_brief or {}).get(
                "product_type", "servo_driven_gripper"
            )
        )
    )
    st.markdown(
        f'<div class="review-banner">{_status_badge(status)}'
        f'<span>{html.escape(str(result.get("explanation", "No explanation returned.")))}</span></div>',
        unsafe_allow_html=True,
    )
    recommendation = result.get("recommended_design_id")
    if recommendation:
        recommended = next(
            (item for item in result.get("alternatives", []) if item.get("id") == recommendation),
            None,
        )
        if recommended:
            st.markdown(
                f'<div class="recommended-panel"><div class="eyebrow">RECOMMENDED BY BACKEND</div>'
                f'<h2>{html.escape(str(recommended.get("name", recommendation)))}</h2>'
                f'<p>Design ID · <code>{html.escape(str(recommendation))}</code></p>'
                f"{_status_badge(recommended.get('status'))}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.info("No recommended design was returned by the backend.")
    if result.get("missing_inputs"):
        st.warning("Missing inputs: " + "; ".join(result["missing_inputs"]))

    alternatives = result.get("alternatives", [])
    if alternatives:
        card_columns = st.columns(3)
        for index, alternative in enumerate(alternatives):
            with card_columns[index % 3]:
                _render_design_card(alternative, recommendation)

    comparison, calculations, evidence, raw = st.tabs(
        ["Comparison", "Calculations", "Evidence Ledger", "Raw API response"]
    )
    with comparison:
        rows = result.get("comparison_table", [])
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("The backend returned no comparison rows.")
    with calculations:
        rows = result.get("calculations", [])
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("The backend returned no calculations.")
    with evidence:
        rows = result.get("evidence_rows", [])
        if rows:
            returned_statuses = sorted(
                {
                    str(row.get("evidence_status"))
                    for row in rows
                    if row.get("evidence_status") is not None
                }
            )
            if returned_statuses:
                st.markdown(
                    " ".join(_status_badge(status) for status in returned_statuses),
                    unsafe_allow_html=True,
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("The backend returned no evidence rows.")
    with raw:
        st.json(result)


def _validated_artifact_path(artifact_path: str, session_id: str, suffix: str) -> Path | None:
    if not artifact_path:
        return None
    relative = Path(artifact_path)
    expected_parent = Path("exports") / session_id
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parent != expected_parent
        or relative.suffix.casefold() != suffix
    ):
        return None
    return relative


def _local_artifact_path(artifact_path: str, session_id: str, suffix: str) -> Path | None:
    relative = _validated_artifact_path(artifact_path, session_id, suffix)
    if relative is None:
        return None
    resolved = (PROJECT_ROOT / relative).resolve()
    export_root = (PROJECT_ROOT / "exports" / session_id).resolve()
    if resolved.parent != export_root or not resolved.is_file() or resolved.stat().st_size <= 0:
        return None
    return resolved


def _local_analysis_path(artifact_path: str, session_id: str, analysis_id: str) -> Path | None:
    relative = Path(artifact_path)
    expected = Path("exports") / session_id / "analysis" / analysis_id
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:4] != expected.parts:
        return None
    resolved = (PROJECT_ROOT / relative).resolve()
    analysis_root = (PROJECT_ROOT / expected).resolve()
    if (
        analysis_root not in resolved.parents
        or not resolved.is_file()
        or resolved.stat().st_size <= 0
    ):
        return None
    return resolved


def _analysis_input_template(analysis_type: str) -> dict[str, Any]:
    if analysis_type == "structural":
        return {
            "material_properties": {
                "density_kg_m3": None,
                "youngs_modulus_mpa": None,
                "poisson_ratio": None,
                "yield_strength_mpa": None,
            },
            "loads": [
                {
                    "magnitude_n": None,
                    "direction": None,
                    "location": None,
                }
            ],
            "supports": [{"type": None, "location": None}],
            "mesh_reference_assumptions": {
                "element_type": None,
                "mesh_size_mm": None,
                "geometry_source": None,
            },
            "solver_input": "",
        }
    return {
        "fluid_domain": {},
        "boundary_conditions": [],
        "inlet_conditions": {},
        "outlet_conditions": {},
        "solver": "",
        "solver_case_inputs": {
            "system/controlDict": "",
            "system/fvSchemes": "",
            "system/fvSolution": "",
            "constant/polyMesh/points": "",
            "constant/polyMesh/faces": "",
            "constant/polyMesh/owner": "",
            "constant/polyMesh/neighbour": "",
            "constant/polyMesh/boundary": "",
            "0/U": "",
            "0/p": "",
        },
    }


def _render_analysis_tab(
    client: ForgeXAPIClient,
    session_id: str,
    design_id: str,
) -> None:
    st.markdown("### Optional solver analysis")
    st.warning(
        "Analysis is a separate, opt-in action. Design generation never starts a solver."
    )
    disclaimer = (
        "Analysis outputs are preliminary engineering decision support. They are not "
        "certification, code compliance, or a substitute for review by a qualified engineer."
    )
    st.markdown(
        f'<div class="engineering-disclaimer">{html.escape(disclaimer)}</div>',
        unsafe_allow_html=True,
    )

    setup_tab, jobs_tab = st.tabs(["Analysis", "Analysis jobs"])
    with setup_tab:
        choice = st.selectbox(
            "Analysis type",
            ["No analysis", "Structural analysis", "CFD analysis"],
            key=f"analysis_choice_{design_id}",
        )
        type_by_choice = {
            "Structural analysis": "structural",
            "CFD analysis": "cfd",
        }
        if choice == "No analysis":
            st.caption("No solver job will be created or run.")
        else:
            analysis_type = type_by_choice[choice]
            st.caption(
                "Provide solver-ready inputs. ForgeX does not generate a mesh, boundary "
                "conditions, solver deck, or CFD case for you."
            )
            template = _analysis_input_template(analysis_type)
            with st.form(f"analysis_create_form_{design_id}_{analysis_type}"):
                inputs_text = st.text_area(
                    "Solver inputs (JSON)",
                    value=json.dumps(template, indent=2),
                    height=330,
                    key=f"analysis_inputs_{design_id}_{analysis_type}",
                    help=(
                        "Structural load rows require magnitude_n, direction, and "
                        "location; support rows require type and location. Include a "
                        "CalculiX .inp solver_input. CFD jobs require OpenFOAM case "
                        "files as relative-path/text entries."
                    ),
                )
                create_job = st.form_submit_button(
                    "Create Analysis Job",
                    type="primary",
                    use_container_width=True,
                )
            if create_job:
                try:
                    inputs = json.loads(inputs_text)
                    if not isinstance(inputs, dict):
                        raise ValueError("Analysis inputs must be a JSON object.")
                except (json.JSONDecodeError, ValueError) as error:
                    st.error(f"Invalid analysis inputs: {error}")
                else:
                    with st.spinner("Creating an opt-in analysis job…"):
                        try:
                            job = client.create_analysis(
                                session_id,
                                design_id,
                                analysis_type,
                                inputs,
                            )
                        except ForgeXAPIError as error:
                            _show_api_error(error)
                        else:
                            jobs = [
                                item
                                for item in st.session_state.analysis_jobs
                                if item.get("analysis_id") != job["analysis_id"]
                            ]
                            jobs.append(job)
                            st.session_state.analysis_jobs = jobs
                            st.session_state.selected_analysis_id = job["analysis_id"]
                            st.rerun()

    with jobs_tab:
        jobs = [
            item
            for item in st.session_state.analysis_jobs
            if item.get("design_id") == design_id
        ]
        job_id = st.session_state.selected_analysis_id
        if jobs:
            job_ids = [item["analysis_id"] for item in jobs]
            if job_id not in job_ids:
                job_id = job_ids[-1]
            job_id = st.selectbox(
                "Analysis job",
                job_ids,
                index=job_ids.index(job_id),
                format_func=lambda ident: next(
                    f"{item['analysis_type']} · {item['status']} · {ident[:8]}"
                    for item in jobs
                    if item["analysis_id"] == ident
                ),
                key=f"analysis_job_selector_{design_id}",
            )
        else:
            job_id = st.text_input(
                "Analysis ID",
                value=job_id or "",
                key=f"analysis_id_lookup_{design_id}",
                help="Enter a previously created analysis ID to retrieve its status.",
            ).strip()
            if not job_id:
                st.info("Create an analysis job to view its status and results.")
                return

        try:
            job = client.get_analysis(job_id)
        except ForgeXAPIError as error:
            _show_api_error(error)
            return
        jobs = [item for item in st.session_state.analysis_jobs if item.get("analysis_id") != job_id]
        jobs.append(job)
        st.session_state.analysis_jobs = jobs
        st.session_state.selected_analysis_id = job_id

        st.markdown(f"**Status** · {_status_badge(job['status'])}", unsafe_allow_html=True)
        st.write(job.get("message", "No status message was returned."))
        if job.get("missing_fields"):
            st.error("Missing required inputs")
            st.write(job["missing_fields"])
        st.caption(
            f"Solver · {job.get('solver_name') or 'Not selected yet'}"
            + (f" · Version {job['solver_version']}" if job.get("solver_version") else "")
        )
        with st.expander("Input snapshot"):
            st.json(job.get("input_snapshot", {}))
        with st.expander("Limitations and disclaimer", expanded=True):
            for limitation in job.get("limitations", []):
                st.write(f"- {limitation}")
            st.info(job.get("disclaimer", disclaimer))

        if job.get("status") in {"DRAFT", "QUEUED"}:
            if st.button(
                "Run Solver (explicit opt-in)",
                type="primary",
                key=f"run_analysis_{job_id}",
            ):
                with st.spinner("Running the requested solver…"):
                    try:
                        updated_job = client.run_analysis(job_id)
                    except ForgeXAPIError as error:
                        _show_api_error(error)
                    else:
                        st.session_state.analysis_jobs = [
                            item
                            for item in st.session_state.analysis_jobs
                            if item.get("analysis_id") != job_id
                        ] + [updated_job]
                        st.rerun()
        if job.get("status") in {"COMPLETED", "FAILED"}:
            try:
                results = client.get_analysis_results(job_id)
            except ForgeXAPIError as error:
                _show_api_error(error)
                return
            st.markdown("#### Solver output")
            if results.get("solver_output_summary"):
                st.caption(
                    "Last non-empty stdout line returned by the solver: "
                    + results["solver_output_summary"]
                )
            if results.get("solver_stdout") is not None:
                with st.expander("Raw solver stdout"):
                    st.code(results["solver_stdout"])
            if results.get("solver_stderr") is not None:
                with st.expander("Raw solver stderr"):
                    st.code(results["solver_stderr"])
            paths = results.get("result_artifact_paths", [])
            if not paths:
                st.info("The API returned no solver result artifact paths.")
            for index, artifact_path in enumerate(paths):
                local_path = _local_analysis_path(
                    artifact_path,
                    session_id,
                    job_id,
                )
                if local_path is None:
                    st.warning(
                        f"Returned solver artifact is not accessible or non-empty: "
                        f"`{artifact_path}`"
                    )
                    continue
                st.caption(
                    f"Solver artifact · `{artifact_path}` · "
                    f"{local_path.stat().st_size:,} bytes"
                )
                st.download_button(
                    "Download solver artifact",
                    data=local_path.read_bytes(),
                    file_name=local_path.name,
                    mime="application/octet-stream",
                    key=f"download_analysis_{job_id}_{index}",
                )


def _render_export_package(client: ForgeXAPIClient, session_id: str) -> None:
    result = st.session_state.design_response
    if result is None:
        return
    _stage_heading(
        5,
        "Export Package",
        "Generate a report and optional reference CAD for one returned design.",
    )
    confirmed_brief = st.session_state.confirmed_brief or {}
    st.markdown(
        f'<div class="engineering-disclaimer">{html.escape(str(confirmed_brief.get("disclaimer", DISCLAIMER)))}</div>',
        unsafe_allow_html=True,
    )
    if confirmed_brief.get("product_type") == "civil_concept_assistant":
        st.info(
            "Preliminary advisory concepts are not validated engineering designs, "
            "construction documents, or safety approvals."
        )
    else:
        st.info(
            "Generated options are reference concepts, not validated or certified designs."
        )
    _render_design_maturity(
        str(confirmed_brief.get("product_type", "servo_driven_gripper"))
    )

    alternatives = result.get("alternatives", [])
    design_ids = [item["id"] for item in alternatives if item.get("id")]
    if not design_ids:
        st.warning("The API response contains no selectable design ID.")
        return
    current_id = st.session_state.selected_design_id
    selected_index = design_ids.index(current_id) if current_id in design_ids else 0
    selected_id = st.selectbox(
        "Generated design",
        design_ids,
        index=selected_index,
        format_func=lambda design_id: next(
            (
                f"{item.get('name', design_id)} · {design_id}"
                for item in alternatives
                if item.get("id") == design_id
            ),
            design_id,
        ),
    )
    st.session_state.selected_design_id = selected_id
    selected = next(item for item in alternatives if item.get("id") == selected_id)
    with st.container(border=True):
        selected_left, selected_right = st.columns([2, 1])
        with selected_left:
            st.markdown(f"### {selected.get('name', selected_id)}")
            st.caption(f"Design ID · `{selected_id}`")
            st.write(selected.get("description", "No description returned by the API."))
        with selected_right:
            st.markdown(_status_badge(selected.get("status")), unsafe_allow_html=True)
            if selected_id == result.get("recommended_design_id"):
                st.markdown("**Backend-recommended alternative**")

    report_col, cad_col = st.columns(2)
    with report_col:
        with st.container(border=True):
            st.markdown("### Engineering report")
            st.write("Create the traceable Markdown report from stored backend results.")
            if st.button(
                "Generate Engineering Report",
                type="primary",
                key="generate_report",
                use_container_width=True,
            ):
                with st.spinner("Generating report through the ForgeX API…"):
                    try:
                        generated = client.generate_report(session_id, selected_id)
                        report = client.get_report(session_id, selected_id)
                    except ForgeXAPIError as error:
                        _show_api_error(error)
                    else:
                        st.session_state.report_response = {
                            **report,
                            "status": generated.get("status"),
                        }
                        st.rerun()
    with cad_col:
        with st.container(border=True):
            st.markdown("### Reference CAD / STL")
            st.write("Request an optional reference concept model from the backend.")
            if st.button(
                "Generate Reference CAD / STL",
                key="generate_cad",
                use_container_width=True,
            ):
                with st.spinner("Requesting CAD generation through the ForgeX API…"):
                    try:
                        st.session_state.cad_response = client.generate_cad(
                            session_id,
                            selected_id,
                        )
                    except ForgeXAPIError as error:
                        _show_api_error(error)
                    else:
                        st.rerun()

    st.markdown("### Artifact status")
    artifact_col_a, artifact_col_b = st.columns(2)
    report = st.session_state.report_response
    with artifact_col_a:
        st.markdown("**Engineering report**")
        if report and report.get("design_id") == selected_id:
            artifact_path = report.get("artifact_path", "")
            valid_path = _validated_artifact_path(artifact_path, session_id, ".md")
            st.markdown(_status_badge(report.get("status")), unsafe_allow_html=True)
            if valid_path:
                st.caption(f"Artifact · `{artifact_path}`")
                local_path = _local_artifact_path(artifact_path, session_id, ".md")
                if local_path:
                    st.caption(f"File size · {local_path.stat().st_size:,} bytes")
                if report.get("report_markdown"):
                    st.download_button(
                        "Download Engineering Report",
                        data=report["report_markdown"].encode("utf-8"),
                        file_name=valid_path.name,
                        mime="text/markdown",
                        key=f"download_report_{selected_id}",
                        use_container_width=True,
                    )
                    with st.expander("Preview report"):
                        st.markdown(report["report_markdown"])
            else:
                st.warning("No valid report artifact path was returned; download is unavailable.")
        else:
            st.caption("No report has been generated for this design in this session.")

    cad = st.session_state.cad_response
    with artifact_col_b:
        st.markdown("**Reference CAD / STL**")
        if cad and cad.get("design_id") == selected_id:
            artifact_path = cad.get("artifact_path") or ""
            st.markdown(_status_badge(cad.get("status")), unsafe_allow_html=True)
            st.write(cad.get("message", "No generation message was returned."))
            valid_path = _validated_artifact_path(artifact_path, session_id, ".stl")
            if valid_path:
                st.caption(f"Artifact · `{artifact_path}`")
                local_path = _local_artifact_path(artifact_path, session_id, ".stl")
                if local_path:
                    st.caption(f"File size · {local_path.stat().st_size:,} bytes")
                    st.download_button(
                        "Download Reference STL",
                        data=local_path.read_bytes(),
                        file_name=valid_path.name,
                        mime="model/stl",
                        key=f"download_stl_{selected_id}",
                        use_container_width=True,
                    )
                else:
                    st.warning(
                        "The API returned an artifact path, but the non-empty STL file is "
                        "not accessible to this Streamlit process."
                    )
            elif artifact_path:
                st.warning("The API returned an invalid artifact path; download is unavailable.")
        else:
            st.caption("No CAD result has been returned for this design in this session.")

    st.divider()
    st.markdown("### STL preview")
    cad = st.session_state.cad_response
    cad_artifact_path = (
        cad.get("artifact_path")
        if cad and cad.get("design_id") == selected_id and cad.get("status") == "CREATED"
        else None
    )
    valid_stl_path = (
        _validated_artifact_path(cad_artifact_path, session_id, ".stl")
        if cad_artifact_path
        else None
    )
    local_stl_path = (
        _local_artifact_path(cad_artifact_path, session_id, ".stl")
        if valid_stl_path is not None
        else None
    )
    if local_stl_path is None:
        st.info(
            "A preview and interactive viewer are available only after the API "
            "returns a real STL artifact that is accessible to this Streamlit process."
        )
    else:
        auto_rotate = st.checkbox(
            "Auto-rotate model",
            value=False,
            key=f"stl_auto_rotate_{selected_id}",
        )
        if st.button(
            "Generate PNG Preview",
            key=f"generate_preview_{selected_id}",
            use_container_width=True,
        ):
            with st.spinner("Rendering an isometric preview from the STL mesh…"):
                try:
                    st.session_state.preview_response = client.generate_preview(
                        session_id,
                        selected_id,
                    )
                except ForgeXAPIError as error:
                    _show_api_error(error)
                else:
                    st.rerun()

        preview = st.session_state.preview_response
        preview_is_current = preview and preview.get("design_id") == selected_id
        image_path = None
        if preview_is_current and preview.get("artifact_path"):
            image_path = _local_artifact_path(
                str(preview["artifact_path"]),
                session_id,
                ".png",
            )

        png_tab, viewer_tab = st.tabs(["PNG preview", "Interactive STL"])
        with png_tab:
            if image_path is not None:
                st.image(
                    image_path,
                    caption=(
                        f"Isometric preview · {preview.get('width_px')} × "
                        f"{preview.get('height_px')} px"
                    ),
                    use_container_width=True,
                )
                st.caption(
                    f"Artifact · `{preview['artifact_path']}` · "
                    f"{preview.get('file_size_bytes', image_path.stat().st_size):,} bytes"
                )
            elif preview_is_current and preview.get("status") == "BLOCKED":
                st.warning(preview.get("message", "Preview generation is blocked."))
            elif preview_is_current and preview.get("artifact_path"):
                st.warning(
                    "The API returned a preview path, but the non-empty PNG file "
                    "is not accessible to this Streamlit process."
                )
            else:
                st.info("Generate a PNG preview from the existing STL mesh.")
        with viewer_tab:
            try:
                from streamlit_stl import stl_from_file
            except ImportError:
                st.info(
                    "The interactive STL viewer is optional. Install "
                    "`frontend/requirements.txt` to enable it."
                )
            else:
                viewer_ready = stl_from_file(
                    file_path=str(local_stl_path),
                    color="#5f8fc7",
                    auto_rotate=auto_rotate,
                    height=500,
                    key=f"stl_viewer_{selected_id}",
                )
                if not viewer_ready:
                    st.warning("The STL viewer could not load the returned mesh file.")
                st.caption(
                    "Reference concept model for engineering decision support. "
                    "Not optimized, validated, certified, or manufacturing-ready."
                )

    st.divider()
    _render_analysis_tab(client, session_id, selected_id)


def _append_chat_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})
    st.session_state.conversation = list(st.session_state.messages)


def _queue_quick_prompt(prompt: str, product_label: str) -> None:
    st.session_state.product_family_selector = product_label
    st.session_state.queued_prompt = prompt


def _design_summary(response: dict[str, Any]) -> str:
    alternatives = response.get("alternatives") or []
    if not alternatives:
        explanation = response.get("explanation") or response.get("message")
        return (
            f"Design screening returned **{response.get('status', 'unknown')}**."
            + (f" {explanation}" if explanation else " No alternatives were returned.")
        )

    recommended_id = response.get("recommended_design_id")
    recommended = next(
        (item for item in alternatives if item.get("id") == recommended_id),
        None,
    )
    lines = [
        f"Design screening returned **{response.get('status', 'unknown')}** "
        f"with {len(alternatives)} reference alternative(s)."
    ]
    if recommended:
        lines.append(
            f"Backend recommendation: **{recommended.get('name', recommended_id)}** "
            f"({recommended.get('status', 'status not returned')})."
        )
    else:
        lines.append("The backend did not return a recommended design.")
    lines.extend(
        f"- {item.get('name', item.get('id', 'Alternative'))}: "
        f"{item.get('status', 'status not returned')}"
        for item in alternatives
    )
    disclaimer = response.get("disclaimer")
    if disclaimer:
        lines.append(f"\n{disclaimer}")
    return "\n".join(lines)


def _gripper_confirmation_payload(
    extraction: dict[str, Any],
    request_text: str,
) -> dict[str, Any]:
    dimensions = extraction.get("dimensions") or {}
    safety_constraints = extraction.get("safety_constraints") or []
    width_m = dimensions.get("width_m")
    payload_mass_kg = extraction.get("payload_mass_kg")
    safety_factor = next(
        (
            item.get("min_safety_factor")
            for item in safety_constraints
            if item.get("min_safety_factor") is not None
        ),
        None,
    )
    if width_m is None or payload_mass_kg is None or safety_factor is None:
        raise ValueError(
            "The backend has not returned all critical gripper inputs "
            "(diameter, filled mass, and minimum safety factor)."
        )
    return _build_confirmed_brief(
        extraction,
        project_name="ForgeX engineering brief",
        product_type="servo_driven_gripper",
        purpose=str(extraction.get("purpose") or request_text),
        performance_statement=request_text,
        diameter_mm=float(width_m) * 1000,
        payload_mass_g=float(payload_mass_kg) * 1000,
        safety_factor=float(safety_factor),
        material_preference=str(extraction.get("material_preference") or ""),
        operating_environment=str(
            extraction.get("operating_environment") or UNSPECIFIED_ENVIRONMENT
        ),
        assumptions_text="\n".join(extraction.get("assumptions") or []),
    )


def _confirm_and_generate(
    client: ForgeXAPIClient,
    session_id: str,
    response: dict[str, Any],
) -> str:
    product_type = response.get("product_type", "servo_driven_gripper")
    brief = response.get("brief") or {}
    if product_type == "servo_driven_gripper":
        confirmed_payload = _gripper_confirmation_payload(
            brief,
            str(brief.get("purpose") or st.session_state.get("initial_request_text", "")),
        )
    else:
        confirmed_payload = {
            "product_type": product_type,
            "project_name": brief.get("project_name"),
            "purpose": brief.get("purpose"),
            "product_inputs": brief.get("product_inputs") or {},
            "disclaimer": brief.get("disclaimer"),
        }

    with st.spinner("Confirming the brief and screening candidate designs…"):
        confirmed = client.confirm_brief(session_id, confirmed_payload)
        st.session_state.brief_response = confirmed
        st.session_state.confirmed_brief = (
            confirmed.get("confirmed_brief")
            or confirmed.get("brief")
            or confirmed_payload
        )
        st.session_state.brief_response = confirmed
        generated = client.generate_designs(session_id)
    st.session_state.design_response = generated
    st.session_state.selected_design_id = generated.get("recommended_design_id")
    return (
        "Parameters are confirmed by the backend. "
        + _design_summary(generated)
    )


def _process_chat_message(
    client: ForgeXAPIClient,
    session_id: str,
    message: str,
    product_inputs: dict[str, Any],
) -> None:
    _append_chat_message("user", message)
    try:
        active_session_id = st.session_state.active_session_id
        if not active_session_id:
            product_type = st.session_state.product_type_input
            with st.spinner("ForgeX is analyzing requirements…"):
                started = client.start_brief(
                    message,
                    session_id,
                    product_type=(
                        None if product_type == "servo_driven_gripper" else product_type
                    ),
                    product_inputs=(
                        product_inputs
                        if product_type != "servo_driven_gripper"
                        else None
                    ),
                )
            st.session_state.active_session_id = started["session_id"]
            st.session_state.initial_request_text = message
            st.session_state.product_type_input = started.get(
                "product_type", product_type
            )
            st.session_state.brief_response = started
            st.session_state.confirmed_brief = None
            st.session_state.design_response = None
            if started.get("phase") == "ready_to_confirm":
                reply = _confirm_and_generate(client, started["session_id"], started)
            else:
                reply = started.get(
                    "agent_message",
                    "I’ve initialized the engineering brief. What critical inputs can you provide?",
                )
        elif st.session_state.design_response is not None:
            with st.spinner("Checking the returned calculations and evidence…"):
                answer = client.ask_design(active_session_id, message)
            reply = answer.get("answer", "The backend did not return an answer.")
            evidence = answer.get("evidence") or []
            if evidence:
                reply += "\n\nEvidence returned by ForgeX:\n" + "\n".join(
                    f"- {source}" for source in evidence
                )
        else:
            current = st.session_state.brief_response or {}
            if current.get("phase") == "confirmed":
                with st.spinner("ForgeX is screening the confirmed brief…"):
                    generated = client.generate_designs(active_session_id)
                st.session_state.design_response = generated
                st.session_state.selected_design_id = generated.get("recommended_design_id")
                reply = _design_summary(generated)
            else:
                product_type = current.get("product_type", "servo_driven_gripper")
                with st.spinner("ForgeX is updating the brief from your answer…"):
                    updated = client.clarify_brief(
                        active_session_id,
                        message,
                        product_inputs=(
                            product_inputs
                            if product_type != "servo_driven_gripper"
                            else None
                        ),
                    )
                st.session_state.brief_response = updated
                if updated.get("phase") == "ready_to_confirm":
                    reply = _confirm_and_generate(client, active_session_id, updated)
                else:
                    reply = updated.get(
                        "agent_message",
                        "I still need the missing requirements shown in the brief.",
                    )
        _append_chat_message("assistant", reply)
    except ForgeXAPIError as error:
        _show_api_error(error)
        _append_chat_message(
            "assistant",
            "I couldn’t complete that step because the backend returned an error. "
            "Please review the error details and try again.",
        )
    except (KeyError, TypeError, ValueError) as error:
        st.error("ForgeX could not safely continue with the returned brief.")
        st.caption(str(error))
        _append_chat_message(
            "assistant",
            "I can’t confirm or screen this brief yet because a required value is "
            "missing or was not returned. Please provide the missing value or review "
            "the backend response.",
        )


def _render_product_canvas_inputs() -> dict[str, Any]:
    product_type = st.session_state.product_type_input
    values: dict[str, Any] = {}
    if product_type != "servo_driven_gripper":
        with st.expander("Product-specific inputs", expanded=True):
            values = _product_input_controls(
                product_type,
                {},
                "chat_canvas",
            )
    st.session_state.chat_product_inputs = values
    return values


def _render_live_canvas(client: ForgeXAPIClient, session_id: str) -> None:
    st.subheader("Live engineering canvas")
    response = st.session_state.brief_response
    if response is None:
        st.info("Your project requirements and returned engineering data will appear here.")
        return

    st.markdown(f"**Workflow status:** {_status_badge(response.get('phase'))}", unsafe_allow_html=True)
    st.markdown(f"**Product family:** {response.get('product_type', 'Not returned')}")
    if response.get("missing_fields"):
        st.markdown("#### Inputs still needed")
        for item in response["missing_fields"]:
            st.markdown(f"- {item.get('question', item.get('name', 'Input not specified'))}")

    confirmed = st.session_state.confirmed_brief
    brief_data = confirmed or response.get("brief") or {}
    with st.expander("Engineering brief", expanded=not bool(confirmed)):
        if brief_data:
            st.json(brief_data)
        else:
            st.caption("The backend has not returned brief data.")
    if confirmed:
        st.success("Brief confirmed and stored for this session.")

    design = st.session_state.design_response
    if not design:
        return
    st.markdown("#### Reference alternatives")
    alternatives = design.get("alternatives") or []
    if not alternatives:
        st.info(design.get("explanation") or "The backend returned no alternatives.")
    alternative_columns = st.columns(3)
    for index, item in enumerate(alternatives):
        with alternative_columns[index % len(alternative_columns)]:
            with st.container(border=True):
                st.markdown(f"**{item.get('name', item.get('id', 'Alternative'))}**")
                st.markdown(_status_badge(item.get("status")), unsafe_allow_html=True)
                metrics = (item.get("key_parameters") or {}).get("calculated_metrics") or {}
                for field, label in (
                    ("required_grip_force_n", "Required grip force (N)"),
                    ("required_servo_torque_nm", "Required servo torque (N·m)"),
                    ("minimum_safety_factor", "Safety factor"),
                    ("grip_force_margin", "Grip force margin"),
                    ("servo_torque_margin", "Servo torque margin"),
                ):
                    value = metrics.get(field)
                    if value is not None:
                        st.metric(label, f"{value:g}")
                score = metrics.get("recommendation_score")
                if isinstance(score, (int, float)):
                    st.progress(max(0.0, min(float(score) / 2.0, 1.0)))
                    st.caption(
                        f"Returned minimum screening ratio: {score:g}× "
                        "(bar display is capped at 2×)."
                    )
                if metrics.get("constraints_pass") is not None:
                    st.caption(
                        "Constraints pass: "
                        + ("Yes" if metrics["constraints_pass"] else "No")
                    )

    if design.get("disclaimer"):
        st.warning(design["disclaimer"])
    with st.expander("Exports and opt-in analysis", expanded=False):
        _render_export_package(client, session_id)


def _render_house_wireframe(values: dict[str, Any]) -> None:
    svg = """
    <svg viewBox="0 0 440 300" role="img" aria-label="Illustrative house concept">
      <rect x="86" y="205" width="264" height="20" fill="#d7e0e8" stroke="#34495e" stroke-width="3"/>
      <path d="M105 205 L105 117 L218 48 L331 117 L331 205" fill="none" stroke="#1769aa" stroke-width="5"/>
      <path d="M105 117 L218 182 L331 117" fill="none" stroke="#1769aa" stroke-width="4"/>
      <path d="M218 48 L218 182" fill="none" stroke="#1769aa" stroke-width="3" stroke-dasharray="7 6"/>
      <rect x="197" y="155" width="42" height="50" fill="#fff" stroke="#34495e" stroke-width="3"/>
      <rect x="126" y="132" width="35" height="30" fill="#eef6fc" stroke="#34495e" stroke-width="3"/>
      <rect x="279" y="132" width="35" height="30" fill="#eef6fc" stroke="#34495e" stroke-width="3"/>
      <path d="M74 232 H362" stroke="#94a3b8" stroke-width="2" stroke-dasharray="5 5"/>
      <text x="218" y="266" text-anchor="middle" fill="#52657a" font-size="14">Foundation · walls · gabled roof</text>
    </svg>
    """
    st.markdown(svg, unsafe_allow_html=True)
    length = values.get("footprint_length_m")
    width = values.get("footprint_width_m")
    if isinstance(length, (int, float)) and isinstance(width, (int, float)):
        st.caption(f"Footprint: {length:g} m × {width:g} m.")
    else:
        st.caption("Schematic only, not to scale; footprint dimensions are not yet available.")


def _render_house_catalog_cards(cards: dict[str, Any]) -> None:
    for key, title, details in (
        (
            "material",
            "Selected material record",
            (
                "density_kg_m3",
                "cost_per_kg_usd",
                "characteristic_strength_cylinder_mpa",
                "characteristic_strength_cube_mpa",
            ),
        ),
        (
            "printer",
            "Construction equipment / 3D printer",
            ("build_volume_mm", "deposition_rate_cm3_per_hour", "nozzle_diameter_mm"),
        ),
        (
            "robotic_arm",
            "Robotic arm record",
            ("payload_kg", "reach_mm", "axis_limits"),
        ),
    ):
        card = cards.get(key) or {}
        with st.container(border=True):
            st.markdown(f"**{title}**")
            st.markdown(_status_badge(card.get("status")), unsafe_allow_html=True)
            record = card.get("record")
            if record:
                st.markdown(f"**{record.get('name', 'Catalog record')}**")
                for field in details:
                    value = record.get(field)
                    label = field.replace("_", " ").title()
                    st.write(f"{label}: {value if value is not None else 'Not supplied'}")
                if record.get("source_note"):
                    st.caption(record["source_note"])
            else:
                st.caption(card.get("message", "No matching catalog record was returned."))
            st.caption(f"Source: {card.get('source', 'Not returned')}")


def _render_residential_canvas(client: ForgeXAPIClient, session_id: str) -> None:
    response = st.session_state.brief_response or {}
    brief = st.session_state.confirmed_brief or response.get("brief") or {}
    values = dict(brief.get("product_inputs") or {})
    design = st.session_state.design_response or {}
    panel = design.get("calculation_panel") or {}
    cards = design.get("catalog_cards") or brief.get("catalog_cards") or {}

    st.subheader("Residential concept workbench")
    left, middle, right = st.columns([1.15, 1.0, 1.0], gap="large")
    with left:
        st.markdown("#### House concept")
        _render_house_wireframe(values)
        if values.get("floor_area_m2") is not None:
            st.metric("Requested floor area", f"{values['floor_area_m2']:g} m²")
    with middle:
        st.markdown("#### Product records")
        if cards:
            _render_house_catalog_cards(cards)
        else:
            st.info("Catalog cards will be returned with the brief and calculation response.")
    with right:
        st.markdown("#### Deterministic calculation panel")
        if panel:
            for name, label, unit in (
                ("floor_area_m2", "Total floor area", "m²"),
                ("wall_volume_m3", "Estimated wall volume", "m³"),
                ("roof_volume_m3", "Estimated roof volume", "m³"),
                ("material_mass_kg", "Estimated material quantity", "kg"),
                ("estimated_material_cost_usd", "Estimated material cost", "USD"),
                ("estimated_print_time_hours", "Estimated extrusion time", "hours"),
            ):
                value = panel.get(name)
                st.metric(
                    label,
                    f"{value:,.3g} {unit}"
                    if isinstance(value, (int, float))
                    else "Not available",
                )
            budget_amount = panel.get("budget_amount")
            budget_currency = panel.get("budget_currency")
            if isinstance(budget_amount, (int, float)):
                st.metric("Recorded budget", f"{budget_amount:,.2f} {budget_currency}")
            if panel.get("within_budget") is not None:
                st.caption(
                    "Catalog material estimate within recorded budget: "
                    + ("Yes" if panel["within_budget"] else "No")
                )
            for flag in panel.get("missing_data_flags", []):
                st.warning(flag)
        elif response.get("missing_fields"):
            st.info("The backend is collecting required inputs before calculating.")
            for field in response["missing_fields"]:
                st.caption(f"Still needed: {field.get('question', field.get('name'))}")
        else:
            st.info("No calculation panel was returned by the backend.")

    st.markdown(
        '<div class="engineering-disclaimer">Reference library: sample layouts, selected materials, real product records with manufacturer specs. Illustrative estimates, not certified quotes.</div>',
        unsafe_allow_html=True,
    )
    st.warning(
        "The local printer catalog is empty and the components catalog contains no "
        "robotic-arm record. Manufacturer specifications, deposition time, and those "
        "records are unavailable—not inferred."
    )
    if design:
        st.caption(
            f"Design workflow status: {design.get('status', 'Not returned')}. "
            f"{design.get('explanation', '')}"
        )
        if st.session_state.confirmed_brief:
            with st.expander("Concept report and parametric STL", expanded=True):
                _render_export_package(client, session_id)


def _render_chat_interface(
    client: ForgeXAPIClient,
    session_id: str,
    product_inputs: dict[str, Any],
) -> None:
    st.subheader("ForgeX AI Engineer")
    st.caption("Describe the project, answer follow-ups, and ask about returned results.")
    quick_prompts = (
        (
            "Servo Bottle Gripper",
            "Design a 3D-printable gripper for a 500 ml bottle using an SG90 servo.",
            "servo_driven_gripper",
        ),
        (
            "Electronics Enclosure",
            "I need a 3D-printable electronics enclosure.",
            "electronics_enclosure",
        ),
        (
            "Residential House",
            "Design a 2-bedroom house model with 80 m² area.",
            "residential_building_concept",
        ),
    )
    if not st.session_state.active_session_id and not st.session_state.messages:
        prompt_columns = st.columns(3)
        for column, (label, prompt, product_type) in zip(prompt_columns, quick_prompts):
            product_label = next(
                name for name, value in PRODUCT_OPTIONS.items() if value == product_type
            )
            column.button(
                label,
                use_container_width=True,
                on_click=_queue_quick_prompt,
                args=(prompt, product_label),
            )
    for item in st.session_state.messages:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])
    chat_message = st.chat_input("Talk to ForgeX AI Engineer...")
    if chat_message:
        _process_chat_message(
            client,
            session_id,
            chat_message,
            st.session_state.get("chat_product_inputs", product_inputs),
        )
        st.rerun()


def main() -> None:
    _initialize_state()
    if "messages" not in st.session_state:
        st.session_state.messages = list(st.session_state.conversation)
    st.markdown(f"<style>{_read_stylesheet()}</style>", unsafe_allow_html=True)
    response_product = (st.session_state.brief_response or {}).get("product_type")
    if response_product in PRODUCT_OPTIONS.values():
        st.session_state.product_type_input = response_product
        st.session_state.product_family_selector = next(
            label for label, value in PRODUCT_OPTIONS.items() if value == response_product
        )
    client = _api_client()
    session_id = _render_sidebar(client)
    _render_header(_active_stage_index())
    with st.sidebar:
        selected_product = st.selectbox(
            "Product family",
            list(PRODUCT_OPTIONS),
            index=list(PRODUCT_OPTIONS.values()).index(st.session_state.product_type_input),
            key="product_family_selector",
            disabled=bool(st.session_state.active_session_id),
        )
        st.session_state.product_type_input = PRODUCT_OPTIONS[selected_product]

    product_inputs = _render_product_canvas_inputs()
    queued_prompt = st.session_state.pop("queued_prompt", None)
    if queued_prompt:
        _process_chat_message(client, session_id, queued_prompt, product_inputs)

    active_product = (
        (st.session_state.brief_response or {}).get("product_type")
        or st.session_state.product_type_input
    )
    if active_product == "residential_building_concept":
        _render_chat_interface(client, session_id, product_inputs)
        st.markdown(
            f'<div class="engineering-disclaimer">{html.escape(DISCLAIMER)}</div>',
            unsafe_allow_html=True,
        )
        _render_residential_canvas(
            client,
            st.session_state.active_session_id or session_id,
        )
    else:
        chat_column, canvas_column = st.columns(2, gap="large")
        with chat_column:
            _render_chat_interface(client, session_id, product_inputs)
            st.markdown(
                f'<div class="engineering-disclaimer">{html.escape(DISCLAIMER)}</div>',
                unsafe_allow_html=True,
            )
        with canvas_column:
            _render_live_canvas(client, st.session_state.active_session_id or session_id)


if __name__ == "__main__":
    main()

"""Backend-ready conversational elicitation for Stage 5 Engineering Briefs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from core.brief_extraction import BriefExtraction, extract_engineering_brief
from core.models import EngineeringBrief
from core.requirements import (
    LoadCondition,
    PerformanceRequirement,
    ProductType,
    SafetyConstraint,
)


_PRODUCT_KEYWORDS: tuple[tuple[ProductType, tuple[str, ...]], ...] = (
    (
        ProductType.CIVIL_CONCEPT_ASSISTANT,
        (r"\bconcrete\b", r"\bm20\b", r"\bm25\b", r"\bfoundation\b"),
    ),
    (
        ProductType.SIMPLE_HOUSE_MODEL,
        (
            r"\bhouse\b",
            r"\bbuilding\b",
            r"\broof\b",
            r"\bgabled\b",
            r"\bscale\s+model\b",
        ),
    ),
    (
        ProductType.ELECTRONICS_ENCLOSURE,
        (r"\benclosure\b", r"\bbox\b", r"\bcase\b", r"\bhousing\b", r"\blid\b"),
    ),
    (
        ProductType.MOUNTING_BRACKET,
        (
            r"\bbracket\b",
            r"\bshelf\b",
            r"\bmount(?:ing)?\b",
            r"\bcantilever\b",
        ),
    ),
    (
        ProductType.SERVO_DRIVEN_GRIPPER,
        (r"\bgripper\b", r"\bjaw\b", r"\bservo\b", r"\bpick[\s-]+up\b"),
    ),
)


def classify_product_type(message: str) -> ProductType | None:
    """Infer a supported product family from explicit request keywords."""
    text = message.casefold()
    for product_type, patterns in _PRODUCT_KEYWORDS:
        if any(re.search(pattern, text) for pattern in patterns):
            return product_type
    return None


def _extraction(session_state: Mapping[str, Any]) -> BriefExtraction:
    try:
        return BriefExtraction.model_validate(session_state["extraction"])
    except (KeyError, ValidationError) as exc:
        raise ValueError("Invalid or missing brief workflow session state.") from exc


def _new_session(extraction: BriefExtraction, transcript: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "version": 1,
        "phase": "clarifying",
        "extraction": extraction.model_dump(mode="json"),
        "transcript": transcript,
        "confirmed_brief": None,
    }


def _missing_fields(extraction: BriefExtraction) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    if extraction.product_type is None:
        missing.append(
            {
                "name": "product_type",
                "label": "Product type",
                "question": (
                    "Is this a gripper, enclosure, mounting bracket, house model, "
                    "or civil concept?"
                ),
            }
        )
        return missing

    if extraction.product_type == ProductType.SIMPLE_HOUSE_MODEL:
        return [
            {
                "name": "house_footprint",
                "label": "House footprint",
                "question": "What footprint length and width should the house model have?",
            },
            {
                "name": "house_roof_dimensions",
                "label": "Wall and roof dimensions",
                "question": (
                    "What wall height and thickness, and what roof pitch or ridge "
                    "height should it use?"
                ),
            },
        ]
    if extraction.product_type == ProductType.SERVO_DRIVEN_GRIPPER:
        if extraction.dimensions is None or extraction.dimensions.width_m is None:
            missing.append(
                {
                    "name": "payload_diameter",
                    "label": "Object diameter",
                    "question": "What is the bottle or object diameter?",
                }
            )
        has_force = extraction.load_condition is not None and extraction.load_condition.force_n is not None
        if extraction.payload_mass_kg is None and not has_force:
            missing.append(
                {
                    "name": "payload_mass",
                    "label": "Filled payload mass",
                    "question": "What is the filled bottle or payload mass?",
                }
            )
    elif extraction.product_type in {
        ProductType.STRUCTURAL_BRACKET,
        ProductType.MOUNTING_BRACKET,
    } and extraction.dimensions is None:
        missing.append(
            {
                "name": "dimensions",
                "label": "Part envelope",
                "question": "What maximum envelope dimensions should the bracket fit within?",
            }
        )
    if extraction.product_type in {
        ProductType.STRUCTURAL_BRACKET,
        ProductType.MOUNTING_BRACKET,
    } and (
        extraction.load_condition is None
        or (
            extraction.load_condition.force_n is None
            and extraction.load_condition.moment_nm is None
        )
    ):
        missing.append(
            {
                "name": "applied_load",
                "label": "Applied load",
                "question": "What load should the bracket support, and in what direction?",
            }
        )

    if not extraction.safety_constraints:
        missing.append(
            {
                "name": "minimum_safety_factor",
                "label": "Minimum safety factor",
                "question": "What minimum safety factor should the design target?",
            }
        )
    return missing


def get_missing_fields(session_state: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return unresolved critical engineering inputs for the current session."""
    return _missing_fields(_extraction(session_state))


def _suggested_title(extraction: BriefExtraction) -> str:
    if extraction.project_name:
        return extraction.project_name
    if extraction.product_type == ProductType.SERVO_DRIVEN_GRIPPER:
        target = "Bottle" if extraction.nominal_volume_ml else "Payload"
        return f"{target} Gripper"
    if extraction.product_type in {
        ProductType.MOUNTING_BRACKET,
        ProductType.STRUCTURAL_BRACKET,
    }:
        return "Mounting Bracket"
    return ""


def _ensure_brief_basics(extraction: BriefExtraction) -> BriefExtraction:
    updates: dict[str, Any] = {}
    if extraction.product_type is not None and not extraction.project_name:
        updates["project_name"] = _suggested_title(extraction)
        updates["assumptions"] = [
            *extraction.assumptions,
            "Suggested project title derived from the user's request; review before confirming.",
        ]

    if extraction.purpose and extraction.performance_requirement is None:
        statement = extraction.purpose.strip()
        if extraction.nominal_volume_ml:
            volume = f"{extraction.nominal_volume_ml:g} ml"
            statement = f"Hold one {volume} bottle as requested."
        updates["performance_requirement"] = PerformanceRequirement(
            name="user_stated_goal",
            statement=statement,
        )

    if (
        extraction.load_condition is None
        and extraction.purpose
        and extraction.product_type == ProductType.SERVO_DRIVEN_GRIPPER
    ):
        description = "User-requested gripper payload; mass has not been provided."
        if extraction.nominal_volume_ml:
            description = (
                f"User-requested bottle, nominal volume "
                f"{extraction.nominal_volume_ml:g} ml."
            )
        updates["load_condition"] = LoadCondition(
            name="user_requested_payload",
            description=description,
        )

    if extraction.component_preferences:
        component_notes = [
            f"User-specified component preference: {component}; compatibility and catalog "
            "availability have not been checked."
            for component in extraction.component_preferences
        ]
        existing = [item for item in extraction.assumptions if item not in component_notes]
        updates["assumptions"] = list(dict.fromkeys([*existing, *component_notes]))

    if not updates:
        return extraction
    return extraction.model_copy(update=updates)


def _merge_extraction(
    current: BriefExtraction,
    update: BriefExtraction,
) -> BriefExtraction:
    merged = current.model_dump()
    for field in (
        "project_name",
        "product_type",
        "performance_requirement",
        "load_condition",
        "material_preference",
        "budget",
        "operating_environment",
        "payload_mass_kg",
        "payload_description",
        "nominal_volume_ml",
    ):
        value = getattr(update, field)
        if value is not None:
            merged[field] = value
    if not current.purpose and update.purpose:
        merged["purpose"] = update.purpose

    if update.dimensions is not None:
        old_dimensions = current.dimensions.model_dump() if current.dimensions else {}
        new_dimensions = update.dimensions.model_dump(exclude_none=True)
        old_dimensions.update(new_dimensions)
        merged["dimensions"] = old_dimensions
    if update.safety_constraints:
        merged["safety_constraints"] = [
            item.model_dump() for item in update.safety_constraints
        ]
    if update.assumptions:
        merged["assumptions"] = list(
            dict.fromkeys([*current.assumptions, *update.assumptions])
        )
    if update.component_preferences:
        merged["component_preferences"] = list(
            dict.fromkeys(
                [*current.component_preferences, *update.component_preferences]
            )
        )
    if update.notes:
        merged["notes"] = list(dict.fromkeys([*current.notes, *update.notes]))
    merged["original_text"] = f"{current.original_text}\n{update.original_text}"
    merged["payload_description"] = _payload_description(current, update)
    return BriefExtraction.model_validate(merged)


def _payload_description(
    current: BriefExtraction,
    update: BriefExtraction,
) -> str | None:
    pieces = [
        item
        for item in (current.payload_description, update.payload_description)
        if item and item not in current.original_text
    ]
    base = current.payload_description or update.payload_description
    if update.payload_mass_kg is not None:
        mass_text = f"User-stated payload mass: {update.payload_mass_kg:g} kg."
        if mass_text not in (base or ""):
            return f"{base} {mass_text}".strip() if base else mass_text
    if pieces:
        return " ".join(dict.fromkeys(pieces))
    return base


def _brief_ready_extraction(extraction: BriefExtraction) -> BriefExtraction:
    extraction = _ensure_brief_basics(extraction)
    if extraction.payload_mass_kg is not None and extraction.load_condition is not None:
        mass_text = f"User-stated payload mass: {extraction.payload_mass_kg:g} kg."
        if mass_text not in extraction.load_condition.description:
            load = extraction.load_condition.model_copy(
                update={
                    "description": (
                        f"{extraction.load_condition.description} {mass_text}"
                    ).strip()
                }
            )
            extraction = extraction.model_copy(update={"load_condition": load})
    return extraction


def _known_summary(extraction: BriefExtraction) -> list[str]:
    known: list[str] = []
    if extraction.product_type:
        known.append(extraction.product_type.value.replace("_", " "))
    if extraction.nominal_volume_ml:
        known.append(f"{extraction.nominal_volume_ml:g} ml nominal bottle volume")
    if extraction.component_preferences:
        known.append(f"user-specified component: {', '.join(extraction.component_preferences)}")
    if extraction.dimensions and extraction.dimensions.width_m is not None:
        known.append(f"diameter: {extraction.dimensions.width_m * 1000:g} mm")
    if extraction.payload_mass_kg is not None:
        known.append(f"filled payload mass: {extraction.payload_mass_kg:g} kg")
    if extraction.safety_constraints:
        factor = extraction.safety_constraints[0].min_safety_factor
        if factor is not None:
            known.append(f"minimum safety factor: {factor:g}")
    if extraction.material_preference:
        known.append(f"material preference: {extraction.material_preference}")
    if extraction.budget:
        known.append(f"budget: ${extraction.budget.amount_usd:g} USD")
    return known


def _assistant_message(extraction: BriefExtraction, missing: list[dict[str, str]]) -> str:
    product = extraction.product_type
    if product == ProductType.SERVO_DRIVEN_GRIPPER:
        object_name = (
            f"a {extraction.nominal_volume_ml:g} ml bottle"
            if extraction.nominal_volume_ml
            else "the requested payload"
        )
        component = (
            f" using your {', '.join(extraction.component_preferences)} servo"
            if extraction.component_preferences
            else ""
        )
        understood = (
            f"I understand you want a 3D-printable, servo-driven gripper for "
            f"{object_name}{component}."
        )
    elif product == ProductType.STRUCTURAL_BRACKET:
        understood = "I understand you want a simple 3D-printable structural bracket."
    elif product == ProductType.SIMPLE_HOUSE_MODEL:
        understood = "I understand you want to develop a simple house scale-model concept."
    elif product == ProductType.ELECTRONICS_ENCLOSURE:
        understood = "I understand you want an electronics enclosure concept."
    elif product == ProductType.MOUNTING_BRACKET:
        understood = "I understand you want a mounting bracket concept."
    elif product == ProductType.CIVIL_CONCEPT_ASSISTANT:
        understood = "I understand you are asking for preliminary civil concept advice."
    else:
        understood = "I’ve read your request and am building a candidate Engineering Brief."

    known = _known_summary(extraction)
    requirements = (
        [extraction.performance_requirement.statement]
        if extraction.performance_requirement
        else []
    )
    sections = [understood]
    if known:
        sections.append("What I captured: " + "; ".join(known) + ".")
    if requirements:
        sections.append("Requirement from your request: " + "; ".join(requirements))
    if extraction.assumptions:
        sections.append("Explicit notes to review: " + "; ".join(extraction.assumptions))
    else:
        sections.append("I have not assumed any missing numeric engineering values.")
    if missing:
        questions = " ".join(item["question"] for item in missing)
        sections.append("To complete the critical inputs, please tell me: " + questions)
    else:
        sections.append(
            "I have the critical inputs. Please review the concise confirmation form below."
        )
    return "\n\n".join(sections)


def _result(session_state: dict[str, Any], assistant_message: str) -> dict[str, Any]:
    extraction = _extraction(session_state)
    missing = _missing_fields(extraction)
    return {
        "session_state": session_state,
        "assistant_message": assistant_message,
        "interpretation": assistant_message,
        "extracted_values": _known_summary(extraction),
        "requirements": (
            [extraction.performance_requirement.model_dump(mode="json")]
            if extraction.performance_requirement
            else []
        ),
        "assumptions": list(extraction.assumptions),
        "missing_fields": missing,
        "follow_up_questions": [item["question"] for item in missing],
        "ready_to_confirm": not missing,
        "confirmed_brief": session_state.get("confirmed_brief"),
    }


def start_brief_session(message: str) -> dict[str, Any]:
    """Create a serializable conversational brief session from the first request."""
    extraction = _brief_ready_extraction(extract_engineering_brief(message))
    inferred_product_type = classify_product_type(message)
    if inferred_product_type is not None:
        extraction = extraction.model_copy(update={"product_type": inferred_product_type})
    missing = _missing_fields(extraction)
    assistant_message = _assistant_message(extraction, missing)
    session_state = _new_session(
        extraction,
        [
            {"role": "user", "content": message.strip()},
            {"role": "assistant", "content": assistant_message},
        ],
    )
    return _result(session_state, assistant_message)


def clarify_brief_session(
    session_state: Mapping[str, Any],
    user_message: str,
) -> dict[str, Any]:
    """Parse a follow-up answer, merge explicit facts, and ask only unresolved questions."""
    if not user_message.strip():
        raise ValueError("A non-empty clarification is required.")
    current = _extraction(session_state)
    update = extract_engineering_brief(user_message)
    extraction = _brief_ready_extraction(_merge_extraction(current, update))
    missing = _missing_fields(extraction)
    assistant_message = _assistant_message(extraction, missing)
    updated_state = dict(session_state)
    updated_state["extraction"] = extraction.model_dump(mode="json")
    updated_state["phase"] = "clarifying" if missing else "ready_to_confirm"
    updated_state["confirmed_brief"] = None
    updated_state["transcript"] = [
        *session_state.get("transcript", []),
        {"role": "user", "content": user_message.strip()},
        {"role": "assistant", "content": assistant_message},
    ]
    return _result(updated_state, assistant_message)


def _confirmed_payload(
    extraction: BriefExtraction,
    confirmed_values: Mapping[str, Any],
) -> dict[str, Any]:
    extraction = _brief_ready_extraction(extraction)
    dimensions = extraction.dimensions
    if dimensions is None:
        raise ValueError("An envelope dimension is required before confirming the brief.")
    load = extraction.load_condition
    if load is None:
        raise ValueError("A load condition is required before confirming the brief.")

    requirement = extraction.performance_requirement
    if requirement is None:
        requirement = PerformanceRequirement(
            name="user_stated_goal",
            statement=extraction.purpose or "User-described engineering goal.",
        )

    environment = extraction.operating_environment
    if not environment:
        environment = "Not specified by user; confirm before engineering evaluation."
    assumptions = list(extraction.assumptions)
    if not extraction.operating_environment:
        assumptions.append(
            "Operating environment was not provided; confirm it before engineering evaluation."
        )

    payload: dict[str, Any] = {
        "project_name": extraction.project_name or "",
        "product_type": extraction.product_type,
        "purpose": extraction.purpose or extraction.original_text,
        "performance_requirements": [requirement.model_dump()],
        "load_conditions": [load.model_dump()],
        "dimensions": dimensions.model_dump(),
        "material_preference": extraction.material_preference,
        "budget": extraction.budget.model_dump() if extraction.budget else None,
        "operating_environment": environment,
        "safety_constraints": [
            item.model_dump() for item in extraction.safety_constraints
        ],
        "assumptions": assumptions,
    }
    reviewed = dict(confirmed_values)
    diameter_mm = reviewed.pop("payload_diameter_mm", None)
    dimensions_value = payload["dimensions"]
    if diameter_mm not in (None, ""):
        diameter = float(diameter_mm)
        if not math.isfinite(diameter) or diameter <= 0:
            raise ValueError("Object diameter must be a finite value greater than zero.")
        dimensions_value["width_m"] = diameter / 1000
        dimensions_value["notes"] = (
            f"User-confirmed object diameter: {diameter:g} mm."
        )
    for field in ("length_m", "height_m"):
        raw_value = reviewed.pop(field, None)
        if raw_value not in (None, ""):
            dimension = float(raw_value)
            if not math.isfinite(dimension) or dimension <= 0:
                raise ValueError(f"{field} must be a finite value greater than zero.")
            dimensions_value[field] = dimension
    payload["dimensions"] = dimensions_value

    mass_grams = reviewed.pop("payload_mass_g", None)
    mass_value = reviewed.pop("payload_mass_kg", extraction.payload_mass_kg)
    if mass_grams not in (None, ""):
        mass_value = float(mass_grams) / 1000
    if mass_value not in (None, ""):
        mass_kg = float(mass_value)
        if not math.isfinite(mass_kg) or mass_kg <= 0:
            raise ValueError("Filled payload mass must be a finite value greater than zero.")
        load_description = str(
            reviewed.pop("load_description", load.description)
        ).strip()
        load_description = re.sub(
            r"\s*User-(?:stated|confirmed) payload mass: [\d.]+ kg\.",
            "",
            load_description,
        )
        payload["load_conditions"] = [
            {
                **load.model_dump(),
                "description": (
                    f"{load_description} User-confirmed payload mass: {mass_kg:g} kg."
                ).strip(),
            }
        ]
    elif (
        extraction.product_type == ProductType.SERVO_DRIVEN_GRIPPER
        and load.force_n is None
    ):
        raise ValueError("A filled payload mass or load force is required for this gripper.")

    safety_value = reviewed.pop(
        "minimum_safety_factor",
        (
            extraction.safety_constraints[0].min_safety_factor
            if extraction.safety_constraints
            else None
        ),
    )
    if safety_value in (None, ""):
        raise ValueError("A minimum safety factor is required before confirming the brief.")
    safety_constraint = SafetyConstraint(
        name="minimum_safety_factor",
        statement=f"Minimum closed-form safety factor of {float(safety_value):g}.",
        min_safety_factor=float(safety_value),
    )
    payload["safety_constraints"] = [safety_constraint.model_dump()]
    if "load_description" in reviewed:
        payload["load_conditions"] = [
            {
                **load.model_dump(),
                "description": str(reviewed.pop("load_description")).strip(),
            }
        ]
    product_type = reviewed.get("product_type", extraction.product_type)
    try:
        product_type = ProductType(product_type)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Only servo-driven grippers and structural brackets are supported."
        ) from exc
    if product_type not in {
        ProductType.SERVO_DRIVEN_GRIPPER,
        ProductType.STRUCTURAL_BRACKET,
    }:
        raise ValueError("Only servo-driven grippers and structural brackets are supported.")
    reviewed["product_type"] = product_type
    payload.update(reviewed)
    if (
        payload["operating_environment"]
        != "Not specified by user; confirm before engineering evaluation."
    ):
        payload["assumptions"] = [
            item
            for item in payload["assumptions"]
            if item
            != "Operating environment was not provided; confirm it before engineering evaluation."
        ]
    if payload["project_name"] != _suggested_title(extraction):
        payload["assumptions"] = [
            item
            for item in payload["assumptions"]
            if item
            != "Suggested project title derived from the user's request; review before confirming."
        ]
    return payload


def confirm_brief(
    session_state: Mapping[str, Any],
    confirmed_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and persist the user-reviewed brief once critical inputs are complete."""
    supplied_brief = confirmed_values.get("confirmed_brief")
    if supplied_brief is not None:
        brief = EngineeringBrief.model_validate(supplied_brief)
        if brief.product_type not in {
            ProductType.SERVO_DRIVEN_GRIPPER,
            ProductType.STRUCTURAL_BRACKET,
        }:
            raise ValueError(
                "Only servo-driven grippers and structural brackets are supported."
            )
        updated_state = dict(session_state)
        updated_state["phase"] = "confirmed"
        updated_state["confirmed_brief"] = brief.model_dump(mode="json")
        assistant_message = "Engineering Brief confirmed and saved for this session."
        updated_state["transcript"] = [
            *session_state.get("transcript", []),
            {"role": "assistant", "content": assistant_message},
        ]
        return _result(updated_state, assistant_message)

    extraction = _extraction(session_state)
    missing = _missing_fields(extraction)
    if missing:
        labels = ", ".join(item["label"] for item in missing)
        raise ValueError(f"Cannot confirm the Engineering Brief; missing: {labels}.")

    brief = EngineeringBrief.model_validate(
        _confirmed_payload(extraction, confirmed_values)
    )
    updated_state = dict(session_state)
    updated_state["phase"] = "confirmed"
    updated_state["confirmed_brief"] = brief.model_dump(mode="json")
    assistant_message = "Engineering Brief confirmed and saved for this session."
    updated_state["transcript"] = [
        *session_state.get("transcript", []),
        {"role": "assistant", "content": assistant_message},
    ]
    return _result(
        updated_state,
        assistant_message,
    )

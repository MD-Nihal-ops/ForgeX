"""Agent-facing entry points for the reusable brief workflow."""

from collections.abc import Mapping
from typing import Any

from core.brief_workflow import (
    clarify_brief_session as _clarify_brief_session,
)
from core.brief_workflow import (
    confirm_brief as _confirm_brief,
)
from core.brief_workflow import (
    get_missing_fields as _get_missing_fields,
)
from core.brief_workflow import (
    start_brief_session as _start_brief_session,
)

from .prompts import BRIEF_CLARIFICATION_STYLE, BRIEF_ELICITATION_SYSTEM_PROMPT

__all__ = [
    "BRIEF_CLARIFICATION_STYLE",
    "BRIEF_ELICITATION_SYSTEM_PROMPT",
    "clarify_brief_session",
    "confirm_brief",
    "get_missing_fields",
    "start_brief_session",
]


def start_brief_session(message: str) -> dict[str, Any]:
    """Start conversational Engineering Brief elicitation."""
    return _start_brief_session(message)


def clarify_brief_session(
    session_state: Mapping[str, Any],
    user_message: str,
) -> dict[str, Any]:
    """Apply a follow-up answer to the current brief conversation."""
    return _clarify_brief_session(session_state, user_message)


def get_missing_fields(session_state: Mapping[str, Any]) -> list[dict[str, str]]:
    """List unresolved critical inputs."""
    return _get_missing_fields(session_state)


def confirm_brief(
    session_state: Mapping[str, Any],
    confirmed_values: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and persist the user's reviewed Engineering Brief."""
    return _confirm_brief(session_state, confirmed_values)

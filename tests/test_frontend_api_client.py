"""Tests for the Streamlit frontend's HTTP-only ForgeX API client."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from frontend.api_client import (
    DEFAULT_API_URL,
    ForgeXAPIClient,
    ForgeXAPIError,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _replace_request(monkeypatch: pytest.MonkeyPatch, response_or_error):
    calls = []

    def fake_request(self, method, url, **kwargs):
        calls.append((method, url, kwargs))
        if isinstance(response_or_error, Exception):
            raise response_or_error
        return response_or_error

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return calls


def test_default_and_environment_api_urls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORGEX_API_URL", raising=False)
    assert ForgeXAPIClient().base_url == DEFAULT_API_URL

    monkeypatch.setenv("FORGEX_API_URL", "http://backend.internal:9000/")
    assert ForgeXAPIClient().base_url == "http://backend.internal:9000"


def test_api_client_sends_product_family_inputs(monkeypatch: pytest.MonkeyPatch):
    calls = _replace_request(monkeypatch, FakeResponse(200, {"ok": True}))
    client = ForgeXAPIClient("http://api.example")
    client.start_brief(
        "An enclosure",
        "session-2",
        product_type="electronics_enclosure",
        product_inputs={"internal_length_mm": 100},
    )
    client.clarify_brief(
        "session-2",
        "The remaining dimensions are known.",
        product_inputs={"internal_width_mm": 80},
    )

    assert calls[0][2]["json"] == {
        "message": "An enclosure",
        "session_id": "session-2",
        "product_type": "electronics_enclosure",
        "product_inputs": {"internal_length_mm": 100},
    }
    assert calls[1][2]["json"] == {
        "session_id": "session-2",
        "message": "The remaining dimensions are known.",
        "product_inputs": {"internal_width_mm": 80},
    }


def test_api_client_routes_grounded_design_questions(monkeypatch: pytest.MonkeyPatch):
    calls = _replace_request(monkeypatch, FakeResponse(200, {"answer": "Returned data"}))
    client = ForgeXAPIClient("http://api.example")

    response = client.ask_design("session-1", "Why did design 2 fail?")

    assert response == {"answer": "Returned data"}
    assert calls[0][0] == "POST"
    assert calls[0][1] == "http://api.example/api/design/ask"
    assert calls[0][2]["json"] == {
        "session_id": "session-1",
        "question": "Why did design 2 fail?",
    }


def test_api_methods_call_existing_backend_routes(monkeypatch: pytest.MonkeyPatch):
    calls = _replace_request(monkeypatch, FakeResponse(200, {"ok": True}))
    client = ForgeXAPIClient("http://api.example/")

    client.start_brief("Design a gripper", "session-1")
    client.clarify_brief("session-1", "Diameter 70 mm")
    client.confirm_brief("session-1", {"project_name": "Gripper"})
    client.generate_designs("session-1")
    client.generate_cad("session-1", "rigid_gripper")
    client.generate_preview("session-1", "rigid_gripper")
    client.create_analysis(
        "session-1",
        "rigid_gripper",
        "structural",
        {"loads": []},
    )
    client.get_analysis("analysis-1")
    client.get_analysis_results("analysis-1")
    client.run_analysis("analysis-1")
    client.generate_report("session-1", "rigid_gripper")
    client.get_report("session-1", "rigid_gripper")
    client.get_health()

    assert [call[0] for call in calls] == [
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "POST",
        "GET",
        "GET",
        "POST",
        "POST",
        "GET",
        "GET",
    ]
    assert [call[1].removeprefix("http://api.example") for call in calls] == [
        "/api/brief/start",
        "/api/brief/clarify",
        "/api/brief/confirm",
        "/api/design/generate",
        "/api/design/rigid_gripper/cad",
        "/api/design/rigid_gripper/preview",
        "/api/analysis/create",
        "/api/analysis/analysis-1",
        "/api/analysis/analysis-1/results",
        "/api/analysis/analysis-1/run",
        "/api/design/rigid_gripper/report",
        "/api/design/rigid_gripper/report",
        "/api/health",
    ]
    assert calls[0][2]["json"] == {
        "message": "Design a gripper",
        "session_id": "session-1",
    }
    assert calls[2][2]["json"]["confirmed_brief"]["project_name"] == "Gripper"
    assert calls[6][2]["json"] == {
        "session_id": "session-1",
        "design_id": "rigid_gripper",
        "analysis_type": "structural",
        "inputs": {"loads": []},
    }
    assert calls[11][2]["params"] == {"session_id": "session-1"}
    assert calls[12][2]["json"] is None
    assert calls[12][2]["params"] is None


@pytest.mark.parametrize(
    ("status_code", "detail", "message_part"),
    [
        (422, [{"loc": ["body", "message"], "msg": "Field required"}], "Validation error (422)"),
        (404, "Brief session not found.", "Not found (404)"),
        (409, "Confirm the brief first.", "Workflow conflict (409)"),
    ],
)
def test_http_errors_include_status_and_detail(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    detail: Any,
    message_part: str,
):
    _replace_request(
        monkeypatch,
        FakeResponse(status_code, {"detail": detail}),
    )
    with pytest.raises(ForgeXAPIError) as raised:
        ForgeXAPIClient().generate_designs("missing-session")

    assert raised.value.status_code == status_code
    assert message_part in str(raised.value)
    assert raised.value.detail


@pytest.mark.parametrize(
    ("network_error", "expected"),
    [
        (requests.ConnectionError("offline"), "Could not connect to ForgeX API"),
        (requests.Timeout("slow"), "timed out"),
    ],
)
def test_network_failures_are_clear(
    monkeypatch: pytest.MonkeyPatch,
    network_error: Exception,
    expected: str,
):
    _replace_request(monkeypatch, network_error)
    with pytest.raises(ForgeXAPIError, match=expected):
        ForgeXAPIClient().start_brief("Design a gripper")


def test_non_json_or_non_object_responses_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    _replace_request(monkeypatch, FakeResponse(200, ValueError("bad json")))
    with pytest.raises(ForgeXAPIError, match="not valid JSON"):
        ForgeXAPIClient().start_brief("Design a gripper")

    _replace_request(monkeypatch, FakeResponse(200, ["unexpected"]))
    with pytest.raises(ForgeXAPIError, match="unexpected format"):
        ForgeXAPIClient().start_brief("Design a gripper")

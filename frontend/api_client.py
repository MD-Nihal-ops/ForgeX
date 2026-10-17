"""Small synchronous client for the existing ForgeX FastAPI backend."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import requests

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 15


class ForgeXAPIError(Exception):
    """An HTTP, network, or response-format error from the ForgeX API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def _format_detail(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        messages = []
        for item in detail:
            if isinstance(item, dict):
                location = ".".join(str(part) for part in item.get("loc", []))
                message = item.get("msg", "Invalid value")
                messages.append(f"{location}: {message}" if location else str(message))
            else:
                messages.append(str(item))
        return "\n".join(messages)
    if detail is None:
        return "The API did not provide error details."
    return str(detail)


class ForgeXAPIClient:
    """Calls ForgeX API endpoints without implementing engineering logic."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        configured_url = base_url or os.getenv("FORGEX_API_URL", DEFAULT_API_URL)
        self.base_url = configured_url.strip().rstrip("/")
        if not self.base_url:
            raise ValueError("ForgeX API base URL cannot be empty.")
        self.timeout = timeout
        self._session = session or requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                json=body,
                params=params,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise ForgeXAPIError(
                f"ForgeX API request timed out after {self.timeout:g} seconds."
            ) from exc
        except requests.ConnectionError as exc:
            raise ForgeXAPIError(
                f"Could not connect to ForgeX API at {self.base_url}. "
                "Check that the backend is running and FORGEX_API_URL is correct."
            ) from exc
        except requests.RequestException as exc:
            raise ForgeXAPIError(f"ForgeX API network request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code >= 400:
                raise ForgeXAPIError(
                    f"ForgeX API returned HTTP {response.status_code} without a JSON error body.",
                    status_code=response.status_code,
                ) from exc
            raise ForgeXAPIError(
                "ForgeX API returned a response that was not valid JSON.",
                status_code=response.status_code,
            ) from exc

        if response.status_code >= 400:
            detail = _format_detail(payload.get("detail") if isinstance(payload, dict) else payload)
            if response.status_code == 422:
                message = f"Validation error (422): {detail}"
            elif response.status_code == 404:
                message = f"Not found (404): {detail}"
            elif response.status_code == 409:
                message = f"Workflow conflict (409): {detail}"
            else:
                message = f"ForgeX API error ({response.status_code}): {detail}"
            raise ForgeXAPIError(
                message,
                status_code=response.status_code,
                detail=detail,
            )
        if not isinstance(payload, dict):
            raise ForgeXAPIError(
                "ForgeX API returned JSON in an unexpected format.",
                status_code=response.status_code,
            )
        return payload

    def start_brief(
        self,
        message: str,
        session_id: str | None = None,
        *,
        product_type: str | None = None,
        product_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"message": message}
        if session_id:
            body["session_id"] = session_id
        if product_type:
            body["product_type"] = product_type
        if product_inputs is not None:
            body["product_inputs"] = product_inputs
        return self._request("POST", "/api/brief/start", body=body)

    def clarify_brief(
        self,
        session_id: str,
        message: str,
        *,
        product_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"session_id": session_id, "message": message}
        if product_inputs is not None:
            body["product_inputs"] = product_inputs
        return self._request(
            "POST",
            "/api/brief/clarify",
            body=body,
        )

    def confirm_brief(
        self,
        session_id: str,
        confirmed_brief: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/brief/confirm",
            body={
                "session_id": session_id,
                "confirmed_brief": confirmed_brief,
            },
        )

    def generate_designs(self, session_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/design/generate",
            body={"session_id": session_id},
        )

    def ask_design(self, session_id: str, question: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/design/ask",
            body={"session_id": session_id, "question": question},
        )

    def generate_cad(self, session_id: str, design_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/design/{quote(design_id, safe='')}/cad",
            body={"session_id": session_id},
        )

    def generate_preview(self, session_id: str, design_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/design/{quote(design_id, safe='')}/preview",
            body={"session_id": session_id},
        )

    def create_analysis(
        self,
        session_id: str,
        design_id: str,
        analysis_type: str,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/analysis/create",
            body={
                "session_id": session_id,
                "design_id": design_id,
                "analysis_type": analysis_type,
                "inputs": inputs,
            },
        )

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/analysis/{quote(analysis_id, safe='')}",
        )

    def get_analysis_results(self, analysis_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/analysis/{quote(analysis_id, safe='')}/results",
        )

    def run_analysis(self, analysis_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/analysis/{quote(analysis_id, safe='')}/run",
        )

    def generate_report(self, session_id: str, design_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/design/{quote(design_id, safe='')}/report",
            body={"session_id": session_id},
        )

    def get_report(self, session_id: str, design_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/design/{quote(design_id, safe='')}/report",
            params={"session_id": session_id},
        )

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

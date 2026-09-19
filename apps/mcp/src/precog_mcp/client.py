"""HTTP client for the Precog REST API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("precog.mcp")

UNAVAILABLE_MESSAGE = "Precog API is unavailable"


class ApiError(RuntimeError):
    """Raised when the Precog API is unreachable or returns an error.

    ``status`` is the HTTP status code when the API answered, or ``None`` for a
    connectivity/timeout failure.
    """

    def __init__(
        self, message: str, *, status: int | None = None, detail: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


PROBLEM_MEDIA_TYPE = "application/problem+json"


def _problem_detail(response: httpx.Response) -> str:
    """Return a sanitized message for an error response.

    Only trust the Precog problem-details media type; never forward an arbitrary
    (possibly proxied) response body to MCP consumers.
    """
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type != PROBLEM_MEDIA_TYPE:
        return f"Precog API error (HTTP {response.status_code})"
    try:
        payload = response.json()
    except ValueError:
        return f"Precog API error (HTTP {response.status_code})"
    title = payload.get("title") or "error"
    detail = payload.get("detail")
    return f"{title}: {detail}" if detail else str(title)


class ForecastApiClient:
    """Minimal async client for ``POST /v1/forecast``."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forecast(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post("/v1/forecast", json=payload)
        except httpx.HTTPError as exc:
            # Transport diagnostics (internal hosts, URLs, TLS/proxy details)
            # stay in logs; consumers get a stable sanitized message.
            logger.warning("Precog API transport failure: %s", exc)
            raise ApiError(UNAVAILABLE_MESSAGE) from exc
        if response.status_code >= 400:
            detail = _problem_detail(response)
            raise ApiError(detail, status=response.status_code, detail=detail)
        try:
            result: dict[str, Any] = response.json()
        except ValueError as exc:
            raise ApiError(
                "Precog API returned a non-JSON response",
                status=response.status_code,
            ) from exc
        return result

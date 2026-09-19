"""HTTP client for the Precog REST API."""

from __future__ import annotations

from typing import Any

import httpx


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


def _problem_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    title = payload.get("title", "error")
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
            raise ApiError(f"cannot reach Precog API: {exc}") from exc
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

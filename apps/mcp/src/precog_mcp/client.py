"""HTTP client for the Precog REST API."""

from __future__ import annotations

from typing import Any

import httpx


class ApiError(RuntimeError):
    """Raised when the Precog API is unreachable or returns an error."""


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
            raise ApiError(_problem_detail(response))
        result: dict[str, Any] = response.json()
        return result

"""Synchronous and asynchronous clients for the Precog REST execution API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import ValidationError as PydanticValidationError

from precog_client.errors import (
    PrecogAPIError,
    PrecogConnectionError,
    PrecogError,
    PrecogTimeoutError,
    PrecogValidationError,
)
from precog_schemas import (
    Capabilities,
    ForecastRequest,
    ForecastResponse,
    HistoricalSeries,
    KnownFutureSeries,
)

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
SeriesLike = HistoricalSeries | Mapping[str, Any]


def build_forecast_request(
    *,
    horizon: int,
    targets: Sequence[SeriesLike],
    past_covariates: Sequence[SeriesLike] | None = None,
    known_future_covariates: Sequence[SeriesLike] | None = None,
    quantiles: Sequence[float] | None = None,
) -> ForecastRequest:
    """Build a canonical execution request, raising a typed client error locally."""
    try:
        return ForecastRequest(
            horizon=horizon,
            targets=[HistoricalSeries.model_validate(item) for item in targets],
            past_covariates=[
                HistoricalSeries.model_validate(item) for item in (past_covariates or [])
            ],
            known_future_covariates=[
                KnownFutureSeries.model_validate(item) for item in (known_future_covariates or [])
            ],
            quantiles=list(quantiles or []),
        )
    except (PydanticValidationError, ValueError) as exc:
        raise PrecogValidationError(str(exc)) from exc


def _media_type(response: httpx.Response) -> str | None:
    raw = response.headers.get("content-type")
    return raw.split(";")[0].strip().lower() if raw else None


def _api_error(response: httpx.Response) -> PrecogAPIError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    payload = body if isinstance(body, dict) else {}
    title = payload.get("title") or response.reason_phrase or "error"
    detail = payload.get("detail")
    return PrecogAPIError(
        response.status_code,
        title,
        detail,
        payload,
        media_type=_media_type(response),
    )


def _parse_forecast_response(response: httpx.Response) -> ForecastResponse:
    try:
        return ForecastResponse.model_validate(response.json())
    except (ValueError, PydanticValidationError) as exc:
        raise PrecogError("Precog API returned a malformed forecast response") from exc


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise PrecogError("Precog API returned a non-JSON response") from exc
    if not isinstance(body, dict):
        raise PrecogError("Precog API returned a non-object response")
    return body


def _parse_capabilities(response: httpx.Response) -> Capabilities:
    try:
        return Capabilities.model_validate(response.json())
    except (ValueError, PydanticValidationError) as exc:
        raise PrecogError("Precog API returned malformed capabilities") from exc


class PrecogClient:
    """Synchronous execution client.

    Example:
        >>> with PrecogClient("http://localhost:8000") as client:
        ...     response = client.forecast(
        ...         horizon=4,
        ...         targets=[{"id": "a", "values": [1.0, 2.0, 3.0]}],
        ...     )
        ...     response.targets[0].forecast
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 300.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._client = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PrecogClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def forecast(
        self,
        *,
        horizon: int,
        targets: Sequence[SeriesLike],
        past_covariates: Sequence[SeriesLike] | None = None,
        known_future_covariates: Sequence[SeriesLike] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> ForecastResponse:
        """Build a canonical execution request and call ``POST /v1/forecast``.

        ``targets`` are forecast jointly. ``quantiles`` defaults to empty, which
        means a point-only forecast.
        """
        request = build_forecast_request(
            horizon=horizon,
            targets=targets,
            past_covariates=past_covariates,
            known_future_covariates=known_future_covariates,
            quantiles=quantiles,
        )
        return self.forecast_request(request)

    def forecast_request(self, request: ForecastRequest) -> ForecastResponse:
        """Send an already-built :class:`ForecastRequest`."""
        return _parse_forecast_response(self._post(request.model_dump(mode="json")))

    def capabilities(self) -> Capabilities:
        """Return the execution/runtime capabilities advertised by the server."""
        return _parse_capabilities(self._capabilities_response())

    def capabilities_payload(self) -> dict[str, Any]:
        """Return the raw capabilities object without typed validation.

        Intended for a caller that needs only a narrow subset (the MCP semantic
        resource) and must not couple to unrelated execution capability fields.
        """
        return _json_object(self._capabilities_response())

    def _capabilities_response(self) -> httpx.Response:
        try:
            response = self._client.get("/v1/capabilities")
        except httpx.TimeoutException as exc:
            raise PrecogTimeoutError(f"request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise PrecogConnectionError(f"cannot reach {self._base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise _api_error(response)
        return response

    def _post(self, payload: dict[str, Any]) -> httpx.Response:
        last_error: PrecogError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.post("/v1/forecast", json=payload)
            except httpx.TimeoutException as exc:
                last_error = PrecogTimeoutError(f"request timed out: {exc}")
            except httpx.TransportError as exc:
                last_error = PrecogConnectionError(f"cannot reach {self._base_url}: {exc}")
            else:
                if response.status_code < 400:
                    return response
                if response.status_code in RETRY_STATUS and attempt < self._max_retries:
                    self._sleep(attempt, response)
                    continue
                raise _api_error(response)
            if attempt < self._max_retries:
                self._sleep(attempt, None)
                continue
            raise last_error
        raise last_error or PrecogError("request failed")

    def _sleep(self, attempt: int, response: httpx.Response | None) -> None:
        if delay := _retry_delay(self._backoff_factor, attempt, response):
            time.sleep(delay)


class AsyncPrecogClient:
    """Asynchronous execution client with the same contract as :class:`PrecogClient`.

    Use it as an async context manager (or call :meth:`aclose`).
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 300.0,
        max_retries: int = 2,
        backoff_factor: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> AsyncPrecogClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def forecast(
        self,
        *,
        horizon: int,
        targets: Sequence[SeriesLike],
        past_covariates: Sequence[SeriesLike] | None = None,
        known_future_covariates: Sequence[SeriesLike] | None = None,
        quantiles: Sequence[float] | None = None,
    ) -> ForecastResponse:
        """Build a canonical execution request and call ``POST /v1/forecast``."""
        request = build_forecast_request(
            horizon=horizon,
            targets=targets,
            past_covariates=past_covariates,
            known_future_covariates=known_future_covariates,
            quantiles=quantiles,
        )
        return await self.forecast_request(request)

    async def forecast_request(self, request: ForecastRequest) -> ForecastResponse:
        """Send an already-built :class:`ForecastRequest`."""
        return _parse_forecast_response(await self._post(request.model_dump(mode="json")))

    async def capabilities(self) -> Capabilities:
        """Return the execution/runtime capabilities advertised by the server."""
        return _parse_capabilities(await self._capabilities_response())

    async def capabilities_payload(self) -> dict[str, Any]:
        """Return the raw capabilities object without typed validation.

        Intended for a caller that needs only a narrow subset (the MCP semantic
        resource) and must not couple to unrelated execution capability fields.
        """
        return _json_object(await self._capabilities_response())

    async def _capabilities_response(self) -> httpx.Response:
        try:
            response = await self._client.get("/v1/capabilities")
        except httpx.TimeoutException as exc:
            raise PrecogTimeoutError(f"request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise PrecogConnectionError(f"cannot reach {self._base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise _api_error(response)
        return response

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        last_error: PrecogError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post("/v1/forecast", json=payload)
            except httpx.TimeoutException as exc:
                last_error = PrecogTimeoutError(f"request timed out: {exc}")
            except httpx.TransportError as exc:
                last_error = PrecogConnectionError(f"cannot reach {self._base_url}: {exc}")
            else:
                if response.status_code < 400:
                    return response
                if response.status_code in RETRY_STATUS and attempt < self._max_retries:
                    await self._sleep(attempt, response)
                    continue
                raise _api_error(response)
            if attempt < self._max_retries:
                await self._sleep(attempt, None)
                continue
            raise last_error
        raise last_error or PrecogError("request failed")

    async def _sleep(self, attempt: int, response: httpx.Response | None) -> None:
        if delay := _retry_delay(self._backoff_factor, attempt, response):
            await asyncio.sleep(delay)


def _retry_delay(backoff_factor: float, attempt: int, response: httpx.Response | None) -> float:
    delay = backoff_factor * (2**attempt)
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                pass
    return delay


__all__ = ["AsyncPrecogClient", "PrecogClient", "build_forecast_request"]

"""Synchronous client for the Precog REST API."""

from __future__ import annotations

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


class PrecogClient:
    """Forecast client.

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
        try:
            request = ForecastRequest(
                horizon=horizon,
                targets=[HistoricalSeries.model_validate(item) for item in targets],
                past_covariates=[
                    HistoricalSeries.model_validate(item) for item in (past_covariates or [])
                ],
                known_future_covariates=[
                    KnownFutureSeries.model_validate(item)
                    for item in (known_future_covariates or [])
                ],
                quantiles=list(quantiles or []),
            )
        except (PydanticValidationError, ValueError) as exc:
            raise PrecogValidationError(str(exc)) from exc
        return self.forecast_request(request)

    def forecast_request(self, request: ForecastRequest) -> ForecastResponse:
        """Send an already-built :class:`ForecastRequest`."""
        response = self._post(request.model_dump(mode="json"))
        try:
            return ForecastResponse.model_validate(response.json())
        except PydanticValidationError as exc:
            raise PrecogError(f"unexpected response from API: {exc}") from exc

    def capabilities(self) -> Capabilities:
        """Return the model and API capabilities advertised by the server."""
        try:
            response = self._client.get("/v1/capabilities")
        except httpx.TimeoutException as exc:
            raise PrecogTimeoutError(f"request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise PrecogConnectionError(f"cannot reach {self._base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise _api_error(response)
        try:
            return Capabilities.model_validate(response.json())
        except PydanticValidationError as exc:
            raise PrecogError(f"unexpected response from API: {exc}") from exc

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
        delay = self._backoff_factor * (2**attempt)
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    pass
        if delay > 0:
            time.sleep(delay)


def _api_error(response: httpx.Response) -> PrecogAPIError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    title = body.get("title") or response.reason_phrase or "error"
    return PrecogAPIError(response.status_code, title, body.get("detail"), body)

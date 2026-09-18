from __future__ import annotations

import httpx
import pytest

from precog_client import (
    PrecogAPIError,
    PrecogClient,
    PrecogConnectionError,
    PrecogTimeoutError,
    PrecogValidationError,
)
from precog_schemas import ForecastResponse

pytestmark = pytest.mark.unit

VALID_RESPONSE = {
    "model": "timesfm-3.0",
    "horizon": 2,
    "quantile_levels": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
    "results": [{"id": "a", "forecast": [1.0, 2.0]}],
    "usage": {"latency_ms": 1.0, "context_len": 3},
}


def _client(handler, **kwargs: object) -> PrecogClient:
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("backoff_factor", 0.0)
    return PrecogClient("http://api.test", transport=httpx.MockTransport(handler), **kwargs)  # type: ignore[arg-type]


def test_forecast_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/forecast"
        return httpx.Response(200, json=VALID_RESPONSE)

    with _client(handler) as client:
        response = client.forecast(horizon=2, series=[{"id": "a", "target": [1.0, 2.0, 3.0]}])

    assert isinstance(response, ForecastResponse)
    assert response.results[0].forecast == [1.0, 2.0]


def test_api_error_is_mapped() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            422,
            headers={"content-type": "application/problem+json"},
            json={"title": "Unprocessable Entity", "detail": "horizon exceeds max"},
        )

    with _client(handler) as client:
        with pytest.raises(PrecogAPIError) as excinfo:
            client.forecast(horizon=99999, series=[{"id": "a", "target": [1.0]}])

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "horizon exceeds max"
    assert calls == 1  # 422 is not retryable


def test_retries_transient_errors_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=VALID_RESPONSE)

    with _client(handler, max_retries=1) as client:
        response = client.forecast(horizon=2, series=[{"id": "a", "target": [1.0, 2.0, 3.0]}])

    assert calls == 2
    assert response.model == "timesfm-3.0"


def test_invalid_payload_is_rejected_locally() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=VALID_RESPONSE)

    with _client(handler) as client:
        with pytest.raises(PrecogValidationError):
            client.forecast(
                horizon=2,
                series=[{"id": "a", "target": [1.0, 2.0], "past_covariates": {"x": [1.0]}}],
            )

    assert called is False


def test_connection_error_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _client(handler) as client:
        with pytest.raises(PrecogConnectionError):
            client.forecast(horizon=1, series=[{"id": "a", "target": [1.0]}])


def test_timeout_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    with _client(handler) as client:
        with pytest.raises(PrecogTimeoutError):
            client.forecast(horizon=1, series=[{"id": "a", "target": [1.0]}])

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from precog_client import (
    AsyncPrecogClient,
    PrecogAPIError,
    PrecogClient,
    PrecogConnectionError,
    PrecogTimeoutError,
    PrecogValidationError,
)

pytestmark = pytest.mark.unit

VALID_RESPONSE = {
    "horizon": 2,
    "targets": [
        {
            "id": "a",
            "forecast": [1.0, 2.0],
            "quantiles": [{"level": 0.5, "values": [1.0, 2.0]}],
        }
    ],
    "model": {"id": "google/timesfm-3.0-pytorch", "revision": None},
    "usage": {"latency_ms": 1.0, "context_len": 3},
}

VALID_CAPABILITIES = {
    "engine": "timesfm3",
    "model": {"id": "google/timesfm-3.0-pytorch", "revision": None},
    "device": "cpu",
    "limits": {"max_horizon": 1024, "max_context": 15360, "max_variates": 32, "max_targets": 64},
    "quantile_levels": [0.1, 0.5, 0.9],
    "features": {
        "point_forecast": True,
        "probabilistic_forecast": True,
        "past_covariates": True,
        "known_future_covariates": True,
        "joint_targets": True,
    },
    "auth_required": False,
}


def _async_client(handler: Any, **kwargs: Any) -> AsyncPrecogClient:
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("backoff_factor", 0.0)
    return AsyncPrecogClient("http://api.test", transport=httpx.MockTransport(handler), **kwargs)


def _sync_client(handler: Any, **kwargs: Any) -> PrecogClient:
    kwargs.setdefault("max_retries", 0)
    kwargs.setdefault("backoff_factor", 0.0)
    return PrecogClient("http://api.test", transport=httpx.MockTransport(handler), **kwargs)


def test_async_forecast_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/forecast"
        return httpx.Response(200, json=VALID_RESPONSE)

    async def scenario() -> None:
        async with _async_client(handler) as client:
            response = await client.forecast(
                horizon=2,
                targets=[{"id": "a", "values": [1.0, 2.0, 3.0]}],
                quantiles=[0.5],
            )
        assert response.targets[0].forecast == [1.0, 2.0]
        assert response.model.id == "google/timesfm-3.0-pytorch"

    asyncio.run(scenario())


def test_sync_and_async_parity_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=VALID_RESPONSE)

    sync_response = _sync_client(handler).forecast(
        horizon=2, targets=[{"id": "a", "values": [1.0, 2.0, 3.0]}], quantiles=[0.5]
    )

    async def scenario() -> dict[str, Any]:
        return (
            await _async_client(handler).forecast(
                horizon=2,
                targets=[{"id": "a", "values": [1.0, 2.0, 3.0]}],
                quantiles=[0.5],
            )
        ).model_dump(mode="json")

    assert asyncio.run(scenario()) == sync_response.model_dump(mode="json")


def test_async_capabilities_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/capabilities"
        return httpx.Response(200, json=VALID_CAPABILITIES)

    async def scenario() -> None:
        async with _async_client(handler) as client:
            capabilities = await client.capabilities()
            payload = await client.capabilities_payload()
        assert capabilities.limits.max_horizon == 1024
        assert capabilities.features.joint_targets is True
        assert payload["limits"]["max_context"] == 15360

    asyncio.run(scenario())


def test_async_api_error_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            headers={"content-type": "application/problem+json"},
            json={"title": "Unprocessable Entity", "detail": "horizon exceeds max"},
        )

    async def scenario() -> None:
        with pytest.raises(PrecogAPIError) as excinfo:
            await _async_client(handler).forecast(
                horizon=99999, targets=[{"id": "a", "values": [1.0]}]
            )
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == "horizon exceeds max"
        assert excinfo.value.media_type == "application/problem+json"

    asyncio.run(scenario())


def test_async_retries_transient_statuses_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=VALID_RESPONSE)

    async def scenario() -> None:
        client = _async_client(handler, max_retries=1)
        response = await client.forecast(horizon=2, targets=[{"id": "a", "values": [1, 2, 3]}])
        assert response.horizon == 2
        await client.aclose()

    asyncio.run(scenario())
    assert calls == 2


def test_async_retries_429_and_honours_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, text="slow down")
        return httpx.Response(200, json=VALID_RESPONSE)

    async def scenario() -> None:
        client = _async_client(handler, max_retries=1)
        response = await client.forecast(horizon=2, targets=[{"id": "a", "values": [1, 2, 3]}])
        assert response.horizon == 2
        await client.aclose()

    asyncio.run(scenario())
    assert calls == 2


def test_async_connection_error_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async def scenario() -> None:
        with pytest.raises(PrecogConnectionError):
            await _async_client(handler).forecast(horizon=1, targets=[{"id": "a", "values": [1]}])

    asyncio.run(scenario())


def test_async_timeout_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    async def scenario() -> None:
        with pytest.raises(PrecogTimeoutError):
            await _async_client(handler).forecast(horizon=1, targets=[{"id": "a", "values": [1]}])

    asyncio.run(scenario())


def test_async_invalid_payload_is_rejected_locally() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=VALID_RESPONSE)

    async def scenario() -> None:
        with pytest.raises(PrecogValidationError):
            await _async_client(handler).forecast(
                horizon=2,
                targets=[{"id": "a", "values": [1.0, 2.0, 3.0]}],
                past_covariates=[{"id": "p", "values": [1.0]}],
            )

    asyncio.run(scenario())
    assert called is False

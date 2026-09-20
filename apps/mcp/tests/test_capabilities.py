from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from precog_client import AsyncPrecogClient
from precog_mcp.capabilities import (
    BACKTEST_METRICS,
    limits_from_rest,
    load_capabilities,
    static_capabilities,
)
from precog_mcp.models import SEMANTIC_QUANTILE_LEVELS as QUANTILE_LEVELS

pytestmark = pytest.mark.unit


def _rest_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "engine": "timesfm3",
        "model": {"id": "google/timesfm-3.0", "revision": None},
        "device": "cpu",
        "limits": {
            "max_horizon": 1024,
            "max_context": 15360,
            "max_variates": 32,
            "max_targets": 64,
        },
        "quantile_levels": list(QUANTILE_LEVELS),
        "features": {
            "point_forecast": True,
            "probabilistic_forecast": True,
            "past_covariates": True,
            "known_future_covariates": True,
            "joint_targets": True,
        },
        "auth_required": False,
    }
    payload.update(overrides)
    return payload


def _client(handler) -> AsyncPrecogClient:
    return AsyncPrecogClient("http://api.test", transport=httpx.MockTransport(handler))


def test_static_capabilities_are_semantic_only() -> None:
    caps = static_capabilities()
    assert caps.forecast.supported is True
    assert caps.forecast.multiple_targets is True
    assert caps.forecast.past_covariates is True
    assert caps.forecast.known_future_covariates is True
    assert caps.forecast.probabilistic_forecast is True
    assert caps.backtest.supported is True
    assert caps.backtest.metrics == list(BACKTEST_METRICS)
    assert caps.backtest.interval_coverage is True
    assert caps.limits.max_horizon is None
    assert caps.limits.max_context_length is None
    assert caps.limits.quantile_levels == list(QUANTILE_LEVELS)

    dumped = caps.model_dump(mode="json")
    for backend_only in (
        "engine",
        "device",
        "model_id",
        "max_variates",
        "max_targets",
        "features",
        "auth_required",
    ):
        assert backend_only not in dumped
        assert backend_only not in dumped["limits"]


def test_limits_from_rest_keeps_public_limits_only() -> None:
    limits = limits_from_rest(_rest_payload())
    assert limits.max_horizon == 1024
    assert limits.max_context_length == 15360
    assert limits.quantile_levels == list(QUANTILE_LEVELS)
    assert set(limits.model_dump()) == {"max_horizon", "max_context_length", "quantile_levels"}


def test_limits_from_rest_owns_quantiles_and_ignores_unrelated_fields() -> None:
    # Divergent quantile levels plus unrelated backend fields must not change
    # the MCP-advertised quantiles or break reading the runtime limits.
    payload = _rest_payload(quantile_levels=[0.5], unexpected={"a": 1})
    payload["engine"] = "some-future-engine"
    limits = limits_from_rest(payload)
    assert limits.max_horizon == 1024
    assert limits.max_context_length == 15360
    assert limits.quantile_levels == list(QUANTILE_LEVELS)


def test_limits_from_rest_requires_the_runtime_limit_fields() -> None:
    with pytest.raises(ValidationError):
        limits_from_rest({"quantile_levels": list(QUANTILE_LEVELS)})


def test_load_capabilities_needs_only_the_runtime_limit_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"limits": {"max_horizon": 512, "max_context": 2048}})

    caps = asyncio.run(load_capabilities(_client(handler)))
    assert caps.limits.max_horizon == 512
    assert caps.limits.max_context_length == 2048
    assert caps.limits.quantile_levels == list(QUANTILE_LEVELS)


def test_load_capabilities_falls_back_when_runtime_limits_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"limits": {"max_horizon": 512}})

    caps = asyncio.run(load_capabilities(_client(handler)))
    assert caps.limits.max_horizon is None
    assert caps.limits.max_context_length is None
    assert caps.limits.quantile_levels == list(QUANTILE_LEVELS)


def test_load_capabilities_includes_effective_limits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/capabilities"
        return httpx.Response(200, json=_rest_payload())

    caps = asyncio.run(load_capabilities(_client(handler)))
    assert caps.limits.max_horizon == 1024
    assert caps.limits.max_context_length == 15360


def test_load_capabilities_falls_back_when_api_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("http://internal.example:9999")

    caps = asyncio.run(load_capabilities(_client(handler)))
    assert caps.limits.max_horizon is None
    assert caps.limits.max_context_length is None
    assert caps.forecast.supported is True
    assert caps.limits.quantile_levels == list(QUANTILE_LEVELS)


def test_load_capabilities_falls_back_on_malformed_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    caps = asyncio.run(load_capabilities(_client(handler)))
    assert caps.limits.max_horizon is None
    assert caps.forecast.supported is True


def test_load_capabilities_falls_back_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"title": "Service Unavailable"})

    caps = asyncio.run(load_capabilities(_client(handler)))
    assert caps.limits.max_horizon is None

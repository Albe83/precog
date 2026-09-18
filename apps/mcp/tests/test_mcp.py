from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from precog_mcp.__main__ import transport_security
from precog_mcp.client import ForecastApiClient
from precog_mcp.config import Settings
from precog_mcp.server import create_server, run_forecast, run_forecast_batch

pytestmark = pytest.mark.unit

PAYLOAD = {
    "mode": "univariate",
    "horizon": 2,
    "series": [{"id": "a", "target": [1.0, 2.0, 3.0]}],
    "options": {"return_quantiles": True},
}


def _client(handler) -> ForecastApiClient:
    return ForecastApiClient("http://api.test", transport=httpx.MockTransport(handler))


def test_forecast_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/forecast"
        assert request.headers["content-type"] == "application/json"
        return httpx.Response(200, json={"model": "timesfm-3.0", "results": [{"id": "a"}]})

    result = asyncio.run(run_forecast(_client(handler), PAYLOAD))
    assert result["model"] == "timesfm-3.0"


def test_api_error_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            headers={"content-type": "application/problem+json"},
            json={"title": "Unprocessable Entity", "detail": "horizon exceeds max"},
        )

    result = asyncio.run(run_forecast(_client(handler), PAYLOAD))
    assert "horizon exceeds max" in result["error"]


def test_unreachable_api_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = asyncio.run(run_forecast(_client(handler), PAYLOAD))
    assert "cannot reach Precog API" in result["error"]


def test_invalid_request_is_rejected_before_calling_api() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    result = asyncio.run(run_forecast(_client(handler), {"mode": "univariate", "series": []}))
    assert result["error"] == "invalid forecast request"
    assert called is False


def test_server_registers_forecast_tool() -> None:
    client = _client(lambda request: httpx.Response(200, json={}))
    server = create_server(Settings(api_url="http://api.test"), client=client)
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert {"forecast", "forecast_batch"} <= names


def test_forecast_batch_preserves_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "timesfm-3.0"})

    payloads: list[dict[str, Any]] = [
        {"mode": "univariate", "horizon": 1, "series": [{"id": "a", "target": [1.0]}]},
        {"mode": "univariate", "horizon": 1, "series": [{"id": "b", "target": [2.0]}]},
        {"mode": "univariate", "horizon": 1, "series": [{"id": "c", "target": [3.0]}]},
    ]
    results = asyncio.run(run_forecast_batch(_client(handler), payloads, concurrency=2))
    assert len(results) == 3
    assert all(r["model"] == "timesfm-3.0" for r in results)


def test_forecast_batch_maps_per_item_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "timesfm-3.0"})

    payloads: list[dict[str, Any]] = [
        {"mode": "univariate", "horizon": 1, "series": [{"id": "a", "target": [1.0]}]},
        {"mode": "univariate", "series": []},  # invalid
    ]
    results = asyncio.run(run_forecast_batch(_client(handler), payloads))
    assert results[0]["model"] == "timesfm-3.0"
    assert results[1]["error"] == "invalid forecast request"


def test_transport_security_defaults_to_localhost() -> None:
    security = transport_security("")
    assert security.enable_dns_rebinding_protection is True
    assert "localhost:*" in security.allowed_hosts


def test_transport_security_accepts_extra_hosts() -> None:
    security = transport_security("precog-mcp.cortana-mcp-servers.svc:8000")
    assert security.enable_dns_rebinding_protection is True
    assert "precog-mcp.cortana-mcp-servers.svc:8000" in security.allowed_hosts


def test_transport_security_wildcard_disables_protection() -> None:
    security = transport_security("*")
    assert security.enable_dns_rebinding_protection is False

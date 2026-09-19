"""Contract tests tying docs/mcp.md examples to the registered MCP surface."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from precog_mcp.client import ForecastApiClient
from precog_mcp.config import Settings
from precog_mcp.server import create_server
from precog_schemas import QUANTILE_LEVELS

INTEGRATION_CONTEXT = [31.2, 32.8, 35.1, 37.4, 41.2, 43.7]

MINIMAL_REQUEST = {
    "targets": [{"id": "cpu_usage", "values": INTEGRATION_CONTEXT}],
    "horizon": 3,
}

FULL_REQUEST = {
    "targets": [
        {"id": "cpu_usage", "values": INTEGRATION_CONTEXT},
        {"id": "memory_usage", "values": [61.0, 61.4, 62.1, 63.0, 64.8, 65.1]},
    ],
    "horizon": 3,
    "past_covariates": [{"id": "request_rate", "values": [1200, 1250, 1410, 1530, 1710, 1800]}],
    "known_future_covariates": [
        {"id": "maintenance_window", "history": [0, 0, 0, 0, 0, 0], "future": [0, 1, 1]}
    ],
    "quantiles": [0.1, 0.9],
}

BATCH_REQUEST = {
    "requests": [
        {"targets": [{"id": "cpu_usage", "values": INTEGRATION_CONTEXT}], "horizon": 2},
        {
            "targets": [{"id": "disk_usage", "values": [10.0, 10.4, 10.9, 11.2, 11.5, 12.0]}],
            "horizon": 99999,
        },
    ]
}


def _rest_payload(ids: list[str], horizon: int) -> dict[str, Any]:
    return {
        "model": "timesfm-3.0",
        "horizon": horizon,
        "quantile_levels": list(QUANTILE_LEVELS),
        "results": [
            {
                "id": series_id,
                "forecast": [1.0] * horizon,
                "quantiles": [[float(index)] * horizon for index in range(len(QUANTILE_LEVELS))],
            }
            for series_id in ids
        ],
        "usage": {"latency_ms": 1.0, "context_len": 6},
    }


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if body["horizon"] > 1024:
        return httpx.Response(422, json={"title": "Unprocessable Entity", "detail": "too long"})
    ids = [series["id"] for series in body["series"]]
    return httpx.Response(200, json=_rest_payload(ids, body["horizon"]))


async def _run(coro_factory):
    settings = Settings(api_url="http://api.test")
    client = ForecastApiClient("http://api.test", transport=httpx.MockTransport(handler))
    server = create_server(settings, client=client)
    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://localhost") as http:
            async with streamable_http_client("http://localhost/mcp", http_client=http) as (
                read,
                write,
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await coro_factory(session)


def test_registered_forecast_schema_matches_documented_contract() -> None:
    async def scenario(session: ClientSession):
        return await session.list_tools()

    tools = asyncio.run(_run(scenario))
    forecast = next(tool for tool in tools.tools if tool.name == "forecast")
    assert forecast.input_schema["required"] == ["targets", "horizon"]
    assert list(forecast.input_schema["properties"]) == [
        "targets",
        "horizon",
        "past_covariates",
        "known_future_covariates",
        "quantiles",
    ]
    assert forecast.input_schema["additionalProperties"] is False
    assert list(forecast.output_schema["properties"]) == ["horizon", "targets", "model", "warnings"]
    assert forecast.output_schema["required"] == ["horizon", "targets", "model"]

    batch = next(tool for tool in tools.tools if tool.name == "forecast_batch")
    assert list(batch.input_schema["properties"]) == ["requests"]
    assert batch.input_schema["additionalProperties"] is False


def test_documented_minimal_payload_is_valid() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", MINIMAL_REQUEST)

    result = asyncio.run(_run(scenario))
    assert result.is_error is False
    assert result.structured_content["horizon"] == 3
    assert result.structured_content["model"] == {"id": "timesfm-3.0"}


def test_documented_full_payload_is_valid() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FULL_REQUEST)

    result = asyncio.run(_run(scenario))
    assert result.is_error is False
    structured = result.structured_content
    assert [target["id"] for target in structured["targets"]] == ["cpu_usage", "memory_usage"]
    assert list(structured["targets"][0]["quantiles"]) == ["0.1", "0.9"]
    assert structured["warnings"] == []


def test_documented_invalid_length_error_shape() -> None:
    invalid = {
        "targets": [{"id": "cpu_usage", "values": INTEGRATION_CONTEXT}],
        "horizon": 3,
        "past_covariates": [{"id": "request_rate", "values": [1, 2, 3, 4, 5]}],
    }

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", invalid)

    result = asyncio.run(_run(scenario))
    assert result.is_error is True
    payload = json.loads(result.content[0].text)
    assert payload["code"] == "INVALID_REQUEST"
    assert payload["details"]["errors"]


def test_documented_batch_example() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", BATCH_REQUEST)

    result = asyncio.run(_run(scenario))
    assert result.is_error is False
    items = result.structured_content["results"]
    assert items[0]["ok"] is True
    assert items[1]["ok"] is False
    assert items[1]["error"]["code"] == "FORECAST_REJECTED"

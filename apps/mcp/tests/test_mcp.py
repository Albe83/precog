from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from precog_mcp.__main__ import transport_security
from precog_mcp.client import ForecastApiClient
from precog_mcp.config import Settings
from precog_mcp.observability import TOOL_CALLS, metrics_handler, record_tool_call
from precog_mcp.server import create_server, run_forecast, run_forecast_batch
from precog_schemas import QUANTILE_LEVELS

pytestmark = pytest.mark.unit

FORECAST_ARGS = {"targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}], "horizon": 2}

LEGACY_PAYLOAD = {
    "mode": "univariate",
    "horizon": 2,
    "series": [{"id": "a", "target": [1.0, 2.0, 3.0]}],
    "options": {"return_quantiles": True},
}


def _client(handler) -> ForecastApiClient:
    return ForecastApiClient("http://api.test", transport=httpx.MockTransport(handler))


def _rest_payload(ids: list[str], horizon: int = 2) -> dict[str, Any]:
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
        "usage": {"latency_ms": 1.0, "context_len": 3},
    }


def _ok_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    ids = [series["id"] for series in body["series"]]
    return httpx.Response(200, json=_rest_payload(ids, body["horizon"]))


async def _run(handler, coro_factory, settings: Settings | None = None):
    settings = settings or Settings(api_url="http://api.test")
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


def _envelope(result) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def test_list_tools_exposes_the_new_contract() -> None:
    async def scenario(session: ClientSession) -> dict[str, Any]:
        tools = await session.list_tools()
        return {tool.name: tool for tool in tools.tools}

    tools = asyncio.run(_run(_ok_handler, scenario))
    forecast = tools["forecast"]
    assert list(forecast.input_schema["properties"]) == [
        "targets",
        "horizon",
        "past_covariates",
        "known_future_covariates",
        "quantiles",
    ]
    assert forecast.input_schema["required"] == ["targets", "horizon"]
    assert forecast.input_schema.get("additionalProperties") is False
    assert forecast.output_schema is not None
    assert list(forecast.output_schema["properties"]) == ["horizon", "targets", "model", "warnings"]
    for removed in ("mode", "series", "return_quantiles"):
        assert removed not in forecast.input_schema["properties"]

    batch = tools["forecast_batch"]
    assert list(batch.input_schema["properties"]) == ["requests"]
    assert batch.input_schema.get("additionalProperties") is False


def test_forecast_success_returns_structured_content() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is False
    structured = result.structured_content
    assert structured["horizon"] == 2
    assert structured["model"] == {"id": "timesfm-3.0"}
    assert structured["warnings"] == []
    assert structured["targets"][0]["id"] == "a"
    assert list(structured["targets"][0]["quantiles"]) == ["0.1", "0.9"]


def test_removed_mode_field_is_rejected() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", {**FORECAST_ARGS, "mode": "univariate"})

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "INVALID_REQUEST"
    assert "mode" in payload["details"]["unknown"]


def test_invalid_length_is_rejected_with_details() -> None:
    args = {
        "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
        "horizon": 2,
        "past_covariates": [{"id": "p", "values": [1.0]}],
    }

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", args)

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "INVALID_REQUEST"
    assert payload["details"]["errors"]


def test_rest_rejection_maps_to_forecast_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"title": "Unprocessable Entity", "detail": "too long"})

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "FORECAST_REJECTED"


def test_unreachable_api_maps_to_api_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "API_UNAVAILABLE"


def test_server_error_maps_to_inference_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"title": "Internal Server Error"})

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "INFERENCE_FAILED"


def test_malformed_success_maps_to_upstream_contract_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "UPSTREAM_CONTRACT_ERROR"


def test_failure_never_returns_nominal_forecast_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(handler, scenario))
    assert result.is_error is True
    assert result.structured_content is None


def test_legacy_forecast_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "timesfm-3.0", "results": [{"id": "a"}]})

    result = asyncio.run(run_forecast(_client(handler), LEGACY_PAYLOAD))
    assert result["model"] == "timesfm-3.0"


def test_legacy_api_error_is_mapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            headers={"content-type": "application/problem+json"},
            json={"title": "Unprocessable Entity", "detail": "horizon exceeds max"},
        )

    result = asyncio.run(run_forecast(_client(handler), LEGACY_PAYLOAD))
    assert "horizon exceeds max" in result["error"]


def test_legacy_unreachable_api_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = asyncio.run(run_forecast(_client(handler), LEGACY_PAYLOAD))
    assert "cannot reach Precog API" in result["error"]


def test_legacy_batch_preserves_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "timesfm-3.0"})

    payloads: list[dict[str, Any]] = [
        {"mode": "univariate", "horizon": 1, "series": [{"id": "a", "target": [1.0]}]},
        {"mode": "univariate", "horizon": 1, "series": [{"id": "b", "target": [2.0]}]},
        {"mode": "univariate", "horizon": 1, "series": [{"id": "c", "target": [3.0]}]},
    ]
    results = asyncio.run(run_forecast_batch(_client(handler), payloads, concurrency=2))
    assert len(results) == 3
    assert all(result["model"] == "timesfm-3.0" for result in results)


def test_legacy_batch_maps_per_item_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "timesfm-3.0"})

    payloads: list[dict[str, Any]] = [
        {"mode": "univariate", "horizon": 1, "series": [{"id": "a", "target": [1.0]}]},
        {"mode": "univariate", "series": []},
    ]
    results = asyncio.run(run_forecast_batch(_client(handler), payloads))
    assert results[0]["model"] == "timesfm-3.0"
    assert results[1]["error"] == "invalid forecast request"


def test_metrics_count_success_and_error_protocol_calls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_rest_payload(["a"]))

    before_ok = TOOL_CALLS.labels("forecast", "ok")._value.get()
    before_err = TOOL_CALLS.labels("forecast", "error")._value.get()

    async def scenario(session: ClientSession) -> None:
        await session.call_tool("forecast", FORECAST_ARGS)
        await session.call_tool("forecast", {**FORECAST_ARGS, "mode": "univariate"})

    asyncio.run(_run(handler, scenario))
    assert TOOL_CALLS.labels("forecast", "ok")._value.get() == before_ok + 1
    assert TOOL_CALLS.labels("forecast", "error")._value.get() == before_err + 1


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


def test_metrics_handler_returns_prometheus() -> None:
    response = asyncio.run(metrics_handler(None))  # type: ignore[arg-type]
    assert response.status_code == 200
    assert b"precog_mcp_tool_calls_total" in response.body


def test_record_tool_call_counts() -> None:
    before = TOOL_CALLS.labels("forecast", "ok")._value.get()
    record_tool_call("forecast", "ok", 0.01)
    after = TOOL_CALLS.labels("forecast", "ok")._value.get()
    assert after == before + 1


def test_http_app_exposes_metrics() -> None:
    client = ForecastApiClient("http://api.test", transport=httpx.MockTransport(_ok_handler))
    server = create_server(Settings(api_url="http://api.test"), client=client)
    app = server.streamable_http_app()

    async def get_metrics() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return await http.get("/metrics")

    response = asyncio.run(get_metrics())
    assert response.status_code == 200
    assert "precog_mcp_tool_calls_total" in response.text

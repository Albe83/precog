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
from precog_mcp.server import create_server
from precog_schemas import QUANTILE_LEVELS

pytestmark = pytest.mark.unit

FORECAST_ARGS = {"targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}], "horizon": 2}
BACKTEST_ARGS = {"targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}], "horizon": 2}


def _rest_payload(ids: list[str], horizon: int = 2) -> dict[str, Any]:
    return {
        "horizon": horizon,
        "targets": [
            {
                "id": series_id,
                "forecast": [1.0] * horizon,
                "quantiles": [
                    {
                        "level": level,
                        "values": [float(row + column) for row in range(horizon)],
                    }
                    for column, level in enumerate(QUANTILE_LEVELS)
                ],
            }
            for series_id in ids
        ],
        "model": {"id": "timesfm-3.0", "revision": None},
        "usage": {"latency_ms": 1.0, "context_len": 3},
    }


def _capabilities_payload() -> dict[str, Any]:
    return {
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


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if request.method == "GET" and request.url.path == "/v1/capabilities":
        return httpx.Response(200, json=_capabilities_payload())
    body = json.loads(request.content)
    ids = [target["id"] for target in body["targets"]]
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
    assert "forecast_batch" not in tools


def test_list_tools_exposes_backtest() -> None:
    async def scenario(session: ClientSession) -> dict[str, Any]:
        tools = await session.list_tools()
        return {tool.name: tool for tool in tools.tools}

    tools = asyncio.run(_run(_ok_handler, scenario))
    backtest = tools["backtest"]
    assert list(backtest.input_schema["properties"]) == [
        "targets",
        "horizon",
        "past_covariates",
        "known_future_covariates",
        "quantiles",
    ]
    assert backtest.input_schema["required"] == ["targets", "horizon"]
    assert backtest.input_schema.get("additionalProperties") is False
    assert backtest.output_schema is not None
    assert list(backtest.output_schema["properties"]) == ["horizon", "targets", "model", "warnings"]


def test_backtest_success_returns_actuals_and_metrics() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("backtest", BACKTEST_ARGS)

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is False
    structured = result.structured_content
    assert structured["horizon"] == 2
    target = structured["targets"][0]
    assert target["id"] == "a"
    assert target["actual"] == [2.0, 3.0]
    assert target["forecast"] == [1.0, 1.0]
    assert target["metrics"]["mae"] == 1.5
    assert target["metrics"]["coverage"] is not None
    assert target["metrics"]["coverage"]["percent"] == 100.0


def test_backtest_holdout_not_shorter_than_series_is_rejected() -> None:
    args = {"targets": [{"id": "a", "values": [1.0, 2.0]}], "horizon": 2}

    async def scenario(session: ClientSession):
        return await session.call_tool("backtest", args)

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "INVALID_REQUEST"
    assert payload["details"]["errors"]


def test_backtest_removed_field_is_rejected() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("backtest", {**BACKTEST_ARGS, "mode": "univariate"})

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "INVALID_REQUEST"
    assert "mode" in payload["details"]["unknown"]


def test_list_resources_exposes_capabilities() -> None:
    async def scenario(session: ClientSession):
        return await session.list_resources()

    resources = asyncio.run(_run(_ok_handler, scenario))
    capabilities = next(r for r in resources.resources if str(r.uri) == "precog://capabilities")
    assert capabilities.mime_type == "application/json"


def test_read_capabilities_resource_returns_semantic_shape() -> None:
    async def scenario(session: ClientSession):
        return await session.read_resource("precog://capabilities")

    result = asyncio.run(_run(_ok_handler, scenario))
    text = result.contents[0].text
    payload = json.loads(text)
    assert payload["forecast"]["supported"] is True
    assert payload["forecast"]["known_future_covariates"] is True
    assert payload["backtest"]["supported"] is True
    assert payload["backtest"]["metrics"] == ["mae", "rmse", "smape"]
    assert payload["backtest"]["interval_coverage"] is True
    assert payload["limits"]["max_horizon"] == 1024
    assert payload["limits"]["max_context_length"] == 15360
    assert payload["limits"]["quantile_levels"] == list(QUANTILE_LEVELS)
    for backend_only in ("engine", "device", "modes", "max_variates", "max_series", "model_id"):
        assert backend_only not in text


def test_capabilities_quantiles_are_owned_by_the_mcp_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/capabilities":
            payload = _capabilities_payload()
            payload["quantile_levels"] = [0.5]
            return httpx.Response(200, json=payload)
        return _ok_handler(request)

    async def scenario(session: ClientSession):
        return await session.read_resource("precog://capabilities")

    result = asyncio.run(_run(handler, scenario))
    payload = json.loads(result.contents[0].text)
    assert payload["limits"]["quantile_levels"] == list(QUANTILE_LEVELS)


def test_capabilities_resource_falls_back_when_api_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            raise httpx.ConnectError("TLS failure for https://internal.example:8443")
        return _ok_handler(request)

    async def scenario(session: ClientSession):
        return await session.read_resource("precog://capabilities")

    result = asyncio.run(_run(handler, scenario))
    text = result.contents[0].text
    payload = json.loads(text)
    assert payload["limits"]["max_horizon"] is None
    assert payload["limits"]["max_context_length"] is None
    assert payload["forecast"]["supported"] is True
    assert "internal.example" not in text


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
        raise httpx.ConnectError("TLS failure for https://internal.example:8443")

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", FORECAST_ARGS)

    result = asyncio.run(_run(handler, scenario))
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "API_UNAVAILABLE"
    assert "internal.example" not in result.content[0].text
    assert payload["message"] == "Precog API is unavailable"


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


def test_forecast_batch_is_not_available() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", {"requests": []})

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "INVALID_REQUEST"


def test_missing_required_field_is_invalid_request() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast", {"horizon": 2})

    result = asyncio.run(_run(_ok_handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "INVALID_REQUEST"


def test_unexpected_tool_failure_is_generic_internal_error() -> None:
    client = ForecastApiClient("http://api.test", transport=httpx.MockTransport(_ok_handler))
    server = create_server(Settings(api_url="http://api.test"), client=client)

    @server.tool(name="boom", description="crash for the test")
    async def boom() -> dict[str, Any]:
        raise RuntimeError("secret internal http://internal.example:9999")

    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )

    async def scenario():
        async with app.router.lifespan_context(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://localhost") as http:
                async with streamable_http_client("http://localhost/mcp", http_client=http) as (
                    read,
                    write,
                ):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        return await session.call_tool("boom", {})

    result = asyncio.run(scenario())
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "INTERNAL_ERROR"
    assert "secret" not in result.content[0].text
    assert "internal.example" not in result.content[0].text


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

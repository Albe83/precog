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


def _rest_payload(ids: list[str], horizon: int = 2) -> dict[str, Any]:
    return {
        "model": "timesfm-3.0",
        "horizon": horizon,
        "quantile_levels": list(QUANTILE_LEVELS),
        "results": [
            {
                "id": series_id,
                "forecast": [1.0] * horizon,
                # Canonical REST orientation: [horizon][quantile].
                "quantiles": [
                    [float(row + column) for column in range(len(QUANTILE_LEVELS))]
                    for row in range(horizon)
                ],
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
    assert batch.output_schema is not None
    assert "results" in batch.output_schema["properties"]


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


def _batch_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if body["series"][0]["id"] == "bad":
        return httpx.Response(422, json={"title": "Unprocessable Entity", "detail": "rejected"})
    return httpx.Response(200, json=_rest_payload([body["series"][0]["id"]], body["horizon"]))


def test_forecast_batch_preserves_order_and_index() -> None:
    requests = [
        {"targets": [{"id": series_id, "values": [1.0, 2.0, 3.0]}], "horizon": 2}
        for series_id in ("a", "b", "c")
    ]

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", {"requests": requests})

    result = asyncio.run(_run(_batch_handler, scenario))
    assert result.is_error is False
    items = result.structured_content["results"]
    assert [item["index"] for item in items] == [0, 1, 2]
    assert [item["ok"] for item in items] == [True, True, True]
    assert [item["result"]["targets"][0]["id"] for item in items] == ["a", "b", "c"]


def test_forecast_batch_partial_failure_does_not_cancel_siblings() -> None:
    requests = [
        {"targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
        {"targets": [{"id": "bad", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
        {"targets": [{"id": "c", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
    ]

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", {"requests": requests})

    result = asyncio.run(_run(_batch_handler, scenario))
    assert result.is_error is False
    items = result.structured_content["results"]
    assert [item["ok"] for item in items] == [True, False, True]
    assert items[1]["error"]["code"] == "FORECAST_REJECTED"


def test_forecast_batch_all_failures_is_still_a_successful_call() -> None:
    requests = [
        {"targets": [{"id": "bad", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
        {"targets": [{"id": "bad", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
    ]

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", {"requests": requests})

    result = asyncio.run(_run(_batch_handler, scenario))
    assert result.is_error is False
    assert all(item["ok"] is False for item in result.structured_content["results"])


def test_forecast_batch_empty_is_a_tool_error() -> None:
    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", {"requests": []})

    result = asyncio.run(_run(_batch_handler, scenario))
    assert result.is_error is True
    assert _envelope(result)["code"] == "INVALID_REQUEST"


def test_forecast_batch_oversize_is_a_tool_error() -> None:
    requests = [
        {"targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
        {"targets": [{"id": "b", "values": [1.0, 2.0, 3.0]}], "horizon": 2},
    ]

    async def scenario(session: ClientSession):
        return await session.call_tool("forecast_batch", {"requests": requests})

    result = asyncio.run(
        _run(_batch_handler, scenario, Settings(api_url="http://api.test", mcp_batch_max=1))
    )
    assert result.is_error is True
    payload = _envelope(result)
    assert payload["code"] == "INVALID_REQUEST"
    assert payload["details"]["max"] == 1


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

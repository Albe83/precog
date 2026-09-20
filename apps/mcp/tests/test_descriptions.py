"""Lock the public agent-guidance semantics of the MCP descriptions (#241).

These tests treat the registered tool/resource descriptions and the server
instructions as public contract: an agent reading only the MCP surface must be
able to tell that multi-target calls are joint, that ``backtest`` is a single
holdout window, how to read the metrics, and that Precog does not decide whether
a forecast is useful.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from precog_client import AsyncPrecogClient
from precog_mcp.config import Settings
from precog_mcp.server import create_server

pytestmark = pytest.mark.unit

# Backend/implementation wording that must never leak into agent-facing text.
# Matched as whole words so legitimate terms such as "covariates" do not trip it.
BACKEND_WORDS = ("timesfm", "attention", "transformer", "torch", "variate", "tensor")


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"targets": [], "horizon": 1})


async def _surface() -> dict[str, Any]:
    client = AsyncPrecogClient("http://api.test", transport=httpx.MockTransport(_handler))
    server = create_server(Settings(api_url="http://api.test"), client=client)
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
                    init = await session.initialize()
                    tools = await session.list_tools()
                    resources = await session.list_resources()
                    return {
                        "instructions": init.instructions or "",
                        "tools": {tool.name: tool.description or "" for tool in tools.tools},
                        "resources": {
                            str(resource.uri): resource.description or ""
                            for resource in resources.resources
                        },
                    }


def _surface_sync() -> dict[str, Any]:
    return asyncio.run(_surface())


def test_forecast_description_explains_joint_targets() -> None:
    description = _surface_sync()["tools"]["forecast"].lower()
    assert "joint" in description
    assert "separate calls" in description
    assert "each other" in description
    assert "related" in description


def test_backtest_description_is_a_single_window() -> None:
    description = _surface_sync()["tools"]["backtest"].lower()
    assert "single-window" in description or "single window" in description
    assert "not a rolling" in description
    assert "cross-validated" in description
    assert "per target" in description


def test_backtest_description_has_metric_caveats_without_thresholds() -> None:
    description = _surface_sync()["tools"]["backtest"].lower()
    assert "native units" in description
    assert "near zero" in description
    assert "calibration" in description
    assert "not a verdict" in description
    assert "baseline" in description
    for threshold in ("smape <", "smape>", "good", "excellent", "acceptable"):
        assert threshold not in description


def test_descriptions_do_not_expose_backend_details() -> None:
    surface = _surface_sync()
    text = " ".join(
        [surface["instructions"], *surface["tools"].values(), *surface["resources"].values()]
    ).lower()
    for word in BACKEND_WORDS:
        assert re.search(rf"\b{word}\b", text) is None


def test_server_instructions_cover_joint_meaning_and_ownership() -> None:
    instructions = _surface_sync()["instructions"].lower()
    assert "joint" in instructions
    assert "separate calls" in instructions
    assert "you own your data" in instructions
    assert "not a verdict" in instructions


def test_capabilities_description_reinforces_joint_semantics() -> None:
    description = _surface_sync()["resources"]["precog://capabilities"].lower()
    assert "joint" in description
    assert "responsibility" in description

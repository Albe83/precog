"""Discovery and invocation tests for the optional MCP workflow prompts (#242).

The prompts must stay generic forecasting recipes: no vertical/domain
assumptions, no fixed success thresholds, no backend internals, and no
redefinition of the tool schemas.
"""

from __future__ import annotations

import asyncio
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

EXPECTED_PROMPTS = {"evaluate_forecastability", "compare_joint_vs_independent"}

# A vertical workflow would name infrastructure/business domains; the prompts
# must encode forecasting discipline instead.
VERTICAL_WORDS = (
    "kubernetes",
    "datacenter",
    "node",
    "cpu",
    "memory",
    "storage",
    "iops",
    "network",
    "energy",
    "sales",
    "finance",
    "inventory",
)
BACKEND_WORDS = ("timesfm", "attention", "transformer", "torch", "tensor")


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"targets": [], "horizon": 1})


async def _app():
    client = AsyncPrecogClient("http://api.test", transport=httpx.MockTransport(_handler))
    server = create_server(Settings(api_url="http://api.test"), client=client)
    return server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )


async def _run(coro_factory):
    app = await _app()
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


def _prompt_text(result: Any) -> str:
    parts = []
    for message in result.messages:
        content = message.content
        text = getattr(content, "text", None)
        if text is None and isinstance(content, str):
            text = content
        if text:
            parts.append(text)
    return "".join(parts)


def test_prompts_are_discoverable_with_semantic_descriptions() -> None:
    async def scenario(session: ClientSession):
        return await session.list_prompts()

    prompts = asyncio.run(_run(scenario))
    by_name = {prompt.name: prompt for prompt in prompts.prompts}
    assert EXPECTED_PROMPTS <= set(by_name)
    for name in EXPECTED_PROMPTS:
        assert by_name[name].description
        arguments = by_name[name].arguments or []
        assert [argument.name for argument in arguments] == ["objective"]
        assert arguments[0].required is False


def test_evaluate_forecastability_prompt_encodes_the_workflow() -> None:
    async def scenario(session: ClientSession):
        return await session.get_prompt("evaluate_forecastability")

    text = _prompt_text(asyncio.run(_run(scenario))).lower()
    assert "backtest" in text
    assert "per target" in text
    assert "native units" in text
    assert "near zero" in text
    assert "calibration" in text
    assert "baseline" in text
    assert "per target" in text
    assert "no universal thresholds" in text or "universal thresholds" in text
    assert "rolling backtest" in text


def test_compare_joint_vs_independent_prompt_encodes_the_comparison() -> None:
    async def scenario(session: ClientSession):
        return await session.get_prompt("compare_joint_vs_independent")

    text = _prompt_text(asyncio.run(_run(scenario))).lower()
    assert "joint" in text
    assert "independent" in text
    assert "same" in text
    assert "multiple historical cutoffs" in text
    assert "per target" in text or "per-target" in text
    assert "insufficient or inconsistent" in text


def test_prompt_objective_argument_is_embedded_when_provided() -> None:
    async def scenario(session: ClientSession):
        return await session.get_prompt(
            "evaluate_forecastability", {"objective": "decide next quarter capacity"}
        )

    text = _prompt_text(asyncio.run(_run(scenario)))
    assert "decide next quarter capacity" in text


def test_prompts_are_generic_and_backend_independent() -> None:
    async def scenario(session: ClientSession):
        return {
            name: _prompt_text(await session.get_prompt(name)) for name in sorted(EXPECTED_PROMPTS)
        }

    texts = asyncio.run(_run(scenario))
    for name, text in texts.items():
        lowered = text.lower()
        for word in (*VERTICAL_WORDS, *BACKEND_WORDS):
            assert word not in lowered, f"{name} prompt leaked '{word}'"
        for threshold in ("smape <", "smape>"):
            assert threshold not in lowered, f"{name} prompt leaked threshold '{threshold}'"

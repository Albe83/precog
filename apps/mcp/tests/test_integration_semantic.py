"""End-to-end semantic contract suite through the real TimesFM-3 backend.

Runs the complete production path:

    MCP client -> MCP server -> Precog REST API -> TimesFM-3 engine -> MCP

Marked ``integration`` and skipped unless the model cache and the engine
dependencies are available. Run explicitly with:

    PRECOG_CACHE_DIR=/path/to/models uv run pytest -m integration \
        apps/mcp/tests/test_integration_semantic.py
"""

from __future__ import annotations

import asyncio
import functools
import json
import math
import os
from pathlib import Path
from typing import Any

import httpx
import httpx2
import numpy as np
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from precog_client import AsyncPrecogClient
from precog_mcp.config import Settings
from precog_mcp.models import SEMANTIC_QUANTILE_LEVELS as QUANTILE_LEVELS
from precog_mcp.server import create_server

pytestmark = pytest.mark.integration

CACHE = os.environ.get("PRECOG_CACHE_DIR", "/home/albe/.cache/precog/models")
CONTEXT = 48
HORIZON = 6


@pytest.fixture(autouse=True)
def _require_backend() -> None:
    if not Path(CACHE).is_dir():
        pytest.skip(f"model cache not available at {CACHE}")
    pytest.importorskip("timesfm3")


def _series(seed: int, level: float, length: int) -> list[float]:
    t = np.arange(length, dtype=np.float32)
    rng = np.random.default_rng(seed)
    values = level + 0.2 * t + 5 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 0.5, length)
    return [float(v) for v in values]


@functools.lru_cache(maxsize=1)
def _model_engine() -> Any:
    from precog_api.config import Settings as ApiSettings
    from precog_api.engine_timesfm3 import TimesFM3Engine

    return TimesFM3Engine(
        ApiSettings(
            engine="timesfm3",
            cache_dir=CACHE,
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )


async def _run_session(action):
    from precog_api.app import create_app
    from precog_api.config import Settings as ApiSettings

    api = create_app(
        ApiSettings(engine="timesfm3", cache_dir=CACHE, local_files_only=True),
        engine=_model_engine(),
    )
    async with api.router.lifespan_context(api):
        client = AsyncPrecogClient("http://api.test", transport=httpx.ASGITransport(app=api))
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
                        await session.initialize()
                        return await action(session)


async def _call_tool(tool_name: str, args: dict[str, Any]):
    async def action(session: ClientSession):
        return await session.call_tool(tool_name, args)

    return await _run_session(action)


async def _read_resource(uri: str):
    async def action(session: ClientSession):
        return await session.read_resource(uri)

    return await _run_session(action)


def _call_forecast(args: dict[str, Any]):
    return _call_tool("forecast", args)


def _call_backtest(args: dict[str, Any]):
    return _call_tool("backtest", args)


def _envelope(result: Any) -> dict[str, Any]:
    return json.loads(result.content[0].text)


def _assert_result_shape(result: Any, ids: list[str]) -> dict[str, Any]:
    assert result.is_error is False
    structured = result.structured_content
    assert structured["horizon"] == HORIZON
    assert [target["id"] for target in structured["targets"]] == ids
    for target in structured["targets"]:
        assert len(target["forecast"]) == HORIZON
        assert all(math.isfinite(value) for value in target["forecast"])
    return structured


def test_single_target_forecast() -> None:
    result = asyncio.run(
        _call_forecast(
            {
                "targets": [{"id": "a", "values": _series(0, 100, CONTEXT)}],
                "horizon": HORIZON,
            }
        )
    )
    _assert_result_shape(result, ["a"])


def test_multiple_related_targets_forecast_jointly() -> None:
    result = asyncio.run(
        _call_forecast(
            {
                "targets": [
                    {"id": "a", "values": _series(0, 100, CONTEXT)},
                    {"id": "b", "values": _series(1, 80, CONTEXT)},
                ],
                "horizon": HORIZON,
            }
        )
    )
    structured = _assert_result_shape(result, ["a", "b"])
    assert structured["model"]["id"] == "google/timesfm-3.0-pytorch"


def test_forecast_with_past_covariate() -> None:
    result = asyncio.run(
        _call_forecast(
            {
                "targets": [{"id": "a", "values": _series(0, 100, CONTEXT)}],
                "horizon": HORIZON,
                "past_covariates": [{"id": "promo", "values": _series(2, 0, CONTEXT)}],
            }
        )
    )
    _assert_result_shape(result, ["a"])


def test_forecast_with_known_future_covariate() -> None:
    result = asyncio.run(
        _call_forecast(
            {
                "targets": [{"id": "a", "values": _series(0, 100, CONTEXT)}],
                "horizon": HORIZON,
                "known_future_covariates": [
                    {
                        "id": "promo",
                        "history": _series(3, 0, CONTEXT),
                        "future": [1.0 if step % 2 == 0 else 0.0 for step in range(HORIZON)],
                    }
                ],
            }
        )
    )
    _assert_result_shape(result, ["a"])


def test_probabilistic_forecast_requested_quantiles() -> None:
    result = asyncio.run(
        _call_forecast(
            {
                "targets": [{"id": "a", "values": _series(0, 100, CONTEXT)}],
                "horizon": HORIZON,
                "quantiles": [0.1, 0.5, 0.9],
            }
        )
    )
    structured = _assert_result_shape(result, ["a"])
    quantiles = structured["targets"][0]["quantiles"]
    assert list(quantiles) == ["0.1", "0.5", "0.9"]
    for vector in quantiles.values():
        assert len(vector) == HORIZON
        assert all(math.isfinite(value) for value in vector)
    # Sorted quantiles must not cross.
    for step in range(HORIZON):
        assert quantiles["0.1"][step] <= quantiles["0.5"][step] <= quantiles["0.9"][step]


def test_point_forecast_matches_requested_median() -> None:
    """The public point forecast is the median for the current backend."""
    scenarios: list[list[dict[str, Any]]] = [
        [{"id": "a", "values": _series(0, 100, CONTEXT)}],
        [
            {"id": "a", "values": _series(0, 100, CONTEXT)},
            {"id": "b", "values": _series(1, 80, CONTEXT)},
        ],
    ]
    for targets in scenarios:
        result = asyncio.run(
            _call_forecast({"targets": targets, "horizon": HORIZON, "quantiles": [0.1, 0.5, 0.9]})
        )
        structured = _assert_result_shape(result, [target["id"] for target in targets])
        for target in structured["targets"]:
            assert target["forecast"] == target["quantiles"]["0.5"]


def test_invalid_semantic_input_is_rejected() -> None:
    result = asyncio.run(
        _call_forecast(
            {
                "targets": [{"id": "a", "values": _series(0, 100, CONTEXT)}],
                "horizon": HORIZON,
                "past_covariates": [{"id": "short", "values": [0.0, 1.0]}],
            }
        )
    )
    assert result.is_error is True
    assert _envelope(result)["code"] == "INVALID_REQUEST"


def test_effective_capability_violation_maps_to_forecast_rejected() -> None:
    targets = [{"id": f"t{index}", "values": _series(index, 100, 8)} for index in range(33)]
    result = asyncio.run(_call_forecast({"targets": targets, "horizon": HORIZON}))
    assert result.is_error is True
    assert _envelope(result)["code"] == "FORECAST_REJECTED"


def test_backtest_single_target_single_window() -> None:
    values = _series(0, 100, CONTEXT + HORIZON)
    result = asyncio.run(
        _call_backtest(
            {
                "targets": [{"id": "a", "values": values}],
                "horizon": HORIZON,
                "quantiles": [0.1, 0.9],
            }
        )
    )
    assert result.is_error is False
    structured = result.structured_content
    assert structured["horizon"] == HORIZON
    assert structured["model"]["id"] == "google/timesfm-3.0-pytorch"
    target = structured["targets"][0]
    assert target["actual"] == pytest.approx(values[-HORIZON:])
    assert len(target["forecast"]) == HORIZON
    assert all(math.isfinite(value) for value in target["forecast"])
    metrics = target["metrics"]
    for name in ("mae", "rmse", "smape"):
        assert math.isfinite(metrics[name])
        assert metrics[name] >= 0.0
    assert metrics["coverage"]["lower_quantile"] == 0.1
    assert metrics["coverage"]["upper_quantile"] == 0.9
    assert 0.0 <= metrics["coverage"]["percent"] <= 100.0


def test_backtest_multiple_targets_with_covariate() -> None:
    targets = [
        {"id": "a", "values": _series(0, 100, CONTEXT + HORIZON)},
        {"id": "b", "values": _series(1, 80, CONTEXT + HORIZON)},
    ]
    result = asyncio.run(
        _call_backtest(
            {
                "targets": targets,
                "horizon": HORIZON,
                "past_covariates": [{"id": "promo", "values": _series(2, 0, CONTEXT + HORIZON)}],
                "quantiles": [0.1, 0.9],
            }
        )
    )
    assert result.is_error is False
    structured = result.structured_content
    assert [target["id"] for target in structured["targets"]] == ["a", "b"]
    for evaluated, source in zip(structured["targets"], targets, strict=True):
        assert evaluated["actual"] == pytest.approx(source["values"][-HORIZON:])
        assert len(evaluated["forecast"]) == HORIZON
        assert all(math.isfinite(value) for value in evaluated["forecast"])
        metrics = evaluated["metrics"]
        for name in ("mae", "rmse", "smape"):
            assert math.isfinite(metrics[name])
            assert metrics[name] >= 0.0
        assert metrics["coverage"] is not None


def test_backtest_with_known_future_covariate() -> None:
    values = _series(0, 100, CONTEXT + HORIZON)
    covariate = _series(3, 0, CONTEXT + HORIZON)
    result = asyncio.run(
        _call_backtest(
            {
                "targets": [{"id": "a", "values": values}],
                "horizon": HORIZON,
                "known_future_covariates": [{"id": "promo", "values": covariate}],
            }
        )
    )
    assert result.is_error is False
    assert result.structured_content["targets"][0]["actual"] == pytest.approx(values[-HORIZON:])


def test_backtest_holdout_not_shorter_than_series_is_rejected() -> None:
    values = _series(0, 100, CONTEXT + HORIZON)
    result = asyncio.run(
        _call_backtest({"targets": [{"id": "a", "values": values}], "horizon": len(values)})
    )
    assert result.is_error is True
    assert _envelope(result)["code"] == "INVALID_REQUEST"


def test_capabilities_resource_reports_effective_limits() -> None:
    result = asyncio.run(_read_resource("precog://capabilities"))
    text = result.contents[0].text
    payload = json.loads(text)
    assert payload["forecast"]["supported"] is True
    assert payload["backtest"]["supported"] is True
    assert payload["limits"]["max_horizon"] == 1024
    # Effective context is min(configured, engine) = 15360 for TimesFM-3.
    assert payload["limits"]["max_context_length"] == 15360
    assert payload["limits"]["quantile_levels"] == list(QUANTILE_LEVELS)
    for backend_only in ("engine", "device", "max_variates", "max_series", "model_id"):
        assert backend_only not in text

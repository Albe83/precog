"""Real end-to-end contract for the sync and async execution clients.

Boots the real Precog ASGI app (real TimesFM-3 engine, cached weights) on a
loopback port and drives it with both ``PrecogClient`` and
``AsyncPrecogClient``. Reproducible with only the model cache: no external
``PRECOG_API_URL`` required.

    PRECOG_CACHE_DIR=/path/to/models uv run pytest -m integration \
        packages/sdk-python/tests/test_integration.py
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from precog_client import AsyncPrecogClient, PrecogAPIError, PrecogClient

pytestmark = pytest.mark.integration

CACHE = os.environ.get("PRECOG_CACHE_DIR", "/home/albe/.cache/precog/models")
MODEL_ID = "google/timesfm-3.0-pytorch"
CONTEXT = 48
HORIZON = 4
TARGET = [100.0 + index for index in range(CONTEXT)]


@contextlib.contextmanager
def _run_api() -> Iterator[str]:
    from precog_api.app import create_app
    from precog_api.config import Settings as ApiSettings
    from precog_api.engine_timesfm3 import TimesFM3Engine

    engine = TimesFM3Engine(
        ApiSettings(
            engine="timesfm3",
            cache_dir=CACHE,
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )
    app = create_app(ApiSettings(engine="timesfm3", cache_dir=CACHE), engine=engine)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    if not server.started:  # pragma: no cover - startup failure
        server.should_exit = True
        raise RuntimeError("API server did not start")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.fixture(scope="module")
def api_url() -> Iterator[str]:
    if not Path(CACHE).is_dir():
        pytest.skip(f"model cache not available at {CACHE}")
    pytest.importorskip("timesfm3")
    with _run_api() as url:
        yield url


def _forecast_sync(base_url: str):
    with PrecogClient(base_url, timeout=60.0) as client:
        return client.forecast(
            horizon=HORIZON,
            targets=[{"id": "a", "values": TARGET}],
            quantiles=[0.1, 0.5, 0.9],
        )


def _forecast_async(base_url: str):
    async def scenario():
        async with AsyncPrecogClient(base_url, timeout=60.0) as client:
            return await client.forecast(
                horizon=HORIZON,
                targets=[{"id": "a", "values": TARGET}],
                quantiles=[0.1, 0.5, 0.9],
            )

    return asyncio.run(scenario())


def _over_context() -> dict:
    return {"id": "a", "values": [0.0] * (15360 + 1)}


def _forecast_sync_over_context(base_url: str):
    with PrecogClient(base_url, timeout=60.0) as client:
        return client.forecast(horizon=HORIZON, targets=[_over_context()])


def test_sync_forecast_canonical_roundtrip(api_url: str) -> None:
    response = _forecast_sync(api_url)

    assert response.horizon == HORIZON
    assert response.model.id == MODEL_ID
    target = response.targets[0]
    assert target.id == "a"
    assert len(target.forecast) == HORIZON
    assert all(math.isfinite(value) for value in target.forecast)
    # Only the requested levels cross the boundary, as {level, values}.
    assert [quantile.level for quantile in target.quantiles] == [0.1, 0.5, 0.9]
    assert all(len(quantile.values) == HORIZON for quantile in target.quantiles)
    # Point forecast is the requested median.
    assert target.forecast == target.quantiles[1].values
    # No backend matrix shape leaks into the public contract.
    assert not hasattr(response, "results")
    assert not hasattr(response, "quantile_levels")


def test_async_forecast_canonical_roundtrip(api_url: str) -> None:
    response = _forecast_async(api_url)

    assert response.horizon == HORIZON
    assert response.model.id == MODEL_ID
    target = response.targets[0]
    assert target.id == "a"
    assert [quantile.level for quantile in target.quantiles] == [0.1, 0.5, 0.9]
    assert target.forecast == target.quantiles[1].values


def test_sync_and_async_success_parity(api_url: str) -> None:
    sync_response = _forecast_sync(api_url)
    async_response = _forecast_async(api_url)

    assert sync_response.model.id == async_response.model.id
    assert sync_response.horizon == async_response.horizon
    assert [target.id for target in sync_response.targets] == [
        target.id for target in async_response.targets
    ]
    # Same engine, same input: the deterministic backend must agree exactly.
    assert sync_response.targets[0].forecast == async_response.targets[0].forecast
    assert sync_response.targets[0].quantiles == async_response.targets[0].quantiles


def test_capabilities_parsing_sync_and_async(api_url: str) -> None:
    with PrecogClient(api_url, timeout=60.0) as client:
        sync_caps = client.capabilities()
        sync_payload = client.capabilities_payload()

    async def scenario():
        async with AsyncPrecogClient(api_url, timeout=60.0) as client:
            return await client.capabilities()

    async_caps = asyncio.run(scenario())

    assert sync_caps.model.id == MODEL_ID
    assert sync_caps.limits.max_context == 15360
    assert sync_caps.limits.max_variates == 32
    assert sync_caps.limits.max_horizon == 1024
    assert sync_caps.limits.max_targets == 64
    assert sync_caps.features.joint_targets is True
    assert async_caps.limits.max_context == 15360
    assert sync_payload["limits"]["max_context"] == 15360


def test_error_parity_context_rejection(api_url: str) -> None:
    async def scenario():
        async with AsyncPrecogClient(api_url, timeout=60.0) as client:
            return await client.forecast(horizon=HORIZON, targets=[_over_context()])

    with pytest.raises(PrecogAPIError) as sync_info:
        _forecast_sync_over_context(api_url)
    with pytest.raises(PrecogAPIError) as async_info:
        asyncio.run(scenario())

    assert sync_info.value.status_code == 422
    assert async_info.value.status_code == 422
    assert type(sync_info.value) is type(async_info.value)


def test_error_parity_variate_rejection(api_url: str) -> None:
    targets = [{"id": "a", "values": TARGET}]
    covariates = [{"id": f"p{index}", "values": [0.0] * CONTEXT} for index in range(40)]

    async def scenario():
        async with AsyncPrecogClient(api_url, timeout=60.0) as client:
            return await client.forecast(
                horizon=HORIZON, targets=targets, past_covariates=covariates
            )

    with pytest.raises(PrecogAPIError) as sync_info:
        with PrecogClient(api_url, timeout=60.0) as client:
            client.forecast(horizon=HORIZON, targets=targets, past_covariates=covariates)
    with pytest.raises(PrecogAPIError) as async_info:
        asyncio.run(scenario())

    assert sync_info.value.status_code == 422
    assert async_info.value.status_code == 422

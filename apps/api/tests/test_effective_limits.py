from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from precog_api.app import create_app
from precog_api.config import Settings
from precog_api.engine import FakeEngine

pytestmark = pytest.mark.unit


def make_client(engine: FakeEngine, **overrides: object) -> TestClient:
    settings = Settings(engine="fake", **overrides)  # type: ignore[arg-type]
    return TestClient(create_app(settings, engine=engine))


def _single_target(
    target_len: int, *, n_past: int = 0, n_future: int = 0, horizon: int = 2
) -> dict[str, Any]:
    return {
        "horizon": horizon,
        "targets": [{"id": "a", "values": [1.0] * target_len}],
        "past_covariates": [
            {"id": f"p{index}", "values": [0.0] * target_len} for index in range(n_past)
        ],
        "known_future_covariates": [
            {
                "id": f"f{index}",
                "history": [0.0] * target_len,
                "future": [0.0] * horizon,
            }
            for index in range(n_future)
        ],
        "quantiles": [],
    }


def _joint_targets(
    n_targets: int,
    *,
    n_past: int = 0,
    n_future: int = 0,
    target_len: int = 4,
    horizon: int = 2,
) -> dict[str, Any]:
    return {
        "horizon": horizon,
        "targets": [
            {"id": f"t{index}", "values": [1.0] * target_len} for index in range(n_targets)
        ],
        "past_covariates": [
            {"id": f"p{index}", "values": [0.0] * target_len} for index in range(n_past)
        ],
        "known_future_covariates": [
            {
                "id": f"f{index}",
                "history": [0.0] * target_len,
                "future": [0.0] * horizon,
            }
            for index in range(n_future)
        ],
        "quantiles": [],
    }


def test_context_at_engine_limit_is_accepted() -> None:
    engine = FakeEngine(max_context=5)
    with make_client(engine, max_context=100) as client:
        assert client.post("/v1/forecast", json=_single_target(5)).status_code == 200


def test_context_above_engine_limit_is_rejected() -> None:
    engine = FakeEngine(max_context=5)
    with make_client(engine, max_context=100) as client:
        response = client.post("/v1/forecast", json=_single_target(6))
    assert response.status_code == 422
    assert "never truncates" in response.json()["detail"]


def test_configured_context_limit_takes_precedence() -> None:
    engine = FakeEngine(max_context=100)
    with make_client(engine, max_context=3) as client:
        response = client.post("/v1/forecast", json=_single_target(4))
    assert response.status_code == 422
    assert "exceeds max 3" in response.json()["detail"]


def test_32_variates_are_accepted() -> None:
    engine = FakeEngine(max_variates=32)
    payload = _joint_targets(30, n_past=1, n_future=1)
    with make_client(engine, max_series=64) as client:
        assert client.post("/v1/forecast", json=payload).status_code == 200


def test_33_variates_are_rejected() -> None:
    engine = FakeEngine(max_variates=32)
    payload = _joint_targets(31, n_past=1, n_future=1)
    with make_client(engine, max_series=64) as client:
        response = client.post("/v1/forecast", json=payload)
    assert response.status_code == 422
    assert "never drops or chunks" in response.json()["detail"]


def test_single_target_variate_limit() -> None:
    engine = FakeEngine(max_variates=3)
    with make_client(engine, max_series=64) as client:
        assert client.post("/v1/forecast", json=_single_target(4, n_past=2)).status_code == 200
        response = client.post("/v1/forecast", json=_single_target(4, n_past=2, n_future=1))
    assert response.status_code == 422


def test_variate_budget_is_independent_of_target_ceiling() -> None:
    # 1 target + 12 covariates = 13 variates: above the target ceiling (10) but
    # below the engine's variate budget (32), so it must be accepted.
    engine = FakeEngine(max_variates=32)
    with make_client(engine, max_series=10) as client:
        response = client.post("/v1/forecast", json=_single_target(4, n_past=12))
    assert response.status_code == 200


def test_capabilities_advertise_effective_limits() -> None:
    engine = FakeEngine(max_context=15360, max_variates=32)
    with make_client(engine, max_context=16384, max_series=64) as client:
        body = client.get("/v1/capabilities").json()
    assert body["limits"]["max_context"] == 15360
    assert body["limits"]["max_variates"] == 32
    assert body["limits"]["max_targets"] == 64


def test_unbounded_engine_keeps_configured_capabilities() -> None:
    with make_client(FakeEngine(), max_context=16384, max_series=64) as client:
        body = client.get("/v1/capabilities").json()
    assert body["limits"]["max_context"] == 16384
    assert body["limits"]["max_variates"] is None
    assert body["limits"]["max_targets"] == 64

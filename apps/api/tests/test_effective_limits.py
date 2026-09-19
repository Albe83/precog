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


def _univariate(
    target_len: int, *, n_past: int = 0, n_future: int = 0, horizon: int = 2
) -> dict[str, Any]:
    return {
        "mode": "univariate",
        "horizon": horizon,
        "series": [
            {
                "id": "a",
                "target": [1.0] * target_len,
                "past_covariates": {f"p{index}": [0.0] * target_len for index in range(n_past)},
                "future_covariates": {
                    f"f{index}": [0.0] * (target_len + horizon) for index in range(n_future)
                },
            }
        ],
    }


def _multivariate(
    n_targets: int,
    *,
    n_past: int = 0,
    n_future: int = 0,
    target_len: int = 4,
    horizon: int = 2,
) -> dict[str, Any]:
    return {
        "mode": "multivariate",
        "horizon": horizon,
        "series": [{"id": f"t{index}", "target": [1.0] * target_len} for index in range(n_targets)],
        "past_covariates": {f"p{index}": [0.0] * target_len for index in range(n_past)},
        "future_covariates": {
            f"f{index}": [0.0] * (target_len + horizon) for index in range(n_future)
        },
    }


def test_context_at_engine_limit_is_accepted() -> None:
    engine = FakeEngine(max_context=5)
    with make_client(engine, max_context=100) as client:
        assert client.post("/v1/forecast", json=_univariate(5)).status_code == 200


def test_context_above_engine_limit_is_rejected() -> None:
    engine = FakeEngine(max_context=5)
    with make_client(engine, max_context=100) as client:
        response = client.post("/v1/forecast", json=_univariate(6))
    assert response.status_code == 422
    assert "never truncates" in response.json()["detail"]


def test_configured_context_limit_takes_precedence() -> None:
    engine = FakeEngine(max_context=100)
    with make_client(engine, max_context=3) as client:
        response = client.post("/v1/forecast", json=_univariate(4))
    assert response.status_code == 422
    assert "exceeds max 3" in response.json()["detail"]


def test_32_variates_are_accepted() -> None:
    engine = FakeEngine(max_variates=32)
    payload = _multivariate(30, n_past=1, n_future=1)
    with make_client(engine, max_series=64) as client:
        assert client.post("/v1/forecast", json=payload).status_code == 200


def test_33_variates_are_rejected() -> None:
    engine = FakeEngine(max_variates=32)
    payload = _multivariate(31, n_past=1, n_future=1)
    with make_client(engine, max_series=64) as client:
        response = client.post("/v1/forecast", json=payload)
    assert response.status_code == 422
    assert "never drops or chunks" in response.json()["detail"]


def test_univariate_per_series_variate_limit() -> None:
    engine = FakeEngine(max_variates=3)
    with make_client(engine, max_series=64) as client:
        assert client.post("/v1/forecast", json=_univariate(4, n_past=2)).status_code == 200
        response = client.post("/v1/forecast", json=_univariate(4, n_past=2, n_future=1))
    assert response.status_code == 422


def test_capabilities_advertise_effective_limits() -> None:
    engine = FakeEngine(max_context=15360, max_variates=32)
    with make_client(engine, max_context=16384, max_series=64) as client:
        body = client.get("/v1/capabilities").json()
    assert body["max_context"] == 15360
    assert body["max_variates"] == 32
    assert body["max_series"] == 64


def test_unbounded_engine_keeps_configured_capabilities() -> None:
    with make_client(FakeEngine(), max_context=16384, max_series=64) as client:
        body = client.get("/v1/capabilities").json()
    assert body["max_context"] == 16384
    assert body["max_variates"] == 64

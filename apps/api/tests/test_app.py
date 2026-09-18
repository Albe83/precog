from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from precog_api.app import create_app
from precog_api.config import Settings
from precog_api.engine import FakeEngine

pytestmark = pytest.mark.unit


def make_client(**overrides: object) -> TestClient:
    settings = Settings(engine="fake", **overrides)  # type: ignore[arg-type]
    return TestClient(create_app(settings, engine=FakeEngine()))


def _payload(**overrides: object) -> dict:
    base: dict = {
        "mode": "univariate",
        "horizon": 4,
        "series": [{"id": "a", "target": [1.0, 2.0, 3.0]}],
    }
    base.update(overrides)
    return base


def test_health_and_ready() -> None:
    with make_client() as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200


def test_forecast_univariate() -> None:
    with make_client() as client:
        response = client.post("/v1/forecast", json=_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["model"] == "timesfm-3.0"
        assert body["results"][0]["id"] == "a"
        assert len(body["results"][0]["forecast"]) == 4
        assert len(body["results"][0]["quantiles"]) == 4
        assert body["usage"]["context_len"] == 3


def test_forecast_with_covariates() -> None:
    payload = _payload(
        series=[
            {
                "id": "a",
                "target": [1.0, 2.0, 3.0],
                "past_covariates": {"temp": [0.1, 0.2, 0.3]},
                "future_covariates": {"promo": [0, 0, 0, 1, 0, 0, 0]},
            }
        ]
    )
    with make_client() as client:
        assert client.post("/v1/forecast", json=payload).status_code == 200


def test_covariate_length_is_validated() -> None:
    payload = _payload(
        series=[
            {
                "id": "a",
                "target": [1.0, 2.0, 3.0],
                "past_covariates": {"temp": [0.1, 0.2]},
            }
        ]
    )
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"


def test_horizon_limit() -> None:
    with make_client(max_horizon=2) as client:
        response = client.post("/v1/forecast", json=_payload(horizon=5))
        assert response.status_code == 422


def test_api_key_required() -> None:
    with make_client(api_key="secret") as client:
        assert client.post("/v1/forecast", json=_payload()).status_code == 401
        ok = client.post(
            "/v1/forecast", json=_payload(), headers={"Authorization": "Bearer secret"}
        )
        assert ok.status_code == 200


def test_docs_can_be_disabled() -> None:
    with make_client(enable_docs=False) as client:
        assert client.get("/openapi.json").status_code == 404

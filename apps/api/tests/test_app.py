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


def _multivariate_payload(**overrides: object) -> dict:
    base: dict = {
        "mode": "multivariate",
        "horizon": 3,
        "series": [
            {"id": "a", "target": [1.0, 2.0, 3.0, 4.0]},
            {"id": "b", "target": [5.0, 6.0, 7.0, 8.0]},
        ],
    }
    base.update(overrides)
    return base


def test_multivariate_with_request_covariates() -> None:
    payload = _multivariate_payload(
        past_covariates={"footfall": [0.1, 0.2, 0.3, 0.4]},
        future_covariates={"promo": [0, 0, 1, 0, 1, 0, 0]},
    )
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 200
        assert len(response.json()["results"]) == 2


def test_multivariate_rejects_per_series_covariates() -> None:
    payload = _multivariate_payload(
        series=[
            {"id": "a", "target": [1.0, 2.0, 3.0], "past_covariates": {"x": [1.0, 2.0, 3.0]}},
            {"id": "b", "target": [4.0, 5.0, 6.0]},
        ]
    )
    with make_client() as client:
        assert client.post("/v1/forecast", json=payload).status_code == 422


def test_univariate_rejects_request_covariates() -> None:
    payload = _payload(past_covariates={"x": [1.0, 2.0, 3.0]})
    with make_client() as client:
        assert client.post("/v1/forecast", json=payload).status_code == 422


def test_multivariate_covariate_length_validated() -> None:
    payload = _multivariate_payload(future_covariates={"promo": [0, 1]})
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 422
        assert "context + horizon" in response.json()["detail"]


def test_capabilities_endpoint() -> None:
    with make_client(max_horizon=10, max_context=99, max_series=3) as client:
        response = client.get("/v1/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["max_horizon"] == 10
    assert body["max_context"] == 99
    assert body["max_series"] == 3
    assert body["modes"] == ["univariate", "multivariate"]
    assert body["covariates"] == {"univariate": True, "multivariate": True}
    assert len(body["quantile_levels"]) == 9
    assert body["auth_required"] is False

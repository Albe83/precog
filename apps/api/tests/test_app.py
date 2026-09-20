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
        "horizon": 4,
        "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
        "quantiles": [0.1, 0.5, 0.9],
    }
    base.update(overrides)
    return base


def test_health_and_ready() -> None:
    with make_client() as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").status_code == 200


def test_forecast_single_target() -> None:
    with make_client() as client:
        response = client.post("/v1/forecast", json=_payload())
        assert response.status_code == 200
        body = response.json()
        assert body["model"]["id"] == "timesfm-3.0"
        assert body["horizon"] == 4
        assert body["targets"][0]["id"] == "a"
        assert len(body["targets"][0]["forecast"]) == 4
        assert len(body["targets"][0]["quantiles"]) == 3
        assert body["targets"][0]["quantiles"][0]["level"] == 0.1
        assert body["usage"]["context_len"] == 3


def test_point_only_forecast_omits_quantiles() -> None:
    with make_client() as client:
        response = client.post("/v1/forecast", json=_payload(quantiles=[]))
        assert response.status_code == 200
        assert response.json()["targets"][0]["quantiles"] == []


def test_forecast_with_covariates() -> None:
    payload = _payload(
        horizon=3,
        targets=[{"id": "a", "values": [1.0, 2.0, 3.0]}],
        past_covariates=[{"id": "temp", "values": [0.1, 0.2, 0.3]}],
        known_future_covariates=[
            {"id": "promo", "history": [0.0, 0.0, 0.0], "future": [1.0, 0.0, 0.0]}
        ],
    )
    with make_client() as client:
        assert client.post("/v1/forecast", json=payload).status_code == 200


def test_joint_targets_are_forecast_together() -> None:
    payload = _payload(
        horizon=3,
        targets=[
            {"id": "a", "values": [1.0, 2.0, 3.0, 4.0]},
            {"id": "b", "values": [5.0, 6.0, 7.0, 8.0]},
        ],
    )
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
    assert response.status_code == 200
    assert [target["id"] for target in response.json()["targets"]] == ["a", "b"]


def test_covariate_length_is_validated() -> None:
    payload = _payload(past_covariates=[{"id": "temp", "values": [0.1, 0.2]}])
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 422
        assert response.headers["content-type"] == "application/problem+json"


def test_known_future_length_is_validated() -> None:
    payload = _payload(
        known_future_covariates=[{"id": "promo", "history": [0.0, 0.0, 0.0], "future": [1.0]}]
    )
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 422
        assert "horizon" in response.json()["detail"]


def test_duplicate_ids_are_rejected() -> None:
    payload = _payload(past_covariates=[{"id": "a", "values": [0.0, 0.0, 0.0]}])
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 422
        assert "globally unique" in response.json()["detail"]


def test_unsupported_quantile_is_rejected() -> None:
    payload = _payload(quantiles=[0.55])
    with make_client() as client:
        response = client.post("/v1/forecast", json=payload)
        assert response.status_code == 422
        assert "unsupported quantile" in response.json()["detail"]


def test_horizon_limit() -> None:
    with make_client(max_horizon=2) as client:
        response = client.post("/v1/forecast", json=_payload(horizon=5))
        assert response.status_code == 422


def test_nan_target_rejected() -> None:
    body = '{"horizon":2,"targets":[{"id":"a","values":[1.0,NaN,3.0]}],"quantiles":[]}'
    with make_client() as client:
        response = client.post(
            "/v1/forecast", content=body, headers={"content-type": "application/json"}
        )
        assert response.status_code == 422
        assert "non-finite" in response.json()["detail"]


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


def test_otel_enabled_does_not_break_startup() -> None:
    with make_client(otel_enabled=True) as client:
        assert client.get("/healthz").status_code == 200

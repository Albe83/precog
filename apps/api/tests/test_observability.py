from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from precog_api.app import create_app
from precog_api.config import Settings
from precog_api.engine import FakeEngine

pytestmark = pytest.mark.unit

PAYLOAD = {
    "horizon": 2,
    "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
    "quantiles": [0.5],
}


def make_client(**overrides: object) -> TestClient:
    settings = Settings(engine="fake", **overrides)  # type: ignore[arg-type]
    return TestClient(create_app(settings, engine=FakeEngine()))


def test_request_id_is_generated_and_echoed() -> None:
    with make_client() as client:
        response = client.post("/v1/forecast", json=PAYLOAD)
        assert response.headers.get("x-request-id")

        echoed = client.post("/v1/forecast", json=PAYLOAD, headers={"x-request-id": "abc123"})
        assert echoed.headers["x-request-id"] == "abc123"


def test_metrics_endpoint_exposes_prometheus() -> None:
    with make_client() as client:
        client.post("/v1/forecast", json=PAYLOAD)
        response = client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "precog_inflight_requests" in body
        assert "precog_requests_total" in body
        assert "precog_forecast_series_total" in body


def test_rate_limit_returns_429_with_retry_after() -> None:
    with make_client(rate_limit_requests=2, rate_limit_window_s=60) as client:
        assert client.post("/v1/forecast", json=PAYLOAD).status_code == 200
        assert client.post("/v1/forecast", json=PAYLOAD).status_code == 200

        blocked = client.post("/v1/forecast", json=PAYLOAD)
        assert blocked.status_code == 429
        assert blocked.headers["content-type"] == "application/problem+json"
        assert "retry-after" in blocked.headers
        assert blocked.json()["title"] == "Too Many Requests"


def test_rate_limit_disabled_by_default() -> None:
    with make_client() as client:
        for _ in range(5):
            assert client.post("/v1/forecast", json=PAYLOAD).status_code == 200


def test_openapi_contains_request_examples() -> None:
    with make_client() as client:
        document = client.get("/openapi.json").json()

    examples = document["paths"]["/v1/forecast"]["post"]["requestBody"]["content"][
        "application/json"
    ]["examples"]
    assert {"targets", "covariates", "joint_targets", "point_only"} <= set(examples)

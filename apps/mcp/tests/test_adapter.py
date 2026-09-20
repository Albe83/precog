from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from precog_mcp.adapter import (
    ErrorCode,
    ForecastAdapterError,
    execute_forecast,
    from_rest_response,
    map_api_error,
    to_rest_request,
)
from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.models import ForecastToolRequest

pytestmark = pytest.mark.unit

TARGET_CONTEXT = [31.2, 32.8, 35.1, 37.4, 41.2, 43.7]


def _request(**overrides: Any) -> ForecastToolRequest:
    payload: dict[str, Any] = {
        "targets": [{"id": "cpu_usage", "values": list(TARGET_CONTEXT)}],
        "horizon": 3,
    }
    payload.update(overrides)
    return ForecastToolRequest.model_validate(payload)


def _rest_payload(
    ids: list[str],
    horizon: int = 3,
    *,
    levels: list[float] | None = None,
    quantiles: list[Any] | None = None,
    model: str = "timesfm-3.0",
    forecast: list[float] | None = None,
) -> dict[str, Any]:
    levels = [0.1, 0.9] if levels is None else levels
    targets = []
    for target_id in ids:
        target_quantiles = quantiles
        if target_quantiles is None:
            target_quantiles = [
                {
                    "level": level,
                    "values": [float(row * 10 + column) for row in range(horizon)],
                }
                for column, level in enumerate(levels)
            ]
        targets.append(
            {
                "id": target_id,
                "forecast": forecast if forecast is not None else [1.0] * horizon,
                "quantiles": target_quantiles,
            }
        )
    return {
        "horizon": horizon,
        "targets": targets,
        "model": {"id": model, "revision": None},
        "usage": {"latency_ms": 1.0, "context_len": len(TARGET_CONTEXT)},
    }


def test_request_maps_structurally_to_the_execution_contract() -> None:
    request = _request(
        past_covariates=[{"id": "request_rate", "values": [1, 2, 3, 4, 5, 6]}],
        known_future_covariates=[
            {"id": "maintenance", "history": [0, 0, 0, 0, 0, 0], "future": [0, 1, 1]}
        ],
        quantiles=[0.1, 0.9],
    )
    rest = to_rest_request(request)
    assert [target.id for target in rest.targets] == ["cpu_usage"]
    assert rest.targets[0].values == TARGET_CONTEXT
    assert [covariate.id for covariate in rest.past_covariates] == ["request_rate"]
    known = rest.known_future_covariates[0]
    assert known.history == [0, 0, 0, 0, 0, 0]
    assert known.future == [0, 1, 1]
    assert rest.quantiles == [0.1, 0.9]


def test_multiple_targets_map_structurally() -> None:
    request = _request(
        targets=[
            {"id": "web_requests", "values": [100, 120, 125, 140, 150, 160]},
            {"id": "cpu_usage", "values": list(TARGET_CONTEXT)},
        ],
        past_covariates=[{"id": "request_rate", "values": [1, 2, 3, 4, 5, 6]}],
    )
    rest = to_rest_request(request)
    assert [target.id for target in rest.targets] == ["web_requests", "cpu_usage"]
    assert [covariate.id for covariate in rest.past_covariates] == ["request_rate"]


def test_response_selects_requested_quantiles_by_level() -> None:
    request = _request(quantiles=[0.9, 0.1])
    quantiles = [
        {"level": 0.9, "values": [9.0, 8.0, 7.0]},
        {"level": 0.1, "values": [1.0, 2.0, 3.0]},
        {"level": 0.5, "values": [5.0, 5.0, 5.0]},
    ]
    result = from_rest_response(request, _rest_payload(["cpu_usage"], quantiles=quantiles))
    target = result.targets[0]
    assert list(target.quantiles) == ["0.9", "0.1"]
    assert target.quantiles["0.9"] == [9.0, 8.0, 7.0]
    assert target.quantiles["0.1"] == [1.0, 2.0, 3.0]


def test_empty_quantiles_returns_empty_map() -> None:
    request = _request(quantiles=[])
    result = from_rest_response(request, _rest_payload(["cpu_usage"]))
    assert result.targets[0].quantiles == {}
    assert result.targets[0].forecast == [1.0, 1.0, 1.0]


def test_point_forecast_is_used_verbatim() -> None:
    request = _request()
    result = from_rest_response(request, _rest_payload(["cpu_usage"], forecast=[45.2, 47.8, 48.1]))
    assert result.targets[0].forecast == [45.2, 47.8, 48.1]


def test_response_exposes_model_provenance_and_warnings() -> None:
    result = from_rest_response(_request(), _rest_payload(["cpu_usage"]))
    assert result.model.id == "timesfm-3.0"
    assert result.warnings == []
    assert result.horizon == 3


def test_reordered_results_are_rejected() -> None:
    request = _request(
        targets=[
            {"id": "a", "values": list(TARGET_CONTEXT)},
            {"id": "b", "values": list(TARGET_CONTEXT)},
        ]
    )
    payload = _rest_payload(["b", "a"])
    with pytest.raises(ForecastAdapterError) as info:
        from_rest_response(request, payload)
    assert info.value.code is ErrorCode.UPSTREAM_CONTRACT_ERROR


def test_missing_result_is_rejected() -> None:
    request = _request(
        targets=[
            {"id": "a", "values": list(TARGET_CONTEXT)},
            {"id": "b", "values": list(TARGET_CONTEXT)},
        ]
    )
    with pytest.raises(ForecastAdapterError):
        from_rest_response(request, _rest_payload(["a"]))


def test_missing_quantile_level_is_rejected() -> None:
    request = _request(quantiles=[0.2])
    payload = _rest_payload(["cpu_usage"], levels=[0.1, 0.5, 0.9])
    with pytest.raises(ForecastAdapterError, match="omitted"):
        from_rest_response(request, payload)


def test_malformed_forecast_length_is_rejected() -> None:
    payload = _rest_payload(["cpu_usage"])
    payload["targets"][0]["forecast"] = [1.0]
    with pytest.raises(ForecastAdapterError, match="wrong length"):
        from_rest_response(_request(), payload)


def test_malformed_quantile_length_is_rejected() -> None:
    request = _request(quantiles=[0.1])
    payload = _rest_payload(["cpu_usage"], quantiles=[{"level": 0.1, "values": [1.0]}])
    with pytest.raises(ForecastAdapterError, match="wrong length"):
        from_rest_response(request, payload)


def test_non_finite_output_is_rejected() -> None:
    payload = _rest_payload(["cpu_usage"])
    payload["targets"][0]["forecast"] = [1.0, 2.0, float("inf")]
    with pytest.raises(ForecastAdapterError, match="non-finite"):
        from_rest_response(_request(), payload)


def test_malformed_success_payload_is_rejected() -> None:
    with pytest.raises(ForecastAdapterError) as info:
        from_rest_response(_request(), {"unexpected": True})
    assert info.value.code is ErrorCode.UPSTREAM_CONTRACT_ERROR


def test_horizon_mismatch_is_rejected() -> None:
    with pytest.raises(ForecastAdapterError, match="horizon"):
        from_rest_response(_request(), _rest_payload(["cpu_usage"], horizon=2))


def _client(handler) -> ForecastApiClient:
    return ForecastApiClient("http://api.test", transport=httpx.MockTransport(handler))


def test_execute_forecast_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_rest_payload(["cpu_usage"]))

    result = asyncio.run(execute_forecast(_client(handler), _request()))
    assert result.targets[0].forecast == [1.0, 1.0, 1.0]


def test_execute_forecast_rejection_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"title": "Unprocessable Entity", "detail": "too long"})

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.FORECAST_REJECTED
    assert info.value.status == 422


def test_execute_forecast_unreachable_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed to connect to http://internal.example:9999 via proxy corp-proxy"
        )

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.API_UNAVAILABLE
    assert "internal.example" not in info.value.message
    assert "corp-proxy" not in info.value.message
    assert info.value.message == "Precog API is unavailable"


def test_execute_forecast_server_error_is_typed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"title": "Internal Server Error"})

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.INFERENCE_FAILED


def test_non_json_upstream_body_is_not_exposed() -> None:
    secret = "http://internal.example:8080 secret-token"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=secret, headers={"content-type": "text/html"})

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.INFERENCE_FAILED
    assert "internal.example" not in info.value.message
    assert "secret-token" not in info.value.message


def test_non_json_4xx_body_is_not_exposed() -> None:
    secret = "Traceback: internal host db.internal.example"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=secret, headers={"content-type": "text/plain"})

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.FORECAST_REJECTED
    assert "db.internal.example" not in info.value.message


def test_json_non_problem_body_is_not_exposed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "proxy at http://internal.example"})

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert "internal.example" not in info.value.message


@pytest.mark.parametrize("body", [[], "boom", 7, None, {"title": ["nope"], "detail": {"a": 1}}])
def test_malformed_problem_json_is_sanitized(body: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text=json.dumps(body),
            headers={"content-type": "application/problem+json"},
        )

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.INFERENCE_FAILED
    assert info.value.message == "Precog API error (HTTP 500)"


def test_valid_problem_json_preserves_title_and_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            text=json.dumps({"title": "Unprocessable Entity", "detail": "too long"}),
            headers={"content-type": "application/problem+json"},
        )

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_forecast(_client(handler), _request()))
    assert info.value.code is ErrorCode.FORECAST_REJECTED
    assert info.value.message == "Unprocessable Entity: too long"


def test_map_api_error_auth_is_unavailable() -> None:
    error = map_api_error(ApiError("no auth", status=401))
    assert error.code is ErrorCode.API_UNAVAILABLE


def test_to_payload_omits_empty_details() -> None:
    error = ForecastAdapterError(ErrorCode.INVALID_REQUEST, "bad")
    assert error.to_payload() == {"code": "INVALID_REQUEST", "message": "bad"}
    error = ForecastAdapterError(ErrorCode.INVALID_REQUEST, "bad", details={"field": "targets"})
    assert error.to_payload()["details"] == {"field": "targets"}

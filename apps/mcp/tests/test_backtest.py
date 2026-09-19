from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from precog_mcp.adapter import (
    ErrorCode,
    ForecastAdapterError,
    backtest_to_forecast_request,
    evaluate_backtest,
    execute_backtest,
)
from precog_mcp.client import ForecastApiClient
from precog_mcp.models import (
    BacktestToolRequest,
    ForecastResult,
    ModelProvenance,
    TargetForecast,
)
from precog_schemas import QUANTILE_LEVELS

pytestmark = pytest.mark.unit

# Full history; the last two values ([4.0, 5.0]) are the holdout.
FULL_VALUES = [1.0, 2.0, 3.0, 4.0, 5.0]
HORIZON = 2
ACTUAL = [4.0, 5.0]


def _request(**overrides: Any) -> BacktestToolRequest:
    payload: dict[str, Any] = {
        "targets": [{"id": "a", "values": list(FULL_VALUES)}],
        "horizon": HORIZON,
    }
    payload.update(overrides)
    return BacktestToolRequest.model_validate(payload)


def _forecast_result(
    *,
    ids: list[str] | None = None,
    horizon: int = HORIZON,
    forecast: list[float] | None = None,
    quantiles: dict[str, list[float]] | None = None,
) -> ForecastResult:
    ids = ids or ["a"]
    return ForecastResult(
        horizon=horizon,
        targets=[
            TargetForecast(
                id=series_id,
                forecast=forecast if forecast is not None else [3.0] * horizon,
                quantiles=quantiles or {},
            )
            for series_id in ids
        ],
        model=ModelProvenance(id="timesfm-3.0"),
    )


def _rest_payload(ids: list[str], horizon: int, forecast: list[float]) -> dict[str, Any]:
    return {
        "model": "timesfm-3.0",
        "horizon": horizon,
        "quantile_levels": list(QUANTILE_LEVELS),
        "results": [
            {
                "id": series_id,
                "forecast": forecast,
                # Canonical REST orientation: one row per step, columns by level.
                "quantiles": [
                    [float(row + column) for column in range(len(QUANTILE_LEVELS))]
                    for row in range(horizon)
                ],
            }
            for series_id in ids
        ],
        "usage": {"latency_ms": 1.0, "context_len": 3},
    }


def _client(handler) -> ForecastApiClient:
    return ForecastApiClient("http://api.test", transport=httpx.MockTransport(handler))


def test_split_holds_out_the_tail_and_splits_covariates() -> None:
    request = _request(
        past_covariates=[{"id": "p", "values": [10.0, 20.0, 30.0, 40.0, 50.0]}],
        known_future_covariates=[{"id": "k", "values": [0.0, 0.0, 0.0, 1.0, 1.0]}],
    )
    forecast_request = backtest_to_forecast_request(request)

    assert forecast_request.targets[0].values == [1.0, 2.0, 3.0]
    assert forecast_request.past_covariates[0].values == [10.0, 20.0, 30.0]
    known = forecast_request.known_future_covariates[0]
    assert known.history == [0.0, 0.0, 0.0]
    assert known.future == [1.0, 1.0]
    assert forecast_request.horizon == HORIZON
    assert forecast_request.quantiles == [0.1, 0.9]


def test_evaluate_backtest_reports_objective_metrics() -> None:
    result = evaluate_backtest(
        _request(),
        _forecast_result(forecast=[3.0, 3.0], quantiles={"0.1": [2.0, 2.0], "0.9": [4.0, 4.0]}),
    )
    target = result.targets[0]
    assert target.actual == ACTUAL
    assert target.forecast == [3.0, 3.0]
    assert target.metrics.mae == pytest.approx(1.5)
    assert target.metrics.rmse == pytest.approx(2.5**0.5)
    assert target.metrics.smape == pytest.approx(39.285714285714285)
    coverage = target.metrics.coverage
    assert coverage is not None
    assert coverage.lower == 0.1
    assert coverage.upper == 0.9
    assert coverage.percent == pytest.approx(50.0)
    assert result.horizon == HORIZON
    assert result.model.id == "timesfm-3.0"


def test_smape_treats_a_zero_denominator_as_zero() -> None:
    request = _request(targets=[{"id": "a", "values": [0.0, 0.0, 0.0]}])
    result = evaluate_backtest(request, _forecast_result(forecast=[0.0, 0.0]))
    assert result.targets[0].metrics.smape == 0.0
    assert result.targets[0].metrics.mae == 0.0


def test_coverage_requires_both_sides_of_the_median() -> None:
    only_lower = evaluate_backtest(_request(), _forecast_result(quantiles={"0.1": [2.0, 2.0]}))
    assert only_lower.targets[0].metrics.coverage is None

    only_median = evaluate_backtest(_request(), _forecast_result(quantiles={"0.5": [3.0, 3.0]}))
    assert only_median.targets[0].metrics.coverage is None


def test_evaluate_backtest_handles_multiple_targets() -> None:
    request = _request(
        targets=[
            {"id": "a", "values": list(FULL_VALUES)},
            {"id": "b", "values": [10.0, 11.0, 12.0, 13.0, 14.0]},
        ]
    )
    result = evaluate_backtest(
        request,
        _forecast_result(
            ids=["a", "b"], forecast=[4.0, 4.0], quantiles={"0.1": [0, 0], "0.9": [9, 9]}
        ),
    )
    assert [target.id for target in result.targets] == ["a", "b"]
    assert result.targets[1].actual == [13.0, 14.0]


def test_evaluate_backtest_rejects_reordered_results() -> None:
    request = _request(
        targets=[
            {"id": "a", "values": list(FULL_VALUES)},
            {"id": "b", "values": list(FULL_VALUES)},
        ]
    )
    with pytest.raises(ForecastAdapterError) as info:
        evaluate_backtest(request, _forecast_result(ids=["b", "a"]))
    assert info.value.code is ErrorCode.UPSTREAM_CONTRACT_ERROR


def test_evaluate_backtest_rejects_wrong_horizon() -> None:
    with pytest.raises(ForecastAdapterError, match="horizon"):
        evaluate_backtest(_request(), _forecast_result(horizon=3, forecast=[1.0, 2.0, 3.0]))


def test_execute_backtest_reuses_the_forecast_path() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_rest_payload(["a"], HORIZON, [4.0, 4.0]))

    result = asyncio.run(execute_backtest(_client(handler), _request()))

    body = seen["body"]
    assert body["series"][0]["target"] == [1.0, 2.0, 3.0]
    assert body["horizon"] == HORIZON
    target = result.targets[0]
    assert target.actual == ACTUAL
    assert target.forecast == [4.0, 4.0]
    assert target.metrics.mae == pytest.approx(0.5)
    assert target.metrics.smape == pytest.approx(11.11111111111111)
    assert target.metrics.coverage is not None
    assert target.metrics.coverage.percent == pytest.approx(100.0)


def test_execute_backtest_maps_transport_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("failed to connect to http://internal.example:9999")

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_backtest(_client(handler), _request()))
    assert info.value.code is ErrorCode.API_UNAVAILABLE
    assert info.value.message == "Precog API is unavailable"


def test_execute_backtest_maps_backend_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"title": "Unprocessable Entity", "detail": "too long"})

    with pytest.raises(ForecastAdapterError) as info:
        asyncio.run(execute_backtest(_client(handler), _request()))
    assert info.value.code is ErrorCode.FORECAST_REJECTED

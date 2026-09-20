from __future__ import annotations

import pytest

from precog_api.execution import (
    ExecutionResult,
    QuantileExecutionResult,
    TargetExecutionResult,
)
from precog_api.mapping import to_execution_problem, to_forecast_response
from precog_schemas import ForecastRequest, HistoricalSeries, KnownFutureSeries

pytestmark = pytest.mark.unit


def test_request_compiles_to_execution_problem() -> None:
    request = ForecastRequest(
        horizon=2,
        targets=[
            HistoricalSeries(id="a", values=[1.0, 2.0, 3.0]),
            HistoricalSeries(id="b", values=[4.0, 5.0, 6.0]),
        ],
        past_covariates=[HistoricalSeries(id="p", values=[0.0, 1.0, 2.0])],
        known_future_covariates=[
            KnownFutureSeries(id="k", history=[0.0, 0.0, 0.0], future=[1.0, 1.0])
        ],
        quantiles=[0.1, 0.5, 0.9],
    )

    problem = to_execution_problem(request)

    assert problem.horizon == 2
    assert [target.id for target in problem.targets] == ["a", "b"]
    assert problem.quantiles == [0.1, 0.5, 0.9]
    assert [covariate.id for covariate in problem.past_covariates] == ["p"]
    known = problem.known_future_covariates[0]
    assert known.history == [0.0, 0.0, 0.0]
    assert known.future == [1.0, 1.0]


def test_response_assembles_the_envelope() -> None:
    request = ForecastRequest(
        horizon=2,
        targets=[HistoricalSeries(id="a", values=[1.0, 2.0, 3.0])],
        quantiles=[0.1, 0.9],
    )
    result = ExecutionResult(
        targets=[
            TargetExecutionResult(
                id="a",
                forecast=[7.0, 8.0],
                quantiles=[
                    QuantileExecutionResult(level=0.1, values=[6.0, 7.0]),
                    QuantileExecutionResult(level=0.9, values=[8.0, 9.0]),
                ],
            )
        ]
    )

    response = to_forecast_response(
        request, result, model="timesfm-3.0", revision="abc123", latency_ms=1.5
    )

    assert response.horizon == 2
    assert response.model.id == "timesfm-3.0"
    assert response.model.revision == "abc123"
    assert response.usage.context_len == 3
    assert response.usage.latency_ms == 1.5
    target = response.targets[0]
    assert target.id == "a"
    assert target.forecast == [7.0, 8.0]
    assert [quantile.level for quantile in target.quantiles] == [0.1, 0.9]
    assert target.quantiles[1].values == [8.0, 9.0]

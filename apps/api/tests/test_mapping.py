from __future__ import annotations

import pytest

from precog_api.execution import (
    ExecutionResult,
    QuantileExecutionResult,
    TargetExecutionResult,
)
from precog_api.mapping import to_execution_problems, to_forecast_response
from precog_schemas import (
    QUANTILE_LEVELS,
    ForecastOptions,
    ForecastRequest,
    Mode,
    SeriesInput,
)

pytestmark = pytest.mark.unit


def test_univariate_multiple_series_compile_to_independent_problems() -> None:
    request = ForecastRequest(
        mode=Mode.univariate,
        horizon=2,
        series=[
            SeriesInput(
                id="a",
                target=[1.0, 2.0, 3.0],
                past_covariates={"p": [0.0, 1.0, 2.0]},
                future_covariates={"k": [0.0, 0.0, 0.0, 1.0, 1.0]},
            ),
            SeriesInput(id="b", target=[4.0, 5.0, 6.0]),
        ],
        options=ForecastOptions(return_quantiles=True),
    )

    problems = to_execution_problems(request)

    assert len(problems) == 2
    first = problems[0]
    assert [target.id for target in first.targets] == ["a"]
    assert [covariate.id for covariate in first.past_covariates] == ["p"]
    assert first.known_future_covariates[0].history == [0.0, 0.0, 0.0]
    assert first.known_future_covariates[0].future == [1.0, 1.0]
    assert first.quantiles == list(QUANTILE_LEVELS)
    assert [target.id for target in problems[1].targets] == ["b"]


def test_multivariate_compiles_to_one_joint_problem() -> None:
    request = ForecastRequest(
        mode=Mode.multivariate,
        horizon=2,
        series=[
            SeriesInput(id="a", target=[1.0, 2.0, 3.0]),
            SeriesInput(id="b", target=[4.0, 5.0, 6.0]),
        ],
        past_covariates={"p": [0.0, 1.0, 2.0]},
        future_covariates={"k": [0.0, 0.0, 0.0, 1.0, 1.0]},
    )

    problems = to_execution_problems(request)

    assert len(problems) == 1
    assert [target.id for target in problems[0].targets] == ["a", "b"]
    assert [covariate.id for covariate in problems[0].past_covariates] == ["p"]


def test_response_rebuilds_the_legacy_matrix() -> None:
    request = ForecastRequest(
        mode=Mode.univariate,
        horizon=2,
        series=[SeriesInput(id="a", target=[1.0, 2.0, 3.0])],
    )
    quantiles = [
        QuantileExecutionResult(level=level, values=[level, level + 1.0])
        for level in QUANTILE_LEVELS
    ]
    results = [
        ExecutionResult(
            targets=[TargetExecutionResult(id="a", forecast=[7.0, 8.0], quantiles=quantiles)]
        )
    ]

    response = to_forecast_response(request, results, model="timesfm-3.0", latency_ms=1.5)

    assert response.model == "timesfm-3.0"
    assert response.quantile_levels == list(QUANTILE_LEVELS)
    assert response.usage.context_len == 3
    first = response.results[0]
    assert first.id == "a"
    assert first.forecast == [7.0, 8.0]
    assert first.quantiles is not None
    assert first.quantiles[0] == list(QUANTILE_LEVELS)

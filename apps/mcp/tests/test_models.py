from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from precog_mcp.models import (
    BacktestToolRequest,
    ForecastResult,
    ForecastToolRequest,
    ModelProvenance,
    TargetForecast,
    quantile_key,
)

pytestmark = pytest.mark.unit

MINIMAL = {
    "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
    "horizon": 2,
}

FULL = {
    "targets": [
        {"id": "cpu_usage", "values": [31.2, 32.8, 35.1, 37.4, 41.2, 43.7]},
        {"id": "memory_usage", "values": [61.0, 61.4, 62.1, 63.0, 64.8, 65.1]},
    ],
    "horizon": 3,
    "past_covariates": [{"id": "request_rate", "values": [1200, 1250, 1410, 1530, 1710, 1800]}],
    "known_future_covariates": [
        {"id": "maintenance_window", "history": [0, 0, 0, 0, 0, 0], "future": [0, 1, 1]}
    ],
    "quantiles": [0.1, 0.9],
}


def test_minimal_request_defaults() -> None:
    request = ForecastToolRequest.model_validate(MINIMAL)
    assert request.past_covariates == []
    assert request.known_future_covariates == []
    assert request.quantiles == [0.1, 0.9]


def test_full_request_round_trips() -> None:
    request = ForecastToolRequest.model_validate(FULL)
    assert [target.id for target in request.targets] == ["cpu_usage", "memory_usage"]
    assert request.known_future_covariates[0].future == [0, 1, 1]


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate({**MINIMAL, "mode": "univariate"})


def test_series_unknown_field_is_rejected() -> None:
    payload = {"targets": [{"id": "a", "values": [1.0], "target": [1.0]}], "horizon": 1}
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate(payload)


def test_targets_required_and_non_empty() -> None:
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate({"horizon": 1})
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate({"targets": [], "horizon": 1})


def test_horizon_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate({**MINIMAL, "horizon": 0})


def test_empty_id_rejected() -> None:
    payload = {"targets": [{"id": "", "values": [1.0]}], "horizon": 1}
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate(payload)


def test_empty_values_rejected() -> None:
    payload = {"targets": [{"id": "a", "values": []}], "horizon": 1}
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate(payload)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_target_rejected(bad: float) -> None:
    payload = {"targets": [{"id": "a", "values": [1.0, bad]}], "horizon": 1}
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate(payload)


def test_null_value_rejected() -> None:
    payload = {"targets": [{"id": "a", "values": [1.0, None]}], "horizon": 1}
    with pytest.raises(ValidationError):
        ForecastToolRequest.model_validate(payload)


def test_target_length_mismatch_rejected() -> None:
    payload = {
        "targets": [
            {"id": "cpu_usage", "values": [1.0, 2.0]},
            {"id": "memory_usage", "values": [1.0]},
        ],
        "horizon": 1,
    }
    with pytest.raises(ValidationError, match="same number of values"):
        ForecastToolRequest.model_validate(payload)


def test_duplicate_ids_across_collections_rejected() -> None:
    payload = {
        "targets": [{"id": "a", "values": [1.0, 2.0]}],
        "horizon": 1,
        "past_covariates": [{"id": "a", "values": [1.0, 2.0]}],
    }
    with pytest.raises(ValidationError, match="globally unique"):
        ForecastToolRequest.model_validate(payload)


def test_duplicate_target_ids_rejected() -> None:
    payload = {
        "targets": [
            {"id": "a", "values": [1.0, 2.0]},
            {"id": "a", "values": [1.0, 2.0]},
        ],
        "horizon": 1,
    }
    with pytest.raises(ValidationError, match="globally unique"):
        ForecastToolRequest.model_validate(payload)


def test_past_covariate_length_must_match_context() -> None:
    payload = {
        "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
        "horizon": 1,
        "past_covariates": [{"id": "p", "values": [1.0, 2.0]}],
    }
    with pytest.raises(ValidationError, match="past covariate"):
        ForecastToolRequest.model_validate(payload)


def test_known_future_history_length_must_match_context() -> None:
    payload = {
        "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
        "horizon": 2,
        "known_future_covariates": [{"id": "k", "history": [1.0, 2.0], "future": [3.0, 4.0]}],
    }
    with pytest.raises(ValidationError, match="history"):
        ForecastToolRequest.model_validate(payload)


def test_known_future_future_length_must_match_horizon() -> None:
    payload = {
        "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
        "horizon": 2,
        "known_future_covariates": [{"id": "k", "history": [1.0, 2.0, 3.0], "future": [3.0]}],
    }
    with pytest.raises(ValidationError, match="future"):
        ForecastToolRequest.model_validate(payload)


def test_quantiles_must_be_known_levels() -> None:
    with pytest.raises(ValidationError, match="unsupported quantile"):
        ForecastToolRequest.model_validate({**MINIMAL, "quantiles": [0.25]})


def test_quantiles_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="duplicate quantile"):
        ForecastToolRequest.model_validate({**MINIMAL, "quantiles": [0.1, 0.1]})


def test_empty_quantiles_allowed() -> None:
    request = ForecastToolRequest.model_validate({**MINIMAL, "quantiles": []})
    assert request.quantiles == []


def test_quantile_order_preserved() -> None:
    request = ForecastToolRequest.model_validate({**MINIMAL, "quantiles": [0.9, 0.1, 0.5]})
    assert request.quantiles == [0.9, 0.1, 0.5]


def test_quantile_key_is_canonical_decimal() -> None:
    assert quantile_key(0.1) == "0.1"
    assert quantile_key(0.5) == "0.5"


def test_target_forecast_quantile_keys_are_canonical() -> None:
    forecast = TargetForecast(
        id="a",
        forecast=[1.0, 2.0],
        quantiles={"0.1": [1.0, 2.0], "0.9": [1.0, 2.0]},
    )
    dumped = forecast.model_dump(mode="json")
    assert list(dumped["quantiles"]) == ["0.1", "0.9"]


def test_target_forecast_rejects_bad_quantile_key() -> None:
    with pytest.raises(ValidationError, match="unsupported quantile key"):
        TargetForecast(id="a", forecast=[1.0], quantiles={"0.15": [1.0]})


def test_result_rejects_non_finite_forecast() -> None:
    with pytest.raises(ValidationError):
        ForecastResult(
            horizon=1,
            targets=[TargetForecast(id="a", forecast=[math.inf])],
            model=ModelProvenance(id="timesfm-3.0"),
        )


BACKTEST_MINIMAL = {
    "targets": [{"id": "a", "values": [1.0, 2.0, 3.0, 4.0, 5.0]}],
    "horizon": 2,
}


def test_backtest_defaults_and_context_length() -> None:
    request = BacktestToolRequest.model_validate(BACKTEST_MINIMAL)
    assert request.past_covariates == []
    assert request.known_future_covariates == []
    assert request.quantiles == [0.1, 0.9]
    assert request.context_length == 3


def test_backtest_target_must_exceed_horizon() -> None:
    with pytest.raises(ValidationError, match="more values than the horizon"):
        BacktestToolRequest.model_validate(
            {"targets": [{"id": "a", "values": [1.0, 2.0]}], "horizon": 2}
        )
    with pytest.raises(ValidationError, match="more values than the horizon"):
        BacktestToolRequest.model_validate(
            {"targets": [{"id": "a", "values": [1.0]}], "horizon": 2}
        )


def test_backtest_target_lengths_must_match() -> None:
    payload = {
        "targets": [
            {"id": "a", "values": [1.0, 2.0, 3.0, 4.0]},
            {"id": "b", "values": [1.0, 2.0, 3.0]},
        ],
        "horizon": 2,
    }
    with pytest.raises(ValidationError, match="same number of values"):
        BacktestToolRequest.model_validate(payload)


def test_backtest_ids_must_be_globally_unique() -> None:
    payload = {
        **BACKTEST_MINIMAL,
        "past_covariates": [{"id": "a", "values": [1.0, 2.0, 3.0, 4.0, 5.0]}],
    }
    with pytest.raises(ValidationError, match="globally unique"):
        BacktestToolRequest.model_validate(payload)


def test_backtest_covariates_must_span_the_full_timeline() -> None:
    payload = {
        **BACKTEST_MINIMAL,
        "past_covariates": [{"id": "p", "values": [1.0, 2.0, 3.0, 4.0]}],
    }
    with pytest.raises(ValidationError, match="full target timeline"):
        BacktestToolRequest.model_validate(payload)

    payload = {
        **BACKTEST_MINIMAL,
        "known_future_covariates": [{"id": "k", "values": [0.0, 0.0, 0.0]}],
    }
    with pytest.raises(ValidationError, match="full target timeline"):
        BacktestToolRequest.model_validate(payload)


def test_backtest_quantiles_share_the_forecast_validation() -> None:
    with pytest.raises(ValidationError, match="unsupported quantile"):
        BacktestToolRequest.model_validate({**BACKTEST_MINIMAL, "quantiles": [0.25]})


def test_backtest_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BacktestToolRequest.model_validate({**BACKTEST_MINIMAL, "mode": "univariate"})

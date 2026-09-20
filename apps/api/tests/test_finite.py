from __future__ import annotations

import pytest
from pydantic import ValidationError

from precog_schemas import ForecastRequest, HistoricalSeries, KnownFutureSeries

pytestmark = pytest.mark.unit


def test_rejects_nan_target() -> None:
    with pytest.raises(ValidationError):
        ForecastRequest(
            horizon=1,
            targets=[HistoricalSeries(id="a", values=[1.0, float("nan"), 3.0])],
        )


def test_rejects_infinite_covariate() -> None:
    with pytest.raises(ValidationError):
        ForecastRequest(
            horizon=1,
            targets=[HistoricalSeries(id="a", values=[1.0, 2.0, 3.0])],
            past_covariates=[HistoricalSeries(id="p", values=[0.0, float("inf"), 0.0])],
        )


def test_rejects_infinite_known_future() -> None:
    with pytest.raises(ValidationError):
        ForecastRequest(
            horizon=1,
            targets=[HistoricalSeries(id="a", values=[1.0, 2.0, 3.0])],
            known_future_covariates=[
                KnownFutureSeries(id="k", history=[0.0, 0.0, 0.0], future=[float("-inf")])
            ],
        )

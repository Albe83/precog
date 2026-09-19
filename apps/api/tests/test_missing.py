from __future__ import annotations

import pytest
from pydantic import ValidationError

from precog_api.engine_timesfm3 import _interpolate
from precog_schemas import ForecastOptions, ForecastRequest, SeriesInput

pytestmark = pytest.mark.unit


def test_rejects_nan_target() -> None:
    with pytest.raises(ValidationError):
        ForecastRequest(horizon=1, series=[SeriesInput(id="a", target=[1.0, float("nan"), 3.0])])


def test_allows_interior_nan_when_interpolating() -> None:
    request = ForecastRequest(
        horizon=1,
        series=[SeriesInput(id="a", target=[1.0, float("nan"), 3.0])],
        options=ForecastOptions(interpolate_missing=True),
    )
    assert request.options.interpolate_missing is True


def test_rejects_edge_nan_even_when_interpolating() -> None:
    with pytest.raises(ValidationError):
        ForecastRequest(
            horizon=1,
            series=[SeriesInput(id="a", target=[float("nan"), 2.0, 3.0])],
            options=ForecastOptions(interpolate_missing=True),
        )


def test_interpolate_fills_interior_nan() -> None:
    result = _interpolate([1.0, float("nan"), 3.0], True)
    assert result.tolist() == [1.0, 2.0, 3.0]


def test_interpolate_is_noop_when_disabled() -> None:
    result = _interpolate([1.0, 2.0, 3.0], False)
    assert result.tolist() == [1.0, 2.0, 3.0]

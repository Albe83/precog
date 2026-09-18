from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from precog_api.engine_timesfm3 import _calibrate_quantiles
from precog_schemas import ForecastOptions

pytestmark = pytest.mark.unit


def test_calibrate_scales_around_median() -> None:
    quantiles = np.array([[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]])
    scaled = _calibrate_quantiles(quantiles, 2.0)
    assert scaled[0, 4] == 4.0
    assert scaled[0, 0] == -4.0
    assert scaled[0, 8] == 12.0


def test_calibrate_is_noop_for_one() -> None:
    quantiles = np.arange(9.0).reshape(1, 9)
    assert np.array_equal(_calibrate_quantiles(quantiles, 1.0), quantiles)


def test_calibrate_preserves_order() -> None:
    quantiles = np.array([[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]])
    for scale in (0.5, 1.5, 3.0):
        scaled = _calibrate_quantiles(quantiles, scale)
        assert np.all(np.diff(scaled[0]) >= 0)


def test_quantile_spread_scale_validation() -> None:
    assert ForecastOptions(quantile_spread_scale=2.5).quantile_spread_scale == 2.5
    with pytest.raises(ValidationError):
        ForecastOptions(quantile_spread_scale=0)
    with pytest.raises(ValidationError):
        ForecastOptions(quantile_spread_scale=11)

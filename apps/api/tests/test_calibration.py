from __future__ import annotations

import pytest
from pydantic import ValidationError

from precog_schemas import ForecastOptions

pytestmark = pytest.mark.unit


def test_quantile_spread_scale_validation() -> None:
    """The legacy wire option is still validated until the #178 cutover."""
    assert ForecastOptions(quantile_spread_scale=2.5).quantile_spread_scale == 2.5
    with pytest.raises(ValidationError):
        ForecastOptions(quantile_spread_scale=0)
    with pytest.raises(ValidationError):
        ForecastOptions(quantile_spread_scale=11)

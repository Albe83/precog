from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_schemas import ForecastOptions, ForecastRequest, Mode, SeriesInput

pytestmark = pytest.mark.integration

CACHE = os.environ.get("PRECOG_CACHE_DIR", "/home/albe/.cache/precog/models")


def _series(seed: int, level: float, length: int) -> list[float]:
    t = np.arange(length, dtype=np.float32)
    rng = np.random.default_rng(seed)
    values = level + 0.2 * t + 5 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 0.5, length)
    return [float(v) for v in values]


def test_multivariate_with_covariates_runs() -> None:
    if not Path(CACHE).is_dir():
        pytest.skip(f"model cache not available at {CACHE}")

    engine = TimesFM3Engine(
        Settings(
            engine="timesfm3",
            cache_dir=CACHE,
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )
    context, horizon = 48, 6
    promo = [0.0] * context + [1.0 if i % 2 == 0 else 0.0 for i in range(horizon)]
    request = ForecastRequest(
        mode=Mode.multivariate,
        horizon=horizon,
        series=[
            SeriesInput(id="a", target=_series(0, 100, context)),
            SeriesInput(id="b", target=_series(1, 80, context)),
        ],
        future_covariates={"promo": promo},
        options=ForecastOptions(return_quantiles=True),
    )

    results = engine.predict(request)

    assert [r.id for r in results] == ["a", "b"]
    assert all(len(r.forecast) == horizon for r in results)
    assert all(r.quantiles is not None and len(r.quantiles) == horizon for r in results)

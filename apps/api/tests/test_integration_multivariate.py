from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_api.execution import (
    ExecutionKnownFutureCovariate,
    ExecutionPastCovariate,
    ExecutionProblem,
    ExecutionTarget,
)
from precog_schemas import QUANTILE_LEVELS

pytestmark = pytest.mark.integration

CACHE = os.environ.get("PRECOG_CACHE_DIR", "/home/albe/.cache/precog/models")


def _engine() -> TimesFM3Engine:
    return TimesFM3Engine(
        Settings(
            engine="timesfm3",
            cache_dir=CACHE,
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )


def _series(seed: int, level: float, length: int) -> list[float]:
    t = np.arange(length, dtype=np.float32)
    rng = np.random.default_rng(seed)
    values = level + 0.2 * t + 5 * np.sin(2 * np.pi * t / 7) + rng.normal(0, 0.5, length)
    return [float(v) for v in values]


def test_multivariate_with_covariates_runs() -> None:
    if not Path(CACHE).is_dir():
        pytest.skip(f"model cache not available at {CACHE}")

    engine = _engine()
    context, horizon = 48, 6
    promo = [1.0 if i % 2 == 0 else 0.0 for i in range(horizon)]
    problem = ExecutionProblem(
        horizon=horizon,
        targets=[
            ExecutionTarget(id="a", values=_series(0, 100, context)),
            ExecutionTarget(id="b", values=_series(1, 80, context)),
        ],
        quantiles=list(QUANTILE_LEVELS),
        known_future_covariates=[
            ExecutionKnownFutureCovariate(id="promo", history=[0.0] * context, future=promo)
        ],
    )

    result = engine.predict(problem)

    assert [target.id for target in result.targets] == ["a", "b"]
    assert all(len(target.forecast) == horizon for target in result.targets)
    assert all(len(target.quantiles) == len(QUANTILE_LEVELS) for target in result.targets)
    assert all(
        len(quantile.values) == horizon
        for target in result.targets
        for quantile in target.quantiles
    )


def test_single_target_with_covariates_runs() -> None:
    if not Path(CACHE).is_dir():
        pytest.skip(f"model cache not available at {CACHE}")

    context, horizon = 48, 6
    problem = ExecutionProblem(
        horizon=horizon,
        targets=[ExecutionTarget(id="solo", values=_series(2, 120, context))],
        quantiles=list(QUANTILE_LEVELS),
        past_covariates=[
            ExecutionPastCovariate(id="temp", values=[float(i % 5) for i in range(context)])
        ],
        known_future_covariates=[
            ExecutionKnownFutureCovariate(
                id="promo", history=[0.0] * context, future=[1.0] * horizon
            )
        ],
    )

    result = _engine().predict(problem)

    assert [target.id for target in result.targets] == ["solo"]
    assert len(result.targets[0].forecast) == horizon
    assert len(result.targets[0].quantiles) == len(QUANTILE_LEVELS)

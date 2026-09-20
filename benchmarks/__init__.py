"""Benchmark helpers."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from precog_api.execution import Engine, ExecutionProblem, ExecutionTarget

# The default TimesFM-3 quantile grid used by the benchmark helpers.
QUANTILE_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


def predict_univariate(
    engine: Engine,
    series_id: str,
    values: Sequence[float],
    horizon: int,
    *,
    return_quantiles: bool = True,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Run one series through the canonical engine boundary.

    Returns ``(point_forecast, quantile_matrix)`` where the matrix is
    ``(horizon, len(QUANTILE_LEVELS))`` in ``QUANTILE_LEVELS`` order.
    """
    problem = ExecutionProblem(
        horizon=horizon,
        targets=[ExecutionTarget(id=series_id, values=[float(v) for v in values])],
        quantiles=list(QUANTILE_LEVELS) if return_quantiles else [],
    )
    return _normalize(engine.predict(problem).targets[0], horizon, return_quantiles)


def predict_multivariate(
    engine: Engine,
    ids: Sequence[str],
    contexts: Sequence[Sequence[float]],
    horizon: int,
    *,
    return_quantiles: bool = True,
) -> list[tuple[np.ndarray, np.ndarray | None]]:
    """Run several jointly-forecast targets through the canonical boundary."""
    problem = ExecutionProblem(
        horizon=horizon,
        targets=[
            ExecutionTarget(id=series_id, values=[float(v) for v in values])
            for series_id, values in zip(ids, contexts, strict=True)
        ],
        quantiles=list(QUANTILE_LEVELS) if return_quantiles else [],
    )
    return [
        _normalize(target, horizon, return_quantiles) for target in engine.predict(problem).targets
    ]


def _normalize(
    target, horizon: int, return_quantiles: bool
) -> tuple[np.ndarray, np.ndarray | None]:
    forecast = np.asarray(target.forecast)
    if not return_quantiles:
        return forecast, None
    by_level = {quantile.level: quantile.values for quantile in target.quantiles}
    matrix = np.asarray(
        [[by_level[level][step] for level in QUANTILE_LEVELS] for step in range(horizon)]
    )
    return forecast, matrix


__all__ = ["predict_multivariate", "predict_univariate"]

"""Translation between the pre-release REST wire contract and the canonical
execution boundary (ADR 0006, Phase 2 step 1).

This is the compatibility bridge: the wire contract in :mod:`precog_schemas`
still carries the legacy shape (``mode``, per-series covariates,
``ForecastOptions``), and this module compiles it into canonical
:class:`~precog_api.execution.ExecutionProblem` values. A univariate request with
several independent series is compiled into one problem per series, which is the
only faithful representation at the canonical boundary.

The reverse direction rebuilds the legacy :class:`ForecastResponse` envelope so
this refactor can land without changing REST/MCP/SDK clients.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from precog_api.execution import (
    ExecutionKnownFutureCovariate,
    ExecutionPastCovariate,
    ExecutionProblem,
    ExecutionResult,
    ExecutionTarget,
    TargetExecutionResult,
)
from precog_schemas import (
    QUANTILE_LEVELS,
    ForecastRequest,
    ForecastResponse,
    Mode,
    SeriesForecast,
    Usage,
)

_MEDIAN_LEVEL = QUANTILE_LEVELS[len(QUANTILE_LEVELS) // 2]


class UnsupportedExecutionOptionError(ValueError):
    """A legacy wire option has no canonical execution equivalent.

    The compatibility bridge must not accept a request it cannot faithfully
    execute; the API surfaces this as a client-visible rejection.
    """


def to_execution_problems(request: ForecastRequest) -> list[ExecutionProblem]:
    """Compile the legacy wire request into canonical execution problems."""
    if request.options.symmetric_averaging:
        raise UnsupportedExecutionOptionError(
            "symmetric_averaging is no longer supported: Precog uses a fixed "
            "execution default (ADR 0006/0007)"
        )

    levels = list(QUANTILE_LEVELS) if request.options.return_quantiles else []
    interpolate = request.options.interpolate_missing

    if request.mode is Mode.multivariate:
        context = request.series[0].context_len
        return [
            ExecutionProblem(
                horizon=request.horizon,
                targets=[
                    ExecutionTarget(id=series.id, values=_interpolate(series.target, interpolate))
                    for series in request.series
                ],
                quantiles=levels,
                past_covariates=[
                    ExecutionPastCovariate(id=name, values=_interpolate(values, interpolate))
                    for name, values in request.past_covariates.items()
                ],
                known_future_covariates=_known_future(
                    request.future_covariates, context, interpolate
                ),
            )
        ]

    problems: list[ExecutionProblem] = []
    for series in request.series:
        problems.append(
            ExecutionProblem(
                horizon=request.horizon,
                targets=[
                    ExecutionTarget(id=series.id, values=_interpolate(series.target, interpolate))
                ],
                quantiles=levels,
                past_covariates=[
                    ExecutionPastCovariate(id=name, values=_interpolate(values, interpolate))
                    for name, values in series.past_covariates.items()
                ],
                known_future_covariates=_known_future(
                    series.future_covariates, series.context_len, interpolate
                ),
            )
        )
    return problems


def to_forecast_response(
    request: ForecastRequest,
    results: Sequence[ExecutionResult],
    *,
    model: str,
    latency_ms: float,
) -> ForecastResponse:
    """Rebuild the legacy REST response from canonical execution results."""
    targets = [target for result in results for target in result.targets]
    return ForecastResponse(
        model=model,
        horizon=request.horizon,
        quantile_levels=list(QUANTILE_LEVELS),
        results=[_series_forecast(target, request) for target in targets],
        usage=Usage(latency_ms=latency_ms, context_len=request.series[0].context_len),
    )


def _known_future(
    covariates: Mapping[str, Sequence[float]], context: int, interpolate: bool
) -> list[ExecutionKnownFutureCovariate]:
    """Split legacy ``context + horizon`` future covariates into history/future."""
    known: list[ExecutionKnownFutureCovariate] = []
    for name, values in covariates.items():
        filled = _interpolate(list(values), interpolate)
        known.append(
            ExecutionKnownFutureCovariate(
                id=name, history=filled[:context], future=filled[context:]
            )
        )
    return known


def _series_forecast(target: TargetExecutionResult, request: ForecastRequest) -> SeriesForecast:
    """Rebuild one legacy per-series result, matrix quantiles included.

    The legacy ``quantile_spread_scale`` is preserved here (it is calibration,
    not execution), so a non-default value still changes the response exactly as
    before the canonical refactor.
    """
    if not request.options.return_quantiles:
        return SeriesForecast(id=target.id, forecast=target.forecast, quantiles=None)
    by_level = {quantile.level: quantile.values for quantile in target.quantiles}
    scale = request.options.quantile_spread_scale
    if scale == 1.0:
        rows = [
            [by_level[level][step] for level in QUANTILE_LEVELS] for step in range(request.horizon)
        ]
        return SeriesForecast(id=target.id, forecast=target.forecast, quantiles=rows)
    median = by_level[_MEDIAN_LEVEL]
    rows = [
        [median[step] + (by_level[level][step] - median[step]) * scale for level in QUANTILE_LEVELS]
        for step in range(request.horizon)
    ]
    return SeriesForecast(id=target.id, forecast=target.forecast, quantiles=rows)


def _interpolate(values: Sequence[float], enabled: bool) -> list[float]:
    """Linearly fill interior NaNs when enabled; edges stay finite by validation."""
    result = [float(value) for value in values]
    if not enabled or all(math.isfinite(value) for value in result):
        return result
    finite = [index for index, value in enumerate(result) if math.isfinite(value)]
    for index, value in enumerate(result):
        if math.isfinite(value):
            continue
        lower = max(candidate for candidate in finite if candidate < index)
        upper = min(candidate for candidate in finite if candidate > index)
        fraction = (index - lower) / (upper - lower)
        result[index] = result[lower] + (result[upper] - result[lower]) * fraction
    return result


__all__ = ["UnsupportedExecutionOptionError", "to_execution_problems", "to_forecast_response"]

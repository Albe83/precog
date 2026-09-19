"""Anti-corruption adapter between the MCP contract and the Precog REST API.

The MCP server remains an HTTP client of ``POST /v1/forecast``. This module owns
the translation so the public tool surface never leaks REST/backend DTOs or
TimesFM-specific execution controls.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.models import (
    BacktestMetrics,
    BacktestResult,
    BacktestToolRequest,
    ForecastResult,
    ForecastToolRequest,
    HistoricalSeries,
    IntervalCoverage,
    KnownFutureSeries,
    ModelProvenance,
    TargetBacktest,
    TargetForecast,
    quantile_key,
)
from precog_schemas import (
    ForecastOptions,
    ForecastRequest,
    ForecastResponse,
    Mode,
    SeriesInput,
)


class ErrorCode(StrEnum):
    """Stable error codes for the MCP boundary.

    The first five describe the forecast pipeline; ``INTERNAL_ERROR`` covers
    unexpected MCP server defects that cannot be attributed to the caller.
    """

    INVALID_REQUEST = "INVALID_REQUEST"
    FORECAST_REJECTED = "FORECAST_REJECTED"
    API_UNAVAILABLE = "API_UNAVAILABLE"
    UPSTREAM_CONTRACT_ERROR = "UPSTREAM_CONTRACT_ERROR"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ForecastAdapterError(RuntimeError):
    """A machine-readable failure crossing the MCP boundary."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.status = status

    def to_payload(self) -> dict[str, Any]:
        """Return the deterministic error envelope exposed to MCP consumers."""
        payload: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


def to_rest_request(request: ForecastToolRequest) -> ForecastRequest:
    """Map one consumer-facing request to the current REST contract.

    Mode selection is an internal adapter concern: a single target maps to a
    univariate request with per-series covariates, multiple targets map to one
    multivariate request with request-level covariates.
    """
    past = {series.id: list(series.values) for series in request.past_covariates}
    # The backend wants a single context+horizon array; concatenation stays
    # internal to the adapter and is never part of the MCP schema.
    known_future = {
        series.id: [*series.history, *series.future] for series in request.known_future_covariates
    }
    options = ForecastOptions(return_quantiles=True)

    if len(request.targets) == 1:
        target = request.targets[0]
        return ForecastRequest(
            mode=Mode.univariate,
            horizon=request.horizon,
            series=[
                SeriesInput(
                    id=target.id,
                    target=list(target.values),
                    past_covariates=past,
                    future_covariates=known_future,
                )
            ],
            options=options,
        )

    return ForecastRequest(
        mode=Mode.multivariate,
        horizon=request.horizon,
        series=[SeriesInput(id=t.id, target=list(t.values)) for t in request.targets],
        options=options,
        past_covariates=past,
        future_covariates=known_future,
    )


def from_rest_response(request: ForecastToolRequest, payload: Mapping[str, Any]) -> ForecastResult:
    """Validate a REST success payload and build the consumer-facing result."""
    try:
        response = ForecastResponse.model_validate(payload)
    except ValidationError as exc:
        raise ForecastAdapterError(
            ErrorCode.UPSTREAM_CONTRACT_ERROR,
            "Precog API returned a malformed forecast response",
            details={"errors": exc.errors(include_url=False)},
        ) from exc

    if response.horizon != request.horizon:
        raise _contract_error(
            "Precog API returned an unexpected horizon",
            {"expected": request.horizon, "received": response.horizon},
        )
    if not response.model:
        raise _contract_error("Precog API returned an empty model identifier")

    requested_ids = [target.id for target in request.targets]
    result_ids = [series.id for series in response.results]
    if result_ids != requested_ids:
        raise _contract_error(
            "Precog API returned unexpected target ids",
            {"expected": requested_ids, "received": result_ids},
        )

    levels = list(response.quantile_levels)
    targets: list[TargetForecast] = []
    for target, series in zip(request.targets, response.results, strict=True):
        forecast = _finite_vector(
            series.forecast, request.horizon, label=f"forecast of '{target.id}'"
        )
        quantiles: dict[str, list[float]] = {}
        if request.quantiles:
            if series.quantiles is None:
                raise _contract_error(
                    "Precog API omitted requested quantiles",
                    {"target": target.id},
                )
            # The REST contract exposes quantiles as ``[horizon][level]`` (one row
            # per future step, columns in ``quantile_levels`` order). Validate the
            # orientation and resolve columns by level rather than by position.
            rows = series.quantiles
            if len(rows) != request.horizon:
                raise _contract_error(
                    "Precog API returned a malformed quantile matrix",
                    {
                        "target": target.id,
                        "expected_rows": request.horizon,
                        "rows": len(rows),
                    },
                )
            for row in rows:
                if len(row) != len(levels):
                    raise _contract_error(
                        "Precog API returned a malformed quantile matrix",
                        {
                            "target": target.id,
                            "expected_columns": len(levels),
                            "columns": len(row),
                        },
                    )
            for level in request.quantiles:
                index = _level_index(levels, level)
                if index is None:
                    raise _contract_error(
                        "Precog API omitted a requested quantile level",
                        {"target": target.id, "level": level},
                    )
                quantiles[quantile_key(level)] = _finite_vector(
                    [row[index] for row in rows],
                    request.horizon,
                    label=f"quantile {quantile_key(level)} of '{target.id}'",
                )
        targets.append(TargetForecast(id=target.id, forecast=forecast, quantiles=quantiles))

    return ForecastResult(
        horizon=request.horizon,
        targets=targets,
        model=ModelProvenance(id=response.model),
        warnings=[],
    )


def map_api_error(exc: ApiError) -> ForecastAdapterError:
    """Translate a REST client failure into a typed MCP-side error."""
    if exc.status is None or exc.status in (401, 403):
        return ForecastAdapterError(ErrorCode.API_UNAVAILABLE, str(exc))
    if exc.status >= 500:
        return ForecastAdapterError(ErrorCode.INFERENCE_FAILED, str(exc), status=exc.status)
    return ForecastAdapterError(ErrorCode.FORECAST_REJECTED, str(exc), status=exc.status)


async def execute_forecast(
    client: ForecastApiClient, request: ForecastToolRequest
) -> ForecastResult:
    """Run one forecast through the REST API, mapping every failure."""
    rest_request = to_rest_request(request)
    try:
        payload = await client.forecast(rest_request.model_dump(mode="json"))
    except ApiError as exc:
        raise map_api_error(exc) from exc
    return from_rest_response(request, payload)


def backtest_to_forecast_request(request: BacktestToolRequest) -> ForecastToolRequest:
    """Split a backtest at the holdout cutoff and build the forecast problem.

    The head of every series becomes the context; the tail is held out. A
    known-future covariate's tail is forwarded as already-known future values,
    which is the anti-leakage assumption the caller is responsible for.
    """
    horizon = request.horizon
    targets = [
        HistoricalSeries(id=series.id, values=series.values[:-horizon])
        for series in request.targets
    ]
    past = [
        HistoricalSeries(id=series.id, values=series.values[:-horizon])
        for series in request.past_covariates
    ]
    known = [
        KnownFutureSeries(
            id=series.id,
            history=series.values[:-horizon],
            future=series.values[-horizon:],
        )
        for series in request.known_future_covariates
    ]
    return ForecastToolRequest(
        targets=targets,
        horizon=horizon,
        past_covariates=past,
        known_future_covariates=known,
        quantiles=list(request.quantiles),
    )


def evaluate_backtest(request: BacktestToolRequest, result: ForecastResult) -> BacktestResult:
    """Compare a forecast against the held-out actuals and compute metrics."""
    if result.horizon != request.horizon:
        raise _contract_error(
            "Precog API returned an unexpected horizon",
            {"expected": request.horizon, "received": result.horizon},
        )
    expected_ids = [target.id for target in request.targets]
    result_ids = [target.id for target in result.targets]
    if result_ids != expected_ids:
        raise _contract_error(
            "Precog API returned unexpected target ids",
            {"expected": expected_ids, "received": result_ids},
        )

    evaluated: list[TargetBacktest] = []
    for source, predicted in zip(request.targets, result.targets, strict=True):
        actual = list(source.values[-request.horizon :])
        forecast = _finite_vector(
            predicted.forecast, request.horizon, label=f"forecast of '{source.id}'"
        )
        evaluated.append(
            TargetBacktest(
                id=source.id,
                actual=actual,
                forecast=forecast,
                metrics=_metrics(actual, forecast, predicted.quantiles),
            )
        )
    return BacktestResult(
        horizon=request.horizon,
        targets=evaluated,
        model=result.model,
        warnings=list(result.warnings),
    )


async def execute_backtest(
    client: ForecastApiClient, request: BacktestToolRequest
) -> BacktestResult:
    """Run one backtest through the same semantic forecast path as ``forecast``."""
    result = await execute_forecast(client, backtest_to_forecast_request(request))
    return evaluate_backtest(request, result)


def _metrics(
    actual: list[float],
    forecast: list[float],
    quantiles: Mapping[str, list[float]],
) -> BacktestMetrics:
    errors = [a - f for a, f in zip(actual, forecast, strict=True)]
    count = len(errors)
    mae = sum(abs(error) for error in errors) / count
    rmse = math.sqrt(sum(error * error for error in errors) / count)
    return BacktestMetrics(
        mae=mae,
        rmse=rmse,
        smape=_smape(actual, forecast),
        coverage=_coverage(actual, quantiles),
    )


def _smape(actual: list[float], forecast: list[float]) -> float:
    """Symmetric MAPE as a percentage.

    ``100 / n * sum(2 * |a - f| / (|a| + |f|))``. When ``|a| + |f| == 0`` the
    term is defined as ``0`` (perfect agreement on a zero value).
    """
    total = 0.0
    for a, f in zip(actual, forecast, strict=True):
        denominator = abs(a) + abs(f)
        if denominator == 0.0:
            continue
        total += 2.0 * abs(a - f) / denominator
    return 100.0 * total / len(actual)


def _coverage(actual: list[float], quantiles: Mapping[str, list[float]]) -> IntervalCoverage | None:
    """Coverage of the widest requested interval that brackets the median."""
    levels = sorted(float(key) for key in quantiles)
    lower_levels = [level for level in levels if level < 0.5]
    upper_levels = [level for level in levels if level > 0.5]
    if not lower_levels or not upper_levels:
        return None
    lower = min(lower_levels)
    upper = max(upper_levels)
    below = quantiles[quantile_key(lower)]
    above = quantiles[quantile_key(upper)]
    inside = sum(1 for a, low, high in zip(actual, below, above, strict=True) if low <= a <= high)
    return IntervalCoverage(
        lower_quantile=lower, upper_quantile=upper, percent=100.0 * inside / len(actual)
    )


def _finite_vector(values: list[float], expected: int, *, label: str) -> list[float]:
    if len(values) != expected:
        raise _contract_error(
            "Precog API returned a vector with the wrong length",
            {"label": label, "expected": expected, "received": len(values)},
        )
    if not all(math.isfinite(value) for value in values):
        raise _contract_error("Precog API returned a non-finite forecast", {"label": label})
    return list(values)


def _level_index(levels: list[float], level: float) -> int | None:
    for index, candidate in enumerate(levels):
        if abs(candidate - level) < 1e-9:
            return index
    return None


def _contract_error(message: str, details: dict[str, Any] | None = None) -> ForecastAdapterError:
    return ForecastAdapterError(ErrorCode.UPSTREAM_CONTRACT_ERROR, message, details=details)


__all__ = [
    "ErrorCode",
    "ForecastAdapterError",
    "backtest_to_forecast_request",
    "evaluate_backtest",
    "execute_backtest",
    "execute_forecast",
    "from_rest_response",
    "map_api_error",
    "to_rest_request",
]

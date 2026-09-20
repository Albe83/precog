"""Anti-corruption adapter between the MCP contract and the Precog REST API.

The MCP server is an HTTP client of ``POST /v1/forecast`` through the official
:class:`~precog_client.AsyncPrecogClient`. This module owns the translation so
the public tool surface never leaks REST/backend DTOs or TimesFM-specific
execution controls, and it owns the sanitization of upstream failures.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from precog_client import (
    AsyncPrecogClient,
    PrecogAPIError,
    PrecogConnectionError,
    PrecogError,
    PrecogTimeoutError,
)
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
    ForecastRequest,
    ForecastResponse,
)
from precog_schemas import (
    HistoricalSeries as RestHistoricalSeries,
)
from precog_schemas import (
    KnownFutureSeries as RestKnownFutureSeries,
)

PROBLEM_MEDIA_TYPE = "application/problem+json"
UNAVAILABLE_MESSAGE = "Precog API is unavailable"


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
    """Map the semantic request to the canonical execution contract.

    This is now a structural mapping: the semantic contract and the execution
    contract share the same shape (targets, past covariates, known-future
    history/future, explicit quantile levels).
    """
    return ForecastRequest(
        horizon=request.horizon,
        targets=[
            RestHistoricalSeries(id=target.id, values=list(target.values))
            for target in request.targets
        ],
        past_covariates=[
            RestHistoricalSeries(id=covariate.id, values=list(covariate.values))
            for covariate in request.past_covariates
        ],
        known_future_covariates=[
            RestKnownFutureSeries(
                id=covariate.id,
                history=list(covariate.history),
                future=list(covariate.future),
            )
            for covariate in request.known_future_covariates
        ],
        quantiles=list(request.quantiles),
    )


def from_rest_response(request: ForecastToolRequest, payload: Mapping[str, Any]) -> ForecastResult:
    """Validate an execution response and build the consumer-facing result."""
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
    if not response.model.id:
        raise _contract_error("Precog API returned an empty model identifier")

    requested_ids = [target.id for target in request.targets]
    result_ids = [target.id for target in response.targets]
    if result_ids != requested_ids:
        raise _contract_error(
            "Precog API returned unexpected target ids",
            {"expected": requested_ids, "received": result_ids},
        )

    targets: list[TargetForecast] = []
    for target, result in zip(request.targets, response.targets, strict=True):
        forecast = _finite_vector(
            result.forecast, request.horizon, label=f"forecast of '{target.id}'"
        )
        quantiles: dict[str, list[float]] = {}
        if request.quantiles:
            by_level = {round(quantile.level, 9): quantile.values for quantile in result.quantiles}
            for level in request.quantiles:
                values = by_level.get(round(level, 9))
                if values is None:
                    raise _contract_error(
                        "Precog API omitted a requested quantile level",
                        {"target": target.id, "level": level},
                    )
                quantiles[quantile_key(level)] = _finite_vector(
                    values,
                    request.horizon,
                    label=f"quantile {quantile_key(level)} of '{target.id}'",
                )
        targets.append(TargetForecast(id=target.id, forecast=forecast, quantiles=quantiles))

    return ForecastResult(
        horizon=request.horizon,
        targets=targets,
        model=ModelProvenance(id=response.model.id),
        warnings=[],
    )


def map_client_error(exc: PrecogError) -> ForecastAdapterError:
    """Translate an SDK client failure into a typed, sanitized MCP-side error.

    Error codes are stable: connectivity/timeouts and 401/403 map to
    ``API_UNAVAILABLE``; 5xx to ``INFERENCE_FAILED``; other 4xx rejections to
    ``FORECAST_REJECTED``; malformed/unexpected upstream contracts to
    ``UPSTREAM_CONTRACT_ERROR``. Messages never forward raw URLs, hosts, proxy
    or TLS details.
    """
    if isinstance(exc, (PrecogConnectionError, PrecogTimeoutError)):
        return ForecastAdapterError(ErrorCode.API_UNAVAILABLE, UNAVAILABLE_MESSAGE)
    if isinstance(exc, PrecogAPIError):
        return _map_api_error(exc)
    return ForecastAdapterError(
        ErrorCode.UPSTREAM_CONTRACT_ERROR,
        "Precog API returned a malformed forecast response",
    )


def _map_api_error(exc: PrecogAPIError) -> ForecastAdapterError:
    status = exc.status_code
    message = _sanitized_message(exc)
    if status in (401, 403):
        return ForecastAdapterError(ErrorCode.API_UNAVAILABLE, message)
    if status >= 500:
        return ForecastAdapterError(ErrorCode.INFERENCE_FAILED, message, status=status)
    return ForecastAdapterError(ErrorCode.FORECAST_REJECTED, message, status=status)


def _sanitized_message(exc: PrecogAPIError) -> str:
    """Rebuild a problem message from trusted fields only, else stay generic."""
    if (
        exc.status_code >= 400
        and exc.media_type == PROBLEM_MEDIA_TYPE
        and isinstance(exc.payload, Mapping)
    ):
        raw_title = exc.payload.get("title")
        raw_detail = exc.payload.get("detail")
        title = raw_title if isinstance(raw_title, str) and raw_title else None
        detail = raw_detail if isinstance(raw_detail, str) and raw_detail else None
        if detail is not None:
            return f"{title or 'error'}: {detail}"
        if title is not None:
            return title
    return f"Precog API error (HTTP {exc.status_code})"


async def execute_forecast(
    client: AsyncPrecogClient, request: ForecastToolRequest
) -> ForecastResult:
    """Run one forecast through the official execution client."""
    rest_request = to_rest_request(request)
    try:
        response = await client.forecast_request(rest_request)
    except PrecogError as exc:
        raise map_client_error(exc) from exc
    return from_rest_response(request, response.model_dump(mode="json"))


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
    client: AsyncPrecogClient, request: BacktestToolRequest
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
    "map_client_error",
    "to_rest_request",
]

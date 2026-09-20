"""Shared request/response schemas for the Precog REST API."""

from precog_schemas.models import (
    QUANTILE_LEVELS,
    Capabilities,
    ExecutionFeatures,
    ExecutionLimits,
    ForecastRequest,
    ForecastResponse,
    HistoricalSeries,
    KnownFutureSeries,
    ModelProvenance,
    QuantileForecast,
    TargetForecast,
    Usage,
)

__all__ = [
    "QUANTILE_LEVELS",
    "Capabilities",
    "ExecutionFeatures",
    "ExecutionLimits",
    "ForecastRequest",
    "ForecastResponse",
    "HistoricalSeries",
    "KnownFutureSeries",
    "ModelProvenance",
    "QuantileForecast",
    "TargetForecast",
    "Usage",
]

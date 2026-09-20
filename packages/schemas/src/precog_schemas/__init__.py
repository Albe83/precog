"""Shared request/response schemas for the Precog REST API."""

from precog_schemas.models import (
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

"""Semantic capabilities resource (``precog://capabilities``).

The resource answers, for an agent, which semantic operations Precog supports
and which public limits apply. It is assembled from the MCP server's own
contract plus, when available, the effective limits reported by the execution
API. The REST capabilities payload is never forwarded verbatim: only
Precog-level semantic information is kept and backend/execution fields are
dropped.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.models import (
    BacktestCapability,
    ForecastCapability,
    PublicLimits,
    SemanticCapabilities,
)
from precog_schemas import QUANTILE_LEVELS
from precog_schemas import Capabilities as RestCapabilities

BACKTEST_METRICS: tuple[str, ...] = ("mae", "rmse", "smape")


def static_capabilities() -> SemanticCapabilities:
    """Semantic capabilities that do not depend on a running execution API."""
    return SemanticCapabilities(
        forecast=ForecastCapability(
            supported=True,
            multiple_targets=True,
            past_covariates=True,
            known_future_covariates=True,
            probabilistic_forecast=True,
        ),
        backtest=BacktestCapability(
            supported=True,
            metrics=list(BACKTEST_METRICS),
            interval_coverage=True,
        ),
        limits=PublicLimits(quantile_levels=list(QUANTILE_LEVELS)),
    )


def limits_from_rest(payload: Mapping[str, Any]) -> PublicLimits:
    """Translate the execution API capabilities into Precog-level public limits.

    Only semantic limits are kept; execution/backend fields (engine, device,
    modes, max_variates, covariate support flags, ...) are intentionally
    dropped.
    """
    response = RestCapabilities.model_validate(payload)
    return PublicLimits(
        max_horizon=response.max_horizon,
        max_context_length=response.max_context,
        quantile_levels=list(response.quantile_levels),
    )


async def load_capabilities(client: ForecastApiClient) -> SemanticCapabilities:
    """Return the semantic capabilities, consulting the API for public limits.

    If the execution API is unavailable or returns an unusable payload, the
    static semantic capabilities are returned with unknown dynamic limits
    (``max_horizon``/``max_context_length`` are ``None``). This conservative
    fallback is documented in ``docs/mcp.md``.
    """
    base = static_capabilities()
    try:
        payload = await client.capabilities()
        limits = limits_from_rest(payload)
    except (ApiError, ValidationError):
        return base
    return base.model_copy(update={"limits": limits})


__all__ = [
    "BACKTEST_METRICS",
    "limits_from_rest",
    "load_capabilities",
    "static_capabilities",
]

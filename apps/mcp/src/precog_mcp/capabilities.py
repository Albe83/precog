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

from pydantic import BaseModel, ConfigDict, ValidationError

from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.models import (
    SEMANTIC_QUANTILE_LEVELS,
    BacktestCapability,
    ForecastCapability,
    PublicLimits,
    SemanticCapabilities,
)

BACKTEST_METRICS: tuple[str, ...] = ("mae", "rmse", "smape")


class _ExecutionLimits(BaseModel):
    """Narrow execution-API view needed for the public runtime limits.

    Deliberately narrow: unrelated execution capability fields (engine, device,
    variate budget, features, ...) are ignored so that an unrelated change in
    the execution payload cannot drop otherwise valid public limits or couple
    the semantic resource to backend concepts.
    """

    model_config = ConfigDict(extra="ignore")

    class _Limits(BaseModel):
        model_config = ConfigDict(extra="ignore")

        max_horizon: int
        max_context: int

    limits: _Limits


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
        limits=PublicLimits(quantile_levels=list(SEMANTIC_QUANTILE_LEVELS)),
    )


def limits_from_rest(payload: Mapping[str, Any]) -> PublicLimits:
    """Translate the execution API capabilities into Precog-level public limits.

    Only the effective runtime limits come from the execution API. Supported
    quantile levels are owned by the MCP semantic contract and must never be
    replaced by the REST payload: the resource and the request validator would
    otherwise be able to disagree.
    """
    response = _ExecutionLimits.model_validate(payload)
    return PublicLimits(
        max_horizon=response.limits.max_horizon,
        max_context_length=response.limits.max_context,
        quantile_levels=list(SEMANTIC_QUANTILE_LEVELS),
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

"""Translation between the REST wire contract and the canonical execution
boundary (ADR 0006).

The wire contract and the canonical execution problem now share the same shape
(Phase 2 cutover); this module keeps the engine boundary from depending on wire
DTOs and assembles the response envelope at the API layer.
"""

from __future__ import annotations

from precog_api.execution import (
    ExecutionKnownFutureCovariate,
    ExecutionPastCovariate,
    ExecutionProblem,
    ExecutionResult,
    ExecutionTarget,
)
from precog_schemas import (
    ForecastRequest,
    ForecastResponse,
    ModelProvenance,
    QuantileForecast,
    TargetForecast,
    Usage,
)


def to_execution_problem(request: ForecastRequest) -> ExecutionProblem:
    """Compile the wire request into one canonical execution problem."""
    return ExecutionProblem(
        horizon=request.horizon,
        targets=[
            ExecutionTarget(id=target.id, values=list(target.values)) for target in request.targets
        ],
        quantiles=list(request.quantiles),
        past_covariates=[
            ExecutionPastCovariate(id=covariate.id, values=list(covariate.values))
            for covariate in request.past_covariates
        ],
        known_future_covariates=[
            ExecutionKnownFutureCovariate(
                id=covariate.id,
                history=list(covariate.history),
                future=list(covariate.future),
            )
            for covariate in request.known_future_covariates
        ],
    )


def to_forecast_response(
    request: ForecastRequest,
    result: ExecutionResult,
    *,
    model: str,
    revision: str | None,
    latency_ms: float,
) -> ForecastResponse:
    """Assemble the wire response envelope around normalized engine output."""
    return ForecastResponse(
        horizon=request.horizon,
        targets=[
            TargetForecast(
                id=target.id,
                forecast=target.forecast,
                quantiles=[
                    QuantileForecast(level=quantile.level, values=quantile.values)
                    for quantile in target.quantiles
                ],
            )
            for target in result.targets
        ],
        model=ModelProvenance(id=model, revision=revision),
        usage=Usage(
            latency_ms=latency_ms,
            context_len=len(request.targets[0].values),
        ),
    )


__all__ = ["to_execution_problem", "to_forecast_response"]

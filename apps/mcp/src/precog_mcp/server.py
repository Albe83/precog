"""MCP server built on the official Python SDK (``MCPServer``)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from precog_mcp.adapter import ForecastAdapterError, execute_forecast
from precog_mcp.client import ForecastApiClient
from precog_mcp.config import Settings
from precog_mcp.errors import (
    ToolErrorMiddleware,
    adapter_error_envelope,
    error_envelope,
    validation_error_details,
)
from precog_mcp.models import (
    BatchFailure,
    BatchSuccess,
    ForecastBatchResult,
    ForecastResult,
    ForecastToolError,
    ForecastToolRequest,
    HistoricalSeries,
    KnownFutureSeries,
)
from precog_mcp.observability import metrics_handler
from precog_mcp.tracing import setup_tracing

TOOL_DESCRIPTION = (
    "Forecast future values for one or more related numeric time series.\n\n"
    "Provide historical values for each target and the number of future steps to "
    "predict. Optionally provide historical-only covariates and covariates whose "
    "future values are already known.\n\n"
    "All input series must already be cleaned, equally sampled, time-aligned, and "
    "ordered from oldest to newest. This tool does not fetch, resample, clean, or "
    "interpret source data.\n\n"
    "Multiple targets are forecast jointly and must represent related series on the "
    "same timeline. Use separate calls for unrelated forecasting problems.\n\n"
    "`horizon` is expressed in future steps using the same sampling interval as the "
    "input data.\n\n"
    "The result contains a point forecast for each target and, when requested, "
    "probabilistic quantiles representing forecast uncertainty."
)

BATCH_TOOL_DESCRIPTION = (
    "Forecast several independent requests in one call. Each item in `requests` is a "
    "complete `forecast` request. Related series that must be forecast jointly belong "
    "together as multiple `targets` inside a single request, not as separate batch "
    "items.\n\n"
    "Returns one ordered result per request. Each item is either a success carrying a "
    "forecast result or a typed failure; a failed item does not cancel the others. "
    "Batch size and concurrency are bounded by PRECOG_MCP_BATCH_MAX and "
    "PRECOG_MCP_BATCH_CONCURRENCY."
)


async def run_forecast_batch(
    client: ForecastApiClient,
    requests: list[ForecastToolRequest],
    *,
    concurrency: int = 4,
) -> list[BatchSuccess | BatchFailure]:
    """Forecast several independent requests concurrently, preserving input order."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(index: int, request: ForecastToolRequest) -> BatchSuccess | BatchFailure:
        async with semaphore:
            try:
                result = await execute_forecast(client, request)
            except ForecastAdapterError as exc:
                return BatchFailure(
                    index=index,
                    ok=False,
                    error=ForecastToolError(
                        code=exc.code.value, message=exc.message, details=exc.details
                    ),
                )
            return BatchSuccess(index=index, ok=True, result=result)

    tasks = (one(index, request) for index, request in enumerate(requests))
    return list(await asyncio.gather(*tasks))


def create_server(
    settings: Settings | None = None,
    client: ForecastApiClient | None = None,
) -> MCPServer:
    """Build the MCP server with the ``forecast`` and ``forecast_batch`` tools."""
    settings = settings or Settings()
    client = client or ForecastApiClient(
        settings.api_url, settings.api_key, settings.request_timeout_s
    )
    if settings.otel_enabled:
        setup_tracing(settings.otel_service_name)

    server: MCPServer = MCPServer(
        name="precog",
        version="0.1.0",
        instructions="Forecast numeric time series with Precog.",
        middleware=[ToolErrorMiddleware()],
    )
    server.custom_route("/metrics", methods=["GET"], include_in_schema=False)(metrics_handler)

    @server.tool(name="forecast", description=TOOL_DESCRIPTION)
    async def forecast(
        targets: list[HistoricalSeries],
        horizon: int,
        past_covariates: Annotated[list[HistoricalSeries], Field(default_factory=list)],
        known_future_covariates: Annotated[list[KnownFutureSeries], Field(default_factory=list)],
        quantiles: Annotated[list[float], Field(default_factory=lambda: [0.1, 0.9])],
    ) -> ForecastResult:
        try:
            request = ForecastToolRequest(
                targets=targets,
                horizon=horizon,
                past_covariates=past_covariates,
                known_future_covariates=known_future_covariates,
                quantiles=quantiles,
            )
        except ValidationError as exc:
            raise ToolError(
                error_envelope(
                    "INVALID_REQUEST", "invalid forecast request", validation_error_details(exc)
                )
            ) from exc
        try:
            return await execute_forecast(client, request)
        except ForecastAdapterError as exc:
            raise ToolError(adapter_error_envelope(exc)) from exc

    @server.tool(name="forecast_batch", description=BATCH_TOOL_DESCRIPTION)
    async def forecast_batch(
        requests: Annotated[list[ForecastToolRequest], Field(min_length=1)],
    ) -> ForecastBatchResult:
        if not requests:
            raise ToolError(error_envelope("INVALID_REQUEST", "requests must not be empty"))
        if len(requests) > settings.mcp_batch_max:
            raise ToolError(
                error_envelope(
                    "INVALID_REQUEST",
                    f"too many requests ({len(requests)} > {settings.mcp_batch_max})",
                    {"max": settings.mcp_batch_max, "received": len(requests)},
                )
            )
        results = await run_forecast_batch(
            client, requests, concurrency=settings.mcp_batch_concurrency
        )
        return ForecastBatchResult(results=list(results))

    return server

"""MCP server built on the official Python SDK (``MCPServer``)."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from precog_mcp.adapter import ForecastAdapterError, execute_forecast
from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.config import Settings
from precog_mcp.errors import (
    ToolErrorMiddleware,
    adapter_error_envelope,
    error_envelope,
    validation_error_details,
)
from precog_mcp.models import (
    ForecastResult,
    ForecastToolRequest,
    HistoricalSeries,
    KnownFutureSeries,
)
from precog_mcp.observability import metrics_handler, record_tool_call
from precog_mcp.tracing import setup_tracing
from precog_schemas import ForecastRequest

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
    "Forecast several requests in one call. `requests` is a list of forecast "
    "payloads, each shaped like the `forecast` tool arguments (mode, horizon, "
    "series, optional past_covariates/future_covariates). Returns one result per "
    "request (a forecast object or an `error`), preserving order."
)


async def run_forecast(client: ForecastApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a legacy forecast payload and call the API, mapping errors to a dict."""
    try:
        ForecastRequest.model_validate(payload)
    except ValidationError as exc:
        return {"error": "invalid forecast request", "detail": exc.errors(include_url=False)}
    try:
        return await client.forecast(payload)
    except ApiError as exc:
        return {"error": str(exc)}


async def run_forecast_batch(
    client: ForecastApiClient,
    payloads: list[dict[str, Any]],
    *,
    concurrency: int = 4,
) -> list[dict[str, Any]]:
    """Forecast several legacy payloads concurrently, preserving order."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(payload: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await run_forecast(client, payload)

    return list(await asyncio.gather(*(one(payload) for payload in payloads)))


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
    async def forecast_batch(requests: list[dict[str, Any]]) -> dict[str, Any]:
        started = time.perf_counter()
        if not requests:
            result: dict[str, Any] = {"error": "requests must not be empty"}
        elif len(requests) > settings.mcp_batch_max:
            result = {"error": f"too many requests ({len(requests)} > {settings.mcp_batch_max})"}
        else:
            results = await run_forecast_batch(
                client, requests, concurrency=settings.mcp_batch_concurrency
            )
            result = {"count": len(results), "results": results}
        status = "error" if "error" in result else "ok"
        record_tool_call("forecast_batch", status, time.perf_counter() - started)
        return result

    return server

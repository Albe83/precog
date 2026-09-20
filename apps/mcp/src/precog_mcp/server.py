"""MCP server built on the official Python SDK (``MCPServer``)."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from precog_client import AsyncPrecogClient
from precog_mcp.adapter import (
    ForecastAdapterError,
    execute_backtest,
    execute_forecast,
)
from precog_mcp.capabilities import load_capabilities
from precog_mcp.config import Settings
from precog_mcp.errors import (
    ToolErrorMiddleware,
    adapter_error_envelope,
    error_envelope,
    validation_error_details,
)
from precog_mcp.models import (
    BacktestResult,
    BacktestToolRequest,
    ForecastResult,
    ForecastToolRequest,
    HistoricalSeries,
    KnownFutureSeries,
    SemanticCapabilities,
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

BACKTEST_TOOL_DESCRIPTION = (
    "Backtest a Precog forecast against a held-out tail of the provided history.\n\n"
    "Provide the complete historical values for each target and a horizon. The last "
    "`horizon` values of every target are held out as ground truth; Precog forecasts "
    "the preceding context through the same semantic path as `forecast` and reports "
    "the prediction next to the actual values.\n\n"
    "Covariates must be aligned to the full target timeline. Historical-only "
    "covariates are split at the same cutoff as the targets. Known-future covariates "
    "may use values from the holdout interval; the caller is responsible for ensuring "
    "they would genuinely have been known at the forecast cutoff. Precog assumes they "
    "were and does not verify it.\n\n"
    "The result reports objective error metrics (MAE and RMSE in the target's units, "
    "sMAPE as a percentage) and interval coverage when the requested quantiles bracket "
    "the median. It is a single window, not a rolling backtest."
)

CAPABILITIES_DESCRIPTION = (
    "Semantic operations and Precog-level public limits supported by this MCP "
    "server, independent from backend/execution details."
)


def create_server(
    settings: Settings | None = None,
    client: AsyncPrecogClient | None = None,
) -> MCPServer:
    """Build the MCP server with the ``forecast`` and ``backtest`` tools."""
    settings = settings or Settings()
    client = client or AsyncPrecogClient(
        settings.api_url,
        api_key=settings.api_key,
        timeout=settings.request_timeout_s,
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

    @server.tool(name="backtest", description=BACKTEST_TOOL_DESCRIPTION)
    async def backtest(
        targets: list[HistoricalSeries],
        horizon: int,
        past_covariates: Annotated[list[HistoricalSeries], Field(default_factory=list)],
        known_future_covariates: Annotated[list[HistoricalSeries], Field(default_factory=list)],
        quantiles: Annotated[list[float], Field(default_factory=lambda: [0.1, 0.9])],
    ) -> BacktestResult:
        try:
            request = BacktestToolRequest(
                targets=targets,
                horizon=horizon,
                past_covariates=past_covariates,
                known_future_covariates=known_future_covariates,
                quantiles=quantiles,
            )
        except ValidationError as exc:
            raise ToolError(
                error_envelope(
                    "INVALID_REQUEST", "invalid backtest request", validation_error_details(exc)
                )
            ) from exc
        try:
            return await execute_backtest(client, request)
        except ForecastAdapterError as exc:
            raise ToolError(adapter_error_envelope(exc)) from exc

    @server.resource(
        "precog://capabilities",
        name="capabilities",
        title="Precog semantic capabilities",
        description=CAPABILITIES_DESCRIPTION,
        mime_type="application/json",
    )
    async def capabilities_resource() -> SemanticCapabilities:
        return await load_capabilities(client)

    return server

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
from precog_mcp.prompts import register_prompts
from precog_mcp.tracing import setup_tracing

SERVER_INSTRUCTIONS = (
    "Forecast numeric time series with Precog.\n\n"
    "Precog exposes two semantic operations: `forecast` (future values) and "
    "`backtest` (evaluate a forecast against a held-out tail), plus the "
    "`precog://capabilities` resource for discovery.\n\n"
    "Multiple `targets` in a single call form **one joint forecasting problem**, "
    "not independent per-series calls: related targets may inform each other's "
    "forecast, so group only series that belong together and use separate calls "
    "for unrelated problems.\n\n"
    "You own your data. Fetch, clean, resample, align and interpret the series "
    "yourself with their real units and domain meaning; Precog does not. Precog "
    "reports forecasts and objective evidence, not a verdict on whether a "
    "forecast is operationally useful."
)

TOOL_DESCRIPTION = (
    "Forecast future values for one or more related numeric time series.\n\n"
    "One call is one joint forecasting problem. When you pass multiple `targets`, "
    "Precog forecasts them together; related targets may contribute information "
    "to each other's forecast, so the result can differ from forecasting the same "
    "series in separate calls. Group series only when they belong to the same "
    "forecasting problem (for example, metrics of the same system on the same "
    "timeline). Use separate calls for unrelated problems: you decide whether the "
    "targets are meaningfully related.\n\n"
    "Provide historical values for each target and the number of future steps to "
    "predict. Optionally provide historical-only covariates and covariates whose "
    "future values are already known.\n\n"
    "All input series must already be cleaned, equally sampled, time-aligned, and "
    "ordered from oldest to newest. This tool does not fetch, resample, clean, or "
    "interpret source data; units and domain meaning remain yours.\n\n"
    "`horizon` is expressed in future steps using the same sampling interval as the "
    "input data.\n\n"
    "The result contains a point forecast for each target and, when requested, "
    "probabilistic quantiles representing forecast uncertainty. Precog reports the "
    "forecast; deciding whether it is useful for your domain is your judgement. "
    "Where feasible, compare against a simple baseline (for example, repeating the "
    "last observed value) before relying on the forecast."
)

BACKTEST_TOOL_DESCRIPTION = (
    "Evaluate a Precog forecast against a held-out tail of the provided history.\n\n"
    "This is a single-window evaluation, not a rolling, walk-forward, or "
    "cross-validated backtest. The last `horizon` values of every target are held "
    "out as ground truth; Precog forecasts the preceding context through the same "
    "semantic path as `forecast` and reports the prediction next to the actual "
    "values.\n\n"
    "Provide the complete historical values for each target and a horizon. "
    "Covariates must be aligned to the full target timeline. Historical-only "
    "covariates are split at the same cutoff as the targets. Known-future covariates "
    "may use values from the holdout interval; you are responsible for ensuring they "
    "would genuinely have been known at the forecast cutoff. Precog assumes they "
    "were and does not verify it.\n\n"
    "Metrics are reported per target and describe this one window. MAE and RMSE are "
    "in the target's native units. sMAPE is scale-relative but unstable and easily "
    "misread near zero, so a particular value is not a pass/fail threshold. Interval "
    "coverage is the share of holdout steps inside the requested interval: "
    "descriptive evidence for this window, not a robust calibration estimate.\n\n"
    "These metrics are objective evidence, not a verdict. Only you can decide "
    "whether the forecast is operationally useful. Comparing against a simple "
    "baseline (for example, repeating the last observed value) helps show whether "
    "the forecast adds value; Precog does not compute baselines for you."
)

CAPABILITIES_DESCRIPTION = (
    "Semantic operations and Precog-level public limits supported by this MCP "
    "server, independent from backend/execution details. Read this to discover "
    "what you can ask for, including that a single `forecast` or `backtest` call "
    "with multiple targets is one joint problem rather than independent per-series "
    "calls. Fetching, cleaning, sampling, aligning and interpreting your data "
    "remain your responsibility."
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
        instructions=SERVER_INSTRUCTIONS,
        middleware=[ToolErrorMiddleware()],
    )
    server.custom_route("/metrics", methods=["GET"], include_in_schema=False)(metrics_handler)
    register_prompts(server)

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

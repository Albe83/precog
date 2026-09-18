"""MCP server built on the official Python SDK (``MCPServer``)."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.config import Settings
from precog_mcp.tracing import setup_tracing
from precog_schemas import ForecastRequest

TOOL_DESCRIPTION = (
    "Zero-shot time-series forecast with TimesFM-3. "
    "`mode` is 'univariate' (each series forecast independently) or 'multivariate' "
    "(targets forecast jointly). Each item in `series` is an object with "
    "`id`, `target` (list of floats), and optional `past_covariates` / "
    "`future_covariates` (maps name -> list of floats; future covariates must "
    "cover context + horizon). In multivariate mode covariates are request-level "
    "(`past_covariates` / `future_covariates` on the arguments). Returns point "
    "forecasts and 9 quantiles."
)

BATCH_TOOL_DESCRIPTION = (
    "Forecast several requests in one call. `requests` is a list of forecast "
    "payloads, each shaped like the `forecast` tool arguments (mode, horizon, "
    "series, optional past_covariates/future_covariates). Returns one result per "
    "request (a forecast object or an `error`), preserving order."
)


async def run_forecast(client: ForecastApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a forecast payload and call the API, mapping errors to a dict."""
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
    """Forecast several payloads concurrently, preserving order."""
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
        instructions="Forecast time series with Google TimesFM-3 via the Precog API.",
    )

    def request_level(payload: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        for key, value in params.items():
            if value:
                payload[key] = value
        return payload

    @server.tool(name="forecast", description=TOOL_DESCRIPTION)
    async def forecast(
        mode: str,
        horizon: int,
        series: list[dict[str, Any]],
        return_quantiles: bool = True,
        past_covariates: dict[str, list[float]] | None = None,
        future_covariates: dict[str, list[float]] | None = None,
    ) -> dict[str, Any]:
        payload = request_level(
            {
                "mode": mode,
                "horizon": horizon,
                "series": series,
                "options": {"return_quantiles": return_quantiles},
            },
            {"past_covariates": past_covariates, "future_covariates": future_covariates},
        )
        return await run_forecast(client, payload)

    @server.tool(name="forecast_batch", description=BATCH_TOOL_DESCRIPTION)
    async def forecast_batch(requests: list[dict[str, Any]]) -> dict[str, Any]:
        if not requests:
            return {"error": "requests must not be empty"}
        if len(requests) > settings.mcp_batch_max:
            return {"error": f"too many requests ({len(requests)} > {settings.mcp_batch_max})"}
        results = await run_forecast_batch(
            client, requests, concurrency=settings.mcp_batch_concurrency
        )
        return {"count": len(results), "results": results}

    return server

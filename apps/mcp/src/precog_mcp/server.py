"""MCP server built on the official Python SDK (``MCPServer``)."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from pydantic import ValidationError

from precog_mcp.client import ApiError, ForecastApiClient
from precog_mcp.config import Settings
from precog_schemas import ForecastRequest

TOOL_DESCRIPTION = (
    "Zero-shot time-series forecast with TimesFM-3. "
    "`mode` is 'univariate' (each series forecast independently) or 'multivariate' "
    "(targets forecast jointly). Each item in `series` is an object with "
    "`id`, `target` (list of floats), and optional `past_covariates` / "
    "`future_covariates` (maps name -> list of floats; future covariates must "
    "cover context + horizon). Returns point forecasts and 9 quantiles."
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


def create_server(
    settings: Settings | None = None,
    client: ForecastApiClient | None = None,
) -> MCPServer:
    """Build the MCP server with the ``forecast`` tool registered."""
    settings = settings or Settings()
    client = client or ForecastApiClient(
        settings.api_url, settings.api_key, settings.request_timeout_s
    )

    server: MCPServer = MCPServer(
        name="precog",
        version="0.1.0",
        instructions="Forecast time series with Google TimesFM-3 via the Precog API.",
    )

    @server.tool(name="forecast", description=TOOL_DESCRIPTION)
    async def forecast(
        mode: str,
        horizon: int,
        series: list[dict[str, Any]],
        return_quantiles: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "mode": mode,
            "horizon": horizon,
            "series": series,
            "options": {"return_quantiles": return_quantiles},
        }
        return await run_forecast(client, payload)

    return server

"""Prometheus metrics for the MCP server."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

TOOL_CALLS = Counter("precog_mcp_tool_calls_total", "MCP tool calls.", ["tool", "status"])
TOOL_DURATION = Histogram(
    "precog_mcp_tool_duration_seconds", "MCP tool duration in seconds.", ["tool"]
)


def record_tool_call(tool: str, status: str, duration_s: float) -> None:
    """Record one tool call outcome (``status`` is ``"ok"`` or ``"error"``)."""
    TOOL_DURATION.labels(tool).observe(duration_s)
    TOOL_CALLS.labels(tool, status).inc()


async def metrics_handler(_: Request) -> Response:
    """Serve the Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

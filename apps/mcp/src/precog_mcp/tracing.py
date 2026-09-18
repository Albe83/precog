"""Optional OpenTelemetry tracing for the MCP server.

Enabled with ``PRECOG_OTEL_ENABLED=true``. Instruments the outbound HTTPX client
so calls to the API join the trace. The OpenTelemetry packages are an optional
extra (``precog-mcp[otel]``); when missing, tracing is skipped with a warning.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("precog.tracing")


def setup_tracing(service_name: str = "precog-mcp") -> bool:
    """Configure a tracer provider and instrument the HTTPX client."""
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry enabled but not installed; skipping tracing")
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    return True

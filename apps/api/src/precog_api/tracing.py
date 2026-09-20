"""Optional OpenTelemetry tracing.

Enabled with ``PRECOG_OTEL_ENABLED=true``. The exporter and endpoint come from
the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``OTEL_SERVICE_NAME`` variables.
The OpenTelemetry packages are an optional extra (``precog-api[otel]``); when
they are missing, tracing is skipped with a warning.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("precog.tracing")


def setup_tracing(service_name: str = "precog-api", *, fastapi_app: FastAPI | None = None) -> bool:
    """Configure a tracer provider and instrument the FastAPI app.

    Returns ``True`` when tracing was configured, ``False`` when the optional
    dependencies are not installed.
    """
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OpenTelemetry enabled but not installed; skipping tracing")
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    if fastapi_app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(fastapi_app)
    return True

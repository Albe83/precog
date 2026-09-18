"""Logging and metrics helpers for the API."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

REQUEST_COUNT = Counter(
    "precog_requests_total", "HTTP requests processed.", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "precog_request_duration_seconds", "HTTP request duration in seconds.", ["method", "path"]
)
INFLIGHT = Gauge("precog_inflight_requests", "In-flight HTTP requests.")
FORECAST_SERIES = Counter("precog_forecast_series_total", "Target series forecast.")
MODEL_LOAD_SECONDS = Gauge("precog_model_load_seconds", "Engine load time in seconds.")

# Paths excluded from request metrics (noise / scraping).
METRICS_EXCLUDED_PATHS = frozenset({"/metrics", "/healthz", "/readyz"})

_LOG_EXTRA_FIELDS = ("request_id", "method", "path", "status", "duration_ms", "client")
_configured = False


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for field in _LOG_EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(*, json_logs: bool = True, level: str = "INFO") -> None:
    """Configure root logging once, with JSON or plain output."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    _configured = True

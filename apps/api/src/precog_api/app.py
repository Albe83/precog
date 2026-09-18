"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from precog_api.config import Settings
from precog_api.engine import Engine, FakeEngine
from precog_api.observability import (
    FORECAST_SERIES,
    INFLIGHT,
    METRICS_EXCLUDED_PATHS,
    MODEL_LOAD_SECONDS,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    configure_logging,
    request_id_var,
)
from precog_api.tracing import setup_tracing
from precog_schemas import (
    QUANTILE_LEVELS,
    Capabilities,
    ForecastRequest,
    ForecastResponse,
    Mode,
    Usage,
)

logger = logging.getLogger("precog.api")

PROBLEM_MEDIA_TYPE = "application/problem+json"

FORECAST_EXAMPLES: dict[str, Any] = {
    "univariate": {
        "summary": "Univariate series",
        "value": {
            "mode": "univariate",
            "horizon": 4,
            "series": [{"id": "sales", "target": [100, 102, 101, 105, 107, 106, 108, 109]}],
        },
    },
    "covariates": {
        "summary": "With past-only and past+future covariates",
        "value": {
            "mode": "univariate",
            "horizon": 3,
            "series": [
                {
                    "id": "kiosk",
                    "target": [50, 52, 51, 53, 55, 54, 56, 57],
                    "past_covariates": {"footfall": [0.1, 0.2, 0.15, 0.3, 0.4, 0.35, 0.5, 0.6]},
                    "future_covariates": {"promo": [0, 1, 0, 0, 0, 1, 0, 0, 1, 0, 0]},
                }
            ],
        },
    },
    "multivariate": {
        "summary": "Multivariate targets forecast jointly",
        "value": {
            "mode": "multivariate",
            "horizon": 3,
            "series": [
                {"id": "a", "target": [10, 11, 12, 13, 14]},
                {"id": "b", "target": [20, 21, 22, 23, 24]},
            ],
        },
    },
    "multivariate_covariates": {
        "summary": "Multivariate targets with request-level covariates",
        "value": {
            "mode": "multivariate",
            "horizon": 3,
            "series": [
                {"id": "brand_a", "target": [100, 102, 101, 105, 107, 106]},
                {"id": "brand_b", "target": [80, 81, 80, 83, 85, 84]},
            ],
            "past_covariates": {"footfall": [0.1, 0.2, 0.15, 0.3, 0.4, 0.35]},
            "future_covariates": {"promo": [0, 1, 0, 0, 0, 1, 0, 1, 0]},
        },
    },
}


class ProblemDetail(BaseModel):
    """RFC 7807 problem payload."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


def load_engine(settings: Settings) -> Engine:
    """Build the configured engine."""
    if settings.engine == "fake":
        logger.info("using FakeEngine")
        return FakeEngine()
    from precog_api.engine_timesfm3 import TimesFM3Engine

    logger.info("loading TimesFM-3 engine (device=%s)", settings.device)
    return TimesFM3Engine(settings)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Create the ASGI application."""
    settings = settings or Settings()
    configure_logging(json_logs=settings.log_json)
    if settings.enable_docs:
        docs_url: str | None = "/docs"
        redoc_url: str | None = "/redoc"
        openapi_url: str | None = "/openapi.json"
    else:
        docs_url = redoc_url = openapi_url = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.semaphore = asyncio.Semaphore(settings.max_concurrency)
        app.state.rate_buckets = {}
        app.state.engine = engine
        if app.state.engine is None:
            started = time.perf_counter()
            app.state.engine = load_engine(settings)
            MODEL_LOAD_SECONDS.set(time.perf_counter() - started)
            logger.info(
                "precog-api %s ready (engine=%s, model=%s)",
                app.version,
                settings.engine,
                settings.model_name,
            )
        app.state.ready = app.state.engine.ready
        yield

    app = FastAPI(
        title="Precog API",
        version="0.1.0",
        summary="Zero-shot forecasting with TimesFM-3.",
        description=(
            "Synchronous TimesFM-3 forecasting. "
            f"Limits: horizon <= {settings.max_horizon}, context <= {settings.max_context}, "
            f"series <= {settings.max_series}. Errors use RFC 7807 "
            "(`application/problem+json`)."
            + (" Bearer authentication is required." if settings.api_key else "")
        ),
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    if settings.otel_enabled:
        setup_tracing(settings.otel_service_name, fastapi_app=app)

    @app.middleware("http")
    async def _observe(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        path = request.url.path
        counted = path not in METRICS_EXCLUDED_PATHS
        if counted:
            INFLIGHT.inc()
        started = time.perf_counter()
        try:
            if settings.rate_limit_requests > 0 and path == "/v1/forecast":
                retry_after = _register_hit(app, settings, request)
                if retry_after > 0:
                    problem = ProblemDetail(
                        title="Too Many Requests",
                        status=429,
                        detail=f"rate limit exceeded; retry in {retry_after}s",
                    )
                    response: Response = JSONResponse(
                        status_code=429,
                        content=problem.model_dump(),
                        media_type=PROBLEM_MEDIA_TYPE,
                        headers={"Retry-After": str(retry_after)},
                    )
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        finally:
            duration = time.perf_counter() - started
            if counted:
                INFLIGHT.dec()
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        if counted:
            REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(duration)
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(duration * 1000, 2),
                "client": _client_key(request),
            },
        )
        return response

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        problem = ProblemDetail(
            title=_status_title(exc.status_code), status=exc.status_code, detail=str(exc.detail)
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=problem.model_dump(),
            media_type=PROBLEM_MEDIA_TYPE,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        problem = ProblemDetail(
            title="Unprocessable Entity", status=422, detail=_format_errors(exc)
        )
        return JSONResponse(
            status_code=422, content=problem.model_dump(), media_type=PROBLEM_MEDIA_TYPE
        )

    def require_api_key(authorization: str | None = Header(default=None)) -> None:
        if not settings.api_key:
            return
        expected = f"Bearer {settings.api_key}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> JSONResponse:
        ready = bool(getattr(app.state, "ready", False))
        payload = {"status": "ready" if ready else "loading"}
        return JSONResponse(status_code=200 if ready else 503, content=payload)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/capabilities", response_model=Capabilities, tags=["forecast"])
    async def capabilities() -> Capabilities:
        return Capabilities(
            model=settings.model_name,
            model_id=settings.model_id,
            revision=settings.model_revision,
            engine=settings.engine,
            device=settings.device,
            modes=[Mode.univariate, Mode.multivariate],
            max_horizon=settings.max_horizon,
            max_context=settings.max_context,
            max_series=settings.max_series,
            quantile_levels=list(QUANTILE_LEVELS),
            covariates={"univariate": True, "multivariate": True},
            auth_required=bool(settings.api_key),
        )

    @app.post(
        "/v1/forecast",
        response_model=ForecastResponse,
        dependencies=[Depends(require_api_key)],
        tags=["forecast"],
        summary="Forecast time series",
        response_description="Point forecast and 9 quantiles per series.",
        responses={
            401: {"description": "Missing or invalid API key"},
            422: {"description": "Validation error or configured limit exceeded"},
            429: {"description": "Rate limit exceeded"},
            504: {"description": "Forecast timed out"},
        },
    )
    async def forecast(
        payload: Annotated[ForecastRequest, Body(openapi_examples=FORECAST_EXAMPLES)],
    ) -> ForecastResponse:
        _enforce_limits(payload, settings)
        started = time.perf_counter()
        async with app.state.semaphore:
            try:
                results = await asyncio.wait_for(
                    asyncio.to_thread(app.state.engine.predict, payload),
                    timeout=settings.request_timeout_s,
                )
            except TimeoutError as exc:
                raise HTTPException(status_code=504, detail="forecast timed out") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        FORECAST_SERIES.inc(len(payload.series))
        return ForecastResponse(
            model=settings.model_name,
            horizon=payload.horizon,
            quantile_levels=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
            results=results,
            usage=Usage(latency_ms=round(latency_ms, 3), context_len=payload.series[0].context_len),
        )

    return app


def _client_key(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization:
        return authorization
    return request.client.host if request.client else "unknown"


def _register_hit(app: FastAPI, settings: Settings, request: Request) -> int:
    """Record a request and return seconds to wait (0 if allowed)."""
    key = _client_key(request)
    now = time.monotonic()
    window = settings.rate_limit_window_s
    bucket: list[float] = app.state.rate_buckets.setdefault(key, [])
    while bucket and now - bucket[0] > window:
        bucket.pop(0)
    if len(bucket) >= settings.rate_limit_requests:
        return max(1, int(window - (now - bucket[0])) + 1)
    bucket.append(now)
    return 0


def _enforce_limits(payload: ForecastRequest, settings: Settings) -> None:
    if payload.horizon > settings.max_horizon:
        raise HTTPException(
            status_code=422,
            detail=f"horizon {payload.horizon} exceeds max {settings.max_horizon}",
        )
    if len(payload.series) > settings.max_series:
        raise HTTPException(
            status_code=422,
            detail=f"{len(payload.series)} series exceed max {settings.max_series}",
        )
    longest = max(s.context_len for s in payload.series)
    if longest > settings.max_context:
        raise HTTPException(
            status_code=422,
            detail=f"context length {longest} exceeds max {settings.max_context}",
        )


def _status_title(status_code: int) -> str:
    return {
        401: "Unauthorized",
        422: "Unprocessable Entity",
        429: "Too Many Requests",
        504: "Gateway Timeout",
    }.get(status_code, "Error")


def _format_errors(exc: RequestValidationError) -> str:
    try:
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
    except (KeyError, TypeError):
        return "invalid request"


__all__ = ["ProblemDetail", "create_app", "load_engine"]

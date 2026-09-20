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
from precog_api.mapping import to_execution_problem, to_forecast_response
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
    Capabilities,
    ExecutionFeatures,
    ExecutionLimits,
    ForecastRequest,
    ForecastResponse,
    ModelProvenance,
)

logger = logging.getLogger("precog.api")

PROBLEM_MEDIA_TYPE = "application/problem+json"

FORECAST_EXAMPLES: dict[str, Any] = {
    "targets": {
        "summary": "Single target with quantiles",
        "value": {
            "horizon": 4,
            "targets": [{"id": "sales", "values": [100, 102, 101, 105, 107, 106, 108, 109]}],
            "quantiles": [0.1, 0.5, 0.9],
        },
    },
    "covariates": {
        "summary": "Target with past-only and known-future covariates",
        "value": {
            "horizon": 3,
            "targets": [{"id": "kiosk", "values": [50, 52, 51, 53, 55, 54, 56, 57]}],
            "past_covariates": [
                {"id": "footfall", "values": [0.1, 0.2, 0.15, 0.3, 0.4, 0.35, 0.5, 0.6]}
            ],
            "known_future_covariates": [
                {
                    "id": "promo",
                    "history": [0, 1, 0, 0, 0, 1, 0, 0],
                    "future": [1, 0, 0],
                }
            ],
            "quantiles": [0.1, 0.9],
        },
    },
    "joint_targets": {
        "summary": "Multiple targets forecast jointly",
        "value": {
            "horizon": 3,
            "targets": [
                {"id": "a", "values": [10, 11, 12, 13, 14]},
                {"id": "b", "values": [20, 21, 22, 23, 24]},
            ],
            "quantiles": [0.5],
        },
    },
    "point_only": {
        "summary": "Point-only forecast (no quantiles)",
        "value": {
            "horizon": 3,
            "targets": [{"id": "cpu", "values": [1.0, 2.0, 3.0, 4.0, 5.0]}],
            "quantiles": [],
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
            "Synchronous TimesFM-3 execution. "
            f"Limits: horizon <= {settings.max_horizon}, context <= {settings.max_context}, "
            f"targets <= {settings.max_series}. Errors use RFC 7807 "
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
        engine = app.state.engine
        return Capabilities(
            engine=settings.engine,
            model=ModelProvenance(id=settings.model_id, revision=settings.model_revision),
            device=settings.device,
            limits=ExecutionLimits(
                max_horizon=settings.max_horizon,
                max_context=_min_limit(settings.max_context, engine.max_context),
                max_variates=engine.max_variates,
                max_targets=settings.max_series,
            ),
            quantile_levels=list(engine.quantile_levels),
            features=ExecutionFeatures(
                point_forecast=True,
                probabilistic_forecast=True,
                past_covariates=True,
                known_future_covariates=True,
                joint_targets=True,
            ),
            auth_required=bool(settings.api_key),
        )

    @app.post(
        "/v1/forecast",
        response_model=ForecastResponse,
        dependencies=[Depends(require_api_key)],
        tags=["forecast"],
        summary="Forecast time series",
        response_description="Point forecast and the caller-selected quantiles per target.",
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
        _enforce_limits(payload, settings, app.state.engine)
        problem = to_execution_problem(payload)
        started = time.perf_counter()
        async with app.state.semaphore:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(app.state.engine.predict, problem),
                    timeout=settings.request_timeout_s,
                )
            except TimeoutError as exc:
                raise HTTPException(status_code=504, detail="forecast timed out") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        FORECAST_SERIES.inc(len(payload.targets))
        return to_forecast_response(
            payload,
            result,
            model=settings.model_id,
            revision=settings.model_revision,
            latency_ms=round(latency_ms, 3),
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


def _min_limit(configured: int, engine_limit: int | None) -> int:
    """Intersect a configured limit with the active engine's effective limit."""
    return configured if engine_limit is None else min(configured, engine_limit)


def _max_unit_variates(payload: ForecastRequest) -> int:
    """Variates Precog sends to the single forward pass for this problem.

    Targets and covariate channels share the same execution budget.
    """
    return (
        len(payload.targets) + len(payload.past_covariates) + len(payload.known_future_covariates)
    )


def _enforce_limits(payload: ForecastRequest, settings: Settings, engine: Engine) -> None:
    if payload.horizon > settings.max_horizon:
        raise HTTPException(
            status_code=422,
            detail=f"horizon {payload.horizon} exceeds max {settings.max_horizon}",
        )
    if len(payload.targets) > settings.max_series:
        raise HTTPException(
            status_code=422,
            detail=f"{len(payload.targets)} targets exceed max {settings.max_series}",
        )
    effective_context = _min_limit(settings.max_context, engine.max_context)
    longest = max(len(target.values) for target in payload.targets)
    if longest > effective_context:
        raise HTTPException(
            status_code=422,
            detail=(
                f"context length {longest} exceeds max {effective_context}; "
                "Precog never truncates input to fit the model context"
            ),
        )
    # The target policy ceiling and the backend execution budget are distinct:
    # targets + covariate channels share the engine's forward-pass budget.
    if engine.max_variates is not None:
        variates = _max_unit_variates(payload)
        if variates > engine.max_variates:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{variates} variates exceed max {engine.max_variates}; "
                    "Precog never drops or chunks covariates/targets to fit the model"
                ),
            )
    _enforce_supported_quantiles(payload, engine)


def _enforce_supported_quantiles(payload: ForecastRequest, engine: Engine) -> None:
    """Reject requested quantile levels the active runtime cannot produce.

    The runtime grid is the execution source of truth (#179); unsupported levels
    fail closed before any backend column lookup.
    """
    supported = engine.quantile_levels
    for level in payload.quantiles:
        if not any(abs(level - candidate) < 1e-9 for candidate in supported):
            allowed = ", ".join(f"{value:g}" for value in supported)
            raise HTTPException(
                status_code=422,
                detail=f"unsupported quantile {level}; supported levels: {allowed}",
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

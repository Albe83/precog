"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from precog_api.config import Settings
from precog_api.engine import Engine, FakeEngine
from precog_schemas import ForecastRequest, ForecastResponse, Usage

logger = logging.getLogger("precog.api")

PROBLEM_MEDIA_TYPE = "application/problem+json"


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
        app.state.engine = engine
        if app.state.engine is None:
            app.state.engine = load_engine(settings)
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
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        problem = ProblemDetail(
            title=_status_title(exc.status_code), status=exc.status_code, detail=str(exc.detail)
        )
        return JSONResponse(
            status_code=exc.status_code, content=problem.model_dump(), media_type=PROBLEM_MEDIA_TYPE
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

    @app.post(
        "/v1/forecast",
        response_model=ForecastResponse,
        dependencies=[Depends(require_api_key)],
        tags=["forecast"],
    )
    async def forecast(payload: ForecastRequest) -> ForecastResponse:
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
        return ForecastResponse(
            model=settings.model_name,
            horizon=payload.horizon,
            quantile_levels=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
            results=results,
            usage=Usage(latency_ms=round(latency_ms, 3), context_len=payload.series[0].context_len),
        )

    return app


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
    return {401: "Unauthorized", 422: "Unprocessable Entity", 504: "Gateway Timeout"}.get(
        status_code, "Error"
    )


def _format_errors(exc: RequestValidationError) -> str:
    try:
        return "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
    except (KeyError, TypeError):
        return "invalid request"


__all__ = ["ProblemDetail", "create_app", "load_engine"]

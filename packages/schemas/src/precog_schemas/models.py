"""Pydantic models describing the forecast contract."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

QUANTILE_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


class Mode(StrEnum):
    """Whether each series is forecast independently or jointly."""

    univariate = "univariate"
    multivariate = "multivariate"


class SeriesInput(BaseModel):
    """One target series with optional past-only and past-and-future covariates."""

    id: str = Field(min_length=1)
    target: list[float] = Field(min_length=1)
    past_covariates: dict[str, list[float]] = Field(default_factory=dict)
    future_covariates: dict[str, list[float]] = Field(default_factory=dict)

    @property
    def context_len(self) -> int:
        return len(self.target)


class ForecastOptions(BaseModel):
    """Toggles forwarded to the underlying model."""

    return_quantiles: bool = True
    symmetric_averaging: bool = False
    # Scale the quantile spread around the median (1.0 = model output). Values
    # above 1 widen the prediction intervals; useful to correct under-coverage
    # on very stable series.
    quantile_spread_scale: float = Field(default=1.0, gt=0, le=10)


class ForecastRequest(BaseModel):
    """A synchronous forecast request.

    In univariate mode covariates are attached to each series. In multivariate
    mode every series is a target variate of one joint context and covariates
    are declared once at request level.
    """

    mode: Mode = Mode.univariate
    horizon: int = Field(gt=0)
    series: list[SeriesInput] = Field(min_length=1)
    options: ForecastOptions = Field(default_factory=ForecastOptions)
    # Request-level covariates, used in multivariate mode.
    past_covariates: dict[str, list[float]] = Field(default_factory=dict)
    future_covariates: dict[str, list[float]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_series(self) -> ForecastRequest:
        lengths = {s.context_len for s in self.series}
        if self.mode is Mode.multivariate and len(lengths) > 1:
            raise ValueError("all series must share the same context length in multivariate mode")

        if self.mode is Mode.multivariate:
            context = self.series[0].context_len
            for series in self.series:
                if series.past_covariates or series.future_covariates:
                    raise ValueError(
                        "in multivariate mode use request-level past_covariates/"
                        "future_covariates, not per-series covariates"
                    )
            for name, values in self.past_covariates.items():
                if len(values) != context:
                    raise ValueError(
                        f"past covariate '{name}' must match context ({len(values)} != {context})"
                    )
            for name, values in self.future_covariates.items():
                expected = context + self.horizon
                if len(values) != expected:
                    raise ValueError(
                        f"future covariate '{name}' must match context + horizon "
                        f"({len(values)} != {expected})"
                    )
            return self

        if self.past_covariates or self.future_covariates:
            raise ValueError(
                "request-level covariates are only supported in multivariate mode; "
                "attach covariates to each series in univariate mode"
            )
        for series in self.series:
            for name, values in series.past_covariates.items():
                if len(values) != series.context_len:
                    raise ValueError(
                        f"past covariate '{name}' must match context "
                        f"({len(values)} != {series.context_len})"
                    )
            for name, values in series.future_covariates.items():
                expected = series.context_len + self.horizon
                if len(values) != expected:
                    raise ValueError(
                        f"future covariate '{name}' must match context + horizon "
                        f"({len(values)} != {expected})"
                    )
        return self


class SeriesForecast(BaseModel):
    """Point forecast and optional quantiles for one target series."""

    id: str
    forecast: list[float]
    quantiles: list[list[float]] | None = None


class Usage(BaseModel):
    """Runtime information returned with every forecast."""

    latency_ms: float
    context_len: int


class ForecastResponse(BaseModel):
    """The result of a synchronous forecast."""

    model: str
    horizon: int
    quantile_levels: list[float]
    results: list[SeriesForecast]
    usage: Usage


class Capabilities(BaseModel):
    """Model and API contract advertised to clients."""

    model: str
    model_id: str
    revision: str | None = None
    engine: str
    device: str
    modes: list[Mode]
    max_horizon: int
    max_context: int
    max_series: int
    quantile_levels: list[float]
    covariates: dict[str, bool]
    auth_required: bool

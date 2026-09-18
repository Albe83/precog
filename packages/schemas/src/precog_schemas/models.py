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


class ForecastRequest(BaseModel):
    """A synchronous forecast request."""

    mode: Mode = Mode.univariate
    horizon: int = Field(gt=0)
    series: list[SeriesInput] = Field(min_length=1)
    options: ForecastOptions = Field(default_factory=ForecastOptions)

    @model_validator(mode="after")
    def _check_series(self) -> ForecastRequest:
        lengths = {s.context_len for s in self.series}
        if self.mode is Mode.multivariate and len(lengths) > 1:
            raise ValueError("all series must share the same context length in multivariate mode")
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

"""Pydantic models describing the forecast contract."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QUANTILE_LEVELS: tuple[float, ...] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)


class _StrictRequestModel(BaseModel):
    """Base for request DTOs: removed/unknown fields must fail closed."""

    model_config = ConfigDict(extra="forbid")


def _require_finite(values: list[float], label: str) -> None:
    """Reject NaN/Inf: Precog never cleans or interpolates caller data."""
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{label} contains non-finite values (NaN/Inf)")


class Mode(StrEnum):
    """Whether each series is forecast independently or jointly.

    Retained for the execution capabilities endpoint until #179 replaces it.
    """

    univariate = "univariate"
    multivariate = "multivariate"


class HistoricalSeries(_StrictRequestModel):
    """One target or past-only covariate series, ordered oldest to newest."""

    id: str = Field(min_length=1)
    values: list[float] = Field(min_length=1)


class KnownFutureSeries(_StrictRequestModel):
    """A covariate whose historical and future values are both known."""

    id: str = Field(min_length=1)
    history: list[float] = Field(min_length=1)
    future: list[float] = Field(min_length=1)

    @property
    def context_len(self) -> int:
        return len(self.history)


class ForecastRequest(_StrictRequestModel):
    """Canonical execution request (ADR 0006).

    Targets are forecast jointly. ``past_covariates`` are known only during the
    historical context; ``known_future_covariates`` carry both the history and
    the already-known future values. ``quantiles`` lists the requested levels;
    an empty list means point-only output.
    """

    horizon: int = Field(gt=0)
    targets: list[HistoricalSeries] = Field(min_length=1)
    past_covariates: list[HistoricalSeries] = Field(default_factory=list)
    known_future_covariates: list[KnownFutureSeries] = Field(default_factory=list)
    quantiles: list[float] = Field(default_factory=list)

    @field_validator("quantiles")
    @classmethod
    def _validate_quantiles(cls, levels: list[float]) -> list[float]:
        seen: set[float] = set()
        for level in levels:
            if level not in QUANTILE_LEVELS:
                allowed = ", ".join(f"{value:.1f}" for value in QUANTILE_LEVELS)
                raise ValueError(f"unsupported quantile {level}; allowed values: {allowed}")
            if level in seen:
                raise ValueError(f"duplicate quantile {level}")
            seen.add(level)
        return levels

    @model_validator(mode="after")
    def _check_consistency(self) -> ForecastRequest:
        context = len(self.targets[0].values)
        for target in self.targets[1:]:
            if len(target.values) != context:
                raise ValueError("all target series must share the same context length")

        ids: set[str] = set()
        series_ids = (
            [target.id for target in self.targets]
            + [past.id for past in self.past_covariates]
            + [known.id for known in self.known_future_covariates]
        )
        for series_id in series_ids:
            if series_id in ids:
                raise ValueError(f"duplicate series id '{series_id}'; ids must be globally unique")
            ids.add(series_id)

        for past in self.past_covariates:
            if len(past.values) != context:
                raise ValueError(
                    f"past covariate '{past.id}' must match the target context "
                    f"({len(past.values)} != {context})"
                )
        for known in self.known_future_covariates:
            if len(known.history) != context:
                raise ValueError(
                    f"known-future covariate '{known.id}' history must match the target "
                    f"context ({len(known.history)} != {context})"
                )
            if len(known.future) != self.horizon:
                raise ValueError(
                    f"known-future covariate '{known.id}' future must match the horizon "
                    f"({len(known.future)} != {self.horizon})"
                )

        for target in self.targets:
            _require_finite(target.values, f"target '{target.id}'")
        for past in self.past_covariates:
            _require_finite(past.values, f"past covariate '{past.id}'")
        for known in self.known_future_covariates:
            _require_finite(known.history, f"known-future covariate '{known.id}' history")
            _require_finite(known.future, f"known-future covariate '{known.id}' future")
        return self


class QuantileForecast(BaseModel):
    """One requested quantile level and its values for a target."""

    level: float
    values: list[float]


class TargetForecast(BaseModel):
    """Point forecast and requested quantiles for one target series."""

    id: str
    forecast: list[float]
    quantiles: list[QuantileForecast] = Field(default_factory=list)


class ModelProvenance(BaseModel):
    """Configured model identity and revision when known."""

    id: str
    revision: str | None = None


class Usage(BaseModel):
    """Runtime information returned with every forecast."""

    latency_ms: float
    context_len: int


class ForecastResponse(BaseModel):
    """The result of a synchronous execution request (ADR 0006)."""

    horizon: int
    targets: list[TargetForecast]
    model: ModelProvenance
    usage: Usage


class Capabilities(BaseModel):
    """Model and API contract advertised to clients.

    Execution/runtime discovery is redesigned in #179; this legacy shape stays
    for now.
    """

    model: str
    model_id: str
    revision: str | None = None
    engine: str
    device: str
    modes: list[Mode]
    max_horizon: int
    max_context: int
    max_series: int
    # Effective total variates per joint forecast (targets + covariates), or
    # ``None`` when the active engine is unbounded.
    max_variates: int | None = None
    quantile_levels: list[float]
    covariates: dict[str, bool]
    auth_required: bool

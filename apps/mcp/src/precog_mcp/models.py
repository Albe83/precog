"""Consumer-facing MCP forecast contract.

These models describe the forecasting problem exposed to MCP consumers and are
independent from the REST/backend DTOs in :mod:`precog_schemas`. The adapter in
:mod:`precog_mcp.adapter` maps between the two.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from precog_schemas import QUANTILE_LEVELS

# Reject ``NaN``/``+Inf``/``-Inf`` samples: the consumer must not rely on Precog
# to clean or interpolate input data.
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
# Error metrics are non-negative; sMAPE and interval coverage are percentages.
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Percent = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]

_DEFAULT_QUANTILES: tuple[float, ...] = (0.1, 0.9)
_QUANTILE_KEY_SET: frozenset[str] = frozenset(f"{level:.1f}" for level in QUANTILE_LEVELS)


def quantile_key(level: float) -> str:
    """Return the canonical serialized key for a quantile level (``0.1`` -> ``"0.1"``)."""
    return f"{level:.1f}"


def _validate_quantile_levels(levels: list[float]) -> list[float]:
    seen: set[float] = set()
    for level in levels:
        if level not in QUANTILE_LEVELS:
            allowed = ", ".join(f"{value:.1f}" for value in QUANTILE_LEVELS)
            raise ValueError(f"unsupported quantile {level}; allowed values: {allowed}")
        if level in seen:
            raise ValueError(f"duplicate quantile {level}")
        seen.add(level)
    return levels


def _register_series_id(ids: set[str], series_id: str) -> None:
    if series_id in ids:
        raise ValueError(f"duplicate series id '{series_id}'; ids must be globally unique")
    ids.add(series_id)


class _StrictModel(BaseModel):
    """Base model that rejects unknown fields on every public contract object."""

    model_config = ConfigDict(extra="forbid")


class HistoricalSeries(_StrictModel):
    """One target or past-only covariate series, ordered oldest to newest."""

    id: str = Field(min_length=1)
    values: list[FiniteFloat] = Field(min_length=1)


class KnownFutureSeries(_StrictModel):
    """A covariate whose historical and future values are both known."""

    id: str = Field(min_length=1)
    history: list[FiniteFloat] = Field(min_length=1)
    future: list[FiniteFloat] = Field(min_length=1)


class ForecastToolRequest(_StrictModel):
    """A model-independent forecasting problem.

    ``targets`` are forecast jointly. ``past_covariates`` are known only during
    the historical context, while ``known_future_covariates`` carry both the
    history and the already-known future values.
    """

    targets: list[HistoricalSeries] = Field(min_length=1)
    horizon: int = Field(ge=1)
    past_covariates: list[HistoricalSeries] = Field(default_factory=list)
    known_future_covariates: list[KnownFutureSeries] = Field(default_factory=list)
    quantiles: list[float] = Field(default_factory=lambda: list(_DEFAULT_QUANTILES))

    @field_validator("quantiles")
    @classmethod
    def _validate_quantiles(cls, levels: list[float]) -> list[float]:
        return _validate_quantile_levels(levels)

    @model_validator(mode="after")
    def _check_consistency(self) -> ForecastToolRequest:
        context = len(self.targets[0].values)
        for target in self.targets[1:]:
            if len(target.values) != context:
                lengths = {t.id: len(t.values) for t in self.targets}
                raise ValueError(
                    f"all target series must contain the same number of values: {lengths}"
                )

        ids: set[str] = set()
        for historical in [*self.targets, *self.past_covariates]:
            _register_series_id(ids, historical.id)
        for known in self.known_future_covariates:
            _register_series_id(ids, known.id)

        for historical in self.past_covariates:
            if len(historical.values) != context:
                raise ValueError(
                    f"past covariate '{historical.id}' must match the target context "
                    f"({len(historical.values)} != {context})"
                )
        for known in self.known_future_covariates:
            if len(known.history) != context:
                raise ValueError(
                    f"known-future covariate '{known.id}' history must match the "
                    f"target context ({len(known.history)} != {context})"
                )
            if len(known.future) != self.horizon:
                raise ValueError(
                    f"known-future covariate '{known.id}' future must match the "
                    f"horizon ({len(known.future)} != {self.horizon})"
                )
        return self


class BacktestToolRequest(_StrictModel):
    """A retrospective evaluation of a forecast against a held-out tail.

    Every series carries the **complete** historical series aligned to the same
    timeline, including the segment that will be held out. Precog splits each
    series at the cutoff ``len(values) - horizon``: the tail becomes the
    ground-truth holdout, the head becomes the forecasting context.

    ``known_future_covariates`` also carry their full timeline; their holdout
    segment is forwarded as already-known future values. The caller is
    responsible for ensuring those values would genuinely have been known at the
    historical cutoff. Precog assumes they were and does not verify it.
    """

    targets: list[HistoricalSeries] = Field(min_length=1)
    horizon: int = Field(ge=1)
    past_covariates: list[HistoricalSeries] = Field(default_factory=list)
    known_future_covariates: list[HistoricalSeries] = Field(default_factory=list)
    quantiles: list[float] = Field(default_factory=lambda: list(_DEFAULT_QUANTILES))

    @field_validator("quantiles")
    @classmethod
    def _validate_quantiles(cls, levels: list[float]) -> list[float]:
        return _validate_quantile_levels(levels)

    @property
    def context_length(self) -> int:
        """Number of context steps after holding out ``horizon`` values."""
        return len(self.targets[0].values) - self.horizon

    @model_validator(mode="after")
    def _check_consistency(self) -> BacktestToolRequest:
        full = len(self.targets[0].values)
        for target in self.targets:
            if len(target.values) <= self.horizon:
                raise ValueError(
                    f"target '{target.id}' must contain more values than the horizon "
                    f"({len(target.values)} <= {self.horizon}); the last {self.horizon} "
                    "values are held out as ground truth"
                )
        for target in self.targets[1:]:
            if len(target.values) != full:
                lengths = {t.id: len(t.values) for t in self.targets}
                raise ValueError(
                    f"all target series must contain the same number of values: {lengths}"
                )

        ids: set[str] = set()
        for series in [*self.targets, *self.past_covariates, *self.known_future_covariates]:
            _register_series_id(ids, series.id)

        for past in self.past_covariates:
            if len(past.values) != full:
                raise ValueError(
                    f"past covariate '{past.id}' must be aligned to the full target timeline "
                    f"({len(past.values)} != {full})"
                )
        for known in self.known_future_covariates:
            if len(known.values) != full:
                raise ValueError(
                    f"known-future covariate '{known.id}' must be aligned to the full target "
                    f"timeline ({len(known.values)} != {full})"
                )
        return self


class TargetForecast(_StrictModel):
    """Point forecast and requested quantiles for one target."""

    id: str = Field(min_length=1)
    forecast: list[FiniteFloat]
    quantiles: dict[str, list[FiniteFloat]] = Field(default_factory=dict)

    @field_validator("quantiles")
    @classmethod
    def _validate_keys(
        cls, quantiles: dict[str, list[FiniteFloat]]
    ) -> dict[str, list[FiniteFloat]]:
        for key in quantiles:
            if key not in _QUANTILE_KEY_SET:
                allowed = ", ".join(sorted(_QUANTILE_KEY_SET))
                raise ValueError(f"unsupported quantile key '{key}'; allowed values: {allowed}")
        return quantiles


class ModelProvenance(_StrictModel):
    """Provenance about the forecasting engine actually used."""

    id: str = Field(min_length=1)


class ForecastWarning(_StrictModel):
    """A non-fatal condition that did not change the forecast semantics."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ForecastResult(_StrictModel):
    """A deterministic, structured forecast result."""

    horizon: int = Field(ge=1)
    targets: list[TargetForecast]
    model: ModelProvenance
    warnings: list[ForecastWarning] = Field(default_factory=list)


class IntervalCoverage(_StrictModel):
    """Empirical coverage of the outer requested prediction interval."""

    lower_quantile: FiniteFloat
    upper_quantile: FiniteFloat
    percent: Percent


class BacktestMetrics(_StrictModel):
    """Objective error measurements for one held-out window.

    ``smape`` is a percentage in ``[0, 200]``; ``coverage`` is present only when
    the requested quantiles bracket the median on both sides.
    """

    mae: NonNegativeFloat
    rmse: NonNegativeFloat
    smape: NonNegativeFloat
    coverage: IntervalCoverage | None = None


class TargetBacktest(_StrictModel):
    """Held-out actuals, the forecast for the same window, and error metrics."""

    id: str = Field(min_length=1)
    actual: list[FiniteFloat]
    forecast: list[FiniteFloat]
    metrics: BacktestMetrics


class BacktestResult(_StrictModel):
    """A deterministic, structured single-window backtest result."""

    horizon: int = Field(ge=1)
    targets: list[TargetBacktest]
    model: ModelProvenance
    warnings: list[ForecastWarning] = Field(default_factory=list)


class ForecastCapability(_StrictModel):
    """Semantic features available through the ``forecast`` tool."""

    supported: bool
    multiple_targets: bool
    past_covariates: bool
    known_future_covariates: bool
    probabilistic_forecast: bool


class BacktestCapability(_StrictModel):
    """Semantic features available through the ``backtest`` tool."""

    supported: bool
    metrics: list[str]
    interval_coverage: bool


class PublicLimits(_StrictModel):
    """Precog-level limits meaningful to an MCP caller.

    ``max_horizon`` and ``max_context_length`` are ``None`` when the execution
    API could not be consulted: the caller then discovers the effective limits
    through stable tool errors rather than an assumed value.
    """

    max_horizon: int | None = None
    max_context_length: int | None = None
    quantile_levels: list[float]


class SemanticCapabilities(_StrictModel):
    """The semantic capabilities resource exposed at ``precog://capabilities``."""

    forecast: ForecastCapability
    backtest: BacktestCapability
    limits: PublicLimits


__all__ = [
    "BacktestCapability",
    "BacktestMetrics",
    "BacktestResult",
    "BacktestToolRequest",
    "FiniteFloat",
    "ForecastCapability",
    "ForecastResult",
    "ForecastToolRequest",
    "ForecastWarning",
    "HistoricalSeries",
    "IntervalCoverage",
    "KnownFutureSeries",
    "ModelProvenance",
    "PublicLimits",
    "SemanticCapabilities",
    "TargetBacktest",
    "TargetForecast",
    "quantile_key",
]

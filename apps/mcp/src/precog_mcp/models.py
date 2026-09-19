"""Consumer-facing MCP forecast contract.

These models describe the forecasting problem exposed to MCP consumers and are
independent from the REST/backend DTOs in :mod:`precog_schemas`. The adapter in
:mod:`precog_mcp.adapter` maps between the two.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

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

_DEFAULT_QUANTILES: tuple[float, ...] = (0.1, 0.9)
_QUANTILE_KEY_SET: frozenset[str] = frozenset(f"{level:.1f}" for level in QUANTILE_LEVELS)


def quantile_key(level: float) -> str:
    """Return the canonical serialized key for a quantile level (``0.1`` -> ``"0.1"``)."""
    return f"{level:.1f}"


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
            self._register_id(ids, historical.id)
        for known in self.known_future_covariates:
            self._register_id(ids, known.id)

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

    @staticmethod
    def _register_id(ids: set[str], series_id: str) -> None:
        if series_id in ids:
            raise ValueError(f"duplicate series id '{series_id}'; ids must be globally unique")
        ids.add(series_id)


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


class ForecastToolError(_StrictModel):
    """Machine-readable payload carried by a failed MCP tool result."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] | None = None


class BatchSuccess(_StrictModel):
    """A successful item inside a forecast batch."""

    index: int = Field(ge=0)
    ok: Literal[True]
    result: ForecastResult


class BatchFailure(_StrictModel):
    """A failed item inside a forecast batch."""

    index: int = Field(ge=0)
    ok: Literal[False]
    error: ForecastToolError


BatchItem = Annotated[BatchSuccess | BatchFailure, Field(discriminator="ok")]


class ForecastBatchResult(_StrictModel):
    """Ordered per-item results for :func:`forecast_batch`."""

    results: list[BatchItem]


__all__ = [
    "BatchFailure",
    "BatchItem",
    "BatchSuccess",
    "FiniteFloat",
    "ForecastBatchResult",
    "ForecastResult",
    "ForecastToolError",
    "ForecastToolRequest",
    "ForecastWarning",
    "HistoricalSeries",
    "KnownFutureSeries",
    "ModelProvenance",
    "TargetForecast",
    "quantile_key",
]

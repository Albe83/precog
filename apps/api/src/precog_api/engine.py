"""Engine abstraction for TimesFM-3 inference.

The API talks to an :class:`Engine`. Tests and local demos use
:class:`FakeEngine`; production uses the TimesFM-3 implementation loaded lazily
so the base install does not require torch.
"""

from __future__ import annotations

from typing import Protocol

from precog_schemas import QUANTILE_LEVELS, ForecastRequest, SeriesForecast


class Engine(Protocol):
    """Minimal contract the API depends on."""

    @property
    def ready(self) -> bool:
        """Whether the engine finished loading and can serve forecasts."""

    @property
    def max_context(self) -> int | None:
        """Effective context length honored by the engine, or ``None`` if unbounded."""

    @property
    def max_variates(self) -> int | None:
        """Effective variates per forward pass, or ``None`` if unbounded."""

    def predict(self, request: ForecastRequest) -> list[SeriesForecast]:
        """Return one forecast per input series."""


class FakeEngine:
    """Deterministic engine that repeats the last observed value."""

    def __init__(
        self,
        *,
        ready: bool = True,
        max_context: int | None = None,
        max_variates: int | None = None,
    ) -> None:
        self._ready = ready
        self._max_context = max_context
        self._max_variates = max_variates

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def max_context(self) -> int | None:
        return self._max_context

    @property
    def max_variates(self) -> int | None:
        return self._max_variates

    def predict(self, request: ForecastRequest) -> list[SeriesForecast]:
        results: list[SeriesForecast] = []
        for series in request.series:
            last = float(series.target[-1])
            quantiles: list[list[float]] | None = None
            if request.options.return_quantiles:
                quantiles = [[last] * len(QUANTILE_LEVELS) for _ in range(request.horizon)]
            results.append(
                SeriesForecast(
                    id=series.id,
                    forecast=[last] * request.horizon,
                    quantiles=quantiles,
                )
            )
        return results

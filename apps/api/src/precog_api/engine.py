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

    def predict(self, request: ForecastRequest) -> list[SeriesForecast]:
        """Return one forecast per input series."""


class FakeEngine:
    """Deterministic engine that repeats the last observed value."""

    def __init__(self, *, ready: bool = True) -> None:
        self._ready = ready

    @property
    def ready(self) -> bool:
        return self._ready

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

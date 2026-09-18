"""TimesFM-3 engine.

This module is imported lazily: the base installation does not depend on torch.
The mapping follows the published TimesFM-3 API and must be validated against
the real checkpoint in PREC-1 before it is considered stable.
"""

from __future__ import annotations

import numpy as np

from precog_api.config import Settings
from precog_schemas import ForecastRequest, SeriesForecast

DEFAULT_QUANTILE_INDEX = 4  # median in the 9-quantile output


class TimesFM3Engine:
    """Thin adapter around ``timesfm3.TimesFM3Evaluator``."""

    def __init__(self, settings: Settings) -> None:
        from timesfm3 import ModelConfig, TimesFM3Evaluator  # noqa: PLC0415

        config = ModelConfig(
            checkpoint_path=settings.model_path,
            per_core_batch_size=settings.per_core_batch_size,
            device=settings.device,
        )
        self._evaluator = TimesFM3Evaluator(config)
        self._ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    def predict(self, request: ForecastRequest) -> list[SeriesForecast]:
        if request.mode.value == "multivariate":
            return self._predict_multivariate(request)
        return self._predict_univariate(request)

    def _predict_univariate(self, request: ForecastRequest) -> list[SeriesForecast]:
        contexts = [np.asarray(s.target, dtype=np.float32) for s in request.series]
        past_only = self._per_series_covariates(request, future=False)
        past_future = self._per_series_covariates(request, future=True)
        outputs = list(
            self._evaluator.predict_batch(
                contexts=contexts,
                horizon=request.horizon,
                past_only_covariates=past_only,
                past_future_covariates=past_future,
                return_quantiles=request.options.return_quantiles,
                use_symmetric_averaging=request.options.symmetric_averaging,
            )
        )
        results: list[SeriesForecast] = []
        for series, output in zip(request.series, outputs, strict=True):
            results.append(
                SeriesForecast(
                    id=series.id,
                    forecast=np.asarray(output.forecast).reshape(-1).tolist(),
                    quantiles=(
                        np.asarray(output.quantiles).tolist()
                        if request.options.return_quantiles
                        else None
                    ),
                )
            )
        return results

    def _predict_multivariate(self, request: ForecastRequest) -> list[SeriesForecast]:
        targets = np.stack([np.asarray(s.target, dtype=np.float32) for s in request.series])
        kwargs: dict[str, object] = {}
        past_only = self._stacked_covariates(request, future=False)
        past_future = self._stacked_covariates(request, future=True)
        if past_only is not None:
            kwargs["past_only_covariates"] = [past_only]
        if past_future is not None:
            kwargs["past_future_covariates"] = [past_future]
        outputs = list(
            self._evaluator.predict_batch(
                contexts=[targets],
                horizon=request.horizon,
                return_quantiles=request.options.return_quantiles,
                use_symmetric_averaging=request.options.symmetric_averaging,
                **kwargs,
            )
        )
        output = outputs[0]
        forecasts = np.asarray(output.forecast)
        quantiles = np.asarray(output.quantiles) if request.options.return_quantiles else None
        return [
            SeriesForecast(
                id=series.id,
                forecast=np.asarray(forecasts[i]).reshape(-1).tolist(),
                quantiles=(quantiles[i].tolist() if quantiles is not None else None),
            )
            for i, series in enumerate(request.series)
        ]

    @staticmethod
    def _per_series_covariates(
        request: ForecastRequest, *, future: bool
    ) -> list[np.ndarray] | None:
        field = "future_covariates" if future else "past_covariates"
        if not any(getattr(s, field) for s in request.series):
            return None
        covariates: list[np.ndarray] = []
        for series in request.series:
            channels = getattr(series, field)
            if channels:
                covariates.append(
                    np.stack([np.asarray(v, dtype=np.float32) for v in channels.values()])
                )
            else:
                covariates.append(np.zeros((0, 0), dtype=np.float32))
        return covariates

    @staticmethod
    def _stacked_covariates(request: ForecastRequest, *, future: bool) -> np.ndarray | None:
        field = "future_covariates" if future else "past_covariates"
        names = {tuple(getattr(s, field).keys()) for s in request.series}
        if names == {()}:
            return None
        if len(names) != 1:
            raise ValueError("all series must share the same covariates in multivariate mode")
        keys = next(iter(names))
        return np.stack(
            [
                np.asarray(getattr(s, field)[k], dtype=np.float32)
                for s in request.series
                for k in keys
            ]
        )

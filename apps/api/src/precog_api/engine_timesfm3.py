"""TimesFM-3 engine.

Imported lazily so the base installation does not require torch. The mapping
follows the real TimesFM-3 API (``TimesFM3Evaluator.predict_batch``) validated
during the PREC-1 spike.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np

from precog_api.config import Settings
from precog_schemas import QUANTILE_LEVELS, ForecastRequest, Mode, SeriesForecast


class TimesFM3Engine:
    """Adapter around ``timesfm3.TimesFM3Evaluator``."""

    def __init__(self, settings: Settings) -> None:
        import torch  # noqa: PLC0415
        from timesfm3 import ModelConfig, TimesFM3Evaluator  # noqa: PLC0415

        if settings.torch_threads > 0:
            torch.set_num_threads(settings.torch_threads)

        model_dir = Path(settings.model_path)
        if model_dir.is_dir():
            checkpoint = settings.model_path
            local_only = True
        else:
            checkpoint = settings.model_id
            local_only = settings.local_files_only
        config = ModelConfig(
            checkpoint_path=checkpoint,
            per_core_batch_size=settings.per_core_batch_size,
            device=settings.device,
            revision=settings.model_revision,
            cache_dir=settings.cache_dir,
            local_files_only=local_only,
        )
        self._evaluator = TimesFM3Evaluator(config)
        self._ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    def predict(self, request: ForecastRequest) -> list[SeriesForecast]:
        if request.mode is Mode.multivariate:
            return self._predict_multivariate(request)
        return self._predict_univariate(request)

    def _predict_univariate(self, request: ForecastRequest) -> list[SeriesForecast]:
        interpolate = request.options.interpolate_missing
        contexts = [_interpolate(s.target, interpolate) for s in request.series]
        past_only = _covariate_list(request, future=False, interpolate=interpolate)
        past_future = _covariate_list(request, future=True, interpolate=interpolate)
        outputs = list(
            self._evaluator.predict_batch(
                contexts=contexts,
                horizon=request.horizon,
                past_only_covariates=past_only,
                past_future_covariates=past_future,
                ts_ids=[s.id for s in request.series],
                return_quantiles=request.options.return_quantiles,
                use_symmetric_averaging=request.options.symmetric_averaging,
            )
        )
        results: list[SeriesForecast] = []
        for series, output in zip(request.series, outputs, strict=True):
            quantiles: list[list[float]] | None = None
            if request.options.return_quantiles and output.quantiles is not None:
                quantiles = _calibrate_quantiles(
                    np.asarray(output.quantiles), request.options.quantile_spread_scale
                ).tolist()
            results.append(
                SeriesForecast(
                    id=series.id,
                    forecast=np.asarray(output.forecast).reshape(-1).tolist(),
                    quantiles=quantiles,
                )
            )
        return results

    def _predict_multivariate(self, request: ForecastRequest) -> list[SeriesForecast]:
        interpolate = request.options.interpolate_missing
        targets = np.stack([_interpolate(s.target, interpolate) for s in request.series])
        kwargs: dict[str, object] = {}
        past_only = _stacked_covariates(request.past_covariates, interpolate=interpolate)
        past_future = _stacked_covariates(request.future_covariates, interpolate=interpolate)
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
        forecasts = np.atleast_2d(np.asarray(output.forecast))
        quantiles = (
            np.asarray(output.quantiles)
            if request.options.return_quantiles and output.quantiles is not None
            else None
        )
        if quantiles is not None:
            quantiles = _calibrate_quantiles(quantiles, request.options.quantile_spread_scale)
        return [
            SeriesForecast(
                id=series.id,
                forecast=forecasts[i].reshape(-1).tolist(),
                quantiles=(quantiles[i].tolist() if quantiles is not None else None),
            )
            for i, series in enumerate(request.series)
        ]


def _covariate_list(
    request: ForecastRequest, *, future: bool, interpolate: bool = False
) -> list[np.ndarray | None] | None:
    """Build the per-series covariate list expected by ``predict_batch``."""
    field = "future_covariates" if future else "past_covariates"
    if not any(getattr(s, field) for s in request.series):
        return None
    covariates: list[np.ndarray | None] = []
    for series in request.series:
        channels = getattr(series, field)
        if channels:
            covariates.append(np.stack([_interpolate(v, interpolate) for v in channels.values()]))
        else:
            covariates.append(None)
    return covariates


def _stacked_covariates(
    covariates: Mapping[str, list[float]], *, interpolate: bool = False
) -> np.ndarray | None:
    """Stack request-level covariate channels into an ``(n_channels, length)`` array."""
    if not covariates:
        return None
    return np.stack([_interpolate(values, interpolate) for values in covariates.values()])


def _interpolate(values: list[float], enabled: bool) -> np.ndarray:
    """Return a float32 array, linearly filling interior NaNs when enabled."""
    array = np.asarray(values, dtype=np.float32)
    if not enabled or np.isfinite(array).all():
        return array
    indices = np.arange(array.size)
    finite = np.isfinite(array)
    array = array.copy()
    array[~finite] = np.interp(indices[~finite], indices[finite], array[finite])
    return array


def _calibrate_quantiles(quantiles: np.ndarray, scale: float) -> np.ndarray:
    """Scale the quantile spread around the median, preserving order."""
    if scale == 1.0:
        return quantiles
    median_index = len(QUANTILE_LEVELS) // 2
    median = quantiles[..., median_index : median_index + 1]
    return median + (quantiles - median) * scale

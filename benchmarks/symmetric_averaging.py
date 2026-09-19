"""Symmetric-averaging sensitivity on the real Grafana/Thanos series.

Forecasts each window once with ``use_symmetric_averaging=False`` (the current
Precog default) and once with ``True`` (the ``TimesFM3Evaluator`` benchmark
default), then compares accuracy, 80% interval coverage, pinball loss and the
forecast sensitivity between the two settings. Writes
``benchmarks/data/symmetric_averaging.json``.

    PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.symmetric_averaging
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_schemas import QUANTILE_LEVELS, ForecastOptions, ForecastRequest, Mode, SeriesInput

DATA = Path(__file__).parent / "data" / "complex_series.json"
OUT = Path(__file__).parent / "data" / "symmetric_averaging.json"
CACHE_DIR = "/home/albe/.cache/precog/models"
CONTEXT = 168
HORIZON = 24
WINDOWS = 4
MEDIAN_INDEX = len(QUANTILE_LEVELS) // 2


def _pinball(actual: np.ndarray, quantiles: np.ndarray) -> float:
    losses = []
    for index, tau in enumerate(QUANTILE_LEVELS):
        diff = actual - quantiles[:, index]
        losses.append(float(np.where(diff >= 0, diff * tau, -diff * (1 - tau)).mean()))
    return float(np.mean(losses))


def _run(engine: TimesFM3Engine, series: list[SeriesInput], symmetric: bool) -> list[np.ndarray]:
    response = engine.predict(
        ForecastRequest(
            mode=Mode.univariate,
            horizon=HORIZON,
            series=series,
            options=ForecastOptions(
                return_quantiles=True,
                symmetric_averaging=symmetric,
            ),
        )
    )
    return [np.asarray(result.quantiles) for result in response]


def main() -> None:
    payload = json.loads(DATA.read_text())
    engine = TimesFM3Engine(
        Settings(
            engine="timesfm3",
            cache_dir=CACHE_DIR,
            local_files_only=True,
            per_core_batch_size=8,
            torch_threads=8,
        )
    )

    inputs: list[SeriesInput] = []
    actuals: list[np.ndarray] = []
    for values in payload["series"].values():
        window = np.asarray(values, dtype=np.float32)
        for start in range(0, len(window) - CONTEXT - HORIZON + 1, CONTEXT):
            if len(inputs) >= WINDOWS * len(payload["series"]):
                break
            context = window[start : start + CONTEXT]
            actual = window[start + CONTEXT : start + CONTEXT + HORIZON]
            inputs.append(SeriesInput(id=f"w{len(inputs)}", target=context.tolist()))
            actuals.append(actual)

    metrics: dict[str, dict[str, float]] = {}
    quantiles: dict[bool, list[np.ndarray]] = {}
    for symmetric in (False, True):
        quantiles[symmetric] = _run(engine, inputs, symmetric)
        mae, coverage, pinball = [], [], []
        for actual, matrix in zip(actuals, quantiles[symmetric], strict=True):
            median = matrix[:, MEDIAN_INDEX]
            mae.append(float(np.mean(np.abs(actual - median))))
            inside = (actual >= matrix[:, 0]) & (actual <= matrix[:, -1])
            coverage.append(float(100.0 * inside.mean()))
            pinball.append(_pinball(actual, matrix))
        metrics[str(symmetric)] = {
            "mae": float(np.mean(mae)),
            "coverage_80": float(np.mean(coverage)),
            "pinball": float(np.mean(pinball)),
        }

    sensitivity = [
        float(np.mean(np.abs(a[:, MEDIAN_INDEX] - b[:, MEDIAN_INDEX])))
        for a, b in zip(quantiles[False], quantiles[True], strict=True)
    ]
    report = {
        "window": len(inputs),
        "context": CONTEXT,
        "horizon": HORIZON,
        "metrics": metrics,
        "median_forecast_mean_abs_difference": float(np.mean(sensitivity)),
        "median_forecast_max_abs_difference": float(np.max(sensitivity)),
    }
    OUT.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

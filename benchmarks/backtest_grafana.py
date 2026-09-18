"""Backtest TimesFM-3 against real Grafana/Prometheus series.

Sample: node-exporter on 172.16.10.41:9100 (hourly, 240 points).
Context = first 8 days (192 points), horizon = last 2 days (48 points).
Compares the model against persistence and seasonal-naive (lag 24h) baselines.

Run with the real engine (weights cached / offline):

    PRECOG_LOCAL_FILES_ONLY=true \
    .venv/bin/python benchmarks/backtest_grafana.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_schemas import ForecastOptions, ForecastRequest, Mode, SeriesInput

DATA = Path(__file__).parent / "data" / "grafana_sample.json"


def metrics(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    err = actual - pred
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(math.sqrt(np.mean(err**2))),
        "mape": float(np.mean(np.abs(err / actual)) * 100),
    }


def run_series(
    name: str, values: list[float], engine: TimesFM3Engine, context: int, horizon: int
) -> dict:
    series = values[:context]
    actual = np.asarray(values[context : context + horizon])
    output = engine.predict(
        ForecastRequest(
            mode=Mode.univariate,
            horizon=horizon,
            series=[SeriesInput(id=name, target=series)],
            options=ForecastOptions(return_quantiles=True),
        )
    )[0]
    pred = np.asarray(output.forecast)
    quantiles = np.asarray(output.quantiles)
    lower, upper = quantiles[:, 0], quantiles[:, -1]

    persistence = np.full(horizon, series[-1])
    seasonal = np.asarray(series[-24:] * (horizon // 24 + 1))[:horizon]

    model = metrics(actual, pred)
    naive = metrics(actual, persistence)
    seas = metrics(actual, seasonal)
    coverage = float(np.mean((actual >= lower) & (actual <= upper)) * 100)

    print(f"\n=== {name} — context {context}h, horizon {horizon}h ===")
    print(f"  TimesFM3 MAE={model['mae']:.4g} MAPE={model['mape']:.2f}% 80%PI={coverage:.1f}%")
    print(f"  naive    MAE={naive['mae']:.4g} MAPE={naive['mape']:.2f}%")
    print(f"  seasonal MAE={seas['mae']:.4g} MAPE={seas['mape']:.2f}%")
    print(f"  skill vs naive: {(1 - model['mae'] / naive['mae']) * 100:+.1f}%")
    return {"model": model, "naive": naive, "seasonal": seas, "coverage": coverage}


def main() -> None:
    payload = json.loads(DATA.read_text())
    context, horizon = payload["context"], payload["horizon"]
    settings = Settings(
        engine="timesfm3",
        cache_dir="/home/albe/.cache/precog/models",
        local_files_only=True,
        per_core_batch_size=4,
        torch_threads=8,
    )
    engine = TimesFM3Engine(settings)
    for name, values in payload["series"].items():
        run_series(name, values, engine, context, horizon)


if __name__ == "__main__":
    main()

"""Quantile calibration sweep on the real Grafana/Thanos series.

Forecasts each window once with the real engine, then evaluates how scaling the
quantile spread around the median affects 80% interval coverage and pinball
loss. Writes ``benchmarks/data/calibration.json``.

    PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.calibration
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from benchmarks import predict_univariate
from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_schemas import QUANTILE_LEVELS

DATA = Path(__file__).parent / "data" / "complex_series.json"
OUT = Path(__file__).parent / "data" / "calibration.json"
CACHE_DIR = "/home/albe/.cache/precog/models"
CONTEXT = 168
HORIZON = 24
WINDOWS = 4
SCALES = (0.8, 1.0, 1.5, 2.0, 3.0)
MEDIAN_INDEX = len(QUANTILE_LEVELS) // 2


def _calibrate(quantiles: np.ndarray, scale: float) -> np.ndarray:
    median = quantiles[:, [MEDIAN_INDEX]]
    return median + (quantiles - median) * scale


def _pinball(actual: np.ndarray, quantiles: np.ndarray) -> float:
    losses = []
    for index, tau in enumerate(QUANTILE_LEVELS):
        diff = actual - quantiles[:, index]
        losses.append(float(np.where(diff >= 0, diff * tau, -diff * (1 - tau)).mean()))
    return float(np.mean(losses))


def main() -> None:
    payload = json.loads(DATA.read_text())
    engine = TimesFM3Engine(
        Settings(
            engine="timesfm3",
            cache_dir=CACHE_DIR,
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )

    coverage: dict[float, list[float]] = {scale: [] for scale in SCALES}
    pinball: dict[float, list[float]] = {scale: [] for scale in SCALES}

    for values in payload["series"].values():
        window = np.asarray(values, dtype=np.float32)
        for k in range(WINDOWS):
            end = len(window) - HORIZON - k * HORIZON
            if end - CONTEXT < 0:
                break
            context = window[end - CONTEXT : end]
            actual = np.asarray(window[end : end + HORIZON])
            _, raw = predict_univariate(engine, "s", context, HORIZON)
            assert raw is not None
            for scale in SCALES:
                quantiles = _calibrate(raw, scale)
                coverage[scale].append(
                    float(np.mean((actual >= quantiles[:, 0]) & (actual <= quantiles[:, -1])) * 100)
                )
                pinball[scale].append(_pinball(actual, quantiles))

    results = [
        {
            "scale": scale,
            "coverage_80_mean": round(float(np.mean(coverage[scale])), 1),
            "pinball_mean": round(float(np.mean(pinball[scale])), 4),
        }
        for scale in SCALES
    ]
    OUT.write_text(
        json.dumps({"horizon": HORIZON, "context": CONTEXT, "results": results}, indent=1)
    )
    print(f"{'scale':>6} {'coverage80':>11} {'pinball':>9}")
    for row in results:
        print(f"{row['scale']:6.1f} {row['coverage_80_mean']:11.1f} {row['pinball_mean']:9.4f}")
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()

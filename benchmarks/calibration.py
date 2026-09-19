"""Quantile calibration sweep on the real Grafana/Thanos series.

Forecasts each window once with the real evaluator under the frozen Phase-2
defaults (ADR 0007), then evaluates how scaling the quantile spread around the
median affects 80% interval coverage and pinball loss. Writes
``benchmarks/data/calibration.json``.

This benchmark drives the evaluator directly so the evidence matches the exact
evaluator arguments Precog sets, including ``make_positive=False``.

    PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.calibration
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent / "data" / "complex_series.json"
OUT = Path(__file__).parent / "data" / "calibration.json"
CACHE_DIR = "/home/albe/.cache/precog/models"
MODEL_ID = "google/timesfm-3.0-pytorch"
CONTEXT = 168
HORIZON = 24
WINDOWS = 4
SCALES = (0.8, 1.0, 1.5, 2.0, 3.0)


def _evaluator():
    from timesfm3 import ModelConfig, TimesFM3Evaluator

    return TimesFM3Evaluator(
        ModelConfig(
            checkpoint_path=MODEL_ID,
            per_core_batch_size=8,
            device="cpu",
            revision=None,
            cache_dir=CACHE_DIR,
            local_files_only=True,
        )
    )


def _calibrate(quantiles: np.ndarray, scale: float, median_index: int) -> np.ndarray:
    median = quantiles[:, [median_index]]
    return median + (quantiles - median) * scale


def _pinball(actual: np.ndarray, quantiles: np.ndarray, grid: tuple[float, ...]) -> float:
    losses = []
    for index, tau in enumerate(grid):
        diff = actual - quantiles[:, index]
        losses.append(float(np.where(diff >= 0, diff * tau, -diff * (1 - tau)).mean()))
    return float(np.mean(losses))


def main() -> None:
    payload = json.loads(DATA.read_text())
    evaluator = _evaluator()
    grid = tuple(float(level) for level in evaluator.config.quantiles)
    median_index = int(evaluator.config.median_quantile_index)

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
            output = next(
                evaluator.predict_batch(
                    contexts=[context],
                    horizon=HORIZON,
                    return_quantiles=True,
                    use_symmetric_averaging=False,
                    make_positive=False,
                    sort_quantiles=True,
                    use_znorm=False,
                    padding_mode="none",
                )
            )
            raw = np.asarray(output.quantiles)
            for scale in SCALES:
                quantiles = _calibrate(raw, scale, median_index)
                coverage[scale].append(
                    float(np.mean((actual >= quantiles[:, 0]) & (actual <= quantiles[:, -1])) * 100)
                )
                pinball[scale].append(_pinball(actual, quantiles, grid))

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

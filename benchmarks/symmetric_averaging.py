"""Symmetric-averaging sensitivity on the real Grafana/Thanos series.

Forecasts each window once with ``use_symmetric_averaging=False`` (the chosen
Precog default, ADR 0007) and once with ``True`` (the ``TimesFM3Evaluator``
benchmark default), then compares accuracy, 80% interval coverage, pinball loss
and the forecast sensitivity between the two settings. Writes
``benchmarks/data/symmetric_averaging.json``.

This benchmark drives the evaluator directly because symmetric averaging is an
engine/evaluator concern, intentionally not part of the execution problem
(ADR 0006/0007).

    PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.symmetric_averaging
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from precog_schemas import QUANTILE_LEVELS

DATA = Path(__file__).parent / "data" / "complex_series.json"
OUT = Path(__file__).parent / "data" / "symmetric_averaging.json"
CACHE_DIR = "/home/albe/.cache/precog/models"
MODEL_ID = "google/timesfm-3.0-pytorch"
CONTEXT = 168
HORIZON = 24
WINDOWS = 4
MEDIAN_INDEX = len(QUANTILE_LEVELS) // 2


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


def _pinball(actual: np.ndarray, quantiles: np.ndarray) -> float:
    losses = []
    for index, tau in enumerate(QUANTILE_LEVELS):
        diff = actual - quantiles[:, index]
        losses.append(float(np.where(diff >= 0, diff * tau, -diff * (1 - tau)).mean()))
    return float(np.mean(losses))


def _run(evaluator, contexts: list[np.ndarray], symmetric: bool) -> list[np.ndarray]:
    outputs = list(
        evaluator.predict_batch(
            contexts=contexts,
            horizon=HORIZON,
            return_quantiles=True,
            use_symmetric_averaging=symmetric,
            make_positive=False,
            sort_quantiles=True,
            use_znorm=False,
            padding_mode="none",
        )
    )
    return [np.asarray(output.quantiles) for output in outputs]


def main() -> None:
    payload = json.loads(DATA.read_text())
    evaluator = _evaluator()

    contexts: list[np.ndarray] = []
    actuals: list[np.ndarray] = []
    for values in payload["series"].values():
        window = np.asarray(values, dtype=np.float32)
        for start in range(0, len(window) - CONTEXT - HORIZON + 1, CONTEXT):
            if len(contexts) >= WINDOWS * len(payload["series"]):
                break
            contexts.append(window[start : start + CONTEXT])
            actuals.append(window[start + CONTEXT : start + CONTEXT + HORIZON])

    metrics: dict[str, dict[str, float]] = {}
    quantiles: dict[bool, list[np.ndarray]] = {}
    for symmetric in (False, True):
        quantiles[symmetric] = _run(evaluator, contexts, symmetric)
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
        "window": len(contexts),
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

"""Record CPU latency and memory of TimesFM-3 on synthetic series.

Writes ``benchmarks/data/baseline_cpu.json`` so future changes can be compared
against a committed baseline. Run with the real engine (offline):

    PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.baseline_cpu
"""

from __future__ import annotations

import json
import resource
import time
from pathlib import Path

import numpy as np

from benchmarks import predict_univariate
from benchmarks.synthetic import generate_series
from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine

OUT = Path(__file__).parent / "data" / "baseline_cpu.json"
CACHE_DIR = "/home/albe/.cache/precog/models"
CONTEXTS = (128, 256)
HORIZONS = (24, 96)
REPEATS = 3


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> None:
    engine = TimesFM3Engine(
        Settings(
            engine="timesfm3",
            cache_dir=CACHE_DIR,
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )
    runs: list[dict[str, float | int]] = []
    for context in CONTEXTS:
        series = generate_series(context, seed=context)
        for horizon in HORIZONS:
            latencies: list[float] = []
            for _ in range(REPEATS):
                started = time.perf_counter()
                predict_univariate(engine, "synthetic", series, horizon, return_quantiles=False)
                latencies.append((time.perf_counter() - started) * 1000)
            run = {
                "context": context,
                "horizon": horizon,
                "latency_ms_median": round(float(np.median(latencies)), 2),
                "latency_ms_min": round(min(latencies), 2),
                "latency_ms_max": round(max(latencies), 2),
                "rss_mb": round(_rss_mb(), 1),
            }
            runs.append(run)
            print(run)

    payload = {
        "engine": "timesfm3",
        "device": "cpu",
        "generator": {"period": 24, "seed": "context"},
        "repeats": REPEATS,
        "runs": runs,
    }
    OUT.write_text(json.dumps(payload, indent=1))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()

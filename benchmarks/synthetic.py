"""Deterministic synthetic time series for benchmarks."""

from __future__ import annotations

import numpy as np


def generate_series(
    n: int,
    *,
    period: int = 24,
    base: float = 100.0,
    trend: float = 0.05,
    amplitude: float = 10.0,
    noise: float = 1.0,
    seed: int = 0,
) -> np.ndarray:
    """Return ``n`` points of trend + seasonality + gaussian noise.

    Deterministic for a given seed, so benchmark baselines are reproducible.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float64)
    values = base + trend * t + amplitude * np.sin(2 * np.pi * t / period)
    values += rng.normal(0.0, noise, n)
    return values.astype(np.float32)

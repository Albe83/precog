"""Rigorous backtest of TimesFM-3 on real Grafana/Thanos series.

Evaluates several complex series across multiple forecast horizons and
non-overlapping windows, against persistence, daily-seasonal, weekly-seasonal
and mean baselines. Reports MAE, RMSE, sMAPE, MASE and 80% interval coverage.

Usage (weights cached / offline):

    PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python benchmarks/evaluate.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from precog_api.config import Settings
from precog_api.engine_timesfm3 import TimesFM3Engine
from precog_schemas import ForecastOptions, ForecastRequest, Mode, SeriesInput

DATA_DIR = Path(__file__).parent / "data"
CONTEXT = 168  # 7 days hourly
HORIZONS = (24, 48, 72)
WINDOWS = 4  # non-overlapping test windows per series/horizon
SEASONAL_DAILY = 24
SEASONAL_WEEKLY = 168


def _smape(actual: np.ndarray, pred: np.ndarray) -> float:
    denom = np.abs(actual) + np.abs(pred)
    ratio = np.divide(2 * np.abs(actual - pred), denom, out=np.zeros_like(actual), where=denom != 0)
    return float(np.mean(ratio) * 100)


def _mase(actual: np.ndarray, pred: np.ndarray, context: np.ndarray) -> float:
    scale = float(np.mean(np.abs(context[SEASONAL_DAILY:] - context[:-SEASONAL_DAILY])))
    if scale == 0:
        return float("nan")
    return float(np.mean(np.abs(actual - pred)) / scale)


def _metrics(actual: np.ndarray, pred: np.ndarray, context: np.ndarray) -> dict[str, float]:
    err = actual - pred
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(math.sqrt(np.mean(err**2))),
        "smape": _smape(actual, pred),
        "mase": _mase(actual, pred, context),
    }


def _baselines(context: np.ndarray, horizon: int) -> dict[str, np.ndarray]:
    daily = np.asarray(list(context[-SEASONAL_DAILY:]) * (horizon // SEASONAL_DAILY + 1))[:horizon]
    weekly = np.asarray(list(context[-SEASONAL_WEEKLY:]) * (horizon // SEASONAL_WEEKLY + 1))[
        :horizon
    ]
    return {
        "persistence": np.full(horizon, context[-1]),
        "seasonal_d": daily,
        "seasonal_w": weekly,
        "mean": np.full(horizon, float(np.mean(context))),
    }


def _windows(values: list[float], horizon: int) -> list[tuple[np.ndarray, np.ndarray]]:
    n = len(values)
    out = []
    for k in range(WINDOWS):
        end = n - horizon - k * horizon
        start = end - CONTEXT
        if start < 0:
            break
        out.append((np.asarray(values[start:end]), np.asarray(values[end : end + horizon])))
    return out


def evaluate_series(name: str, values: list[float], engine: TimesFM3Engine) -> list[dict]:
    rows = []
    for horizon in HORIZONS:
        acc: dict[str, list[float]] = {
            "model": [],
            "persistence": [],
            "seasonal_d": [],
            "seasonal_w": [],
            "mean": [],
            "coverage": [],
        }
        mase_scales: list[float] = []
        for context, actual in _windows(values, horizon):
            output = engine.predict(
                ForecastRequest(
                    mode=Mode.univariate,
                    horizon=horizon,
                    series=[SeriesInput(id=name, target=context.tolist())],
                    options=ForecastOptions(return_quantiles=True),
                )
            )[0]
            pred = np.asarray(output.forecast)
            quantiles = np.asarray(output.quantiles)
            below, above = quantiles[:, 0], quantiles[:, -1]
            acc["coverage"].append(float(np.mean((actual >= below) & (actual <= above)) * 100))
            acc["model"].append(_metrics(actual, pred, context)["mae"])
            mase_scales.append(_mase(actual, pred, context))
            for baseline, series in _baselines(context, horizon).items():
                acc[baseline].append(_metrics(actual, series, context)["mae"])
        if not acc["model"]:
            continue
        rows.append(
            {
                "series": name,
                "horizon": horizon,
                "windows": len(acc["model"]),
                "model": float(np.mean(acc["model"])),
                "mase": float(np.nanmean(mase_scales)),
                "persistence": float(np.mean(acc["persistence"])),
                "seasonal_d": float(np.mean(acc["seasonal_d"])),
                "seasonal_w": float(np.mean(acc["seasonal_w"])),
                "mean": float(np.mean(acc["mean"])),
                "coverage": float(np.mean(acc["coverage"])),
            }
        )
    return rows


def multivariate_test(payload: dict, engine: TimesFM3Engine) -> None:
    series = payload["series"]
    names = ["net_rx_bytes", "net_tx_bytes"]
    if not all(n in series for n in names):
        return
    horizon = 24
    contexts = [np.asarray(series[n][-CONTEXT:]) for n in names]
    actuals = [np.asarray(series[n][-horizon:]) for n in names]
    joint = engine.predict(
        ForecastRequest(
            mode=Mode.multivariate,
            horizon=horizon,
            series=[
                SeriesInput(id=n, target=c.tolist()) for n, c in zip(names, contexts, strict=True)
            ],
        )
    )
    print("\n=== multivariate vs univariate (net_rx / net_tx, horizon 24) ===")
    for i, name in enumerate(names):
        uni = engine.predict(
            ForecastRequest(
                mode=Mode.univariate,
                horizon=horizon,
                series=[SeriesInput(id=name, target=contexts[i].tolist())],
            )
        )[0]
        uni_mae = float(np.mean(np.abs(actuals[i] - np.asarray(uni.forecast))))
        mvi_mae = float(np.mean(np.abs(actuals[i] - np.asarray(joint[i].forecast))))
        flag = "better" if mvi_mae < uni_mae else "worse"
        print(
            f"  {name:12s} univariate MAE={uni_mae:.4g}  multivariate MAE={mvi_mae:.4g}  ({flag})"
        )


def main() -> None:
    payload = json.loads((DATA_DIR / "complex_series.json").read_text())
    engine = TimesFM3Engine(
        Settings(
            engine="timesfm3",
            cache_dir="/home/albe/.cache/precog/models",
            local_files_only=True,
            per_core_batch_size=4,
            torch_threads=8,
        )
    )

    rows: list[dict] = []
    for name, values in payload["series"].items():
        rows.extend(evaluate_series(name, values, engine))

    header = (
        f"{'series':18s} {'H':>3s} {'model':>10s} {'persist':>10s} {'seas_d':>10s} "
        f"{'seas_w':>10s} {'mean':>10s} {'MASE':>6s} {'cov%':>5s}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['series']:18s} {row['horizon']:3d} {row['model']:10.3g} "
            f"{row['persistence']:10.3g} {row['seasonal_d']:10.3g} "
            f"{row['seasonal_w']:10.3g} {row['mean']:10.3g} "
            f"{row['mase']:6.2f} {row['coverage']:5.1f}"
        )

    model = np.array([r["model"] for r in rows])
    best_baseline = np.array(
        [min(r["persistence"], r["seasonal_d"], r["seasonal_w"], r["mean"]) for r in rows]
    )
    print("\n=== aggregate (all series/horizons) ===")
    print(f"  TimesFM-3 mean MAE: {model.mean():.4g}")
    print(f"  best-baseline mean MAE: {best_baseline.mean():.4g}")
    mean_mase = np.nanmean([r["mase"] for r in rows])
    print(f"  mean MASE: {mean_mase:.2f}  (MASE < 1 = better than seasonal-naive)")
    print(f"  win rate vs best baseline: {(model < best_baseline).mean() * 100:.0f}%")
    print(f"  mean 80% interval coverage: {np.mean([r['coverage'] for r in rows]):.1f}%")

    multivariate_test(payload, engine)


if __name__ == "__main__":
    main()

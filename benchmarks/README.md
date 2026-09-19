# Benchmarks

Backtests of TimesFM-3 (zero-shot, CPU) against real series collected from
Grafana / Thanos, compared with trivial baselines.

## Scripts

- `fetch_thanos.py` — collects the sample series into `data/complex_series.json`
  (needs a port-forward to `thanos-system/thanos-query`).
- `evaluate.py` — multi-series, multi-horizon, multi-window backtest with MAE,
  sMAPE, MASE, pinball loss and 80% interval coverage. Writes a versioned
  aggregate baseline (`data/benchmark_baseline.json`) and can gate on it.
- `backtest_grafana.py` — single-metric sanity backtest on `data/grafana_sample.json`.
- `synthetic.py` — deterministic synthetic series generator (trend + seasonality
  + noise).
- `baseline_cpu.py` — records CPU latency and RSS on synthetic series into
  `data/baseline_cpu.json` (a committed baseline).
- `load_test.py` — concurrent load test against a running API; writes
  `data/load_test[_<label>].json`.
- `calibration.py` — quantile-spread calibration sweep on the real series
  (coverage vs pinball loss); writes `data/calibration.json`.
- `symmetric_averaging.py` — compares `use_symmetric_averaging` on/off on the
  real series (MAE, coverage, pinball, forecast sensitivity); writes
  `data/symmetric_averaging.json`. Backs ADR 0007.

## Run

```bash
kubectl -n thanos-system port-forward svc/thanos-query 9091:9090 &
.venv/bin/python benchmarks/fetch_thanos.py      # refresh data (optional)
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python benchmarks/evaluate.py
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python benchmarks/evaluate.py --write-baseline
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python benchmarks/evaluate.py --check
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.baseline_cpu
PRECOG_API_URL=http://127.0.0.1:8000 CONCURRENCY=4 REQUESTS=16 \
  .venv/bin/python -m benchmarks.load_test
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.calibration
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python -m benchmarks.symmetric_averaging
```

## Baselines

`persistence` (last value), `seasonal_d` (lag 24h), `seasonal_w` (lag 168h),
`mean` (context mean). `MASE < 1` means the model beats the seasonal-naive
baseline.

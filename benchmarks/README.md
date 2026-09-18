# Benchmarks

Backtests of TimesFM-3 (zero-shot, CPU) against real series collected from
Grafana / Thanos, compared with trivial baselines.

## Scripts

- `fetch_thanos.py` — collects the sample series into `data/complex_series.json`
  (needs a port-forward to `thanos-system/thanos-query`).
- `evaluate.py` — multi-series, multi-horizon, multi-window backtest with MAE,
  sMAPE, MASE and 80% interval coverage.
- `backtest_grafana.py` — single-metric sanity backtest on `data/grafana_sample.json`.

## Run

```bash
kubectl -n thanos-system port-forward svc/thanos-query 9091:9090 &
.venv/bin/python benchmarks/fetch_thanos.py      # refresh data (optional)
PRECOG_LOCAL_FILES_ONLY=true .venv/bin/python benchmarks/evaluate.py
```

## Baselines

`persistence` (last value), `seasonal_d` (lag 24h), `seasonal_w` (lag 168h),
`mean` (context mean). `MASE < 1` means the model beats the seasonal-naive
baseline.

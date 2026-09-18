# Observability

Sample Grafana dashboard and Prometheus alerting rules for the API metrics
exposed on `GET /metrics`.

- `grafana-dashboard.json` — import via Grafana → Dashboards → Import.
- `prometheus-alerts.yaml` — Prometheus rule group (adjust the `job` label).

Metrics used: `precog_requests_total`, `precog_request_duration_seconds`,
`precog_inflight_requests`, `precog_forecast_series_total`,
`precog_model_load_seconds`.

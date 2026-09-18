# Precog

Zero-shot forecasting with [TimesFM-3](https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/), packaged as a REST API, an MCP server and a Python SDK.

## Status

Early development. The current MVP exposes a single synchronous endpoint:

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET`  | `/healthz` | Liveness |
| `GET`  | `/readyz`  | Readiness (model loaded) |
| `POST` | `/v1/forecast` | Synchronous forecast (univariate / multivariate / covariates) |
| `GET`  | `/docs` | OpenAPI docs (disable with `PRECOG_ENABLE_DOCS=false`) |

## Quickstart

```bash
uv sync --all-packages
uv run precog-api          # starts on http://localhost:8000
```

By default the API uses the real TimesFM-3 engine. For local development
without torch, use the deterministic fake engine:

```bash
PRECOG_ENGINE=fake uv run precog-api
curl -s localhost:8000/v1/forecast -H 'content-type: application/json' -d '{
  "mode": "univariate",
  "horizon": 4,
  "series": [{"id": "a", "target": [1.0, 2.0, 3.0]}]
}'
```

## Configuration

All settings use the `PRECOG_` prefix (see `apps/api/src/precog_api/config.py`):
`PRECOG_ENGINE`, `PRECOG_DEVICE`, `PRECOG_MODEL_PATH`, `PRECOG_MAX_HORIZON`,
`PRECOG_MAX_CONTEXT`, `PRECOG_MAX_SERIES`, `PRECOG_MAX_CONCURRENCY`,
`PRECOG_API_KEY`, `PRECOG_ENABLE_DOCS`.

## Repository layout

```
apps/api            FastAPI service (engine + HTTP)
apps/mcp            MCP server exposing the forecast tool
packages/schemas    Shared Pydantic models
benchmarks          Backtests against real Grafana/Thanos series
deploy              Dockerfile, compose, Helm chart, Kustomize
docs                ADRs, deployment and MCP guides
```

## Deploy

CPU container with the weights baked in, built and run locally (never
published). See [docs/deploy.md](docs/deploy.md). Quick version:

```bash
podman build --format docker -t precog-api:local .
docker compose -f deploy/compose/docker-compose.yml up
```


## Development env note (TLS inspection)

If you are behind a corporate TLS-inspecting proxy, `uv` needs the system trust
store:

```bash
uv sync --all-packages --system-certs      # or set UV_SYSTEM_CERTS=1
```

## License

Application code is MIT (see `LICENSE`). The TimesFM-3 model weights are
distributed under the **TimesFM Non-Commercial License v1.0** and are **not**
part of this repository. See `THIRD_PARTY_NOTICES.md`. This project is a
non-commercial, hobby effort.

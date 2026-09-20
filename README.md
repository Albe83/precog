# Precog

Zero-shot forecasting with [TimesFM-3](https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/), packaged as a REST API, an MCP server and a Python SDK.

## Status

Early development. The current MVP exposes a single synchronous endpoint:

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET`  | `/healthz` | Liveness |
| `GET`  | `/readyz`  | Readiness (model loaded) |
| `GET`  | `/v1/capabilities` | Model and API capabilities (limits, modes, covariates) |
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
  "horizon": 4,
  "targets": [{"id": "a", "values": [1.0, 2.0, 3.0]}],
  "quantiles": [0.1, 0.5, 0.9]
}'
```

## Targets and covariates

`POST /v1/forecast` takes a single canonical execution problem (ADR 0006).
Multiple `targets` are forecast **jointly**; covariates are declared once at
request level:

- `past_covariates` are known only during the context and must match the target
  context length;
- `known_future_covariates` carry `history` (context length) and `future`
  (`horizon`).

`quantiles` lists the requested levels (`[]` means point-only); unsupported
levels are rejected.

```bash
curl -s localhost:8000/v1/forecast -H 'content-type: application/json' -d '{
  "horizon": 3,
  "targets": [
    {"id": "brand_a", "values": [100,102,101,105,107,106]},
    {"id": "brand_b", "values": [80,81,80,83,85,84]}
  ],
  "past_covariates": [{"id": "footfall", "values": [0.1,0.2,0.15,0.3,0.4,0.35]}],
  "known_future_covariates": [
    {"id": "promo", "history": [0,1,0,0,0,1], "future": [0,1,0]}
  ],
  "quantiles": [0.1, 0.9]
}'
```

The same contract is available as OpenAPI examples on `/docs`.

Only the requested quantile levels are returned, as self-describing
`{level, values}` entries per target. Non-finite inputs (`NaN`/`Inf`) are
rejected: Precog never interpolates, truncates or otherwise mutates caller data.

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
packages/sdk-python Synchronous Python client
packages/sdk-ts     TypeScript client (browser / Node)
webui               Minimal web UI built on the TypeScript SDK
benchmarks          Backtests against real Grafana/Thanos series
deploy              Dockerfile, compose, Helm chart, Kustomize
docs                ADRs, deployment, MCP and SDK guides
```

## Deploy

CPU container that downloads the weights into a cache volume at startup (not
baked in), built and run locally. See [docs/deploy.md](docs/deploy.md).
Weight-free images are also published to GHCR on release:
`ghcr.io/albe83/precog-api` and `ghcr.io/albe83/precog-mcp`.
Quick version:

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

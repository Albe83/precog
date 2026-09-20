# Precog

Zero-shot forecasting with [TimesFM-3](https://research.google/blog/timesfm-3-a-zero-shot-foundation-model-for-multivariate-forecasting/).

Precog has three supported v1 surfaces:

- **REST Execution API** (`apps/api`) — the canonical synchronous execution
  contract (targets, covariates, explicit quantiles; ADR 0006);
- **MCP semantic interface** (`apps/mcp`) — agent-facing `forecast`/`backtest`
  tools and the `precog://capabilities` resource (ADR 0005);
- **Python SDK** (`packages/sdk-python`) — the official supported execution
  client, with synchronous and asynchronous clients.

The WebUI and the TypeScript SDK are kept in-tree but are **experimental and
outside the supported v1 product surface** (see their READMEs).

## REST API

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET`  | `/healthz` | Liveness |
| `GET`  | `/readyz`  | Readiness (model loaded) |
| `GET`  | `/v1/capabilities` | Execution/runtime capabilities (engine, model, limits, quantiles, features) |
| `POST` | `/v1/forecast` | Synchronous execution (joint targets + optional covariates) |
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

## MCP server

`apps/mcp` exposes Precog to MCP clients as the semantic `forecast` and
`backtest` tools plus the `precog://capabilities` resource. It talks to the REST
API over HTTP through the official `AsyncPrecogClient` and carries no model
weights. See [docs/mcp.md](docs/mcp.md).

```bash
PRECOG_ENGINE=fake uv run precog-api                                     # API
PRECOG_API_URL=http://localhost:8000 uv run --no-sync precog-mcp         # MCP (stdio)
```

## Python SDK

`packages/sdk-python` is the official supported execution client:
`PrecogClient` (sync), `AsyncPrecogClient` (async) and the `precog` CLI, sharing
the `precog-schemas` wire models. Install the published pair from PyPI:

```bash
pip install precog-client
```

The `precog-schemas`/`precog-client` version train is independent from the
application/Helm release version. See [docs/sdk.md](docs/sdk.md).

## Configuration

All settings use the `PRECOG_` prefix (see `apps/api/src/precog_api/config.py`):
`PRECOG_ENGINE`, `PRECOG_DEVICE`, `PRECOG_MODEL_PATH`, `PRECOG_MAX_HORIZON`,
`PRECOG_MAX_CONTEXT`, `PRECOG_MAX_SERIES`, `PRECOG_MAX_CONCURRENCY`,
`PRECOG_API_KEY`, `PRECOG_ENABLE_DOCS`.

## Repository layout

```
apps/api            FastAPI service (engine + HTTP execution API)
apps/mcp            MCP server (semantic tools + capabilities resource)
packages/schemas    Shared Pydantic wire models (published: precog-schemas)
packages/sdk-python Python execution clients, sync + async (published: precog-client)
packages/sdk-ts     TypeScript client (experimental, not supported in v1)
webui               Web UI built on the TypeScript SDK (experimental, not supported in v1)
benchmarks          Backtests against real Grafana/Thanos series
deploy              Compose, Helm chart, Kustomize, observability assets
docs                ADRs, deployment, MCP and SDK guides
```

## Deploy

The API ships as a CPU-only container that downloads the weights into a cache
volume at startup (never baked in). Weight-free images and the Helm chart are
published per release:

- `ghcr.io/albe83/precog-api` (downloads weights at runtime)
- `ghcr.io/albe83/precog-mcp` (no weights at all)
- `oci://ghcr.io/albe83/precog-charts/precog` (pin with `--version`)

Local builds are still supported. See [docs/deploy.md](docs/deploy.md).

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
part of this repository or the published images. See `THIRD_PARTY_NOTICES.md`.
This project is a non-commercial, hobby effort.

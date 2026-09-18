# Runbook

Operational notes for running Precog.

## Architecture

- `apps/api` — FastAPI service, TimesFM-3 loaded in-process (CPU).
- `apps/mcp` — MCP server that calls the API over HTTP.
- `packages/schemas` — shared Pydantic models.
- Model weights are **not** baked into the image; the entrypoint downloads the
  pinned revision into `PRECOG_CACHE_DIR` if missing.

## Start / stop

Standalone (compose):

```bash
docker compose -f deploy/compose/docker-compose.yml up -d
docker compose -f deploy/compose/docker-compose.yml logs -f api
docker compose -f deploy/compose/docker-compose.yml down
```

Kubernetes (Helm):

```bash
helm upgrade --install precog deploy/helm/precog -n precog --create-namespace
kubectl -n precog port-forward svc/precog 8000:80
helm uninstall precog -n precog
```

Published images: `ghcr.io/albe83/precog-api:latest`, `ghcr.io/albe83/precog-mcp:latest`.

## Model cache

| Volume | Behaviour |
| ------ | --------- |
| `emptyDir` (Helm default) | per-pod; every pod downloads; lost on restart |
| PVC RWX | shared; first pod downloads, the rest reuse |
| PVC RWO | single replica only |
| `downloadJob.enabled` | one-shot Job pre-populates a PVC |
| `downloadInitContainer.enabled` | download runs before the app container |

Cold start downloads ~1.3 GB (a couple of minutes); warm start then loads the
model from cache (~10 s). `PRECOG_PRELOAD=never` fails fast if the model is
missing — use it for pre-seeded/air-gapped volumes.

## Performance and tuning

Measured on a 22-core CPU host (`benchmarks/load_test.py`, 16 requests,
concurrency 4, horizon 24):

| Config | p50 | p95 | rps |
| ------ | --- | --- | --- |
| `MAX_CONCURRENCY=1`, default torch threads | 857 ms | 1092 ms | 4.4 |
| `MAX_CONCURRENCY=4`, `TORCH_THREADS=4` | 901 ms | 1299 ms | 4.2 |

The model is CPU-bound and torch already parallelizes a single inference.
Raising `PRECOG_MAX_CONCURRENCY` does not improve throughput and hurts latency;
keep it at `1` and **scale horizontally with replicas** instead. Tune
`PRECOG_TORCH_THREADS` only if you co-locate other workloads.

Single-forecast latency is ~200 ms for small contexts; budget for variance under
load.

## Observability

- Structured JSON logs with `x-request-id` (echo the header to correlate).
- `GET /metrics` (Prometheus): request counts, latency histogram, in-flight
  gauge, forecast series, model load time.
- `deploy/observability/` has a sample Grafana dashboard and Prometheus alerts.

## TLS / corporate CA

The image must trust the corporate CA to download the weights behind a
TLS-inspecting proxy: build with `--build-arg CA_CERT="$(cat corp-root.crt)"`.
For other tooling use `uv --system-certs` / `UV_SYSTEM_CERTS=1`.

## Auth

Set `PRECOG_API_KEY` (Helm `config.apiKey`, compose env) to require
`Authorization: Bearer <key>`. To rotate: update the secret / env and restart;
there is no downtime-free rotation yet (do it during a quiet window or rolling
update).

## Troubleshooting

| Symptom | Likely cause | Action |
| ------- | ------------ | ------ |
| `/readyz` 503 for minutes | cold download | wait; check egress/CA; consider `downloadJob` |
| Pods restarting on start | `preload=never` with empty cache | pre-seed the volume or set `auto` |
| 429 responses | rate limit enabled | raise `PRECOG_RATE_LIMIT_REQUESTS` or back off (`Retry-After`) |
| 504 responses | request timeout | raise `PRECOG_REQUEST_TIMEOUT_S` or reduce horizon |
| OOMKilled | memory limit too low | the model needs ~3 GB RSS; raise limits |
| `LocalEntryNotFoundError` | cache empty and offline | populate the volume or bake weights |

## Releases

`release-please` opens a release PR from `main`; merging it publishes a GitHub
Release and triggers `publish-images` (via the release-please workflow, because
releases created with `GITHUB_TOKEN` do not fire the `release` event). Images
are pushed to GHCR with semver, `sha-<short>` and `latest` tags. The Helm chart
is packaged and published to `oci://ghcr.io/albe83/precog-charts/precog`
(pinnable with `--version`) and attached to the release as `precog-<version>.tgz`.
The baked variant (`PRECOG_BAKE_WEIGHTS=true`) must never be published.

## License

Application code is MIT. TimesFM-3 weights are non-commercial and are downloaded
at runtime; see `THIRD_PARTY_NOTICES.md`.

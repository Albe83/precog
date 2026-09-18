# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); the project
follows [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added

- CI publishes the weight-free images to GHCR on release
  (`ghcr.io/<owner>/precog-api`, `ghcr.io/<owner>/precog-mcp`), with a check that
  no model weights are embedded. The baked variant is never published.
- API: JSON structured logging with a per-request id (`x-request-id` echoed back),
  a Prometheus `/metrics` endpoint (request counts, latency histogram, in-flight
  gauge, forecast series, model load time) and optional in-process rate limiting
  (`PRECOG_RATE_LIMIT_REQUESTS`/`PRECOG_RATE_LIMIT_WINDOW_S`, 429 with
  `Retry-After`).
- API: richer OpenAPI with request examples (univariate, covariates,
  multivariate), response descriptions and documented error responses.

### Changed

- The API image no longer bakes the TimesFM-3 weights by default. The entrypoint
  downloads the pinned revision into `PRECOG_CACHE_DIR` at startup when missing
  and reuses the cache volume (ephemeral directory, named volume, bind mount or
  PVC). Set `PRECOG_BAKE_WEIGHTS=true` for an air-gapped image.
- Helm: new `modelCache` values (ephemeral `emptyDir` by default, optional PVC
  that defaults to `ReadWriteMany` so scaling reuses the volume, `preload`,
  `revision`, `hfTokenSecret`) and a `startupProbe` for cold starts.
- Helm: optional model-download `initContainer`
  (`modelCache.downloadInitContainer.enabled`); the app container then uses
  `PRECOG_PRELOAD=never`. `PRECOG_PRELOAD=never` now fails fast when the model
  is absent.
- Helm: optional one-shot model-download `Job`
  (`modelCache.downloadJob.enabled`, post-install/post-upgrade hook) to
  pre-populate a persistent cache; requires a PVC.
- Compose: named `precog-models` volume mounted at `/opt/precog/hf`.

## [0.1.0] - 2026-09-18

First source release. TimesFM-3 zero-shot forecasting exposed as a REST API,
an MCP server and a Python package set.

### Added

- **REST API** (`apps/api`): synchronous `POST /v1/forecast` for univariate and
  multivariate series with past-only and past+future covariates; `GET /healthz`
  and `GET /readyz`; RFC 7807 error responses; configurable limits, optional
  bearer auth, request timeout and bounded concurrency.
- **Engine**: TimesFM-3 adapter (`TimesFM3Engine`, CPU, lazy torch import) and a
  deterministic `FakeEngine` for tests.
- **Shared schemas** (`packages/schemas`): Pydantic request/response models and
  the 9 quantile levels.
- **MCP server** (`apps/mcp`): `forecast` tool over stdio and streamable-http,
  with error mapping and payload validation.
- **Containerization**: CPU image with the weights baked in and offline loading
  (`Dockerfile`), MCP image without weights (`Dockerfile.mcp`), docker-compose,
  Helm chart (probes, resources, HPA/PDB, non-root security context, optional MCP
  deployment) and Kustomize base/overlays.
- **CI**: lint, format check, typecheck and tests; build-only image workflow with
  a Trivy scan. No images are published.
- **Benchmarks**: backtests against real Grafana/Thanos series with MAE, sMAPE,
  MASE and interval coverage against multiple baselines.
- **Docs**: architecture/stack/licensing ADRs, deployment and MCP guides.

### Notes

- Application code is MIT. The TimesFM-3 model weights are under the TimesFM
  Non-Commercial License v1.0; they are not committed to this repository and no
  artifact embedding them is published. See `THIRD_PARTY_NOTICES.md`.
- The API image embeds the weights and must not be published; build it locally.

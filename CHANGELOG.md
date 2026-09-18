# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); the project
follows [Conventional Commits](https://www.conventionalcommits.org/).

## [0.7.1](https://github.com/Albe83/precog/compare/v0.7.0...v0.7.1) (2026-09-18)


### Bug Fixes

* **deploy:** reconcile existingClaim, harden runtime and support existing secret ([#96](https://github.com/Albe83/precog/issues/96)) ([1dec8d7](https://github.com/Albe83/precog/commit/1dec8d73ecd76b725661954dad5cb4568a491345))

## [0.7.0](https://github.com/Albe83/precog/compare/v0.6.0...v0.7.0) (2026-09-18)


### Features

* **api:** add capabilities endpoint and repo governance ([#85](https://github.com/Albe83/precog/issues/85)) ([9755457](https://github.com/Albe83/precog/commit/97554572f833f28dea2afaf1df25109f11642000))


### Documentation

* **deploy:** fix chart version examples ([#83](https://github.com/Albe83/precog/issues/83)) ([314df9b](https://github.com/Albe83/precog/commit/314df9b8530a3f3d5b1d49f037ad9e628aab9b12))

## [0.6.0](https://github.com/Albe83/precog/compare/v0.5.0...v0.6.0) (2026-09-18)


### Features

* **deploy:** publish the Helm chart per release ([#81](https://github.com/Albe83/precog/issues/81)) ([8b9ff08](https://github.com/Albe83/precog/commit/8b9ff0821944bfdb75019b2d6480a2c3067a15e2))

## [0.5.0](https://github.com/Albe83/precog/compare/v0.4.0...v0.5.0) (2026-09-18)


### Features

* **api:** support covariates in multivariate mode ([a1165fc](https://github.com/Albe83/precog/commit/a1165fc370d8de06be47e44e50deeec3c078a767))
* **sdk:** pass request-level covariates ([d4af243](https://github.com/Albe83/precog/commit/d4af243fc6089c2946a519a219f551c024cca2a4))


### Documentation

* **api:** document multivariate covariates ([0515e59](https://github.com/Albe83/precog/commit/0515e59315137971c667ea7b1df21f020bd1721c))
* **deploy:** document the Helm chart install and values ([e65fb27](https://github.com/Albe83/precog/commit/e65fb27f203453618091b6ef4273fa0a4c96b591))
* **repo:** document branch protection ([6538182](https://github.com/Albe83/precog/commit/65381829a27bd67d9168baebf877a63071c3cd76))

## [0.4.0](https://github.com/Albe83/precog/compare/v0.3.0...v0.4.0) (2026-09-18)


### Features

* **mcp:** make HTTP host validation configurable ([5c3888a](https://github.com/Albe83/precog/commit/5c3888a366d45097a07d1465b383bf40e30540f7))


### Documentation

* **mcp:** document PRECOG_MCP_ALLOWED_HOSTS ([50d22f6](https://github.com/Albe83/precog/commit/50d22f68269e19729155e453537e62fbe1fd111c))

## [0.3.0](https://github.com/Albe83/precog/compare/v0.2.0...v0.3.0) (2026-09-18)


### Features

* **deploy:** add Grafana dashboard and Prometheus alerts ([7512cd9](https://github.com/Albe83/precog/commit/7512cd96b61bd9c2e9ce3bfe9fbfd9efa8ed82f8))
* **deploy:** run containers with a read-only root filesystem ([f74868e](https://github.com/Albe83/precog/commit/f74868e4930d8e3c9d76721e6849eeed6587d245))


### Bug Fixes

* **ci:** publish images from the release-please workflow ([8e75254](https://github.com/Albe83/precog/commit/8e75254a9776df1a2ac6ee3a6d30eb9d1e60edec))
* **ci:** use a valid trivy-action tag ([a4628ca](https://github.com/Albe83/precog/commit/a4628ca7406a7a5995a448a3ab43c50514dca3b8))


### Documentation

* **repo:** add operations runbook ([663b3c8](https://github.com/Albe83/precog/commit/663b3c833c9c8190f2701a75c927bef96d9a019a))
* **sdk:** apply ruff formatting to markdown examples ([40aef98](https://github.com/Albe83/precog/commit/40aef98ad2bb9aeabfdf7a5071dc5a39b1e3e834))

## [0.2.0](https://github.com/Albe83/precog/compare/v0.1.0...v0.2.0) (2026-09-18)


### Features

* **api:** add observability, rate limiting and OpenAPI examples ([270022a](https://github.com/Albe83/precog/commit/270022a395c60b3bb67298e33c304b06a0c0c4b7))
* **api:** fail fast when preload is never and the model is absent ([05e3661](https://github.com/Albe83/precog/commit/05e366195a9c9ccca78aa1b1077df08a4897e363))
* **api:** provision model weights at startup into a cache volume ([544c59c](https://github.com/Albe83/precog/commit/544c59cc224c9970aacef04a26f42b2da6ca7719))
* **deploy:** add optional model download initContainer for scaling ([9ce5d0e](https://github.com/Albe83/precog/commit/9ce5d0e04628f7a0c9e6009a982fb81b620798ab))
* **deploy:** add optional one-shot model download Job ([9780037](https://github.com/Albe83/precog/commit/9780037d310c65b82562127dc7b24596db8ab5ab))
* **deploy:** download weights into a volume instead of baking them ([0468f32](https://github.com/Albe83/precog/commit/0468f3278d000e7e0c95855c529d3c59cf8d33ac))
* **sdk:** add synchronous typed Python client ([3e034a4](https://github.com/Albe83/precog/commit/3e034a4bad1c7b0c5320c3fdf4f64a2a03489af9))


### Documentation

* **api:** document observability and rate limiting ([fca7b95](https://github.com/Albe83/precog/commit/fca7b9579cc9cc8ed3e328bce596f330f1d70203))
* **deploy:** document published images and licensing guard ([5429434](https://github.com/Albe83/precog/commit/54294344a9fcc781f78cab766206a3a70acaaf07))
* **deploy:** document volume-based model provisioning ([6e99a70](https://github.com/Albe83/precog/commit/6e99a70574f9d3f492ed79a62fa108b6e13d0cf8))
* **repo:** document hooks and release automation ([74ecd57](https://github.com/Albe83/precog/commit/74ecd57a1e19492716a1f80c10577add6146836c))
* **sdk:** add Python SDK guide ([0ba7bea](https://github.com/Albe83/precog/commit/0ba7beae3c42f154104901d17994ac84326934e7))

## [Unreleased]

### Added

- Helm: `config.existingSecret` / `config.existingSecretKey` to reference an
  existing Secret for the API key (mutually exclusive with `config.apiKey`).
- Helm: consistent `modelCache.persistence.existingClaim` handling — it now
  enables persistence, suppresses the chart-managed PVC and is used by the
  Deployment and the download Job; `NOTES.txt` matches the real behavior
  (published images, weights downloaded at runtime).
- Helm: runtime hardening — `automountServiceAccountToken: false`, a
  configurable `terminationGracePeriodSeconds` (API default 360s), and a
  read-only root filesystem with a `/tmp` emptyDir for the download
  initContainer and Job.
- Repo: allow the `deps` scope for semantic PR titles (Dependabot).
- API: `GET /v1/capabilities` advertises the model, limits, modes, quantile
  levels, covariate support and whether auth is required; the Python SDK exposes
  `client.capabilities()`.
- Repo: `CODEOWNERS`, `SECURITY.md` and Dependabot (uv + GitHub Actions).
- API: multivariate forecasting with covariates. In `mode=multivariate` the
  target variates share one joint context and covariates are declared once at
  request level (`past_covariates`/`future_covariates`); per-series covariates
  remain for univariate mode. The engine now maps them to TimesFM-3's
  `predict_batch`.
- SDK: `forecast(..., past_covariates=..., future_covariates=...)` for
  request-level covariates.
- MCP: `PRECOG_MCP_ALLOWED_HOSTS` to configure the HTTP transport Host
  validation (comma-separated list, or `*` to disable DNS-rebinding protection).
  Required when the server runs behind a gateway such as agentgateway.
- CI publishes the weight-free images to GHCR on release
  (`ghcr.io/<owner>/precog-api`, `ghcr.io/<owner>/precog-mcp`, `ghcr.io/<owner>/precog-charts`),
  with a check that no model weights are embedded. The baked variant is never
  published.
- Helm: the chart is packaged per release and published as an OCI chart
  (`oci://ghcr.io/albe83/precog-charts/precog`, pin with `--version`) and
  attached to the GitHub release as `precog-<version>.tgz`. `release-please`
  keeps `Chart.yaml` `version`/`appVersion` in lockstep with the release.
- Helm: pods roll on ConfigMap changes (`checksum/config`) and on API key
  changes (`checksum/secret`).
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

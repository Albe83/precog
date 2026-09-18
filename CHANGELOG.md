# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/); the project
follows [Conventional Commits](https://www.conventionalcommits.org/).

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

# AGENTS

Context for automated contributors.

## Project

Precog exposes Google TimesFM-3 zero-shot forecasting through three supported v1
surfaces:

- **REST Execution API** (`apps/api`) — the canonical execution contract; owns
  the engine, limits and the `/v1/forecast` + `/v1/capabilities` wire API
  (ADR 0006, ADR 0007);
- **MCP semantic interface** (`apps/mcp`) — agent-facing `forecast`/`backtest`
  tools and `precog://capabilities`; talks to the REST API via the Python SDK
  and carries no model weights (ADR 0005);
- **Python SDK** (`packages/sdk-python`) — the official supported execution
  client (`PrecogClient`, `AsyncPrecogClient`, `precog` CLI), published as the
  independently versioned `precog-client` / `precog-schemas` pair.

WebUI and the TypeScript SDK are retained in-tree but are experimental and
outside the supported v1 surface; they must not drive REST/MCP/Python design.

## Key constraints

- **TimesFM-3 weights are non-commercial.** Never commit weights, never publish
  artifacts that redistribute them (see `THIRD_PARTY_NOTICES.md`, `PREC-9`).
- **CPU-only** for now. `PRECOG_DEVICE` is parametric for future GPU support.
- **MVP mindset**: prefer the smallest working solution; avoid premature
  abstraction.
- Published images are **weight-free**; the API downloads weights at runtime.
  Never publish an image built with `PRECOG_BAKE_WEIGHTS=true`.
- Python package versions are independent from the application/Helm release
  version.

## Commands

```bash
uv sync --all-packages --system-certs   # --system-certs behind TLS inspection
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
PRECOG_ENGINE=fake uv run precog-api    # no torch required
```

## Environment note (TLS inspection)

The build environment performs TLS inspection with a corporate CA in the OS
trust store. Use `uv --system-certs` / `UV_SYSTEM_CERTS=1`, and for standard
Python tooling rely on the OS default trust store (`SSL_CERT_FILE`,
`REQUESTS_CA_BUNDLE`) instead of bundled `certifi` where possible.

## Layout

```
apps/api/src/precog_api   execution contract, engine, mapping, config, app
apps/mcp/src/precog_mcp   MCP server, adapter, semantic models/capabilities
packages/schemas          shared request/response wire models
packages/sdk-python       official Python execution clients (sync + async)
packages/sdk-ts           experimental TypeScript client
webui                     experimental web UI
deploy                    compose, Helm chart, Kustomize, observability
docs/adr                  architecture decisions (0005-0007 shape the split)
```

## Docs contract

Keep the semantic MCP plane and the execution REST plane distinct when writing
docs, and describe WebUI/TypeScript as experimental. Do not introduce Phase 3
promises.

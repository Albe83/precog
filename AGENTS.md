# AGENTS

Context for automated contributors.

## Project

Precog exposes Google TimesFM-3 zero-shot forecasting as a REST API (MVP),
later as an MCP server and a Python SDK. Deployed as a container, standalone or
on Kubernetes.

## Key constraints

- **TimesFM-3 weights are non-commercial.** Never commit weights, never publish
  artifacts that redistribute them (see `THIRD_PARTY_NOTICES.md`, `PREC-9`).
- **CPU-only** for now. `PRECOG_DEVICE` is parametric for future GPU support.
- **MVP mindset**: prefer the smallest working solution; avoid premature
  abstraction.
- The container is **not published**; it is built locally.

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
apps/api/src/precog_api   engine.py, engine_timesfm3.py, config.py, app.py
packages/schemas          request/response Pydantic models
```

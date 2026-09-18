# ADR 0001 — Architecture

- Status: accepted
- Date: 2026-09-18

## Context

Precog must make TimesFM-3 usable in real workflows. The delivery chain is a
REST API, then an MCP server, then a Python SDK (and later a TypeScript SDK and
a web UI). Deployments are containers, standalone or on Kubernetes.

## Decision

Monorepo with a uv workspace:

```
apps/api            FastAPI service; loads the model in-process
packages/schemas    Shared Pydantic request/response models (OpenAPI source of truth)
apps/mcp            MCP server; consumes the REST API over HTTP (later)
packages/sdk-python Typed synchronous client (later)
deploy/             Dockerfile, compose, Helm, Kustomize (later)
docs/adr            This directory
```

The API owns inference. Every other consumer talks HTTP, so the MCP server and
SDK never link torch. The engine is behind a small `Engine` protocol so tests
use a deterministic `FakeEngine` and production uses `TimesFM3Engine`.

Phase 1 exposes a single synchronous endpoint, `POST /v1/forecast`, plus
liveness/readiness. No job queue, no async API: the MVP stays small.

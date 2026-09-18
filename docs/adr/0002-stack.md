# ADR 0002 — Stack

- Status: accepted
- Date: 2026-09-18

## Decision

- **API**: FastAPI + Pydantic v2 + Uvicorn.
- **MCP**: Python MCP SDK (FastMCP).
- **Packaging**: `uv` workspace.
- **Tests**: pytest with `unit` / `integration` markers.
- **Lint/format**: ruff. **Types**: mypy.
- **Model runtime**: `timesfm[torch]` (CPU), installed as an optional extra
  (`precog-api[engine]`) so the base install and CI do not need torch.

## Consequences

- The API can start with `PRECOG_ENGINE=fake` without torch, which keeps CI
  fast and lets contributors work on the HTTP layer in isolation.
- Real inference lives behind `TimesFM3Engine`, imported lazily.
- Python 3.12 is the target runtime.

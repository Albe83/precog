# Python SDK

`packages/sdk-python` provides typed synchronous and asynchronous clients for the
Precog Execution API. Both clients use the canonical `precog_schemas` wire
models and the same typed error hierarchy.

The Python distribution is intentionally an **execution-plane SDK**:

- it calls `POST /v1/forecast` and `GET /v1/capabilities`;
- it does not expose the MCP semantic contract;
- it does not expose TimesFM-specific evaluator controls;
- backend/runtime details remain behind the execution API and Engine boundary.

## Package boundary

The distributable Python surface is split into two packages:

- `precog-client`: sync/async HTTP clients, retry/error handling and CLI;
- `precog-schemas`: canonical Pydantic request/response and capability DTOs.

The schema package is a real distribution dependency of the client rather than
workspace-only implementation detail. The two packages use one synchronized
Python-package version and are built/published together.

This package version is independent from the Precog application/Helm release
version. Application releases therefore do not implicitly publish Python
packages.

## Install

After a manual Python-package release:

```bash
pip install precog-client
```

From this repository:

```bash
uv sync --all-packages --system-certs
# or build/install the local packages explicitly:
uv pip install ./packages/schemas ./packages/sdk-python
```

ADR 0003 permits publication because both Python packages contain MIT-licensed
code only and no TimesFM model weights.

## Quickstart

```python
from precog_client import PrecogClient

with PrecogClient("http://localhost:8000") as client:
    capabilities = client.capabilities()
    print(capabilities.model.id, capabilities.limits.max_horizon)

    response = client.forecast(
        horizon=4,
        targets=[{"id": "sales", "values": [100, 102, 101, 105, 107, 106, 108, 109]}],
        quantiles=[0.1, 0.5, 0.9],
    )
    print(response.targets[0].forecast)
    print(response.targets[0].quantiles)
```

Multiple targets are forecast jointly; covariates are request-level:

```python
response = client.forecast(
    horizon=3,
    targets=[
        {"id": "brand_a", "values": [100, 102, 101, 105, 107, 106]},
        {"id": "brand_b", "values": [80, 81, 80, 83, 85, 84]},
    ],
    past_covariates=[{"id": "footfall", "values": [0.1, 0.2, 0.15, 0.3, 0.4, 0.35]}],
    known_future_covariates=[
        # history matches the context length; future matches the horizon
        {"id": "promo", "history": [0, 1, 0, 0, 0, 1], "future": [0, 1, 0]}
    ],
    quantiles=[0.1, 0.9],
)

# Point-only forecast
point = client.forecast(
    horizon=3,
    targets=[{"id": "kiosk", "values": [50, 52, 51, 53, 55, 54, 56]}],
)
```

You can also send an already-built `ForecastRequest` with
`client.forecast_request(request)`.

## Async client

`AsyncPrecogClient` mirrors `PrecogClient` (`forecast`,
`forecast_request`, `capabilities`) with the same request models,
retry/backoff behavior and typed errors.

```python
import asyncio

from precog_client import AsyncPrecogClient


async def main() -> None:
    async with AsyncPrecogClient("http://localhost:8000") as client:
        response = await client.forecast(
            horizon=4,
            targets=[{"id": "sales", "values": [100, 102, 101, 105, 107, 106, 108, 109]}],
            quantiles=[0.1, 0.9],
        )
        print(response.targets[0].forecast)


asyncio.run(main())
```

## Auth and tuning

```python
client = PrecogClient(
    "http://localhost:8000",
    api_key="secret",  # sent as Authorization: Bearer
    timeout=300.0,
    max_retries=2,  # retries 429/5xx and transport errors with backoff
    backoff_factor=0.5,
)
```

## CLI

The package installs a `precog` command:

```bash
precog --url http://localhost:8000 capabilities
precog --url http://localhost:8000 forecast --file request.json
precog --url http://localhost:8000 forecast --csv series.csv --horizon 24 --id sales --quantiles 0.1,0.9
```

`--file` takes a full `ForecastRequest` JSON payload; `--csv` takes a
single-column CSV (header optional) and builds a single-target request (point
forecast unless `--quantiles` is given). Output is the API response as JSON.

## Errors

All exceptions derive from `PrecogError`:

| Exception | When |
| --------- | ---- |
| `PrecogValidationError` | payload rejected locally before the request |
| `PrecogConnectionError` | API unreachable |
| `PrecogTimeoutError` | request timed out |
| `PrecogAPIError` | API returned an HTTP error (`status_code`, `title`, `detail`) |

## Package validation and publication

`.github/workflows/python-packages.yml` validates the distributable boundary on
pull requests and relevant pushes:

1. `precog-client` and `precog-schemas` must have the same package version;
2. wheel and sdist artifacts are built for both packages;
3. archive contents are checked for model/cache payloads;
4. the built wheels are installed into a clean virtual environment and imported.

Publication is deliberately separate from normal application releases. It is
available only through an explicit `workflow_dispatch` run on `main` with
`publish=true`, using PyPI Trusted Publishing and the protected `pypi`
environment. The workflow publishes `precog-schemas` first and
`precog-client` second.

Before the first publication, configure a PyPI Trusted Publisher (or pending
publisher) for both projects against this repository, the
`python-packages.yml` workflow and the `pypi` environment.

## Real contract test

The real SDK gate boots the Precog ASGI application in-process with the cached
TimesFM-3 engine and drives it through both sync and async clients. It does not
require an externally running `PRECOG_API_URL`.

```bash
PRECOG_CACHE_DIR=/path/to/models \
  uv run pytest -m integration -q packages/sdk-python/tests/test_integration.py
```

## TypeScript SDK

A TypeScript client (`@precog/sdk`) lives in `packages/sdk-ts` (Node 18+ and
browsers, `fetch`-based) with the same execution `forecast`/`capabilities`
surface; see `packages/sdk-ts/README.md`.

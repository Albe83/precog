# Python SDK

`packages/sdk-python` provides typed synchronous and asynchronous clients for the
Precog execution API. They share the `precog_schemas` models and the typed error
classes.

## Install (from this repository)

```bash
uv sync --all-packages --system-certs      # installs precog-client into the workspace venv
# or, standalone:
uv pip install ./packages/sdk-python
```

Publishing to a package index is intentionally not wired up yet (source-only
release policy, see `THIRD_PARTY_NOTICES.md`).

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

`AsyncPrecogClient` mirrors `PrecogClient` (`forecast`, `forecast_request`,
`capabilities`) with the same request models, retry/backoff and typed errors.

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
| `PrecogAPIError` | API returned RFC 7807 error (`status_code`, `title`, `detail`) |

## Contract test

The SDK is validated against a running API:

```bash
PRECOG_API_URL=http://127.0.0.1:8000 \
  pytest packages/sdk-python/tests/test_integration.py -m integration
```

## TypeScript SDK

A TypeScript client (`@precog/sdk`) lives in `packages/sdk-ts` (Node 18+ and
browsers, `fetch`-based) with the same `forecast`/`capabilities` surface; see
`packages/sdk-ts/README.md`.

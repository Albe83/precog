# Python SDK

`packages/sdk-python` provides a synchronous, typed client for the Precog REST
API. It reuses the shared Pydantic models from `packages/schemas`.

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
    print(capabilities.max_horizon, capabilities.modes)

    response = client.forecast(
        mode="univariate",
        horizon=4,
        series=[{"id": "sales", "target": [100, 102, 101, 105, 107, 106, 108, 109]}],
    )
    print(response.results[0].forecast)
    print(response.quantile_levels)
```

Multivariate and covariates:

```python
response = client.forecast(
    mode="multivariate",
    horizon=3,
    series=[
        {"id": "a", "target": [10, 11, 12, 13, 14]},
        {"id": "b", "target": [20, 21, 22, 23, 24]},
    ],
)

response = client.forecast(
    mode="univariate",
    horizon=3,
    series=[
        {
            "id": "kiosk",
            "target": [50, 52, 51, 53, 55, 54, 56],
            "past_covariates": {"footfall": [0.1, 0.2, 0.15, 0.3, 0.4, 0.35, 0.5]},
            "future_covariates": {"promo": [0, 1, 0, 1, 0, 0, 0, 1, 0, 1]},  # context + horizon
        }
    ],
)

# Multivariate with request-level covariates (shared across the target variates)
response = client.forecast(
    mode="multivariate",
    horizon=3,
    series=[
        {"id": "brand_a", "target": [100, 102, 101, 105, 107, 106]},
        {"id": "brand_b", "target": [80, 81, 80, 83, 85, 84]},
    ],
    past_covariates={"footfall": [0.1, 0.2, 0.15, 0.3, 0.4, 0.35]},
    future_covariates={"promo": [0, 1, 0, 0, 0, 1, 0, 1, 0]},
)
```

You can also send an already-built `ForecastRequest` with
`client.forecast_request(request)`.

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
precog --url http://localhost:8000 forecast --csv series.csv --horizon 24 --id sales
```

`--file` takes a full `ForecastRequest` JSON payload; `--csv` takes a
single-column CSV (header optional) for a univariate series. Output is the API
response as JSON.

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

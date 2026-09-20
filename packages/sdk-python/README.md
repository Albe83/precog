# precog-client

Typed synchronous and asynchronous Python clients for the Precog Execution API.

The SDK is an execution-plane client. It speaks the canonical `/v1/forecast`
and `/v1/capabilities` contracts defined by Precog; it does not expose MCP
semantic tools or TimesFM-specific execution knobs.

## Install

After a manual Python-package release:

```bash
pip install precog-client
```

For development from the repository:

```bash
uv sync --all-packages
```

`precog-client` depends on the separately packaged `precog-schemas` wire
models. The two Python packages use one synchronized package version and are
built and published together, independently from the Precog application/Helm
release version.

## Sync client

```python
from precog_client import PrecogClient

with PrecogClient("http://localhost:8000") as client:
    response = client.forecast(
        horizon=3,
        targets=[{"id": "sales", "values": [10, 11, 12, 13, 14]}],
        quantiles=[0.1, 0.5, 0.9],
    )
    print(response.targets[0].forecast)
```

## Async client

```python
from precog_client import AsyncPrecogClient

async with AsyncPrecogClient("http://localhost:8000") as client:
    response = await client.forecast(
        horizon=3,
        targets=[{"id": "sales", "values": [10, 11, 12, 13, 14]}],
        quantiles=[0.1, 0.9],
    )
```

Both clients share the same request/response models, retry behavior and typed
error hierarchy.

See `docs/sdk.md` in the repository for the complete contract and examples.

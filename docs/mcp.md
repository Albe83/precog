# MCP server

`apps/mcp` exposes Precog forecasts as an MCP tool. It talks to the REST API
over HTTP and contains no model weights.

> **Breaking change (MCP only).** The `forecast` and `forecast_batch` tools use
> a new consumer-facing contract. The REST API (`POST /v1/forecast`), the shared
> `precog_schemas` models and the Python/TypeScript SDKs are unchanged; only the
> MCP surface moved to the model-independent contract below.

## What Precog does and does not do

The MCP consumer is responsible for its own data. Before calling `forecast`, it
must fetch, clean, resample and align the series, understand units and
timestamps, and decide which series are targets and which are covariates.

Precog does **not**:

- fetch source data or understand Prometheus, SQL, CSV, etc.;
- resample, interpolate missing values or infer a sampling frequency;
- interpret units or timestamps;
- truncate, reorder or otherwise clean the values it receives.

If the input is invalid the request fails. Precog never silently changes the
data. All series must already be equally sampled, time-aligned and ordered from
oldest to newest.

## Tool: `forecast`

Forecast future values for one or more related numeric time series.

| Argument | Type | Required | Notes |
| -------- | ---- | -------- | ----- |
| `targets` | array of `{id, values}` | yes | Series to forecast jointly, each `values` oldest → newest |
| `horizon` | integer ≥ 1 | yes | Number of future steps using the input sampling interval |
| `past_covariates` | array of `{id, values}` | no | Known only during the historical context |
| `known_future_covariates` | array of `{id, history, future}` | no | Historical values plus already-known future values |
| `quantiles` | array of levels from `0.1`…`0.9` | no | Default `[0.1, 0.9]`; `[]` returns no quantiles |

`horizon` is expressed in steps: with one sample every 5 minutes, `horizon: 12`
means the next hour. Precog does not need to know the sampling interval.

Multiple `targets` are forecast **jointly** and must represent related series on
the same timeline. Unrelated forecasting problems require separate calls (or
separate items in `forecast_batch`).

### Historical-only vs known-future covariates

`past_covariates` are available only before the forecast boundary; each series
length must equal the target context length.

```
TARGET          ------------------------|????????
PAST COVARIATE  ------------------------|
```

`known_future_covariates` carry both the history and the already-known future
values, so they are intentionally split into two arrays. `history` must equal
the target context length and `future` must equal `horizon`.

```
TARGET                  ------------------------|????????????
KNOWN FUTURE COVARIATE  ------------------------|-------------
                             history           |   future
```

Precog internally concatenates `history + future` when talking to the current
backend; that representation is never exposed.

### Validation rules

- At least one target is required; IDs must be non-empty and globally unique
  across targets and both covariate collections.
- All target histories must have the same length.
- Each `past_covariates[].values` must equal the target context length.
- Each `known_future_covariates[].history` must equal the target context length
  and each `.future` must equal `horizon`.
- Every value must be a finite number. `null`, `NaN` and `±Infinity` are
  rejected. No interpolation or truncation is performed.
- `quantiles` must be unique levels from `0.1`…`0.9`; the caller order is
  preserved. An empty list means “return no probabilistic quantiles”.

### Result

A successful call returns MCP structured content:

```json
{
  "horizon": 3,
  "targets": [
    {
      "id": "cpu_usage",
      "forecast": [45.2, 47.8, 48.1],
      "quantiles": {
        "0.1": [41.3, 42.1, 41.8],
        "0.9": [49.7, 54.2, 57.6]
      }
    }
  ],
  "model": { "id": "timesfm-3.0" },
  "warnings": []
}
```

- `forecast` is the Precog point forecast and has stable Precog semantics. For
  the current TimesFM-3 backend it is the median (`q0.5`), independent of which
  quantiles were requested.
- `quantiles` is a map from quantile level to forecast vector, keyed by
  canonical decimal strings.
- `model` reports the forecasting engine actually used.
- `warnings` lists non-fatal conditions. It does not hide destructive or
  semantic changes to the input; invalid input fails instead.

## Tool: `forecast_batch`

Forecast several **independent** requests in one call. Each item in `requests`
is a complete `forecast` request. Related series that must be forecast jointly
belong together as multiple `targets` inside a single request, never as separate
batch items.

Each result carries a stable zero-based `index` and preserves input order:

```json
{
  "results": [
    { "index": 0, "ok": true, "result": { "horizon": 2, "targets": [], "model": { "id": "timesfm-3.0" }, "warnings": [] } },
    { "index": 1, "ok": false, "error": { "code": "FORECAST_REJECTED", "message": "horizon 2 exceeds max 1" } }
  ]
}
```

A valid batch with one or more per-item forecast failures is still a successful
call (`isError=false`); failed items use the typed failure variant and do not
cancel their siblings. An empty or oversized batch fails the whole tool call.

Batch size and concurrency are bounded by `PRECOG_MCP_BATCH_MAX` (default 32)
and `PRECOG_MCP_BATCH_CONCURRENCY` (default 4).

## Errors

Invalid requests and inference failures are real MCP tool errors
(`isError=true`), never a nominal result containing an `error` field. The error
content is a deterministic JSON envelope:

```json
{
  "code": "INVALID_REQUEST",
  "message": "invalid forecast request",
  "details": {
    "errors": [
      { "loc": [], "msg": "Value error, past covariate 'p' must match the target context (1 != 3)", "type": "value_error" }
    ]
  }
}
```

Stable codes:

| Code | Meaning |
| ---- | ------- |
| `INVALID_REQUEST` | Schema or cross-field validation failure (including removed/unknown fields) |
| `FORECAST_REJECTED` | The REST API rejected the request (validation or configured limits) |
| `API_UNAVAILABLE` | The Precog API is unreachable or timed out |
| `UPSTREAM_CONTRACT_ERROR` | The API returned a malformed or inconsistent success response |
| `INFERENCE_FAILED` | The API reported an inference/server failure |
| `INTERNAL_ERROR` | The MCP server hit an unexpected internal defect; details stay in logs |

`INVALID_REQUEST` also covers removed `forecast` fields: passing `mode`,
`series`, `return_quantiles`, request-level covariate maps or any other unknown
field is rejected.

Error messages are sanitized: only intentional Precog problem-details are
forwarded. An arbitrary or non-JSON upstream response body is never exposed to
the agent, and unexpected failures never leak tracebacks, internal URLs or
hostnames.

## Examples

### One target, no covariates

```json
{
  "targets": [{ "id": "cpu_usage", "values": [31.2, 32.8, 35.1, 37.4, 41.2, 43.7] }],
  "horizon": 3
}
```

### Multiple related targets with both covariate types

```json
{
  "targets": [
    { "id": "cpu_usage", "values": [31.2, 32.8, 35.1, 37.4, 41.2, 43.7] },
    { "id": "memory_usage", "values": [61.0, 61.4, 62.1, 63.0, 64.8, 65.1] }
  ],
  "horizon": 3,
  "past_covariates": [
    { "id": "request_rate", "values": [1200, 1250, 1410, 1530, 1710, 1800] }
  ],
  "known_future_covariates": [
    { "id": "maintenance_window", "history": [0, 0, 0, 0, 0, 0], "future": [0, 1, 1] }
  ],
  "quantiles": [0.1, 0.9]
}
```

### Successful structured result

See the `forecast` result example above.

### Invalid length request and structured error

Calling `forecast` with a `past_covariates` series shorter than the target
context returns:

```json
{
  "code": "INVALID_REQUEST",
  "message": "invalid forecast request",
  "details": {
    "errors": [
      { "loc": [], "msg": "Value error, past covariate 'request_rate' must match the target context (5 != 6)", "type": "value_error" }
    ]
  }
}
```

### Independent batch with one failed item

```json
{
  "requests": [
    { "targets": [{ "id": "cpu_usage", "values": [31.2, 32.8, 35.1, 37.4, 41.2, 43.7] }], "horizon": 2 },
    { "targets": [{ "id": "disk_usage", "values": [10.0, 10.4, 10.9, 11.2, 11.5, 12.0] }], "horizon": 99999 }
  ]
}
```

The second item is rejected by the API limit and appears as an `ok: false` item
with `FORECAST_REJECTED`; the first item is unaffected.

## Migrating from the old MCP contract

| Removed / old | New |
| ------------- | --- |
| `mode` | removed; multiple `targets` imply joint forecasting |
| `series[].target` | `targets[].values` |
| per-series / request-level covariate maps | top-level `past_covariates[]` / `known_future_covariates[]` |
| combined future covariate values (`context + horizon`) | `known_future_covariates[].history` + `.future` |
| `return_quantiles` | `quantiles` (requested levels) |
| `results[]` + `quantile_levels` | `targets[].forecast` + `targets[].quantiles[level]` |
| nominal `{ "error": ... }` | MCP tool errors; typed per-item errors only inside a successful batch |

This change is MCP-only. The REST request/response shapes and the SDKs keep
their current contract.

## Run locally (stdio)

```bash
# 1) Start the API (see docs/deploy.md or: PRECOG_ENGINE=fake uv run precog-api)
# 2) Run the MCP server, pointing at the API
PRECOG_API_URL=http://localhost:8000 uv run --no-sync precog-mcp
```

## Run over HTTP

```bash
PRECOG_MCP_TRANSPORT=http PRECOG_MCP_PORT=8765 \
PRECOG_API_URL=http://localhost:8000 uv run --no-sync precog-mcp
# MCP endpoint: http://localhost:8765/mcp
```

### Host validation (running behind a gateway)

The HTTP transport enables DNS-rebinding protection by default and only accepts
`localhost` / `127.0.0.1` / `[::1]` hosts. Behind a gateway that reaches the
server through a Service or DNS name (for example agentgateway in Kubernetes),
configure the allowed hosts or disable the check:

```bash
# add specific hosts
PRECOG_MCP_ALLOWED_HOSTS="precog-mcp.cortana-mcp-servers.svc:8000,mcp-cortana.gewiss.ai"

# or disable it entirely (only where the listener is reachable exclusively
# through a trusted gateway + NetworkPolicy, since there is no auth on the
# MCP listener itself)
PRECOG_MCP_ALLOWED_HOSTS="*"
```

## Client configuration

Claude Desktop / Cursor / opencode (stdio):

```json
{
  "mcpServers": {
    "precog": {
      "command": "precog-mcp",
      "env": { "PRECOG_API_URL": "http://localhost:8000" }
    }
  }
}
```

With API auth enabled, also set `PRECOG_API_KEY`.

## Container

```bash
podman build --format docker -f Dockerfile.mcp -t precog-mcp:local .
podman run --rm -p 8765:8765 -e PRECOG_API_URL=http://host.docker.internal:8000 precog-mcp:local
```

## Metrics

The HTTP transport exposes Prometheus metrics on `/metrics`
(`precog_mcp_tool_calls_total{tool,status}` and
`precog_mcp_tool_duration_seconds{tool}`). A tool-level failure increments the
`error` status; per-item failures inside a successful batch do not.

The Helm chart can deploy it next to the API with `--set mcp.enabled=true`.

# MCP server

`apps/mcp` exposes Precog forecasting as MCP tools and a semantic capabilities
resource. It talks to the REST API over HTTP through the official
`AsyncPrecogClient` from the Python SDK and contains no model weights.

The architectural role of the MCP server — the agent-facing semantic interface,
with the REST API as its execution dependency — is recorded in
[ADR 0005](adr/0005-mcp-semantic-boundary.md).

> **Execution API cutover.** The REST execution API now uses the canonical
> contract from ADR 0006 (`targets` / `past_covariates` /
> `known_future_covariates` / explicit `quantiles`). The MCP public tool
> contract below is unchanged; only the adapter mapping is simpler.

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
the same timeline. Unrelated forecasting problems require separate `forecast`
calls; the MCP server intentionally does not expose a batch tool.

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

## Tool: `backtest`

Retrospectively evaluate a Precog forecast against a held-out tail of the
provided history. This is a single window, not a rolling or walk-forward
backtest.

| Argument | Type | Required | Notes |
| -------- | ---- | -------- | ----- |
| `targets` | array of `{id, values}` | yes | Complete historical series; the last `horizon` values are held out |
| `horizon` | integer ≥ 1 | yes | Number of holdout steps and forecast steps |
| `past_covariates` | array of `{id, values}` | no | Full-timeline series; only the context segment is used |
| `known_future_covariates` | array of `{id, values}` | no | Full-timeline series; the holdout segment is used as known-future input |
| `quantiles` | array of levels from `0.1`…`0.9` | no | Default `[0.1, 0.9]`; used for interval coverage (and not otherwise returned) |

### Holdout split

`backtest` takes the **complete** historical series. Precog holds out the last
`horizon` values of every target and forecasts the preceding context through the
same semantic path used by `forecast`:

```
full historical target
┌────────────────────────────┬──────────┐
│          context           │ holdout  │
└────────────────────────────┴──────────┘
                             ← horizon →
```

`len(targets[].values)` must be strictly greater than `horizon` so the remaining
context is valid for a normal forecast. All targets must share the same full
length.

### Covariates and the holdout cutoff

Covariates are aligned to the **full** target timeline (the same length as
`targets[].values`) and are split at the same cutoff:

- `past_covariates`: only the context segment is used; the holdout segment is
  ignored.
- `known_future_covariates`: the context segment becomes history and the holdout
  segment becomes the already-known future values.

```
TARGET                  ------------------------|----------
PAST COVARIATE          ------------------------|..........  (holdout ignored)
KNOWN FUTURE COVARIATE  ------------------------|----------  (holdout used as future)
                             context           |  holdout
```

**Anti-leakage is the caller's responsibility.** A covariate presented as
known-future must genuinely have been known at the forecast cutoff. Precog
assumes it and does not verify or infer that fact. Feeding holdout information as
“known future” when it would not have been known produces an optimistic backtest.

### Metrics

For each target the result contains the held-out `actual` values, the `forecast`
for the same steps, and objective metrics in the target's units:

- **MAE** — mean absolute error: `mean(|actual - forecast|)`.
- **RMSE** — root mean squared error: `sqrt(mean((actual - forecast)²))`.
- **sMAPE** — symmetric mean absolute percentage error:
  `100 / n · Σ 2·|actual - forecast| / (|actual| + |forecast|)`, where a term with
  `|actual| + |forecast| = 0` contributes `0`. The value is a percentage in
  `[0, 200]`.

When the requested quantiles bracket the median (at least one level `< 0.5` and
one `> 0.5`), the result also reports `coverage` for the widest such interval:
the percentage of holdout steps whose actual value lies inside
`[lower_quantile, upper_quantile]`. With the default `[0.1, 0.9]` that is the
empirical 80% interval coverage of this single window. It is a measurement, not a
calibration guarantee.

### Backtest result

```json
{
  "horizon": 3,
  "targets": [
    {
      "id": "cpu_usage",
      "actual": [45.2, 47.8, 48.1],
      "forecast": [44.9, 46.5, 47.2],
      "metrics": {
        "mae": 0.9,
        "rmse": 1.03,
        "smape": 2.0,
        "coverage": {
          "lower_quantile": 0.1,
          "upper_quantile": 0.9,
          "percent": 66.66666666666666
        }
      }
    }
  ],
  "model": { "id": "timesfm-3.0" },
  "warnings": []
}
```

`coverage` is `null` when the requested quantiles do not identify both a lower
and an upper side of the median (for example `quantiles: []` or `[0.5]`).

### Backtest validation rules

- At least one target; every `targets[].values` must be longer than `horizon`.
- All targets must share the same full length.
- Every `past_covariates[].values` and `known_future_covariates[].values` must be
  aligned to the full target timeline.
- IDs must be globally unique across targets and covariates.
- Finite-value and quantile rules are identical to `forecast`.

Invalid requests fail with the same stable error envelope. A backend capability
rejection (for example a context longer than the model supports) maps to
`FORECAST_REJECTED`; failures are never returned as a successful result
containing nominal error fields.

### Backtest example

```json
{
  "targets": [
    { "id": "cpu_usage", "values": [31.2, 32.8, 35.1, 37.4, 41.2, 43.7, 45.2, 47.8, 48.1] }
  ],
  "horizon": 3,
  "past_covariates": [
    { "id": "request_rate", "values": [1200, 1250, 1410, 1530, 1710, 1800, 1850, 1900, 1950] }
  ],
  "known_future_covariates": [
    { "id": "maintenance_window", "values": [0, 0, 0, 0, 0, 0, 0, 1, 1] }
  ],
  "quantiles": [0.1, 0.9]
}
```

Here the last three target values are the holdout, the last three
`request_rate` values are ignored, and `maintenance_window`'s last three values
are forwarded as known-future inputs.

## Resource: `precog://capabilities`

The server exposes one MCP resource, `precog://capabilities`
(`application/json`), describing the **semantic** capabilities of this MCP
server: which operations an agent can ask for and which Precog-level limits
apply. It is intended for discovery before the first call.

This is deliberately **not** a mirror of the REST `GET /v1/capabilities`
endpoint. The MCP resource translates the execution API's information into the
semantic contract and drops backend/execution fields (engine, device, model
identifier, per-forward-pass variate budget, execution feature flags, ...). A
backend concept is published here only when it is a meaningful Precog-level
constraint for the caller.

### Schema

| Field | Type | Meaning |
| ----- | ---- | ------- |
| `forecast.supported` | boolean | The `forecast` tool is available |
| `forecast.multiple_targets` | boolean | Multiple targets are forecast jointly |
| `forecast.past_covariates` | boolean | Historical-only covariates are supported |
| `forecast.known_future_covariates` | boolean | Already-known future covariates are supported |
| `forecast.probabilistic_forecast` | boolean | Quantiles can be requested |
| `backtest.supported` | boolean | The `backtest` tool is available |
| `backtest.metrics` | array of strings | Metrics returned per target |
| `backtest.interval_coverage` | boolean | Outer-interval coverage can be returned |
| `limits.max_horizon` | integer or `null` | Maximum `horizon` in steps |
| `limits.max_context_length` | integer or `null` | Maximum accepted context length per series |
| `limits.quantile_levels` | array of numbers | Quantile levels accepted by the MCP semantic contract |

Only limits that are meaningful to the caller as Precog-level constraints are
advertised. Combinatory execution limits (targets plus covariates per forward
pass) are intentionally not exposed; a request that exceeds the effective
backend capability fails with `FORECAST_REJECTED` rather than being silently
adapted.

### Limits availability

The semantic capability flags and the supported quantile levels are part of the
MCP contract and are always present; they are never overridden by the execution
API, so the resource cannot advertise quantiles that `forecast`/`backtest`
would reject. `max_horizon` and `max_context_length` are derived from the
execution API's effective limits. If the API cannot be consulted, the resource
still succeeds and returns `null` for those two fields: the caller then
discovers limits through stable tool errors (`FORECAST_REJECTED`) instead of
assuming a value. The resource never returns raw upstream error bodies or
infrastructure details.

### Example response

```json
{
  "forecast": {
    "supported": true,
    "multiple_targets": true,
    "past_covariates": true,
    "known_future_covariates": true,
    "probabilistic_forecast": true
  },
  "backtest": {
    "supported": true,
    "metrics": ["mae", "rmse", "smape"],
    "interval_coverage": true
  },
  "limits": {
    "max_horizon": 1024,
    "max_context_length": 15360,
    "quantile_levels": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
  }
}
```

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

### Independent problems

Independent forecasting problems use independent `forecast` calls. The MCP
client or harness can parallelize those calls. Do not pack unrelated series into
one request: every `targets` entry in a request is forecast jointly.

## Migrating from the old MCP contract

| Removed / old | New |
| ------------- | --- |
| `mode` | removed; multiple `targets` imply joint forecasting |
| `series[].target` | `targets[].values` |
| per-series / request-level covariate maps | top-level `past_covariates[]` / `known_future_covariates[]` |
| combined future covariate values (`context + horizon`) | `known_future_covariates[].history` + `.future` |
| `return_quantiles` | `quantiles` (requested levels) |
| `results[]` + `quantile_levels` | `targets[].forecast` + `targets[].quantiles[level]` |
| nominal `{ "error": ... }` | MCP tool errors with stable codes |
| `forecast_batch` tool | removed; use separate `forecast` calls |

This migration was MCP-only at the time. The REST execution API has since been
cut over to the same canonical shape (ADR 0006 / #178); the MCP contract above
is unchanged, and the adapter now maps it structurally onto the execution API.

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
`error` status.

The Helm chart can deploy it next to the API with `--set mcp.enabled=true`.

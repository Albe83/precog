# MCP server

`apps/mcp` exposes Precog forecasts as an MCP tool. It talks to the REST API
over HTTP and contains no model weights.

## Tool: `forecast`

| Argument | Type | Notes |
| -------- | ---- | ----- |
| `mode` | `"univariate" \| "multivariate"` | Each series independently, or targets jointly |
| `horizon` | int | Number of steps to forecast |
| `series` | list of objects | `id`, `target` (floats), optional `past_covariates` / `future_covariates` |
| `return_quantiles` | bool | Include the 9 quantiles (default `true`) |
| `past_covariates` | object | Request-level past covariates (multivariate mode only) |
| `future_covariates` | object | Request-level future covariates (multivariate mode only) |

Returns the API response (`results[].forecast`, `results[].quantiles`,
`quantile_levels`, `usage`) or `{"error": ...}` on failure.

## Tool: `forecast_batch`

Forecast several requests in one call.

| Argument | Type | Notes |
| -------- | ---- | ----- |
| `requests` | list of objects | Each object takes the `forecast` arguments |

Returns `{"count": N, "results": [...]}` preserving order; each result is a
forecast object or `{"error": ...}`. Batch size and concurrency are bounded by
`PRECOG_MCP_BATCH_MAX` (default 32) and `PRECOG_MCP_BATCH_CONCURRENCY`
(default 4).

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
`precog_mcp_tool_duration_seconds{tool}`).

The Helm chart can deploy it next to the API with `--set mcp.enabled=true`.

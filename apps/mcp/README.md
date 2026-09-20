# precog-mcp

MCP server exposing Precog zero-shot forecasting to agents as the semantic
`forecast` and `backtest` tools plus the `precog://capabilities` resource.

It talks to the Precog **REST Execution API** over HTTP through the official
`precog-client` and contains **no model weights**.

## Install

```bash
pip install precog-mcp
```

## Run

```bash
# stdio transport
PRECOG_API_URL=http://localhost:8000 precog-mcp

# HTTP transport (endpoint: http://localhost:8765/mcp)
PRECOG_MCP_TRANSPORT=http PRECOG_MCP_PORT=8765 \
  PRECOG_API_URL=http://localhost:8000 precog-mcp
```

The API must be reachable; see `precog-api` or the container/Helm deployment.

## License

MIT.

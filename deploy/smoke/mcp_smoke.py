"""Generic MCP-client smoke test for a published ``precog-mcp`` server.

Black-box check: it uses only the public MCP Python client (``mcp``) and the
streamable HTTP transport. It never imports Precog MCP source code, so it
verifies the shipped container, not the checkout.

    python mcp_smoke.py --url http://127.0.0.1:8765/mcp

Exits non-zero on the first failed expectation.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

FORECAST_ARGS = {
    "targets": [{"id": "smoke", "values": [10.0 + index for index in range(24)]}],
    "horizon": 4,
    "quantiles": [0.1, 0.9],
}

EXECUTION_ONLY_FIELDS = ("engine", "device", "max_variates")


async def _run(url: str) -> None:
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"forecast", "backtest"} <= names, f"tools missing: {names}"

            resources = await session.list_resources()
            uris = {str(resource.uri) for resource in resources.resources}
            assert "precog://capabilities" in uris, f"resource missing: {uris}"

            capabilities = await session.read_resource("precog://capabilities")
            payload = json.loads(capabilities.contents[0].text)
            assert payload["forecast"]["supported"] is True, payload
            blob = json.dumps(payload).lower()
            leaked = [field for field in EXECUTION_ONLY_FIELDS if field in blob]
            assert not leaked, f"semantic capabilities leak execution fields: {leaked}"

            result = await session.call_tool("forecast", FORECAST_ARGS)
            assert not result.is_error, result
            structured = result.structured_content
            if structured is None:
                structured = json.loads(result.content[0].text)
            target = structured["targets"][0]
            assert len(target["forecast"]) == FORECAST_ARGS["horizon"], target
            assert target["quantiles"], target

    print("MCP smoke OK: tools, capabilities resource and a forecast call")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="MCP streamable HTTP endpoint")
    args = parser.parse_args()
    asyncio.run(_run(args.url))


if __name__ == "__main__":
    main()

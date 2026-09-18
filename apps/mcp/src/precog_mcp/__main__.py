"""Entry point for the Precog MCP server."""

from __future__ import annotations

from precog_mcp.config import Settings
from precog_mcp.server import create_server


def main() -> None:
    settings = Settings()
    server = create_server(settings)
    if settings.mcp_transport == "http":
        import uvicorn

        uvicorn.run(
            server.streamable_http_app(),
            host=settings.mcp_host,
            port=settings.mcp_port,
        )
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()

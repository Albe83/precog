"""Entry point for the Precog MCP server."""

from __future__ import annotations

from precog_mcp.config import Settings
from precog_mcp.server import create_server

DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]


def transport_security(allowed_hosts: str):
    """Build the HTTP transport security settings from ``PRECOG_MCP_ALLOWED_HOSTS``.

    - ``"*"`` disables DNS-rebinding protection (use only where the listener is
      reachable exclusively through a trusted gateway).
    - a comma-separated list adds hosts to the localhost defaults.
    - empty keeps the secure localhost-only default.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    entries = [host.strip() for host in allowed_hosts.split(",") if host.strip()]
    if "*" in entries:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(allowed_hosts=[*DEFAULT_ALLOWED_HOSTS, *entries])


def main() -> None:
    settings = Settings()
    server = create_server(settings)
    if settings.mcp_transport == "http":
        import uvicorn

        app = server.streamable_http_app(
            transport_security=transport_security(settings.mcp_allowed_hosts)
        )
        uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()

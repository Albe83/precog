"""Configuration for the Precog MCP server."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from ``PRECOG_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="PRECOG_", env_file=".env", extra="ignore")

    api_url: str = "http://localhost:8000"
    api_key: str | None = None
    request_timeout_s: float = 300.0

    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8765
    # Comma-separated allowed Host headers for the HTTP transport. Use "*" to
    # disable DNS-rebinding protection entirely (needed behind a gateway such as
    # agentgateway, where the Host is the Service/DNS name, not localhost).
    mcp_allowed_hosts: str = ""
    mcp_batch_max: int = 32
    mcp_batch_concurrency: int = 4

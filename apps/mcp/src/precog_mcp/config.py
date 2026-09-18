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

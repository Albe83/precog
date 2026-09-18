"""Runtime configuration, loaded from ``PRECOG_*`` environment variables."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API settings.

    Every field can be overridden with a ``PRECOG_``-prefixed env var, e.g.
    ``PRECOG_MAX_HORIZON=512``.
    """

    model_config = SettingsConfigDict(env_prefix="PRECOG_", env_file=".env", extra="ignore")

    engine: Literal["fake", "timesfm3"] = "timesfm3"
    device: str = "cpu"
    model_path: str = "/opt/precog/models"
    model_id: str = "google/timesfm-3.0-pytorch"
    per_core_batch_size: int = 16
    torch_threads: int = 0
    max_concurrency: int = 1
    request_timeout_s: float = 300.0
    api_key: str | None = None
    enable_docs: bool = True

    max_horizon: int = 1024
    max_context: int = 16384
    max_series: int = 64

    @property
    def model_name(self) -> str:
        return "timesfm-3.0"

"""Synchronous Python client for the Precog REST API."""

from precog_client.client import PrecogClient
from precog_client.errors import (
    PrecogAPIError,
    PrecogConnectionError,
    PrecogError,
    PrecogTimeoutError,
    PrecogValidationError,
)

__all__ = [
    "PrecogAPIError",
    "PrecogClient",
    "PrecogConnectionError",
    "PrecogError",
    "PrecogTimeoutError",
    "PrecogValidationError",
]

"""Typed errors raised by the Precog client."""

from __future__ import annotations

from typing import Any


class PrecogError(Exception):
    """Base class for all client errors."""


class PrecogConnectionError(PrecogError):
    """The API could not be reached."""


class PrecogTimeoutError(PrecogError):
    """The request timed out."""


class PrecogValidationError(PrecogError):
    """The request payload is invalid (rejected before calling the API)."""


class PrecogAPIError(PrecogError):
    """The API returned an error response (RFC 7807)."""

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.payload = payload or {}
        message = f"{status_code} {title}" + (f": {detail}" if detail else "")
        super().__init__(message)

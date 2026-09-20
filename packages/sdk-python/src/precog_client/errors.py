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
    """The API returned an error response (RFC 7807).

    ``media_type`` is the response content type without parameters, and
    ``payload`` is the parsed response body when it was a JSON object. Both are
    exposed so callers (e.g. the MCP boundary) can apply their own sanitization
    instead of trusting an arbitrary upstream body.
    """

    def __init__(
        self,
        status_code: int,
        title: str,
        detail: str | None = None,
        payload: dict[str, Any] | None = None,
        media_type: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.payload = payload or {}
        self.media_type = media_type
        message = f"{status_code} {title}" + (f": {detail}" if detail else "")
        super().__init__(message)

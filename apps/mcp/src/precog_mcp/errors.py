"""Stable, machine-readable MCP tool errors and boundary validation."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from mcp.server.context import CallNext, ServerRequestContext
from pydantic import ValidationError

from precog_mcp.adapter import ErrorCode, ForecastAdapterError

logger = logging.getLogger("precog.mcp")

INTERNAL_ERROR_MESSAGE = "Precog MCP encountered an unexpected internal error"

# Public argument names per tool, used to reject removed/unknown fields as
# additional properties even though the SDK's generated argument model ignores
# them by default.
_ALLOWED_ARGUMENTS: dict[str, frozenset[str]] = {
    "forecast": frozenset(
        {"targets", "horizon", "past_covariates", "known_future_covariates", "quantiles"}
    ),
    "forecast_batch": frozenset({"requests"}),
}


def error_envelope(
    code: ErrorCode | str, message: str, details: dict[str, Any] | None = None
) -> str:
    """Serialize a deterministic error envelope for an MCP tool failure."""
    value = code.value if isinstance(code, ErrorCode) else code
    payload: dict[str, Any] = {"code": value, "message": message}
    if details:
        payload["details"] = details
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def adapter_error_envelope(exc: ForecastAdapterError) -> str:
    """Serialize a typed adapter failure."""
    return error_envelope(exc.code, exc.message, exc.details)


def validation_error_details(exc: ValidationError) -> dict[str, Any]:
    """Return field-level context for a request validation failure."""
    errors = [
        {
            "loc": [str(part) for part in error["loc"]],
            "msg": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors(include_url=False)
    ]
    return {"errors": errors}


def _tool_name(ctx: ServerRequestContext[Any, Any]) -> str | None:
    params = ctx.params if isinstance(ctx.params, Mapping) else None
    if params is None:
        return None
    name = params.get("name")
    return name if isinstance(name, str) else None


def _error_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a wire-shaped failed tool result (``_dump_result`` accepts dicts)."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, separators=(",", ":"))}],
        "isError": True,
    }


def _is_error_result(result: Any) -> bool:
    if isinstance(result, Mapping):
        return bool(result.get("isError"))
    return bool(getattr(result, "is_error", False))


def _first_text(result: Any) -> str | None:
    if isinstance(result, Mapping):
        content = result.get("content")
    else:
        content = getattr(result, "content", None)
    if not isinstance(content, list):
        return None
    for block in content:
        if isinstance(block, Mapping):
            text = block.get("text")
            if isinstance(text, str):
                return text
        else:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return text
    return None


_SDK_TOOL_PREFIX = re.compile(r"^Error executing tool [^:]+: (.*)$", re.DOTALL)


def extract_envelope(text: str | None) -> dict[str, Any] | None:
    """Extract a Precog error envelope from a tool failure message, if present."""
    if not text:
        return None
    match = _SDK_TOOL_PREFIX.match(text)
    candidate = match.group(1) if match else text
    try:
        payload = json.loads(candidate)
    except ValueError:
        return None
    if isinstance(payload, dict) and "code" in payload and "message" in payload:
        return payload
    return None


class ToolErrorMiddleware:
    """Enforce the public argument surface and normalize tool failures.

    * ``tools/call``: removed/unknown fields are rejected before the handler with
      a structured ``INVALID_REQUEST``, and any remaining SDK argument or untyped
      failure is rewritten into a stable, machine-readable envelope without the
      SDK prefix.
    * ``tools/list``: the published input schemas get ``additionalProperties: false``
      so the advertised surface matches the enforced one.
    """

    def __init__(self) -> None:
        from precog_mcp.observability import record_tool_call

        self._record = record_tool_call

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> Any:
        if ctx.method == "tools/list":
            return _harden_tool_schemas(await call_next(ctx))
        if ctx.method != "tools/call":
            return await call_next(ctx)

        name = _tool_name(ctx)
        started = time.perf_counter()
        rejected = self._reject_unknown_arguments(name, ctx)
        if rejected is not None:
            if name is not None:
                self._record(name, "error", time.perf_counter() - started)
            return rejected

        result = await call_next(ctx)
        is_error = _is_error_result(result)
        if name is not None:
            self._record(name, "error" if is_error else "ok", time.perf_counter() - started)
        if not is_error:
            return result

        text = _first_text(result)
        payload = extract_envelope(text)
        if payload is None:
            payload = _untyped_failure(text)
        return _error_result(payload)

    def _reject_unknown_arguments(
        self, name: str | None, ctx: ServerRequestContext[Any, Any]
    ) -> dict[str, Any] | None:
        params = ctx.params if isinstance(ctx.params, Mapping) else None
        if params is None or name is None:
            return None
        arguments = params.get("arguments")
        allowed = _ALLOWED_ARGUMENTS.get(name)
        if allowed is None or not isinstance(arguments, Mapping):
            return None
        unknown = sorted(key for key in arguments if key not in allowed)
        if not unknown:
            return None
        return _error_result(
            {
                "code": ErrorCode.INVALID_REQUEST.value,
                "message": f"unknown request field(s): {', '.join(unknown)}",
                "details": {"unknown": unknown},
            }
        )


_VALIDATION_ERROR_MARKER = "validation error"


def _untyped_failure(text: str | None) -> dict[str, Any]:
    """Classify a tool failure that did not carry a Precog envelope.

    The SDK's own input-schema rejections are the caller's mistake and keep
    field-level context; anything else is an unexpected server-side defect whose
    details stay in the logs.
    """
    if text and _VALIDATION_ERROR_MARKER in text:
        return {"code": ErrorCode.INVALID_REQUEST.value, "message": text}
    logger.error("unexpected tool failure: %s", text or "<no message>")
    return {"code": ErrorCode.INTERNAL_ERROR.value, "message": INTERNAL_ERROR_MESSAGE}


def _harden_tool_schemas(result: Any) -> Any:
    if not isinstance(result, Mapping):
        return result
    tools = result.get("tools")
    if not isinstance(tools, list):
        return result
    hardened = []
    for tool in tools:
        if isinstance(tool, Mapping) and tool.get("name") in _ALLOWED_ARGUMENTS:
            schema = tool.get("inputSchema")
            if isinstance(schema, Mapping) and not schema.get("additionalProperties"):
                tool = {**tool, "inputSchema": {**schema, "additionalProperties": False}}
        hardened.append(tool)
    return {**result, "tools": hardened}


__all__ = [
    "ToolErrorMiddleware",
    "adapter_error_envelope",
    "error_envelope",
    "extract_envelope",
    "validation_error_details",
]

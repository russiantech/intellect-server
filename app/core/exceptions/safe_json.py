"""
app/core/exceptions/safe_json.py

Root-cause fix for:
    TypeError: Object of type ValueError is not JSON serializable

Pydantic v2 puts the raw exception object into exc.errors()[i]["ctx"]["error"]
whenever a field_validator / model_validator raises ValueError. json.dumps()
cannot encode that, so the *error handler itself* crashed, which escaped to
Passenger ("start_response() return NULL") and killed the worker.

This module guarantees that building an error response can NEVER raise.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.core.exceptions")

_MAX_STR = 500
# never echo these back to the client
_SENSITIVE = {"password", "new_password", "old_password", "token", "secret", "otp", "pin"}


def _safe(value: Any, _depth: int = 0) -> Any:
    """Convert anything into a JSON-safe value. Never raises."""
    if _depth > 6:
        return "<max depth>"
    try:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "..."
        if isinstance(value, BaseException):
            return str(value)[:_MAX_STR] or value.__class__.__name__
        if isinstance(value, bytes):
            return f"<{len(value)} bytes>"
        if isinstance(value, dict):
            return {str(k): _safe(v, _depth + 1) for k, v in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [_safe(v, _depth + 1) for v in value]
        return jsonable_encoder(value)
    except Exception:
        try:
            return str(value)[:_MAX_STR]
        except Exception:
            return "<unserializable>"


def sanitize_validation_errors(errors: Any) -> list[dict]:
    """Make exc.errors() JSON-safe; drop 'input' (may hold passwords) and the
    raw exception/url noise."""
    out: list[dict] = []
    try:
        for err in list(errors or []):
            if not isinstance(err, dict):
                out.append({"msg": _safe(err)})
                continue
            loc = [str(p) for p in err.get("loc", ())]
            item = {
                "loc": loc,
                "msg": _safe(err.get("msg", "Invalid value")),
                "type": _safe(err.get("type", "value_error")),
            }
            ctx = err.get("ctx")
            if isinstance(ctx, dict) and not (set(map(str.lower, loc)) & _SENSITIVE):
                item["ctx"] = _safe(ctx)
            out.append(item)
    except Exception:
        logger.exception("sanitize_validation_errors failed")
        out = [{"loc": [], "msg": "Invalid request", "type": "value_error"}]
    return out


def safe_json_response(status_code: int, content: Any, headers: dict | None = None) -> JSONResponse:
    """JSONResponse that cannot raise. Falls back to a minimal static body."""
    try:
        return JSONResponse(status_code=status_code, content=_safe(content), headers=headers)
    except Exception:
        logger.exception("safe_json_response fallback triggered")
        return JSONResponse(
            status_code=status_code if status_code else 500,
            content={"success": False, "message": "Request could not be processed"},
            headers=headers,
        )

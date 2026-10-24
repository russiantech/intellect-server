"""
Drop-in handlers. Register AFTER your existing ones (in main.py):

    from app.core.exceptions.resilient_handlers import register_resilient_handlers
    register_resilient_handlers(app)

Replaces the three failure points seen in the logs:
  1. RequestValidationError  -> was crashing on exc.errors() containing ValueError
  2. pydantic ValidationError raised manually in services
  3. any other Exception     -> last-resort 500 JSON, never propagates to Passenger
Every handler is wrapped so that *building the error response* cannot raise.
"""
import logging
import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .safe_json import safe_json_response, sanitize_validation_errors

log = logging.getLogger("app.core.exceptions")


def _body(message: str, code: str, request_id: str, details=None) -> dict:
    d = {"success": False, "message": message, "error_code": code, "request_id": request_id}
    if details is not None:
        d["details"] = details
    return d


def _rid(request: Request) -> str:
    return getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]


def register_resilient_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: RequestValidationError):
        rid = _rid(request)
        try:
            errs = sanitize_validation_errors(exc.errors())
            log.warning("422 %s %s [%s] %s", request.method, request.url.path, rid, errs)
            return safe_json_response(422, _body("Validation error", "VALIDATION_ERROR", rid, {"errors": errs}))
        except Exception:
            log.exception("validation handler failed [%s]", rid)
            return safe_json_response(422, _body("Validation error", "VALIDATION_ERROR", rid))

    @app.exception_handler(ValidationError)
    async def _pydantic_validation(request: Request, exc: ValidationError):
        rid = _rid(request)
        try:
            errs = sanitize_validation_errors(exc.errors())
        except Exception:
            errs = []
        return safe_json_response(422, _body("Validation error", "VALIDATION_ERROR", rid, {"errors": errs}))

    @app.exception_handler(ResponseValidationError)
    async def _response_validation(request: Request, exc: ResponseValidationError):
        rid = _rid(request)
        log.error("Response validation failed %s %s [%s]: %s", request.method, request.url.path, rid, exc)
        return safe_json_response(500, _body("Internal server error", "RESPONSE_INVALID", rid))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        rid = _rid(request)
        return safe_json_response(
            exc.status_code,
            _body(str(exc.detail), f"HTTP_{exc.status_code}", rid),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _catch_all(request: Request, exc: Exception):
        rid = _rid(request)
        try:
            log.error("Unhandled %s on %s %s [%s]\n%s", type(exc).__name__, request.method,
                      request.url.path, rid, "".join(traceback.format_exception(exc)))
        except Exception:
            pass
        return safe_json_response(500, _body("Internal server error", "INTERNAL_ERROR", rid))

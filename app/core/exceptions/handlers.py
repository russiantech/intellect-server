# """
# app/core/exceptions/handlers.py  v3
# ====================================
# Production-grade exception handling for Intellect LMS.

# Design principles:
# - Standalone functions (FastAPI native pattern)
# - Structured logging with request IDs
# - Client errors (4xx) → warning logs, server errors (5xx) → error logs
# - Consistent error envelope: {success, message, error_id, timestamp, details?}
# - Never re-raise after catching (prevents middleware double-send bugs)
# """

# import logging
# import traceback
# import uuid
# from datetime import datetime, timezone
# from typing import Any, Callable, Dict, Optional

# from fastapi import Request
# from fastapi.responses import JSONResponse
# from fastapi.exceptions import RequestValidationError
# from starlette.exceptions import HTTPException as StarletteHTTPException
# from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

# from .custom_exceptions import CustomAPIException

# logger = logging.getLogger(__name__)


# # ═══════════════════════════════════════════════════════════════════════════════
# # ERROR ENVELOPE (consistent response shape)
# # ═══════════════════════════════════════════════════════════════════════════════

# def _error_response(
#     status_code: int,
#     message: str,
#     *,
#     error_code: Optional[str] = None,
#     details: Optional[Dict[str, Any]] = None,
#     error_id: Optional[str] = None,
#     request_id: Optional[str] = None,
# ) -> JSONResponse:
#     """
#     Build a consistent error response envelope.
    
#     Shape:
#         {
#             "success": false,
#             "message": "Human-readable description",
#             "error_id": "uuid-for-support",
#             "error_code": "MACHINE_READABLE_CODE",
#             "timestamp": "2026-05-20T18:37:00+00:00",
#             "request_id": "optional-trace-id",
#             "details": {}  # optional, machine-readable extra context
#         }
#     """
#     content: Dict[str, Any] = {
#         "success": False,
#         "message": message,
#         "timestamp": datetime.now(timezone.utc).isoformat(),
#     }
    
#     if error_id:
#         content["error_id"] = error_id
#     if error_code:
#         content["error_code"] = error_code
#     if request_id:
#         content["request_id"] = request_id
#     if details:
#         content["details"] = details
        
#     return JSONResponse(status_code=status_code, content=content)


# def _generate_error_id() -> str:
#     """Generate a short, URL-safe error ID for support tickets."""
#     return f"err-{uuid.uuid4().hex[:12]}"


# def _extract_request_id(request: Request) -> Optional[str]:
#     """Extract request ID from headers if present (for distributed tracing)."""
#     return request.headers.get("x-request-id") or request.headers.get("x-trace-id")


# def _log_client_error(
#     exc: Exception,
#     request: Request,
#     error_id: str,
#     status_code: int,
# ) -> None:
#     """
#     Log client errors (4xx) as warnings — these are the client's fault.
#     """
#     logger.warning(
#         "[%s] %s %s %s — %s (status=%d)",
#         error_id,
#         request.method,
#         request.url.path,
#         type(exc).__name__,
#         str(exc)[:200],
#         status_code,
#         extra={
#             "error_id": error_id,
#             "request_id": _extract_request_id(request),
#             "client_ip": request.client.host if request.client else None,
#             "user_agent": request.headers.get("user-agent"),
#         },
#     )


# def _log_server_error(
#     exc: Exception,
#     request: Request,
#     error_id: str,
#     status_code: int,
# ) -> None:
#     """
#     Log server errors (5xx) as errors with full traceback — these are our fault.
#     """
#     logger.error(
#         "[%s] %s %s %s — %s (status=%d)\n[%s] Traceback:\n%s",
#         error_id,
#         request.method,
#         request.url.path,
#         type(exc).__name__,
#         str(exc)[:200],
#         status_code,
#         error_id,
#         traceback.format_exc(),
#         extra={
#             "error_id": error_id,
#             "request_id": _extract_request_id(request),
#             "client_ip": request.client.host if request.client else None,
#             "user_agent": request.headers.get("user-agent"),
#         },
#     )


# # ═══════════════════════════════════════════════════════════════════════════════
# # HANDLER REGISTRY (clean, declarative mapping)
# # ═══════════════════════════════════════════════════════════════════════════════

# # Mapping: exception class → (handler function, default status code)
# HANDLER_REGISTRY: Dict[type, tuple[Callable, int]] = {}


# def register_handler(exc_class: type, status_code: int = 500):
#     """
#     Decorator to register an exception handler.
    
#     Usage:
#         @register_handler(CustomAPIException, 400)
#         async def handle_custom_api_exception(request, exc):
#             ...
#     """
#     def decorator(func: Callable) -> Callable:
#         HANDLER_REGISTRY[exc_class] = (func, status_code)
#         return func
#     return decorator


# # ═══════════════════════════════════════════════════════════════════════════════
# # SPECIFIC HANDLERS
# # ═══════════════════════════════════════════════════════════════════════════════

# @register_handler(CustomAPIException, 400)
# async def handle_custom_api_exception(request: Request, exc: CustomAPIException) -> JSONResponse:
#     """
#     Domain-specific exceptions from our business logic.
#     These are predictable, client-friendly errors.
#     """
#     error_id = _generate_error_id()
#     _log_client_error(exc, request, error_id, exc.status_code)
    
#     return _error_response(
#         status_code=exc.status_code,
#         message=exc.message,
#         error_code=exc.error_code,
#         details=exc.details,
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(RequestValidationError, 422)
# async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
#     """
#     Pydantic / FastAPI validation errors.
#     Return the first error for UX simplicity, but include all in details.
#     """
#     error_id = _generate_error_id()
#     _log_client_error(exc, request, error_id, 422)
    
#     errors = exc.errors()
#     first_error = errors[0] if errors else {}
#     field = first_error.get("loc", ["unknown"])[-1]
    
#     # Friendly field-specific messages
#     friendly_messages = {
#         "username": "Username must be 3–30 characters (letters, numbers, hyphens, underscores).",
#         "email": "Please enter a valid email address.",
#         "phone": "Invalid phone number. Use local (08012345678) or international (+14155552671) format.",
#         "name": "Name must be 2–50 letters and spaces only.",
#         "password": "Password must be at least 5 characters with uppercase, lowercase, number, and special character.",
#     }
    
#     message = friendly_messages.get(field, first_error.get("msg", "Invalid input"))
    
#     return _error_response(
#         status_code=422,
#         message=message,
#         error_code="VALIDATION_ERROR",
#         details={
#             "field": field,
#             "errors": errors,  # Full list for debugging
#         },
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(StarletteHTTPException, 500)
# async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
#     """
#     Starlette HTTP exceptions (404, 405, 429, etc.).
#     """
#     error_id = _generate_error_id()
    
#     # 4xx = client error, 5xx = server error
#     if exc.status_code >= 500:
#         _log_server_error(exc, request, error_id, exc.status_code)
#     else:
#         _log_client_error(exc, request, error_id, exc.status_code)
    
#     return _error_response(
#         status_code=exc.status_code,
#         message=str(exc.detail),
#         error_code=f"HTTP_{exc.status_code}",
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(IntegrityError, 409)
# async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
#     """
#     Database integrity errors: duplicates, FK violations, check violations.
#     """
#     error_id = _generate_error_id()
#     _log_server_error(exc, request, error_id, 409)
    
#     # Extract specific violation type
#     orig = getattr(exc, "orig", None)
#     violation_type = type(orig).__name__ if orig else "UNKNOWN"
    
#     # User-friendly messages
#     messages = {
#         "UniqueViolation": "A record with this value already exists.",
#         "ForeignKeyViolation": "Referenced record does not exist.",
#         "CheckViolation": "Invalid data violates a constraint.",
#         "NotNullViolation": "Required field cannot be empty.",
#     }
#     message = messages.get(violation_type, "Database constraint violated.")
    
#     return _error_response(
#         status_code=409,
#         message=message,
#         error_code="INTEGRITY_ERROR",
#         details={
#             "violation_type": violation_type,
#             "db_message": str(orig)[:500] if orig else None,
#         },
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(ProgrammingError, 500)
# async def handle_programming_error(request: Request, exc: ProgrammingError) -> JSONResponse:
#     """
#     Database schema errors: missing tables, columns, bad migrations.
#     """
#     error_id = _generate_error_id()
#     _log_server_error(exc, request, error_id, 500)
    
#     orig = getattr(exc, "orig", None)
    
#     return _error_response(
#         status_code=500,
#         message="Database schema error. The application may not be fully migrated.",
#         error_code="SCHEMA_ERROR",
#         details={
#             "db_message": str(orig)[:500] if orig else None,
#             "hint": "Run 'alembic upgrade head' or check migration status.",
#         },
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(SQLAlchemyError, 500)
# async def handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
#     """
#     Catch-all SQLAlchemy: connection pool exhaustion, timeouts, etc.
#     """
#     error_id = _generate_error_id()
#     _log_server_error(exc, request, error_id, 500)
    
#     return _error_response(
#         status_code=500,
#         message="A database error occurred. Please try again shortly.",
#         error_code="DATABASE_ERROR",
#         details={"db_message": str(exc)[:500]},
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(ValueError, 400)
# async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
#     """
#     Common Python ValueError — usually a client input issue.
#     """
#     error_id = _generate_error_id()
#     _log_client_error(exc, request, error_id, 400)
    
#     return _error_response(
#         status_code=400,
#         message=str(exc) or "Invalid value provided.",
#         error_code="INVALID_VALUE",
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(KeyError, 400)
# async def handle_key_error(request: Request, exc: KeyError) -> JSONResponse:
#     """
#     Missing key in dict — usually a malformed request.
#     """
#     error_id = _generate_error_id()
#     _log_client_error(exc, request, error_id, 400)
    
#     return _error_response(
#         status_code=400,
#         message=f"Missing required field: {exc}",
#         error_code="MISSING_FIELD",
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# @register_handler(AttributeError, 500)
# async def handle_attribute_error(request: Request, exc: AttributeError) -> JSONResponse:
#     """
#     AttributeError — usually a code bug (None where object expected).
#     """
#     error_id = _generate_error_id()
#     _log_server_error(exc, request, error_id, 500)
    
#     return _error_response(
#         status_code=500,
#         message="An unexpected error occurred. Please try again.",
#         error_code="INTERNAL_ERROR",
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# # ═══════════════════════════════════════════════════════════════════════════════
# # GLOBAL CATCH-ALL (last resort)
# # ═══════════════════════════════════════════════════════════════════════════════

# async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
#     """
#     Last-resort handler for any exception not caught above.
#     CRITICAL: Must not re-raise. The ASGI server may have already
#     started sending response bytes; re-raising causes cascading
#     RuntimeError: Response content shorter than Content-Length.
#     """
#     error_id = _generate_error_id()
#     _log_server_error(exc, request, error_id, 500)
    
#     return _error_response(
#         status_code=500,
#         message="An unexpected error occurred. Please try again or contact support.",
#         error_code="INTERNAL_ERROR",
#         error_id=error_id,
#         request_id=_extract_request_id(request),
#     )


# # ═══════════════════════════════════════════════════════════════════════════════
# # REGISTRATION FUNCTION (called from main.py)
# # ═══════════════════════════════════════════════════════════════════════════════

# def register_all_exception_handlers(app) -> None:
#     """
#     Register all exception handlers on a FastAPI app.
    
#     Call this in main.py after creating the app but before including routers:
    
#         from app.core.exceptions.handlers import register_all_exception_handlers
#         register_all_exception_handlers(app)
#     """
#     # Register specific handlers from registry
#     for exc_class, (handler, _) in HANDLER_REGISTRY.items():
#         app.add_exception_handler(exc_class, handler)
    
#     # Register catch-all last
#     app.add_exception_handler(Exception, handle_unhandled_exception)
    
#     logger.info(
#         "Registered %d exception handlers: %s",
#         len(HANDLER_REGISTRY) + 1,
#         [c.__name__ for c in list(HANDLER_REGISTRY.keys()) + [Exception]],
#     )






# v2
"""
app/core/exceptions/handlers.py  v3
====================================
Production-grade exception handling.

Pattern: standalone async functions with @register_handler decorator.
No classes, no manual app.add_exception_handler() scattered everywhere.
"""

import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Type

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

from .custom_exceptions import CustomAPIException

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

# Mapping: exception class → handler function
HANDLER_REGISTRY: Dict[Type[Exception], Callable] = {}


def register_handler(exc_class: Type[Exception]):
    """Decorator to register an exception handler."""
    def decorator(func: Callable) -> Callable:
        HANDLER_REGISTRY[exc_class] = func
        return func
    return decorator


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def _error_response(
    status_code: int,
    message: str,
    *,
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    error_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> JSONResponse:
    """Consistent error envelope."""
    content: Dict[str, Any] = {
        "success": False,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if error_id:
        content["error_id"] = error_id
    if error_code:
        content["error_code"] = error_code
    if request_id:
        content["request_id"] = request_id
    if details:
        content["details"] = details
    return JSONResponse(status_code=status_code, content=content)


def _error_id() -> str:
    return f"err-{uuid.uuid4().hex[:12]}"


def _request_id(request: Request) -> Optional[str]:
    return request.headers.get("x-request-id") or request.headers.get("x-trace-id")


def _log_warning(exc: Exception, request: Request, eid: str, status: int) -> None:
    logger.warning(
        "[%s] %s %s — %s (status=%d)",
        eid, request.method, request.url.path, type(exc).__name__, status,
        extra={
            "error_id": eid,
            "request_id": _request_id(request),
            "client_ip": request.client.host if request.client else None,
        },
    )


def _log_error(exc: Exception, request: Request, eid: str, status: int) -> None:
    logger.error(
        "[%s] %s %s — %s (status=%d)\n[%s] %s",
        eid, request.method, request.url.path, type(exc).__name__, status,
        eid, traceback.format_exc(),
        extra={
            "error_id": eid,
            "request_id": _request_id(request),
            "client_ip": request.client.host if request.client else None,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HANDLERS — SPECIFIC
# ═══════════════════════════════════════════════════════════════════════════════

@register_handler(CustomAPIException)
async def handle_custom_api_exception(request: Request, exc: CustomAPIException) -> JSONResponse:
    eid = _error_id()
    _log_warning(exc, request, eid, exc.status_code)
    return _error_response(
        status_code=exc.status_code,
        message=exc.message,
        error_code=exc.error_code,
        details=exc.details,
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    eid = _error_id()
    _log_warning(exc, request, eid, 422)
    
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = first.get("loc", ["unknown"])[-1]
    
    friendly = {
        "username": "Username must be 3–30 characters (letters, numbers, hyphens, underscores).",
        "email": "Please enter a valid email address.",
        "phone": "Invalid phone number. Use local (08012345678) or international (+14155552671) format.",
        "name": "Name must be 2–50 letters and spaces only.",
        "password": "Password must be at least 5 characters with uppercase, lowercase, number, and special character.",
    }
    
    return _error_response(
        status_code=422,
        message=friendly.get(field, first.get("msg", "Invalid input")),
        error_code="VALIDATION_ERROR",
        details={"field": field, "errors": errors},
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    eid = _error_id()
    if exc.status_code >= 500:
        _log_error(exc, request, eid, exc.status_code)
    else:
        _log_warning(exc, request, eid, exc.status_code)
    
    return _error_response(
        status_code=exc.status_code,
        message=str(exc.detail),
        error_code=f"HTTP_{exc.status_code}",
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(IntegrityError)
async def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    eid = _error_id()
    _log_error(exc, request, eid, 409)
    
    orig = getattr(exc, "orig", None)
    violation = type(orig).__name__ if orig else "UNKNOWN"
    
    messages = {
        "UniqueViolation": "A record with this value already exists.",
        "ForeignKeyViolation": "Referenced record does not exist.",
        "CheckViolation": "Invalid data violates a constraint.",
        "NotNullViolation": "Required field cannot be empty.",
    }
    
    return _error_response(
        status_code=409,
        message=messages.get(violation, "Database constraint violated."),
        error_code="INTEGRITY_ERROR",
        details={"violation_type": violation, "db_message": str(orig)[:500] if orig else None},
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(ProgrammingError)
async def handle_programming_error(request: Request, exc: ProgrammingError) -> JSONResponse:
    eid = _error_id()
    _log_error(exc, request, eid, 500)
    
    orig = getattr(exc, "orig", None)
    return _error_response(
        status_code=500,
        message="Database schema error. The application may not be fully migrated.",
        error_code="SCHEMA_ERROR",
        details={"db_message": str(orig)[:500] if orig else None, "hint": "Run 'alembic upgrade head'"},
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(SQLAlchemyError)
async def handle_sqlalchemy_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    eid = _error_id()
    _log_error(exc, request, eid, 500)
    
    return _error_response(
        status_code=500,
        message="A database error occurred. Please try again shortly.",
        error_code="DATABASE_ERROR",
        details={"db_message": str(exc)[:500]},
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
    eid = _error_id()
    _log_warning(exc, request, eid, 400)
    
    return _error_response(
        status_code=400,
        message=str(exc) or "Invalid value provided.",
        error_code="INVALID_VALUE",
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(KeyError)
async def handle_key_error(request: Request, exc: KeyError) -> JSONResponse:
    eid = _error_id()
    _log_warning(exc, request, eid, 400)
    
    return _error_response(
        status_code=400,
        message=f"Missing required field: {exc}",
        error_code="MISSING_FIELD",
        error_id=eid,
        request_id=_request_id(request),
    )


@register_handler(AttributeError)
async def handle_attribute_error(request: Request, exc: AttributeError) -> JSONResponse:
    eid = _error_id()
    _log_error(exc, request, eid, 500)
    
    return _error_response(
        status_code=500,
        message="An unexpected error occurred. Please try again.",
        error_code="INTERNAL_ERROR",
        error_id=eid,
        request_id=_request_id(request),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CATCH-ALL (last resort — never re-raises)
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """
    CRITICAL: Never re-raise. The ASGI server may have already started
    sending response bytes; re-raising causes cascading RuntimeError.
    """
    eid = _error_id()
    _log_error(exc, request, eid, 500)
    
    return _error_response(
        status_code=500,
        message="An unexpected error occurred. Please try again or contact support.",
        error_code="INTERNAL_ERROR",
        error_id=eid,
        request_id=_request_id(request),
    )


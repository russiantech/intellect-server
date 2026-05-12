# from fastapi import Request
# from fastapi.responses import JSONResponse
# from fastapi.exceptions import RequestValidationError
# from starlette.exceptions import HTTPException as StarletteHTTPException
# from jose import JWTError
# from sqlalchemy.exc import IntegrityError
# from psycopg2.errors import CheckViolation, UniqueViolation, ForeignKeyViolation
# import logging
# from app.utils.responses import api_response
# from app.core.exceptions.custom_exceptions import CustomAPIException

# logger = logging.getLogger(__name__)

# class ExceptionHandler:
#     def __init__(self, config):
#         self.config = config

#     async def custom_api_exception_handler(request, exc: CustomAPIException):
#         logger.warning(
#             f"Custom API exception at {request.url.path}: {exc.message}"
#         )
                
#         return api_response(
#             success=False,
#             message=exc.message,
#             errors={
#                 "error_code": exc.error_code,
#                 "details": exc.details
#             },
#             status_code=exc.status_code,
#             path=str(request.url.path)
#         )

#     async def jwt_exception_handler(self, request: Request, exc: JWTError) -> JSONResponse:
#         """Handle JWT token validation errors."""
#         error_detail = "Invalid authentication token"
#         if "expired" in str(exc).lower():
#             error_detail = "Authentication token has expired"
        
#         logger.warning(f"JWT validation failed: {error_detail}")
        
#         return JSONResponse(
#             status_code=401,
#             content={
#                 "detail": error_detail,
#                 "error_code": "INVALID_TOKEN"
#             }
#         )

#     async def http_exception_handler(self, request: Request, exc: StarletteHTTPException) -> JSONResponse:
#         """Handle HTTP exceptions (404, 403, etc.)."""
#         logger.warning(
#             f"HTTPException {exc.status_code} at {request.url.path}: {exc.detail}"
#         )
                
#         return api_response(
#             success=False,
#             message=str(exc.detail),
#             errors={"status_code": exc.status_code},
#             status_code=exc.status_code,
#             path=str(request.url.path)
#         )
    
#     async def validation_exception_handler_0(
#         self,
#         request: Request,
#         exc: RequestValidationError
#     ) -> JSONResponse:
#         """Handle validation errors and return clean, structured responses."""
        
#         logger.warning(
#             f"Validation error at {request.url.path}: {exc.errors()}"
#         )

#         formatted_errors = []

#         for err in exc.errors():
#             field = err.get("loc", [])[-1]
#             message = err.get("msg", "Invalid input")

#             formatted_errors.append({
#                 "field": field,
#                 "message": message
#             })

#         return api_response(
#             success=False,
#             # message="Validation error.",
#             message=f"{formatted_errors[0].get('message')}",
#             errors=formatted_errors,
#             status_code=422,
#             path=str(request.url.path)
#         )

#     async def validation_exception_handler(self, request: Request, exc: RequestValidationError) -> JSONResponse:
#         """Handle Pydantic validation errors and return a friendly message."""
#         logger.warning(f"Validation error at {request.url.path}: {exc.errors()}")

#         # from app.utils.responses import api_response

#         # Take the first error only for smoother UX
#         first_error = exc.errors()[0]

#         # Map field-specific friendly messages
#         field = first_error.get("loc", ["field"])[-1]
#         err_type = first_error.get("type", "")
#         msg = first_error.get("msg", "Invalid input")

#         if field == "username":
#             msg = "Username must be 3–30 characters (letters, numbers, hyphens, underscores)."
#         elif field == "email":
#             msg = "Please enter a valid email address."
#         elif field == "phone":
#             msg = "Invalid phone number format. Use a valid local number, (e.g., 08012345678) or international format (e.g., +14155552671)."
#         elif field == "name":
#             msg = "Name must be 2–50 letters and spaces only."
#         elif field == "password":
#             msg = "Password must be at least 5 characters, with uppercase, lowercase, number, and special character."

#         return api_response(
#             success=False,
#             message=msg,
#             errors={
#                 "status_code": 422,
#                 "field": field,
#                 "type": err_type,
#             },
#             status_code=422,
#             path=str(request.url.path)
#         )

#     async def integrity_error_handler(self, request: Request, exc: IntegrityError) -> JSONResponse:
#         """Handle database integrity errors."""
#         logger.error(f"Database integrity error at {request.url.path}: {str(exc)}", exc_info=True)

#         # Default message
#         message = "Database integrity constraint violated"
#         error_detail = str(exc.orig) if hasattr(exc, "orig") else str(exc)

#         # Specific constraint types
#         if isinstance(exc.orig, UniqueViolation):
#             message = "Duplicate value violates unique constraint"
#         elif isinstance(exc.orig, CheckViolation):
#             message = "Invalid data violates database check constraint"
#         elif isinstance(exc.orig, ForeignKeyViolation):
#             message = "Referenced record does not exist (foreign key constraint)"

#         # from app.utils.responses import api_response
        
#         return api_response(
#             success=False,
#             message=message,
#             errors={"detail": error_detail},
#             status_code=400,
#             path=str(request.url.path)
#         )

#     async def global_exception_handler(self, request: Request, exc: Exception) -> JSONResponse:
#         logger.error(
#             f"Unhandled exception at {request.url.path}: {str(exc)}",
#             exc_info=True
#         )

#         # Handle validation-like errors safely
#         errors = None
#         if isinstance(exc, (RequestValidationError,)):
#             errors = exc.errors()

#             json_errors = [
#                 err for err in errors if err.get("type") == "json_invalid"
#             ]

#             if json_errors:
#                 return api_response(
#                     success=False,
#                     message="Invalid JSON payload",
#                     errors={
#                         "hint": "Check quotes, commas, and JSON structure",
#                         "details": json_errors,
#                     },
#                     status_code=422,
#                     path=str(request.url.path),
#                 )

#         # Environment-based detail exposure
#         if self.config.general_config.development_mode:
#             error_detail = str(exc)
#         else:
#             error_detail = "Internal server error"

#         return api_response(
#             success=False,
#             message="An unexpected error occurred",
#             errors={"detail": error_detail},
#             status_code=500,
#             path=str(request.url.path),
#         )





# v2
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError
import logging
import traceback
import uuid
from datetime import datetime, timezone

from .custom_exceptions import CustomAPIException

logger = logging.getLogger(__name__)


class ExceptionHandler:
    def __init__(self, config):
        self.config = config

    def _log_error(self, exc: Exception, request: Request, error_id: str):
        logger.error(
            f"[{error_id}] {type(exc).__name__} on {request.method} {request.url.path}\n"
            f"[{error_id}] {exc}\n"
            f"[{error_id}] Traceback:\n{traceback.format_exc()}"
        )

    def _error_response(
        self,
        status_code: int,
        message: str,
        *,
        error_code: str | None = None,
        details: dict | None = None,
        error_id: str | None = None,
    ):
        content = {
            "success": False,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if error_code:
            content["error_code"] = error_code
        if details:
            content["details"] = details
        if error_id:
            content["error_id"] = error_id
        return JSONResponse(status_code=status_code, content=content)

    # ── 1. Custom domain exceptions ──────────────────────────────────────────
    async def custom_api_exception_handler(self, request: Request, exc: CustomAPIException):
        return self._error_response(
            status_code=exc.status_code,
            message=exc.message,
            error_code=exc.error_code,
            details=exc.details,
        )

    # ── 2. Pydantic / request validation ─────────────────────────────────────
    async def validation_exception_handler(self, request: Request, exc: RequestValidationError):
        return self._error_response(
            status_code=422,
            message="Request validation failed",
            error_code="VALIDATION_ERROR",
            details={"errors": exc.errors()},
        )

    # ── 3. Starlette HTTP exceptions (404, 405, etc.) ────────────────────────
    async def http_exception_handler(self, request: Request, exc: StarletteHTTPException):
        return self._error_response(
            status_code=exc.status_code,
            message=exc.detail,
            error_code=f"HTTP_{exc.status_code}",
        )

    # ── 4. IntegrityError (duplicates, FK violations) ────────────────────────
    async def integrity_error_handler(self, request: Request, exc: IntegrityError):
        error_id = str(uuid.uuid4())
        self._log_error(exc, request, error_id)
        detail = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
        return self._error_response(
            status_code=409,
            message="Database integrity error. Possible duplicate or constraint violation.",
            error_code="INTEGRITY_ERROR",
            details={"db_message": detail},
            error_id=error_id,
        )

    # ── 5. ProgrammingError (missing tables, columns, bad SQL) ───────────────
    async def programming_error_handler(self, request: Request, exc: ProgrammingError):
        error_id = str(uuid.uuid4())
        self._log_error(exc, request, error_id)
        detail = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)
        return self._error_response(
            status_code=500,
            message="Database schema error. The application may not be fully migrated.",
            error_code="PROGRAMMING_ERROR",
            details={"db_message": detail},
            error_id=error_id,
        )

    # ── 6. Catch-all SQLAlchemy (connection pool, timeouts, etc.) ────────────
    async def sqlalchemy_error_handler(self, request: Request, exc: SQLAlchemyError):
        error_id = str(uuid.uuid4())
        self._log_error(exc, request, error_id)
        return self._error_response(
            status_code=500,
            message="A database error occurred.",
            error_code="DATABASE_ERROR",
            details={"db_message": str(exc)},
            error_id=error_id,
        )

    # ── 7. Global last-resort handler ────────────────────────────────────────
    async def global_exception_handler(self, request: Request, exc: Exception):
        error_id = str(uuid.uuid4())
        self._log_error(exc, request, error_id)
        return self._error_response(
            status_code=500,
            message="An unexpected error occurred. Please try again or contact support.",
            error_code="INTERNAL_ERROR",
            error_id=error_id,
        )

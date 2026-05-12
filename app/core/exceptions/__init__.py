# # app/core/exceptions/__init__.py

# from fastapi import FastAPI
# from psycopg2 import IntegrityError

# #
# from fastapi.exceptions import RequestValidationError
# from starlette.exceptions import HTTPException as StarletteHTTPException
# # from authlib.jose import JoseError
# from sqlalchemy.exc import IntegrityError
# # from psycopg2.errors import CheckViolation, UniqueViolation, ForeignKeyViolation

# from .handlers import ExceptionHandler
# from .custom_exceptions import CustomAPIException
# import logging

# logger = logging.getLogger(__name__)

# # v2 - correct order
# def setup_exception_handlers(app: FastAPI, config):
#     handler = ExceptionHandler(config)

#     # 1 Custom domain exceptions
#     app.add_exception_handler(
#         CustomAPIException,
#         handler.custom_api_exception_handler
#     )

#     # 2 Request validation (Pydantic, JSON parsing, body errors)
#     app.add_exception_handler(
#         RequestValidationError,
#         handler.validation_exception_handler
#     )

#     # 3 HTTP errors (404, 405, etc.)
#     app.add_exception_handler(
#         StarletteHTTPException,
#         handler.http_exception_handler
#     )

#     # 4 Database integrity errors
#     app.add_exception_handler(
#         IntegrityError,
#         handler.integrity_error_handler
#     )

#     # 5 LAST RESORT — unknown errors
#     app.add_exception_handler(
#         Exception,
#         handler.global_exception_handler
#     )

#     logger.info("Exception handlers registered successfully")

# # Import for easy access
# from .custom_exceptions import (
#     CustomAPIException,
#     AuthenticationException,
#     AuthorizationException,
#     ResourceNotFoundException,
#     ValidationException,
#     BusinessRuleException,
#     ExternalServiceException
# )

# __all__ = [
#     "CustomAPIException",
#     "AuthenticationException",
#     "AuthenticationException",
# ]



# v2
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import IntegrityError, ProgrammingError, SQLAlchemyError

from .handlers import ExceptionHandler
from .custom_exceptions import (
    CustomAPIException,
    AuthenticationException,
    AuthorizationException,
    ResourceNotFoundException,
    ValidationException,
    BusinessRuleException,
    ExternalServiceException,
)
import logging

logger = logging.getLogger(__name__)

# v3 - consistent order: specific → general
def setup_exception_handlers(app: FastAPI, config):
    handler = ExceptionHandler(config)

    # 1 Custom domain exceptions
    app.add_exception_handler(
        CustomAPIException,
        handler.custom_api_exception_handler,
    )

    # 2 Request validation (Pydantic, JSON parsing, body errors)
    app.add_exception_handler(
        RequestValidationError,
        handler.validation_exception_handler,
    )

    # 3 HTTP errors (404, 405, etc.)
    app.add_exception_handler(
        StarletteHTTPException,
        handler.http_exception_handler,
    )

    # 4 Database: integrity (unique, fk, check violations)
    app.add_exception_handler(
        IntegrityError,
        handler.integrity_error_handler,
    )

    # 5 Database: programming (missing tables, columns, syntax)
    app.add_exception_handler(
        ProgrammingError,
        handler.programming_error_handler,
    )

    # 6 Database: catch-all SQLAlchemy (connection pool, timeout, etc.)
    app.add_exception_handler(
        SQLAlchemyError,
        handler.sqlalchemy_error_handler,
    )

    # 7 LAST RESORT — unknown errors
    app.add_exception_handler(
        Exception,
        handler.global_exception_handler,
    )

    logger.info("Exception handlers registered successfully")


__all__ = [
    "CustomAPIException",
    "AuthenticationException",
    "AuthorizationException",
    "ResourceNotFoundException",
    "ValidationException",
    "BusinessRuleException",
    "ExternalServiceException",
    "setup_exception_handlers",
]

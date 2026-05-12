from datetime import datetime
from fastapi import Request, HTTPException, status, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from typing import Type, Callable


from pydantic import ValidationError
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi import status

def friendly_error_message(err: dict) -> str:
    """Map a Pydantic error to a friendly message."""
    loc = err.get("loc", [])
    field = loc[-1] if loc else "field"
    err_type = err.get("type", "")
    
    # Custom messages based on field & error type
    if field == "phone":
        return "Phone number must include country code (e.g., +234...) and contain 7-15 digits"
    if field == "password":
        return "Password must contain at least one uppercase letter, one lowercase letter, one number, and one special character"
    if field == "email":
        return "Invalid email format"
    if field == "username":
        return "Username can only contain letters, numbers, hyphens, and underscores (3-30 characters)"
    
    # Fallback
    return err.get("msg", "Invalid input")


# @app.exception_handler(RequestValidationError)
async def enhanced_validation(request: Request, exc: RequestValidationError):
    first_error = exc.errors()[0]  # Only return first error
    friendly_msg = friendly_error_message(first_error)
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": friendly_msg,
            "timestamp": datetime.now().isoformat(),
            "path": request.url.path,
            "errors": {"status_code": 422}
        }
    )

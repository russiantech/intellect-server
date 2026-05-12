from typing import Any, Dict, List, Optional

class CustomAPIException(Exception):
    """Custom Base exception class for our API"""
    
    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

class AuthenticationException(CustomAPIException):
    """Authentication related exceptions"""
    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=401,
            error_code="AUTHENTICATION_ERROR",
            details=details
        )

class AuthorizationException(CustomAPIException):
    """Authorization related exceptions"""
    def __init__(
        self,
        message: str = "Insufficient permissions",
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            message=message,
            status_code=403,
            error_code="AUTHORIZATION_ERROR",
            details=details
        )

class ResourceNotFoundException(CustomAPIException):
    """Resource not found exceptions"""
    def __init__(
        self,
        resource: str = "Resource",
        resource_id: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        message = f"{resource} not found"
        if resource_id:
            message = f"{resource} with ID {resource_id} not found"
            
        super().__init__(
            message=message,
            status_code=404,
            error_code="RESOURCE_NOT_FOUND",
            details=details
        )

class ValidationException(CustomAPIException):
    """Validation related exceptions"""
    def __init__(
        self,
        message: str = "Validation failed",
        field_errors: Optional[Dict[str, List[str]]] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if field_errors:
            details["field_errors"] = field_errors
            
        super().__init__(
            message=message,
            status_code=422,
            error_code="VALIDATION_ERROR",
            details=details
        )

class BusinessRuleException(CustomAPIException):
    """Business rule violation exceptions"""
    def __init__(
        self,
        message: str = "Business rule violation",
        rule: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        if rule:
            details["rule"] = rule
            
        super().__init__(
            message=message,
            status_code=400,
            error_code="BUSINESS_RULE_ERROR",
            details=details
        )

class ExternalServiceException(CustomAPIException):
    """External service related exceptions"""
    def __init__(
        self,
        service: str,
        message: str = "External service error",
        details: Optional[Dict[str, Any]] = None
    ):
        details = details or {}
        details["service"] = service
        
        super().__init__(
            message=message,
            status_code=502,
            error_code="EXTERNAL_SERVICE_ERROR",
            details=details
        )

# SEE USAGE

""" 
from fastapi import APIRouter, Depends, HTTPException
from src.core.exceptions import (
    ResourceNotFoundException, 
    ValidationException,
    BusinessRuleException
)

router = APIRouter()

@router.get("/users/{user_id}")
async def get_user(user_id: int):
    try:
        user = await user_service.get_user(user_id)
        if not user:
            raise ResourceNotFoundException("User", user_id)
        
        return user
        
    except ResourceNotFoundException:
        # This will be handled by our custom exception handler
        raise
        
    except Exception as e:
        # This will be handled by our global exception handler
        raise

@router.post("/users")
async def create_user(user_data: dict):
    # Custom validation
    if not user_data.get("email"):
        raise ValidationException(
            "Email is required",
            field_errors={"email": ["Email field is required"]}
        )
    
    # Business rule validation
    if await user_service.email_exists(user_data["email"]):
        raise BusinessRuleException(
            "Email already exists",
            rule="UNIQUE_EMAIL"
        )
    
    return await user_service.create_user(user_data)
"""
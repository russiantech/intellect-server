"""Common/shared schemas"""
from typing import Optional, Any
from pydantic import BaseModel


class SuccessResponse(BaseModel):
    success: bool = True
    message: str
    data: Optional[Any] = None


class ErrorResponse(BaseModel):
    success: bool = False
    message: str
    detail: Optional[Any] = None


class BrandConfigUpdate(BaseModel):
    site_name: Optional[str] = None
    tagline: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    socials: Optional[dict] = None
    whatsapp_link: Optional[str] = None
    default_creator_pct: Optional[float] = None
    default_platform_pct: Optional[float] = None


from typing import List, Any

class PaginatedResponse(SuccessResponse):
    items: List[Any] = []
    total: int = 0
    page: int = 1
    per_page: int = 20
    pages: int = 1

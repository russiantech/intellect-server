"""Partnership schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr
from app.enums import PartnershipStatus

class PartnershipCreate(BaseModel):
    org_name: str
    org_email: EmailStr
    org_phone: Optional[str] = None
    contact_person: Optional[str] = None
    price_per_student: float = 0.0
    max_students: Optional[int] = None
    course_ids: List[int] = []
    path_ids: List[int] = []
    contract_start: Optional[datetime] = None
    contract_end: Optional[datetime] = None


class PartnershipUpdate(BaseModel):
    org_name: Optional[str] = None
    org_email: Optional[EmailStr] = None
    org_phone: Optional[str] = None
    contact_person: Optional[str] = None
    status: Optional[PartnershipStatus] = None
    price_per_student: Optional[float] = None
    max_students: Optional[int] = None
    course_ids: Optional[List[int]] = None
    path_ids: Optional[List[int]] = None
    contract_end: Optional[datetime] = None

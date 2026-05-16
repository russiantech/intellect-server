"""Enrollment schemas"""
from typing import Optional, List
from pydantic import BaseModel, Field


class EnrollRequest(BaseModel):
    course_id: int


class ProgressUpdate(BaseModel):
    topic_id: int
    completed: bool = True


class PathEnrollRequest(BaseModel):
    path_id: int


class AdminEnrollRequest(BaseModel):
    user_id: int
    course_id: Optional[int] = None
    path_id: Optional[int] = None


class EnrollmentStatusUpdate(BaseModel):
    status: str  # active, completed, dropped, suspended



# new
class DeenrollRequest(BaseModel):
    user_id: int
    course_id: Optional[int] = None
    path_id: Optional[int] = None
    reason: Optional[str] = "Admin de-enrollment"


class EnrollmentAnalytics(BaseModel):
    course_id: Optional[int] = None
    path_id: Optional[int] = None
    period_days: int = Field(default=30, ge=1, le=365)

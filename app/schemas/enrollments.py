"""Enrollment schemas"""
from typing import Optional, List
from pydantic import BaseModel


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

"""
app/schemas/projects.py
=======================
Pydantic request schemas for course-level Projects and Attendance.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────
#  Project brief CRUD (creator / admin)
# ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    title:            str
    description:      str
    course_id:        int
    lesson_id:        Optional[int]      = None
    due_date:         Optional[datetime] = None
    max_file_size_mb: int                = Field(default=50, ge=1)
    allowed_formats:  Optional[str]      = None   # "pdf,zip,docx"
    rubric:           Optional[str]      = None   # Markdown


class ProjectUpdate(BaseModel):
    title:            Optional[str]      = None
    description:      Optional[str]      = None
    due_date:         Optional[datetime] = None
    max_file_size_mb: Optional[int]      = None
    allowed_formats:  Optional[str]      = None
    rubric:           Optional[str]      = None
    is_active:        Optional[bool]     = None


# ──────────────────────────────────────────────────────────────────
#  Project submission (student)
# ──────────────────────────────────────────────────────────────────

class ProjectSubmissionCreate(BaseModel):
    """
    At least one of note / external_url must be provided.
    File is sent as multipart/form-data — not in this schema.
    """
    title:        Optional[str] = None
    note:         Optional[str] = None
    external_url: Optional[str] = None


# ──────────────────────────────────────────────────────────────────
#  Grading
# ──────────────────────────────────────────────────────────────────

class ProjectTutorReview(BaseModel):
    submission_id: int
    score:         Optional[float] = None
    feedback:      str
    passed:        Optional[bool]  = None


# ──────────────────────────────────────────────────────────────────
#  Attendance
# ──────────────────────────────────────────────────────────────────

class AttendanceRecordItem(BaseModel):
    user_id: int
    status:  str   # "present" | "absent" | "late" | "excused"
    note:    Optional[str] = None


class AttendanceMarkRequest(BaseModel):
    schedule_id: int
    records:     List[AttendanceRecordItem]


class AttendanceSelfCheckIn(BaseModel):
    schedule_id:    int
    check_in_code:  str

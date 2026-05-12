"""
app/api/v1/attendance.py
========================
Schedule and attendance routes.  All routes prefixed /attendance.

Student
  GET  /schedule/{schedule_id}           – get schedule detail
  POST /check-in                         – self check-in using OTP
  GET  /my                               – own attendance records

Tutor / Admin
  POST /schedule/{schedule_id}/mark      – bulk-mark attendance
  GET  /schedule/{schedule_id}/records   – list records for a session
  POST /schedule/{schedule_id}/code      – generate OTP check-in code
  GET  /course/{course_id}/summary       – per-student attendance summary

Creator / Admin CRUD
  GET  /course/{course_id}/schedules     – list schedules
  POST /schedules                        – create schedule
  PUT  /schedules/{schedule_id}          – update schedule
  DELETE /schedules/{schedule_id}        – delete schedule
"""

from __future__ import annotations

import logging
import secrets
import string
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps.auth import (
    get_current_user,
    require_tutor_or_admin,
    require_creator_or_admin,
)
from app.db.database import get_db
from app.enums import AttendanceStatus
from app.models import Course, User
from app.models.quizzes import AttendanceCheckInCode, AttendanceRecord, Schedule
from app.schemas.projects import AttendanceMarkRequest, AttendanceSelfCheckIn

router = APIRouter(prefix="/attendance", tags=["Attendance"])
logger = logging.getLogger(__name__)

_CODE_CHARS = string.ascii_uppercase + string.digits


# ──────────────────────────────────────────────────────────────────
#  Local schemas (schedule only — attendance schemas are in schemas/projects.py)
# ──────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    title:           str
    description:     Optional[str]      = None
    course_id:       Optional[int]      = None
    tutor_id:        Optional[int]      = None
    start_time:      datetime
    end_time:        datetime
    meeting_link:    Optional[str]      = None
    is_recurring:    bool               = False
    recurrence_rule: Optional[str]      = None


class ScheduleUpdate(BaseModel):
    title:           Optional[str]      = None
    description:     Optional[str]      = None
    start_time:      Optional[datetime] = None
    end_time:        Optional[datetime] = None
    meeting_link:    Optional[str]      = None
    is_recurring:    Optional[bool]     = None
    recurrence_rule: Optional[str]      = None


# ──────────────────────────────────────────────────────────────────
#  Serialisation
# ──────────────────────────────────────────────────────────────────

def _serialize_schedule(s: Schedule) -> dict:
    return {
        "id":             s.id,
        "title":          s.title,
        "description":    s.description,
        "course_id":      s.course_id,
        "tutor_id":       s.tutor_id,
        "start_time":     s.start_time,
        "end_time":       s.end_time,
        "meeting_link":   s.meeting_link,
        "is_recurring":   s.is_recurring,
        "recurrence_rule": s.recurrence_rule,
        "created_at":     s.created_at,
    }


def _serialize_record(r: AttendanceRecord) -> dict:
    return {
        "id":            r.id,
        "schedule_id":   r.schedule_id,
        "user_id":       r.user_id,
        "status":        r.status,
        "check_in_time": r.check_in_time,
        "note":          r.note,
        "marked_by_id":  r.marked_by_id,
        "created_at":    r.created_at,
    }


# ──────────────────────────────────────────────────────────────────
#  Access helpers
# ──────────────────────────────────────────────────────────────────

def _is_schedule_staff(schedule: Schedule, user: User, db: Session) -> bool:
    if user.is_admin():
        return True
    if schedule.tutor_id and schedule.tutor_id == user.id:
        return True
    if schedule.course_id:
        course = db.query(Course).filter(Course.id == schedule.course_id).first()
        return bool(course and course.creator_id == user.id)
    return False


def _make_code() -> str:
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(6))


# ══════════════════════════════════════════════════════════════════
#  Student Routes
# ══════════════════════════════════════════════════════════════════

@router.get("/schedule/{schedule_id}", summary="Get schedule detail")
async def get_schedule(
    schedule_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    return _serialize_schedule(s)


@router.post("/check-in", summary="Self check-in using OTP code")
async def self_check_in(
    payload: AttendanceSelfCheckIn,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Validate the 6-char OTP and mark the student present (or late if
    they arrive more than 15 min after the session start time).
    """
    now = datetime.now(timezone.utc)

    code_row = db.query(AttendanceCheckInCode).filter(
        AttendanceCheckInCode.code          == payload.check_in_code.upper().strip(),
        AttendanceCheckInCode.schedule_id   == payload.schedule_id,
        AttendanceCheckInCode.is_active     == True,
    ).first()

    if not code_row:
        raise HTTPException(400, "Invalid or expired check-in code.")
    if now > code_row.expires_at:
        code_row.is_active = False
        db.commit()
        raise HTTPException(400, "Check-in code has expired.")

    schedule = db.query(Schedule).filter(Schedule.id == payload.schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")

    late_threshold = schedule.start_time + timedelta(minutes=15)
    status = AttendanceStatus.late if now > late_threshold else AttendanceStatus.present

    existing = db.query(AttendanceRecord).filter(
        AttendanceRecord.schedule_id == payload.schedule_id,
        AttendanceRecord.user_id     == user.id,
    ).first()

    if existing:
        existing.status        = status
        existing.check_in_time = now
        record = existing
    else:
        record = AttendanceRecord(
            schedule_id=payload.schedule_id,
            user_id=user.id,
            status=status,
            check_in_time=now,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return _serialize_record(record)


@router.get("/my", summary="My attendance records")
async def my_attendance(
    course_id:   Optional[int] = None,
    schedule_id: Optional[int] = None,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AttendanceRecord).filter(AttendanceRecord.user_id == user.id)
    if schedule_id:
        q = q.filter(AttendanceRecord.schedule_id == schedule_id)
    if course_id:
        q = q.join(Schedule, AttendanceRecord.schedule_id == Schedule.id).filter(
            Schedule.course_id == course_id
        )
    records = q.order_by(AttendanceRecord.check_in_time.desc()).all()
    return [_serialize_record(r) for r in records]


# ══════════════════════════════════════════════════════════════════
#  Tutor / Admin Routes
# ══════════════════════════════════════════════════════════════════

@router.post("/schedule/{schedule_id}/mark",
             summary="Bulk-mark attendance (tutor/admin)")
async def mark_attendance(
    schedule_id: int,
    payload: AttendanceMarkRequest,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upsert one AttendanceRecord per entry in payload.records."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    if not _is_schedule_staff(schedule, user, db):
        raise HTTPException(403, "Access denied")

    now     = datetime.now(timezone.utc)
    results = []
    for item in payload.records:
        existing = db.query(AttendanceRecord).filter(
            AttendanceRecord.schedule_id == schedule_id,
            AttendanceRecord.user_id     == item.user_id,
        ).first()
        if existing:
            existing.status       = item.status
            existing.note         = item.note
            existing.marked_by_id = user.id
            if item.status == AttendanceStatus.present and not existing.check_in_time:
                existing.check_in_time = now
            results.append(existing)
        else:
            rec = AttendanceRecord(
                schedule_id=schedule_id,
                user_id=item.user_id,
                status=item.status,
                note=item.note,
                marked_by_id=user.id,
                check_in_time=now if item.status == AttendanceStatus.present else None,
            )
            db.add(rec)
            results.append(rec)

    db.commit()
    for r in results:
        db.refresh(r)
    return [_serialize_record(r) for r in results]


@router.get("/schedule/{schedule_id}/records",
            summary="List attendance for a session (tutor/admin)")
async def get_schedule_records(
    schedule_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    if not _is_schedule_staff(schedule, user, db):
        raise HTTPException(403, "Access denied")

    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.schedule_id == schedule_id)
        .order_by(AttendanceRecord.user_id)
        .all()
    )
    return [_serialize_record(r) for r in records]


@router.post("/schedule/{schedule_id}/code",
             summary="Generate OTP check-in code (tutor/admin)")
async def generate_checkin_code(
    schedule_id: int,
    ttl_minutes: int = 30,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deactivates any existing active code for this schedule, then issues
    a new 6-character alphanumeric OTP valid for ``ttl_minutes``.
    """
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(404, "Schedule not found")
    if not _is_schedule_staff(schedule, user, db):
        raise HTTPException(403, "Access denied")

    db.query(AttendanceCheckInCode).filter(
        AttendanceCheckInCode.schedule_id == schedule_id,
        AttendanceCheckInCode.is_active   == True,
    ).update({"is_active": False})
    db.flush()

    # Retry to avoid the (extremely unlikely) collision
    for _ in range(5):
        code = _make_code()
        if not db.query(AttendanceCheckInCode).filter(
            AttendanceCheckInCode.code == code
        ).first():
            break

    now        = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=max(1, ttl_minutes))

    code_row = AttendanceCheckInCode(
        code=code,
        schedule_id=schedule_id,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(code_row)
    db.commit()
    db.refresh(code_row)
    return {
        "code":        code_row.code,
        "schedule_id": schedule_id,
        "expires_at":  expires_at,
        "ttl_minutes": ttl_minutes,
    }


@router.get("/course/{course_id}/summary",
            summary="Per-student attendance summary for a course (tutor/admin)")
async def course_attendance_summary(
    course_id: int,
    user: User  = Depends(require_tutor_or_admin),
    db: Session = Depends(get_db),
):
    schedules    = db.query(Schedule).filter(Schedule.course_id == course_id).all()
    schedule_ids = [s.id for s in schedules]
    if not schedule_ids:
        return {"course_id": course_id, "total_sessions": 0, "records": []}

    records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.schedule_id.in_(schedule_ids))
        .all()
    )

    by_user: dict = defaultdict(lambda: {
        "present": 0, "late": 0, "absent": 0, "excused": 0
    })
    for r in records:
        by_user[r.user_id][r.status] += 1

    total = len(schedule_ids)
    summary = [
        {
            "user_id":        uid,
            "present":        counts["present"],
            "late":           counts["late"],
            "absent":         counts["absent"],
            "excused":        counts["excused"],
            "total_sessions": total,
            "attendance_pct": round(
                (counts["present"] + counts["late"]) / total * 100, 1
            ) if total else 0.0,
        }
        for uid, counts in by_user.items()
    ]
    return {"course_id": course_id, "total_sessions": total, "records": summary}


# ══════════════════════════════════════════════════════════════════
#  Creator / Admin CRUD — Schedules
# ══════════════════════════════════════════════════════════════════

@router.get("/course/{course_id}/schedules",
            summary="List schedules for a course")
async def list_course_schedules(
    course_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedules = (
        db.query(Schedule)
        .filter(Schedule.course_id == course_id)
        .order_by(Schedule.start_time)
        .all()
    )
    return [_serialize_schedule(s) for s in schedules]


@router.post("/schedules", status_code=201,
             summary="Create schedule (creator/admin)")
async def create_schedule(
    payload: ScheduleCreate,
    user: User  = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    if payload.course_id:
        course = db.query(Course).filter(Course.id == payload.course_id).first()
        if not course:
            raise HTTPException(404, "Course not found")
        if not user.is_admin() and course.creator_id != user.id:
            raise HTTPException(403, "Access denied")

    s = Schedule(
        title=payload.title,
        description=payload.description,
        course_id=payload.course_id,
        tutor_id=payload.tutor_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        meeting_link=payload.meeting_link,
        is_recurring=payload.is_recurring,
        recurrence_rule=payload.recurrence_rule,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _serialize_schedule(s)


@router.put("/schedules/{schedule_id}",
            summary="Update schedule (creator/admin)")
async def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    user: User  = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    if not _is_schedule_staff(s, user, db):
        raise HTTPException(403, "Access denied")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.commit()
    return _serialize_schedule(s)


@router.delete("/schedules/{schedule_id}",
               summary="Delete schedule (creator/admin)")
async def delete_schedule(
    schedule_id: int,
    user: User  = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    s = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not s:
        raise HTTPException(404, "Schedule not found")
    if not _is_schedule_staff(s, user, db):
        raise HTTPException(403, "Access denied")
    db.delete(s)
    db.commit()
    return {"message": "Schedule deleted"}

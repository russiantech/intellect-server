# v2
from datetime import datetime, timedelta, timezone
import os
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, text

from app.db.database import get_db
from app.models import User, Role
from app.schemas import UserUpdateRequest, AdminUpdateUser
from app.api.deps.auth import get_current_user, require_admin
from app.core.config import get_app_config
from app.api.v1.courses import _absolute_url
from app.models.courses import Course, Topic
from app.models.payments import Enrollment, EnrollmentStatus, PathEnrollment, Payment, PaymentStatus
from app.models.quizzes import AttendanceRecord

router = APIRouter(prefix="/users", tags=["Users"])
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Roles that are publicly listable as instructors/creators
PUBLIC_INSTRUCTOR_ROLES = {"tutor", "creator", "instructor"}

def _avatar_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("http"):
        return path
    cfg = get_app_config()
    base = cfg.hosting_config.api_url.rstrip("/")
    return f"{base}/uploads/avatars/{path}"


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "username": user.username,
        "email": user.email, "phone": user.phone, "image": _avatar_url(user.image),
        "title": user.title, "gender": user.gender, "city": user.city,
        "country": user.country, "lang": user.lang, "about": user.about,
        "socials": user.socials, "education": user.education, "expertise": user.expertise,
        "projects": getattr(user, "projects", None),
        "is_creator": user.is_creator, "creator_bio": user.creator_bio,
        "creator_approved": user.creator_approved, "email_verified": user.email_verified,
        "is_online": user.is_online, "last_seen": user.last_seen,
        "roles": [r.name for r in user.roles], "primary_role": user.primary_role(),
        "bank_name": user.bank_name, "bank_account_number": user.bank_account_number,
        "bank_account_name": user.bank_account_name,
        "active": user.is_active, "created_at": user.created_at,
    }


def _public_instructor_dict(user: User) -> dict:
    """Curated public profile — no sensitive fields."""
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        # "image": user.image,
        "image": _avatar_url(user.image),
        "title": user.title,
        "city": user.city,
        "country": user.country,
        "about": user.about,
        "creator_bio": user.creator_bio,
        "expertise": user.expertise,
        "education": user.education,
        "socials": user.socials,
        "projects": getattr(user, "projects", None),
        "is_creator": user.is_creator,
        "creator_approved": user.creator_approved,
        "is_online": user.is_online,
        "last_seen": user.last_seen,
        "roles": [r.name for r in user.roles],
        "primary_role": user.primary_role(),
        "created_at": user.created_at,
    }


# ─────────────────────────────────────────────────────────────
#  PUBLIC ENDPOINTS  (no authentication required)
# ─────────────────────────────────────────────────────────────

@router.get("/instructors")
async def list_instructors(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,          # 'tutor' | 'creator' | None (all)
    db: Session = Depends(get_db),
):
    """
    Public endpoint — lists approved instructors and creators.
    No authentication required. Safe fields only.
    """
    # Base: active users with at least one instructor-class role
    # q = (
    #     db.query(User)
    #     .join(User.roles)
    #     .filter(
    #         User.is_active == True,
    #         Role.name.in_(PUBLIC_INSTRUCTOR_ROLES),
    #     )
    #     .distinct()
    # )
    
    from sqlalchemy import distinct

    q = (
    db.query(User)
    .join(User.roles)
    .filter(
        User.is_active == True,
        Role.name.in_(PUBLIC_INSTRUCTOR_ROLES),
    )
    .group_by(User.id)
)

    if role and role in PUBLIC_INSTRUCTOR_ROLES:
        q = q.filter(Role.name == role)

    if search:
        q = q.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.username.ilike(f"%{search}%"),
                User.title.ilike(f"%{search}%"),
                User.expertise.ilike(f"%{search}%"),
                User.city.ilike(f"%{search}%"),
            )
        )

    total = q.count()
    users = (
        q.order_by(User.creator_approved.desc(), User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "items": [_public_instructor_dict(u) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/public/{username}")
async def get_public_profile(username: str, db: Session = Depends(get_db)):
    """Public profile — available for any active user; richer data for instructors."""
    user = db.query(User).filter(
        User.username == username,
        User.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _public_instructor_dict(user)


# ─────────────────────────────────────────────────────────────
#  AUTHENTICATED USER ENDPOINTS
# ─────────────────────────────────────────────────────────────

@router.get("/profile")
async def get_my_profile(user: User = Depends(get_current_user)):
    return _user_to_dict(user)


@router.put("/profile")
async def update_profile(
    payload: UserUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, val in payload.model_dump(exclude_none=True).items():
        setattr(user, field, val)
    db.commit()
    db.refresh(user)
    return _user_to_dict(user)


@router.post("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    cfg = get_app_config()
    upload_dir = os.path.join(cfg.hosting_config.content_delivery.filesystem_base_path, "avatars")
    os.makedirs(upload_dir, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_dir, filename)

    content = await file.read()
    if len(content) > cfg.hosting_config.content_delivery.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")

    with open(filepath, "wb") as f:
        f.write(content)

    if user.image and user.image != "default.svg":
        old = os.path.join(upload_dir, user.image)
        if os.path.exists(old):
            os.remove(old)

    user.image = filename
    db.commit()
    # return {"image": filename, "url": f"/uploads/avatars/{filename}"}
    return {
        "image": _avatar_url(filename),   # ← full absolute URL
        "url": _avatar_url(filename),     # ← full absolute URL
    }


# ─────────────────────────────────────────────────────────────
#  ADMIN ENDPOINTS
# ─────────────────────────────────────────────────────────────

@router.get("/", dependencies=[Depends(require_admin)])
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if search:
        q = q.filter(or_(
            User.name.ilike(f"%{search}%"),
            User.email.ilike(f"%{search}%"),
            User.username.ilike(f"%{search}%"),
        ))
    if role:
        q = q.join(User.roles).filter(Role.name == role)
    if active is not None:
        q = q.filter(User.is_active == active)

    total = q.count()
    users = q.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "items": [_user_to_dict(u) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{user_id}", dependencies=[Depends(require_admin)])
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_dict(user)


@router.put("/{user_id}/admin", dependencies=[Depends(require_admin)])
async def admin_update_user(
    user_id: int,
    payload: AdminUpdateUser,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for field, val in payload.model_dump(exclude_none=True, exclude={"roles"}).items():
        setattr(user, field, val)

    if payload.roles is not None:
        roles = db.query(Role).filter(Role.name.in_(payload.roles)).all()
        user.roles = roles

    db.commit()
    db.refresh(user)
    return _user_to_dict(user)


@router.post("/{user_id}/toggle-active", dependencies=[Depends(require_admin)])
async def toggle_user_active(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"active": user.is_active, "message": f"User {'activated' if user.is_active else 'deactivated'}"}


@router.post("/{user_id}/assign-role", dependencies=[Depends(require_admin)])
async def assign_role(user_id: int, role_name: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
    if role not in user.roles:
        user.roles.append(role)
        db.commit()
    return {"message": f"Role '{role_name}' assigned", "roles": [r.name for r in user.roles]}


@router.delete("/{user_id}/remove-role/{role_name}", dependencies=[Depends(require_admin)])
async def remove_role(user_id: int, role_name: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.roles = [r for r in user.roles if r.name != role_name]
    db.commit()
    
    data = {"message": f"Role '{role_name}' removed", "roles": [r.name for r in user.roles]}
    return data


# 

# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN USER ENROLLMENT TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{user_id}/enrollments", dependencies=[Depends(require_admin)])
async def get_user_enrollments(
    user_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Admin view: Get all course enrollments for a specific user.
    Includes progress, payment status, and enrollment history.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    enrollments = db.query(Enrollment).filter(
        Enrollment.user_id == user_id,
    ).options(
        joinedload(Enrollment.course).joinedload(Course.creator),
        joinedload(Enrollment.course).joinedload(Course.categories),
    ).order_by(Enrollment.created_at.desc()).all()

    # Get payment status for each enrollment
    result = []
    for e in enrollments:
        payment = db.query(Payment).filter(
            Payment.user_id == user_id,
            Payment.course_id == e.course_id,
            Payment.tx_status == PaymentStatus.successful,
        ).order_by(Payment.created_at.desc()).first()

        result.append({
            "id": e.id,
            "course": {
                "id": e.course.id,
                "title": e.course.title,
                "slug": e.course.slug,
                "thumbnail": _absolute_url(e.course.thumbnail, "courses/thumbnails"),
                "level": e.course.level,
                "fee": e.course.fee,
                "creator_name": e.course.creator.name if e.course.creator else None,
                "categories": [c.title for c in e.course.categories],
            } if e.course else None,
            "status": e.status.value if hasattr(e.status, 'value') else str(e.status),
            "progress_pct": e.progress_pct,
            "completed_topics": e.completed_topics,
            "admin_assigned": getattr(e, "admin_assigned", False),
            "created_at": e.created_at,
            "completed_at": e.completed_at,
            "deenrolled_at": getattr(e, "deenrolled_at", None),
            "deenrollment_reason": getattr(e, "deenrollment_reason", None),
            "payment": {
                "amount": float(payment.amount) if payment else None,
                "status": payment.tx_status.value if payment and hasattr(payment.tx_status, 'value') else None,
                "paid_at": payment.created_at if payment else None,
                "payment_method": getattr(payment, "payment_method", None),
            },
            "throttle_stats": {
                "topics_this_week": getattr(e, "topics_accessed_this_week", 0),
                "topics_this_month": getattr(e, "topics_accessed_this_month", 0),
                "weekly_limit": e.course.weekly_topic_limit if e.course else None,
                "monthly_limit": e.course.monthly_topic_limit if e.course else None,
            } if e.course and getattr(e.course, "throttle_enabled", False) else None,
        })

    total = len(result)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "username": user.username,
            "image": _avatar_url(user.image),
        },
        "items": result[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{user_id}/path-enrollments", dependencies=[Depends(require_admin)])
async def get_user_path_enrollments(
    user_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    Admin view: Get all learning path enrollments for a specific user.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.user_id == user_id,
    ).options(
        joinedload(PathEnrollment.path),
    ).order_by(PathEnrollment.created_at.desc()).all()

    result = []
    for pe in enrollments:
        # Count completed courses in this path
        path_course_ids = [c.id for c in pe.path.courses] if pe.path and pe.path.courses else []
        completed_courses = db.query(Enrollment).filter(
            Enrollment.user_id == user_id,
            Enrollment.course_id.in_(path_course_ids),
            Enrollment.status == EnrollmentStatus.completed,
        ).count() if path_course_ids else 0

        result.append({
            "id": pe.id,
            "path": {
                "id": pe.path.id,
                "title": pe.path.title,
                "slug": pe.path.slug,
                "thumbnail": pe.path.thumbnail,
                "courses_count": len(pe.path.courses) if pe.path.courses else 0,
                "fee": pe.path.fee,
            } if pe.path else None,
            "status": pe.status.value if hasattr(pe.status, 'value') else str(pe.status),
            "progress_pct": pe.progress_pct,
            "completed_courses": completed_courses,
            "total_courses": len(path_course_ids),
            "created_at": pe.created_at,
            "completed_at": pe.completed_at,
        })

    total = len(result)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "username": user.username,
            "image": _avatar_url(user.image),
        },
        "items": result[start:end],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{user_id}/activity", dependencies=[Depends(require_admin)])
async def get_user_learning_activity(
    user_id: int,
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Admin view: Comprehensive learning activity report for a user.
    Includes topic progress, assessment submissions, attendance, and engagement metrics.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days)

    # Recent topic completions
    recent_completions = db.execute(
        text("""
            SELECT t.title, t.course_id, c.title as course_title, utp.completed_at
            FROM user_topic_progress utp
            JOIN topics t ON utp.topic_id = t.id
            JOIN courses c ON t.course_id = c.id
            WHERE utp.user_id = :uid AND utp.completed = true AND utp.completed_at >= :start
            ORDER BY utp.completed_at DESC
            LIMIT 20
        """),
        {"uid": user_id, "start": period_start},
    ).fetchall()

    # Assessment submissions
    from app.models import LessonAssessmentSubmission
    assessments = db.query(LessonAssessmentSubmission).filter(
        LessonAssessmentSubmission.user_id == user_id,
        LessonAssessmentSubmission.created_at >= period_start,
    ).order_by(LessonAssessmentSubmission.created_at.desc()).limit(20).all()

    # Attendance records
    attendance = db.query(AttendanceRecord).filter(
        AttendanceRecord.user_id == user_id,
        AttendanceRecord.created_at >= period_start,
    ).order_by(AttendanceRecord.created_at.desc()).limit(20).all()

    # Enrollment history
    enrollment_history = db.query(Enrollment).filter(
        Enrollment.user_id == user_id,
    ).order_by(Enrollment.created_at.desc()).all()

    # Calculate engagement score (topics accessed / total topics available)
    total_topics_available = db.query(func.count(Topic.id)).join(Course).join(Enrollment).filter(
        Enrollment.user_id == user_id,
        Enrollment.is_active == True,
    ).scalar() or 0

    total_topics_completed = db.execute(
        text("SELECT COUNT(*) FROM user_topic_progress WHERE user_id = :uid AND completed = true"),
        {"uid": user_id},
    ).scalar() or 0

    engagement_score = round((total_topics_completed / total_topics_available * 100), 1) if total_topics_available > 0 else 0.0

    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "username": user.username,
            "image": _avatar_url(user.image),
        },
        "period_days": period_days,
        "summary": {
            "total_enrollments": len(enrollment_history),
            "active_enrollments": sum(1 for e in enrollment_history if e.is_active),
            "completed_enrollments": sum(1 for e in enrollment_history if getattr(e.status, 'value', str(e.status)) == 'completed'),
            "total_topics_completed": total_topics_completed,
            "engagement_score": engagement_score,
        },
        "recent_topic_completions": [
            {
                "topic_title": r.title,
                "course_title": r.course_title,
                "completed_at": r.completed_at,
            }
            for r in recent_completions
        ],
        "recent_assessments": [
            {
                "id": a.id,
                "assessment_id": a.assessment_id,
                "score": a.score,
                "percentage": a.percentage,
                "passed": a.passed,
                "attempt_number": a.attempt_number,
                "submitted_at": a.submitted_at,
            }
            for a in assessments
        ],
        "recent_attendance": [
            {
                "schedule_id": att.schedule_id,
                "present": att.status,
                "marked_at": att.created_at,
            }
            for att in attendance
        ],
        "enrollment_timeline": [
            {
                "course_id": e.course_id,
                "course_title": e.course.title if e.course else None,
                "status": e.status.value if hasattr(e.status, 'value') else str(e.status),
                "enrolled_at": e.created_at,
                "completed_at": e.completed_at,
                "progress_pct": e.progress_pct,
            }
            for e in enrollment_history[:50]
        ],
    }


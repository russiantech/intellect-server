"""
Intellect LMS — Enrollments, Progress & Learning Paths API
Includes content throttle enforcement for subscription/pay-as-you-go courses.
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.db.database import get_db
from app.models import (
    Enrollment, Course, LearningPath, PathEnrollment,
    User, Topic,
)
from app.enums import CourseStatus
from app.schemas import PathCreate, PathUpdate, SuccessResponse
from app.api.deps.auth import require_admin, optional_user
from app import db
from app.utils.courses import _pricing_fields

router = APIRouter(prefix="/paths", tags=["Learning Paths"])
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# LEARNING PATHS — LIST (with slug-based lookup support)
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize_course_minimal(c: Course) -> dict:
    """Minimal course serialization for path listings."""
    return {
        "id": c.id,
        "title": c.title,
        "slug": c.slug,
        "thumbnail": c.thumbnail,
        "level": c.level,
        "fee": c.fee,
        "payment_type": c.payment_type,
        "lessons_count": len(c.lessons) if c.lessons else 0,
        "topics_count": db.query(Topic).filter(Topic.course_id == c.id).count() if hasattr(c, 'id') else 0,
        "duration_weeks": c.duration_weeks,
        "status": c.status,
    }


def _calculate_path_duration(path: LearningPath, db: Session) -> int:
    """Calculate path duration: use path.duration_weeks if set, otherwise sum course durations."""
    if path.duration_weeks and path.duration_weeks > 0:
        return path.duration_weeks

    total = 0
    for course in path.courses:
        if course.duration_weeks:
            total += course.duration_weeks
    return total


def _calculate_path_stats(path: LearningPath, db: Session) -> dict:
    """Calculate aggregated stats for a learning path."""
    total_lessons = 0
    total_topics = 0
    total_duration = 0

    for course in path.courses:
        total_lessons += len(course.lessons) if course.lessons else 0
        total_topics += db.query(func.count(Topic.id)).filter(Topic.course_id == course.id).scalar() or 0
        total_duration += course.duration_weeks or 0

    return {
        "lessons_count": total_lessons,
        "topics_count": total_topics,
        "duration_weeks": path.duration_weeks or total_duration,
    }


@router.get("/")
async def list_paths(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    q = db.query(LearningPath).filter(
        LearningPath.status == CourseStatus.published, LearningPath.is_active == True,
    )
    if search:
        q = q.filter(LearningPath.title.ilike(f"%{search}%"))

    total = q.with_entities(func.count(LearningPath.id)).scalar()
    paths = q.order_by(LearningPath.created_at.desc())             .offset((page - 1) * per_page)             .limit(per_page)             .all()

    enrolled_ids = set()
    if current_user:
        pes = db.query(PathEnrollment.path_id).filter(
            PathEnrollment.user_id == current_user.id,
        ).all()
        enrolled_ids = {pe.path_id for pe in pes}

    return {
        "items": [
            {
                "id": p.id,
                "title": p.title,
                "slug": p.slug,
                "description": p.description,
                "thumbnail": p.thumbnail,
                "fee": p.fee,
                "payment_type": p.payment_type,
                "courses_count": len(p.courses),
                "course_ids": [c.id for c in p.courses],
                "duration_weeks": _calculate_path_duration(p, db),
                "issues_certificate": p.issues_certificate,
                "is_enrolled": p.id in enrolled_ids,
                # "available_payment_types": _derive_payment_types(p),
                **_pricing_fields(p),
                "instructor_led_fee": getattr(p, 'instructor_led_fee', None),
            }
            for p in paths
        ],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


# def _derive_payment_types(path: LearningPath) -> List[dict]:
#     """Derive available payment types for a path, matching course behavior."""
#     types = []

#     if not path.fee or path.fee == 0:
#         types.append({"payment_type": "free", "fee": 0})
#         return types

#     # Always offer one-time
#     types.append({"payment_type": "one_time", "fee": path.fee})

#     # Subscription if configured
#     if getattr(path, 'subscription_enabled', False):
#         interval = getattr(path, 'subscription_interval', 'monthly')
#         types.append({
#             "payment_type": "subscription",
#             "fee": getattr(path, 'subscription_fee', path.fee * 0.9),
#             "subscription_interval": interval,
#         })

#     # Pay-as-you-go if configured
#     if getattr(path, 'pay_as_you_go_enabled', False):
#         types.append({
#             "payment_type": "pay_as_you_go",
#             "fee": getattr(path, 'pay_as_you_go_fee', path.fee),
#             "access_period_days": getattr(path, 'access_period_days', 30),
#         })

#     return types if types else [{"payment_type": "one_time", "fee": path.fee}]

# v2
# enrollments.py — replace the existing _derive_payment_types function
#
# Problem
# ───────
# The old function gated subscription and pay_as_you_go on boolean flags
# (subscription_enabled / pay_as_you_go_enabled) that the AdminPathsPage
# sets, but were never surfaced to the frontend selector.  More importantly,
# the intended UX is: if a fee is configured for a billing model, that model
# is available for the student to choose — no separate boolean needed.
#
# Rule applied here (mirrors _build_payment_types for courses):
#   • payment_type == 'free'          → only "Free" shown, nothing else
#   • fee > 0                         → "One-time" is available
#   • subscription_fee > 0            → "Subscription" is available
#   • pay_as_you_go_fee > 0           → "Pay-as-you-go" is available
#   • instructor_led_fee > 0          → shown as optional add-on (not a separate pill)
#
# This means admins configure pricing by filling in the fee fields, not by
# toggling booleans.  The boolean columns (subscription_enabled, etc.) are
# kept for backward compatibility but are no longer load-bearing.
#
# Usage: drop this function in to replace _derive_payment_types in
#        enrollments.py.  It is called by list_paths, get_path_by_slug,
#        and get_path — all three already pass the path object.

from typing import List  # already imported in enrollments.py


# INTERVAL_LABELS = {
#     "weekly":    "Weekly",
#     "monthly":   "Monthly",
#     "quarterly": "Quarterly",
#     "yearly":    "Yearly",
# }


# def _derive_payment_types(path) -> List[dict]:
#     """
#     Return every billing option the student may choose for this path.

#     Each entry shape:
#         {
#             "payment_type":          str,
#             "fee":                   float,          # actual charge for this model
#             "subscription_interval": str | None,
#             "access_period_days":    int | None,
#             "label":                 str,
#         }
#     """

#     # ── Free path — nothing else offered ────────────────────────────────
#     pt = getattr(path, "payment_type", None) or "one_time"
#     if pt == "free":
#         return [{"payment_type": "free", "fee": 0, "label": "Free",
#                  "subscription_interval": None, "access_period_days": None}]

#     options: list = []

#     # ── One-time ─────────────────────────────────────────────────────────
#     one_time_fee = float(getattr(path, "fee", None) or 0)
#     if one_time_fee > 0:
#         options.append({
#             "payment_type":          "one_time",
#             "fee":                   one_time_fee,
#             "label":                 "One-time",
#             "subscription_interval": None,
#             "access_period_days":    None,
#         })

#     # ── Subscription ─────────────────────────────────────────────────────
#     sub_fee = float(getattr(path, "subscription_fee", None) or 0)
#     if sub_fee > 0:
#         interval = (getattr(path, "subscription_interval", None) or "monthly").lower()
#         options.append({
#             "payment_type":          "subscription",
#             "fee":                   sub_fee,
#             "label":                 INTERVAL_LABELS.get(interval, "Subscription"),
#             "subscription_interval": interval,
#             "access_period_days":    None,
#         })

#     # ── Pay-as-you-go ────────────────────────────────────────────────────
#     payg_fee = float(getattr(path, "pay_as_you_go_fee", None) or 0)
#     if payg_fee > 0:
#         access_days = int(getattr(path, "access_period_days", None) or 30)
#         options.append({
#             "payment_type":          "pay_as_you_go",
#             "fee":                   payg_fee,
#             "label":                 "Pay-as-you-go",
#             "subscription_interval": None,
#             "access_period_days":    access_days,
#         })

#     # ── Fallback — path has fee but no specific options resolved ─────────
#     # e.g. payment_type='one_time' but fee column is 0 (misconfigured).
#     # Return a single option so the UI never shows nothing.
#     if not options:
#         options.append({
#             "payment_type":          pt,
#             "fee":                   one_time_fee,
#             "label":                 {"one_time": "One-time"}.get(pt, pt),
#             "subscription_interval": None,
#             "access_period_days":    None,
#         })

#     return options


# ═══════════════════════════════════════════════════════════════════════════════
# LEARNING PATHS — DETAIL (slug-based)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/by-slug/{slug}")
async def get_path_by_slug(
    slug: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    """Get path details by slug — primary public endpoint."""
    path = db.query(LearningPath).options(
        joinedload(LearningPath.courses).joinedload(Course.lessons),
    ).filter(
        LearningPath.slug == slug,
        LearningPath.is_active == True,
    ).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")

    is_enrolled = False
    progress_pct = 0

    if current_user:
        pe = db.query(PathEnrollment).filter(
            PathEnrollment.user_id == current_user.id,
            PathEnrollment.path_id == path.id,
        ).first()
        is_enrolled = pe is not None
        if pe:
            progress_pct = pe.progress_pct or 0

    stats = _calculate_path_stats(path, db)

    return {
        "id": path.id,
        "title": path.title,
        "slug": path.slug,
        "description": path.description,
        "thumbnail": path.thumbnail,
        "fee": path.fee,
        "payment_type": path.payment_type,
        "status": path.status,
        "issues_certificate": path.issues_certificate,
        "is_enrolled": is_enrolled,
        "progress_pct": progress_pct,
        "duration_weeks": stats["duration_weeks"],
        "courses_count": len(path.courses),
        "lessons_count": stats["lessons_count"],
        "topics_count": stats["topics_count"],
        # "available_payment_types": _derive_payment_types(path),
        **_pricing_fields(path),
        "instructor_led_fee": getattr(path, 'instructor_led_fee', 0),
        "what_you_achieve": getattr(path, 'what_you_achieve', None),
        "creator": {
            "id": path.created_by_id,
            "name": path.creator.name if hasattr(path, 'creator') and path.creator else None,
            "image": path.creator.image if hasattr(path, 'creator') and path.creator else None,
        } if hasattr(path, 'creator') else None,
        "courses": [
            {
                "id": c.id,
                "title": c.title,
                "slug": c.slug,
                "thumbnail": c.thumbnail,
                "level": c.level,
                "fee": c.fee,
                "payment_type": c.payment_type,
                "lessons_count": len(c.lessons) if c.lessons else 0,
                "topics_count": db.query(func.count(Topic.id)).filter(Topic.course_id == c.id).scalar() or 0,
                "duration_weeks": c.duration_weeks,
                "status": c.status,
                "is_enrolled": db.query(Enrollment).filter(
                    Enrollment.user_id == current_user.id if current_user else None,
                    Enrollment.course_id == c.id,
                ).first() is not None if current_user else False,
            }
            for c in path.courses
        ],
    }


# Keep ID-based endpoint for backward compatibility / admin
@router.get("/{path_id}")
async def get_path(
    path_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    """Get path by ID — primarily for admin/internal use."""
    path = db.query(LearningPath).options(
        joinedload(LearningPath.courses),
    ).filter(LearningPath.id == path_id).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")

    is_enrolled = False
    if current_user:
        pe = db.query(PathEnrollment).filter(
            PathEnrollment.user_id == current_user.id, PathEnrollment.path_id == path_id,
        ).first()
        is_enrolled = pe is not None

    stats = _calculate_path_stats(path, db)

    return {
        "id": path.id,
        "title": path.title,
        "slug": path.slug,
        "description": path.description,
        "thumbnail": path.thumbnail,
        "fee": path.fee,
        "payment_type": path.payment_type,
        "status": path.status,
        "issues_certificate": path.issues_certificate,
        "is_enrolled": is_enrolled,
        "duration_weeks": stats["duration_weeks"],
        "courses_count": len(path.courses),
        "lessons_count": stats["lessons_count"],
        "topics_count": stats["topics_count"],
        # "available_payment_types": _derive_payment_types(path),
        **_pricing_fields(path),
        "instructor_led_fee": getattr(path, 'instructor_led_fee', 0),
        "courses": [
            {
                "id": c.id,
                "title": c.title,
                "slug": c.slug,
                "thumbnail": c.thumbnail,
                "level": c.level,
                "fee": c.fee,
                "lessons_count": len(c.lessons) if c.lessons else 0,
                "topics_count": db.query(func.count(Topic.id)).filter(Topic.course_id == c.id).scalar() or 0,
                "duration_weeks": c.duration_weeks,
            }
            for c in path.courses
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# LEARNING PATHS — ADMIN CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/", dependencies=[Depends(require_admin)], status_code=201)
async def create_path(
    payload: PathCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from slugify import slugify as _slugify

    path = LearningPath(
        title=payload.title,
        description=payload.description,
        fee=payload.fee,
        payment_type=payload.payment_type,
        slug=_slugify(payload.title),
        created_by_id=admin.id,
        issues_certificate=payload.issues_certificate,
        duration_weeks=payload.duration_weeks,
        instructor_led_fee=payload.instructor_led_fee,
        subscription_enabled=payload.subscription_enabled or False,
        subscription_interval=payload.subscription_interval,
        subscription_fee=payload.subscription_fee,
        pay_as_you_go_enabled=payload.pay_as_you_go_enabled,
        pay_as_you_go_fee=payload.pay_as_you_go_fee,
        access_period_days=payload.access_period_days or 30,
        what_you_achieve=payload.what_you_achieve,

        # installment not on LearningPath model yet — add columns if needed
    )

    if payload.course_ids:
        path.courses = db.query(Course).filter(Course.id.in_(payload.course_ids)).all()

    db.add(path)
    db.commit()
    db.refresh(path)

    return {
        "id": path.id,
        "title": path.title,
        "slug": path.slug,
        "courses_count": len(path.courses),
    }


@router.put("/{path_id}", dependencies=[Depends(require_admin)])
async def update_path(
    path_id: int,
    payload: PathUpdate,
    db: Session = Depends(get_db),
):  
    # print(payload)
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")

    # Update scalar fields
    update_data = payload.model_dump(exclude_none=True, exclude={"course_ids"})
    for k, v in update_data.items():
        setattr(path, k, v)
    #     # The current update_path already does this generically — it will
    #     # automatically persist any fields present in the payload schema and
    #     # model, so no further changes are needed there.

    # Update courses if provided
    if payload.course_ids is not None:
        path.courses = db.query(Course).filter(Course.id.in_(payload.course_ids)).all()

    db.commit()
    db.refresh(path)

    return {
        "id": path.id,
        "title": path.title,
        "slug": path.slug,
        "courses_count": len(path.courses),
        "course_ids": [c.id for c in path.courses],
    }


@router.post("/{path_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
async def add_course_to_path(path_id: int, course_id: int, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    course = db.query(Course).filter(Course.id == course_id).first()
    if not path or not course:
        raise HTTPException(status_code=404, detail="Path or course not found")
    if course not in path.courses:
        path.courses.append(course)
        db.commit()
    return SuccessResponse(message="Course added to path")


@router.delete("/{path_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
async def remove_course_from_path(path_id: int, course_id: int, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")
    path.courses = [c for c in path.courses if c.id != course_id]
    db.commit()
    return SuccessResponse(message="Course removed from path")


@router.delete("/{path_id}", dependencies=[Depends(require_admin)])
async def delete_path(path_id: int, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")
    path.is_deleted = True
    path.is_active = False
    db.commit()
    return SuccessResponse(message="Path deleted")


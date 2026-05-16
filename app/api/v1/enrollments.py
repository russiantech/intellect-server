"""
Intellect LMS — Enrollments, Progress & Learning Paths API
Includes content throttle enforcement for subscription/pay-as-you-go courses.
"""
import logging
import uuid as _uuid
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, text

from app.db.database import get_db
from app.models import (
    Enrollment, Course, Payment, LearningPath, PathEnrollment,
    Certificate, User, Topic,
)
from app.models.payments import PaymentStatus, EnrollmentStatus
from app.enums import CourseStatus, CertStatus
from app.schemas import EnrollRequest, ProgressUpdate
from app.api.deps.auth import get_current_user, get_current_verified_user, require_admin
from app.services.email_service import send_enrollment_confirmation
from app.core.config import get_app_config
from app.api.v1.courses import _absolute_url
from app.api.v1.users import _avatar_url
from app.schemas.common import SuccessResponse
from app.schemas.enrollments import DeenrollRequest

router = APIRouter(prefix="/enrollments", tags=["Enrollments & Progress"])
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# ACCESS CONTROL
# ═══════════════════════════════════════════════════════════════════════════════

def _check_access(user, course: Course, db: Session) -> bool:
    """Returns True if user currently has valid access to this course."""
    if not course.fee or course.fee == 0:
        return True

    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.course_id == course.id,
    ).first()

    if not enrollment:
        return False
    if getattr(enrollment, "status", None) == EnrollmentStatus.suspended:
        return False

    # Pay-as-you-go: check valid_until
    if course.payment_type and course.payment_type.value == 'pay_as_you_go':
        valid_until = getattr(enrollment, "valid_until", None)
        if valid_until and valid_until < datetime.now(timezone.utc):
            enrollment.status = EnrollmentStatus.suspended
            db.commit()
            return False

    # One-time / subscription: successful payment required
    paid = db.query(Payment).filter(
        Payment.user_id == user.id,
        Payment.course_id == course.id,
        Payment.tx_status == PaymentStatus.successful,
    ).first()

    return paid is not None


def _check_throttle(enrollment: Enrollment, course: Course, db: Session) -> tuple[bool, str]:
    """Check if user can access the next topic given throttle settings."""
    if not course.throttle_enabled:
        return True, ""

    now = datetime.now(timezone.utc)

    # Reset weekly counter if week has passed
    if enrollment.throttle_week_reset is None or        (now - enrollment.throttle_week_reset) >= timedelta(weeks=1):
        enrollment.topics_accessed_this_week = 0
        enrollment.throttle_week_reset = now

    # Reset monthly counter if month has passed
    if enrollment.throttle_month_reset is None or        (now - enrollment.throttle_month_reset) >= timedelta(days=30):
        enrollment.topics_accessed_this_month = 0
        enrollment.throttle_month_reset = now

    if course.weekly_topic_limit and enrollment.topics_accessed_this_week >= course.weekly_topic_limit:
        reset_time = enrollment.throttle_week_reset + timedelta(weeks=1)
        return False, f"Weekly topic limit reached. Resets on {reset_time.strftime('%b %d, %Y')}."

    if course.monthly_topic_limit and enrollment.topics_accessed_this_month >= course.monthly_topic_limit:
        reset_time = enrollment.throttle_month_reset + timedelta(days=30)
        return False, f"Monthly topic limit reached. Resets on {reset_time.strftime('%b %d, %Y')}."

    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# COURSE ENROLLMENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/enroll")
async def enroll_in_course(
    payload: EnrollRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(
        Course.id == payload.course_id, Course.status == CourseStatus.published,
    ).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found or not published")

    existing = db.query(Enrollment).filter(
        Enrollment.user_id == user.id, Enrollment.course_id == course.id,
    ).first()
    if existing:
        return {"message": "Already enrolled", "enrollment_id": existing.id}

    if not _check_access(user, course, db):
        raise HTTPException(status_code=402, detail="Payment required to enroll")

    enrollment = Enrollment(user_id=user.id, course_id=course.id)
    db.add(enrollment)
    db.commit()
    db.refresh(enrollment)

    cfg = get_app_config()
    course_url = f"{cfg.hosting_config.frontend_url}/learn/{course.slug}"
    background_tasks.add_task(
        send_enrollment_confirmation,
        user.email, user.name or user.username, course.title, course_url,
    )
    return {"message": "Enrolled successfully", "enrollment_id": enrollment.id}


# ═══════════════════════════════════════════════════════════════════════════════
# PATH ENROLLMENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/enroll-path/{path_id}")
async def enroll_in_path(
    path_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    path = db.query(LearningPath).filter(
        LearningPath.id == path_id, LearningPath.status == CourseStatus.published,
    ).first()
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")

    existing = db.query(PathEnrollment).filter(
        PathEnrollment.user_id == user.id, PathEnrollment.path_id == path_id,
    ).first()
    if existing:
        return {"message": "Already enrolled in this path", "path_enrollment_id": existing.id}

    path_enrollment = PathEnrollment(user_id=user.id, path_id=path_id)
    db.add(path_enrollment)
    db.flush()

    for course in path.courses:
        existing_ce = db.query(Enrollment).filter(
            Enrollment.user_id == user.id, Enrollment.course_id == course.id,
        ).first()
        if not existing_ce:
            db.add(Enrollment(
                user_id=user.id, course_id=course.id,
                path_enrollment_id=path_enrollment.id,
            ))

    db.commit()
    return {"message": "Enrolled in learning path", "path_enrollment_id": path_enrollment.id}


# ═══════════════════════════════════════════════════════════════════════════════
# MY ENROLLMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/my-courses")
async def my_enrollments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enrollments = db.query(Enrollment).filter(
        Enrollment.user_id == user.id, Enrollment.is_active == True,
    ).options(joinedload(Enrollment.course).joinedload(Course.categories)).all()

    return [
        {
            "enrollment_id": e.id,
            "course_id": e.course_id,
            "status": e.status,
            "progress_pct": e.progress_pct,
            "completed_topics": e.completed_topics,
            "completed_at": e.completed_at,
            "topics_accessed_this_week": e.topics_accessed_this_week,
            "topics_accessed_this_month": e.topics_accessed_this_month,
            "course": {
                "id": e.course.id, "title": e.course.title, "slug": e.course.slug,
                "thumbnail": e.course.thumbnail, "level": e.course.level,
                "lessons_count": len(e.course.lessons),
                "throttle_enabled": e.course.throttle_enabled,
                "weekly_topic_limit": e.course.weekly_topic_limit,
                "monthly_topic_limit": e.course.monthly_topic_limit,
            } if e.course else None,
        }
        for e in enrollments
    ]


@router.get("/my-paths")
async def my_path_enrollments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    path_enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.user_id == user.id, PathEnrollment.is_active == True,
    ).options(joinedload(PathEnrollment.path)).all()

    return [
        {
            "path_enrollment_id": pe.id,
            "path_id": pe.path_id,
            "status": pe.status,
            "progress_pct": pe.progress_pct,
            "completed_at": pe.completed_at,
            "path": {
                "id": pe.path.id, "title": pe.path.title, "slug": pe.path.slug,
                "thumbnail": pe.path.thumbnail,
                "courses_count": len(pe.path.courses),
            } if pe.path else None,
        }
        for pe in path_enrollments
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESS & THROTTLE
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/progress")
async def mark_topic_complete(
    payload: ProgressUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == payload.topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id, Enrollment.course_id == topic.course_id,
    ).first()
    if not enrollment:
        raise HTTPException(status_code=403, detail="Not enrolled in this course")

    if enrollment.status == EnrollmentStatus.suspended:
        raise HTTPException(status_code=403, detail="Enrollment suspended — please renew your subscription")

    course = db.query(Course).filter(Course.id == topic.course_id).first()

    if payload.completed:
        existing_progress = db.execute(
            text("SELECT completed FROM user_topic_progress WHERE user_id=:uid AND topic_id=:tid"),
            {"uid": user.id, "tid": payload.topic_id},
        ).fetchone()

        if not existing_progress or not existing_progress.completed:
            allowed, reason = _check_throttle(enrollment, course, db)
            if not allowed:
                raise HTTPException(status_code=429, detail=reason)
            enrollment.topics_accessed_this_week += 1
            enrollment.topics_accessed_this_month += 1

    # Upsert topic progress
    existing = db.execute(
        text("SELECT * FROM user_topic_progress WHERE user_id=:uid AND topic_id=:tid"),
        {"uid": user.id, "tid": payload.topic_id},
    ).fetchone()

    if existing:
        db.execute(
            text("UPDATE user_topic_progress SET completed=:c, completed_at=:ts WHERE user_id=:uid AND topic_id=:tid"),
            {"c": payload.completed, "ts": datetime.now(timezone.utc), "uid": user.id, "tid": payload.topic_id},
        )
    else:
        db.execute(
            text("INSERT INTO user_topic_progress(user_id, topic_id, completed, completed_at) VALUES(:uid,:tid,:c,:ts)"),
            {"uid": user.id, "tid": payload.topic_id, "c": payload.completed, "ts": datetime.now(timezone.utc)},
        )

    # Recalculate progress
    total = db.query(Topic).filter(Topic.course_id == topic.course_id).count()
    completed_count = db.execute(
        text("""
            SELECT COUNT(*) FROM user_topic_progress utp
            JOIN topics t ON utp.topic_id = t.id
            WHERE utp.user_id=:uid AND t.course_id=:cid AND utp.completed=true
        """),
        {"uid": user.id, "cid": topic.course_id},
    ).scalar()

    pct = round((completed_count / total) * 100, 1) if total > 0 else 0.0
    enrollment.progress_pct = pct
    enrollment.completed_topics = completed_count

    if pct >= 100 and not enrollment.completed_at:
        enrollment.status = EnrollmentStatus.completed
        enrollment.completed_at = datetime.now(timezone.utc)
        cert = await _issue_certificate(user, topic.course_id, None, db)

    db.commit()
    return {
        "progress_pct": pct,
        "completed_topics": completed_count,
        "total_topics": total,
        "topics_accessed_this_week": enrollment.topics_accessed_this_week,
        "topics_accessed_this_month": enrollment.topics_accessed_this_month,
        "weekly_limit": course.weekly_topic_limit,
        "monthly_limit": course.monthly_topic_limit,
    }


@router.get("/check-throttle/{course_id}")
async def check_throttle_status(
    course_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id == user.id, Enrollment.course_id == course_id,
    ).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Not enrolled")
    course = db.query(Course).filter(Course.id == course_id).first()
    allowed, reason = _check_throttle(enrollment, course, db)
    return {
        "throttle_enabled": course.throttle_enabled,
        "weekly_limit": course.weekly_topic_limit,
        "monthly_limit": course.monthly_topic_limit,
        "topics_this_week": enrollment.topics_accessed_this_week,
        "topics_this_month": enrollment.topics_accessed_this_month,
        "can_access": allowed,
        "reason": reason,
    }


async def _issue_certificate(user: User, course_id: int, path_id: Optional[int], db: Session):
    existing = db.query(Certificate).filter(
        Certificate.user_id == user.id,
        Certificate.course_id == course_id,
    ).first()
    if existing:
        return existing
    cert_num = f"ILT-{_uuid.uuid4().hex[:12].upper()}"
    cert = Certificate(
        cert_number=cert_num, user_id=user.id,
        course_id=course_id, path_id=path_id,
        status=CertStatus.issued,
    )
    db.add(cert)
    db.flush()
    return cert


@router.get("/certificates")
async def my_certificates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    certs = db.query(Certificate).filter(
        Certificate.user_id == user.id, Certificate.status == CertStatus.issued,
    ).options(joinedload(Certificate.course)).all()
    return [
        {
            "id": c.id, "cert_number": c.cert_number, "cert_url": c.cert_url,
            "issued_at": c.issued_at, "status": c.status,
            "course_id": c.course_id, "path_id": c.path_id,
            "course": {"id": c.course.id, "title": c.course.title, "slug": c.course.slug} if c.course else None,
        }
        for c in certs
    ]



# # ═══════════════════════════════════════════════════════════════════════════════
# # ADMIN ENROLLMENT MANAGEMENT — Course & Path
# # ═══════════════════════════════════════════════════════════════════════════════

# @router.get("/courses", dependencies=[Depends(require_admin)])
# async def list_course_enrollments(
#     course_id: Optional[int] = None,
#     user_id: Optional[int] = None,
#     status: Optional[str] = None,
#     page: int = Query(1, ge=1),
#     per_page: int = Query(20, ge=1, le=100),
#     db: Session = Depends(get_db),
# ):
#     """
#     List all course enrollments with filtering.
#     Returns enrollment details including student info, progress, and payment status.
#     """
#     q = db.query(Enrollment).options(
#         joinedload(Enrollment.user),
#         joinedload(Enrollment.course).joinedload(Course.creator),
#     )

#     if course_id:
#         q = q.filter(Enrollment.course_id == course_id)
#     if user_id:
#         q = q.filter(Enrollment.user_id == user_id)
#     if status:
#         q = q.filter(Enrollment.status == status)

#     total = q.count()
#     enrollments = q.order_by(Enrollment.created_at.desc())\
#         .offset((page - 1) * per_page)\
#         .limit(per_page)\
#         .all()

#     return {
#         "items": [
#             {
#                 "id": e.id,
#                 "user": {
#                     "id": e.user.id,
#                     "name": e.user.name,
#                     "email": e.user.email,
#                     "username": e.user.username,
#                     "image": _avatar_url(e.user.image),
#                 } if e.user else None,
#                 "course": {
#                     "id": e.course.id,
#                     "title": e.course.title,
#                     "slug": e.course.slug,
#                     "thumbnail": _absolute_url(e.course.thumbnail, "courses/thumbnails"),
#                     "creator_name": e.course.creator.name if e.course.creator else None,
#                 } if e.course else None,
#                 "status": e.status.value if hasattr(e.status, 'value') else str(e.status),
#                 "progress_pct": e.progress_pct,
#                 "completed_topics": e.completed_topics,
#                 "admin_assigned": getattr(e, "admin_assigned", False),
#                 "created_at": e.created_at,
#                 "completed_at": e.completed_at,
#                 "topics_accessed_this_week": getattr(e, "topics_accessed_this_week", 0),
#                 "topics_accessed_this_month": getattr(e, "topics_accessed_this_month", 0),
#             }
#             for e in enrollments
#         ],
#         "total": total,
#         "page": page,
#         "per_page": per_page,
#         "pages": (total + per_page - 1) // per_page,
#     }


# @router.get("/paths", dependencies=[Depends(require_admin)])
# async def list_path_enrollments(
#     path_id: Optional[int] = None,
#     user_id: Optional[int] = None,
#     page: int = Query(1, ge=1),
#     per_page: int = Query(20, ge=1, le=100),
#     db: Session = Depends(get_db),
# ):
#     """
#     List all learning path enrollments with filtering.
#     """
#     q = db.query(PathEnrollment).options(
#         joinedload(PathEnrollment.user),
#         joinedload(PathEnrollment.path),
#     )

#     if path_id:
#         q = q.filter(PathEnrollment.path_id == path_id)
#     if user_id:
#         q = q.filter(PathEnrollment.user_id == user_id)

#     total = q.count()
#     enrollments = q.order_by(PathEnrollment.created_at.desc())\
#         .offset((page - 1) * per_page)\
#         .limit(per_page)\
#         .all()

#     return {
#         "items": [
#             {
#                 "id": pe.id,
#                 "user": {
#                     "id": pe.user.id,
#                     "name": pe.user.name,
#                     "email": pe.user.email,
#                     "username": pe.user.username,
#                     "image": _avatar_url(pe.user.image),
#                 } if pe.user else None,
#                 "path": {
#                     "id": pe.path.id,
#                     "title": pe.path.title,
#                     "slug": pe.path.slug,
#                     "thumbnail": pe.path.thumbnail,
#                     "courses_count": len(pe.path.courses) if pe.path.courses else 0,
#                 } if pe.path else None,
#                 "status": pe.status.value if hasattr(pe.status, 'value') else str(pe.status),
#                 "progress_pct": pe.progress_pct,
#                 "created_at": pe.created_at,
#                 "completed_at": pe.completed_at,
#             }
#             for pe in enrollments
#         ],
#         "total": total,
#         "page": page,
#         "per_page": per_page,
#         "pages": (total + per_page - 1) // per_page,
#     }


# @router.post("/courses/{enrollment_id}/deenroll", dependencies=[Depends(require_admin)])
# async def deenroll_from_course(
#     enrollment_id: int,
#     payload: DeenrollRequest,
#     db: Session = Depends(get_db),
# ):
#     """
#     Admin de-enroll a student from a course.
#     Also removes associated payments (refund logic handled separately).
#     """
#     enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
#     if not enrollment:
#         raise HTTPException(status_code=404, detail="Enrollment not found")

#     course = enrollment.course
#     user = enrollment.user

#     # Soft delete — mark as inactive rather than hard delete for audit trail
#     enrollment.is_active = False
#     enrollment.status = EnrollmentStatus.suspended
#     enrollment.deenrolled_at = datetime.now(timezone.utc)
#     enrollment.deenrollment_reason = payload.reason
#     enrollment.deenrolled_by_id = payload.user_id  # Admin user ID from token

#     db.commit()

#     logger.info(
#         "Admin de-enrolled user %s from course %s. Reason: %s",
#         user.id if user else "unknown",
#         course.id if course else "unknown",
#         payload.reason,
#     )

#     return SuccessResponse(
#         message=f"User de-enrolled from '{course.title if course else 'course'}' successfully"
#     )


# @router.post("/paths/{path_enrollment_id}/deenroll", dependencies=[Depends(require_admin)])
# async def deenroll_from_path(
#     path_enrollment_id: int,
#     payload: DeenrollRequest,
#     db: Session = Depends(get_db),
# ):
#     """
#     Admin de-enroll a student from a learning path.
#     Also de-enrolls from all associated courses in the path.
#     """
#     path_enrollment = db.query(PathEnrollment).filter(PathEnrollment.id == path_enrollment_id).first()
#     if not path_enrollment:
#         raise HTTPException(status_code=404, detail="Path enrollment not found")

#     path = path_enrollment.path
#     user = path_enrollment.user

#     # De-enroll from all courses in the path
#     if path and path.courses:
#         for course in path.courses:
#             course_enrollment = db.query(Enrollment).filter(
#                 Enrollment.user_id == user.id,
#                 Enrollment.course_id == course.id,
#                 Enrollment.path_enrollment_id == path_enrollment.id,
#             ).first()
#             if course_enrollment:
#                 course_enrollment.is_active = False
#                 course_enrollment.status = EnrollmentStatus.suspended

#     # Soft delete path enrollment
#     path_enrollment.is_active = False
#     path_enrollment.status = EnrollmentStatus.suspended
#     path_enrollment.deenrolled_at = datetime.now(timezone.utc)
#     path_enrollment.deenrollment_reason = payload.reason

#     db.commit()

#     return SuccessResponse(
#         message=f"User de-enrolled from path '{path.title if path else 'path'}' and all associated courses"
#     )


# @router.get("/analytics/courses/{course_id}", dependencies=[Depends(require_admin)])
# async def get_course_enrollment_analytics(
#     course_id: int,
#     period_days: int = Query(30, ge=1, le=365),
#     db: Session = Depends(get_db),
# ):
#     """
#     Comprehensive analytics for a specific course:
#     - Enrollment trends over time
#     - Completion rates
#     - Student engagement (topics accessed)
#     - Revenue from enrollments
#     - Demographics (if available)
#     """
#     course = db.query(Course).filter(Course.id == course_id).first()
#     if not course:
#         raise HTTPException(status_code=404, detail="Course not found")

#     now = datetime.now(timezone.utc)
#     period_start = now - timedelta(days=period_days)

#     # Total enrollments
#     total_enrollments = db.query(Enrollment).filter(Enrollment.course_id == course_id).count()
#     active_enrollments = db.query(Enrollment).filter(
#         Enrollment.course_id == course_id,
#         Enrollment.is_active == True,
#     ).count()
#     completed_enrollments = db.query(Enrollment).filter(
#         Enrollment.course_id == course_id,
#         Enrollment.status == EnrollmentStatus.completed,
#     ).count()

#     # New enrollments in period
#     new_enrollments = db.query(Enrollment).filter(
#         Enrollment.course_id == course_id,
#         Enrollment.created_at >= period_start,
#     ).count()

#     # Average progress
#     avg_progress = db.query(func.avg(Enrollment.progress_pct)).filter(
#         Enrollment.course_id == course_id,
#         Enrollment.is_active == True,
#     ).scalar() or 0.0

#     # Revenue from this course
#     course_revenue = db.query(func.sum(Payment.amount)).filter(
#         Payment.course_id == course_id,
#         Payment.tx_status == PaymentStatus.successful,
#         Payment.created_at >= period_start,
#     ).scalar() or 0.0

#     # Daily enrollment trend
#     daily_trend = []
#     for i in range(period_days - 1, -1, -1):
#         day = now - timedelta(days=i)
#         day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
#         day_end = day_start + timedelta(days=1)
#         count = db.query(Enrollment).filter(
#             Enrollment.course_id == course_id,
#             Enrollment.created_at >= day_start,
#             Enrollment.created_at < day_end,
#         ).count()
#         daily_trend.append({
#             "date": day.strftime("%Y-%m-%d"),
#             "enrollments": count,
#         })

#     # Top students by progress
#     top_students = db.query(Enrollment).filter(
#         Enrollment.course_id == course_id,
#         Enrollment.is_active == True,
#     ).order_by(Enrollment.progress_pct.desc()).limit(10).all()

#     return {
#         "course_id": course_id,
#         "course_title": course.title,
#         "period_days": period_days,
#         "summary": {
#             "total_enrollments": total_enrollments,
#             "active_enrollments": active_enrollments,
#             "completed_enrollments": completed_enrollments,
#             "completion_rate": round((completed_enrollments / total_enrollments * 100), 1) if total_enrollments > 0 else 0.0,
#             "new_enrollments_in_period": new_enrollments,
#             "average_progress_pct": round(float(avg_progress), 1),
#             "revenue_in_period": float(course_revenue),
#         },
#         "daily_enrollment_trend": daily_trend,
#         "top_performers": [
#             {
#                 "user_id": e.user_id,
#                 "name": e.user.name if e.user else None,
#                 "progress_pct": e.progress_pct,
#                 "completed_topics": e.completed_topics,
#             }
#             for e in top_students
#         ],
#     }


# @router.get("/analytics/paths/{path_id}", dependencies=[Depends(require_admin)])
# async def get_path_enrollment_analytics(
#     path_id: int,
#     period_days: int = Query(30, ge=1, le=365),
#     db: Session = Depends(get_db),
# ):
#     """
#     Comprehensive analytics for a specific learning path.
#     """
#     path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
#     if not path:
#         raise HTTPException(status_code=404, detail="Learning path not found")

#     now = datetime.now(timezone.utc)
#     period_start = now - timedelta(days=period_days)

#     total_enrollments = db.query(PathEnrollment).filter(PathEnrollment.path_id == path_id).count()
#     active_enrollments = db.query(PathEnrollment).filter(
#         PathEnrollment.path_id == path_id,
#         PathEnrollment.is_active == True,
#     ).count()
#     completed = db.query(PathEnrollment).filter(
#         PathEnrollment.path_id == path_id,
#         PathEnrollment.status == EnrollmentStatus.completed,
#     ).count()

#     new_in_period = db.query(PathEnrollment).filter(
#         PathEnrollment.path_id == path_id,
#         PathEnrollment.created_at >= period_start,
#     ).count()

#     avg_progress = db.query(func.avg(PathEnrollment.progress_pct)).filter(
#         PathEnrollment.path_id == path_id,
#         PathEnrollment.is_active == True,
#     ).scalar() or 0.0

#     daily_trend = []
#     for i in range(period_days - 1, -1, -1):
#         day = now - timedelta(days=i)
#         day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
#         day_end = day_start + timedelta(days=1)
#         count = db.query(PathEnrollment).filter(
#             PathEnrollment.path_id == path_id,
#             PathEnrollment.created_at >= day_start,
#             PathEnrollment.created_at < day_end,
#         ).count()
#         daily_trend.append({"date": day.strftime("%Y-%m-%d"), "enrollments": count})

#     return {
#         "path_id": path_id,
#         "path_title": path.title,
#         "period_days": period_days,
#         "summary": {
#             "total_enrollments": total_enrollments,
#             "active_enrollments": active_enrollments,
#             "completed_enrollments": completed,
#             "completion_rate": round((completed / total_enrollments * 100), 1) if total_enrollments > 0 else 0.0,
#             "new_enrollments_in_period": new_in_period,
#             "average_progress_pct": round(float(avg_progress), 1),
#         },
#         "daily_enrollment_trend": daily_trend,
#     }


# @router.get("/analytics/global", dependencies=[Depends(require_admin)])
# async def get_global_enrollment_analytics(
#     period_days: int = Query(30, ge=1, le=365),
#     db: Session = Depends(get_db),
# ):
#     """
#     Global enrollment analytics across all courses and paths.
#     """
#     now = datetime.now(timezone.utc)
#     period_start = now - timedelta(days=period_days)

#     # Course enrollments
#     total_course_enrollments = db.query(Enrollment).count()
#     active_course_enrollments = db.query(Enrollment).filter(Enrollment.is_active == True).count()
#     new_course_enrollments = db.query(Enrollment).filter(Enrollment.created_at >= period_start).count()

#     # Path enrollments
#     total_path_enrollments = db.query(PathEnrollment).count()
#     active_path_enrollments = db.query(PathEnrollment).filter(PathEnrollment.is_active == True).count()
#     new_path_enrollments = db.query(PathEnrollment).filter(PathEnrollment.created_at >= period_start).count()

#     # Revenue
#     total_revenue = db.query(func.sum(Payment.amount)).filter(
#         Payment.tx_status == PaymentStatus.successful,
#         Payment.created_at >= period_start,
#     ).scalar() or 0.0

#     # Top courses by enrollment
#     top_courses = db.query(
#         Course.id, Course.title, func.count(Enrollment.id).label("enrollment_count")
#     ).join(Enrollment, Enrollment.course_id == Course.id)\
#         .filter(Enrollment.created_at >= period_start)\
#         .group_by(Course.id, Course.title)\
#         .order_by(func.count(Enrollment.id).desc())\
#         .limit(10)\
#         .all()

#     # Top paths by enrollment
#     top_paths = db.query(
#         LearningPath.id, LearningPath.title, func.count(PathEnrollment.id).label("enrollment_count")
#     ).join(PathEnrollment, PathEnrollment.path_id == LearningPath.id)\
#         .filter(PathEnrollment.created_at >= period_start)\
#         .group_by(LearningPath.id, LearningPath.title)\
#         .order_by(func.count(PathEnrollment.id).desc())\
#         .limit(10)\
#         .all()

#     return {
#         "period_days": period_days,
#         "courses": {
#             "total_enrollments": total_course_enrollments,
#             "active_enrollments": active_course_enrollments,
#             "new_in_period": new_course_enrollments,
#         },
#         "paths": {
#             "total_enrollments": total_path_enrollments,
#             "active_enrollments": active_path_enrollments,
#             "new_in_period": new_path_enrollments,
#         },
#         "revenue_in_period": float(total_revenue),
#         "top_courses": [
#             {"id": c.id, "title": c.title, "enrollments": c.enrollment_count}
#             for c in top_courses
#         ],
#         "top_paths": [
#             {"id": p.id, "title": p.title, "enrollments": p.enrollment_count}
#             for p in top_paths
#         ],
#     }
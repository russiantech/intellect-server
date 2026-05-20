# """
# Intellect LMS — Enrollments, Progress & Learning Paths API
# Includes content throttle enforcement for subscription/pay-as-you-go courses.
# """
# import logging
# import uuid as _uuid
# from typing import Optional
# from datetime import datetime, timezone, timedelta
# from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
# from sqlalchemy.orm import Session, joinedload
# from sqlalchemy import text

# from app.db.database import get_db
# from app.models import (
#     Enrollment, Course, Payment, LearningPath, PathEnrollment,
#     Certificate, User, Topic,
# )
# from app.models.payments import PaymentStatus, EnrollmentStatus
# from app.enums import CourseStatus, CertStatus
# from app.schemas import EnrollRequest, ProgressUpdate
# from app.api.deps.auth import get_current_user, get_current_verified_user
# from app.services.email_service import send_enrollment_confirmation
# from app.core.config import get_app_config

# router = APIRouter(prefix="/enrollments", tags=["Enrollments & Progress"])
# logger = logging.getLogger(__name__)


# # ═══════════════════════════════════════════════════════════════════════════════
# # ACCESS CONTROL
# # ═══════════════════════════════════════════════════════════════════════════════

# def _check_access(user, course: Course, db: Session) -> bool:
#     """Returns True if user currently has valid access to this course."""
#     if not course.fee or course.fee == 0:
#         return True

#     enrollment = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id,
#         Enrollment.course_id == course.id,
#     ).first()

#     if not enrollment:
#         return False
#     if getattr(enrollment, "status", None) == EnrollmentStatus.suspended:
#         return False

#     # Pay-as-you-go: check valid_until
#     if course.payment_type and course.payment_type.value == 'pay_as_you_go':
#         valid_until = getattr(enrollment, "valid_until", None)
#         if valid_until and valid_until < datetime.now(timezone.utc):
#             enrollment.status = EnrollmentStatus.suspended
#             db.commit()
#             return False

#     # One-time / subscription: successful payment required
#     paid = db.query(Payment).filter(
#         Payment.user_id == user.id,
#         Payment.course_id == course.id,
#         Payment.tx_status == PaymentStatus.successful,
#     ).first()

#     return paid is not None


# def _check_throttle(enrollment: Enrollment, course: Course, db: Session) -> tuple[bool, str]:
#     """Check if user can access the next topic given throttle settings."""
#     if not course.throttle_enabled:
#         return True, ""

#     now = datetime.now(timezone.utc)

#     # Reset weekly counter if week has passed
#     if enrollment.throttle_week_reset is None or        (now - enrollment.throttle_week_reset) >= timedelta(weeks=1):
#         enrollment.topics_accessed_this_week = 0
#         enrollment.throttle_week_reset = now

#     # Reset monthly counter if month has passed
#     if enrollment.throttle_month_reset is None or        (now - enrollment.throttle_month_reset) >= timedelta(days=30):
#         enrollment.topics_accessed_this_month = 0
#         enrollment.throttle_month_reset = now

#     if course.weekly_topic_limit and enrollment.topics_accessed_this_week >= course.weekly_topic_limit:
#         reset_time = enrollment.throttle_week_reset + timedelta(weeks=1)
#         return False, f"Weekly topic limit reached. Resets on {reset_time.strftime('%b %d, %Y')}."

#     if course.monthly_topic_limit and enrollment.topics_accessed_this_month >= course.monthly_topic_limit:
#         reset_time = enrollment.throttle_month_reset + timedelta(days=30)
#         return False, f"Monthly topic limit reached. Resets on {reset_time.strftime('%b %d, %Y')}."

#     return True, ""


# # ═══════════════════════════════════════════════════════════════════════════════
# # COURSE ENROLLMENT
# # ═══════════════════════════════════════════════════════════════════════════════

# @router.post("/enroll")
# async def enroll_in_course(
#     payload: EnrollRequest,
#     background_tasks: BackgroundTasks,
#     user: User = Depends(get_current_verified_user),
#     db: Session = Depends(get_db),
# ):
#     course = db.query(Course).filter(
#         Course.id == payload.course_id, Course.status == CourseStatus.published,
#     ).first()
#     if not course:
#         raise HTTPException(status_code=404, detail="Course not found or not published")

#     existing = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id, Enrollment.course_id == course.id,
#     ).first()
#     if existing:
#         return {"message": "Already enrolled", "enrollment_id": existing.id}

#     if not _check_access(user, course, db):
#         raise HTTPException(status_code=402, detail="Payment required to enroll")

#     enrollment = Enrollment(user_id=user.id, course_id=course.id)
#     db.add(enrollment)
#     db.commit()
#     db.refresh(enrollment)

#     cfg = get_app_config()
#     course_url = f"{cfg.hosting_config.frontend_url}/learn/{course.slug}"
#     background_tasks.add_task(
#         send_enrollment_confirmation,
#         user.email, user.name or user.username, course.title, course_url,
#     )
#     return {"message": "Enrolled successfully", "enrollment_id": enrollment.id}


# # ═══════════════════════════════════════════════════════════════════════════════
# # PATH ENROLLMENT
# # ═══════════════════════════════════════════════════════════════════════════════

# @router.post("/enroll-path/{path_id}")
# async def enroll_in_path(
#     path_id: int,
#     background_tasks: BackgroundTasks,
#     user: User = Depends(get_current_verified_user),
#     db: Session = Depends(get_db),
# ):
#     path = db.query(LearningPath).filter(
#         LearningPath.id == path_id, LearningPath.status == CourseStatus.published,
#     ).first()
#     if not path:
#         raise HTTPException(status_code=404, detail="Learning path not found")

#     existing = db.query(PathEnrollment).filter(
#         PathEnrollment.user_id == user.id, PathEnrollment.path_id == path_id,
#     ).first()
#     if existing:
#         return {"message": "Already enrolled in this path", "path_enrollment_id": existing.id}

#     path_enrollment = PathEnrollment(user_id=user.id, path_id=path_id)
#     db.add(path_enrollment)
#     db.flush()

#     for course in path.courses:
#         existing_ce = db.query(Enrollment).filter(
#             Enrollment.user_id == user.id, Enrollment.course_id == course.id,
#         ).first()
#         if not existing_ce:
#             db.add(Enrollment(
#                 user_id=user.id, course_id=course.id,
#                 path_enrollment_id=path_enrollment.id,
#             ))

#     db.commit()
#     return {"message": "Enrolled in learning path", "path_enrollment_id": path_enrollment.id}


# # ═══════════════════════════════════════════════════════════════════════════════
# # MY ENROLLMENTS
# # ═══════════════════════════════════════════════════════════════════════════════

# @router.get("/my-courses")
# async def my_enrollments(
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     enrollments = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id, Enrollment.is_active == True,
#     ).options(joinedload(Enrollment.course).joinedload(Course.categories)).all()

#     return [
#         {
#             "enrollment_id": e.id,
#             "course_id": e.course_id,
#             "status": e.status,
#             "progress_pct": e.progress_pct,
#             "completed_topics": e.completed_topics,
#             "completed_at": e.completed_at,
#             "topics_accessed_this_week": e.topics_accessed_this_week,
#             "topics_accessed_this_month": e.topics_accessed_this_month,
#             "course": {
#                 "id": e.course.id, "title": e.course.title, "slug": e.course.slug,
#                 "thumbnail": e.course.thumbnail, "level": e.course.level,
#                 "lessons_count": len(e.course.lessons),
#                 "throttle_enabled": e.course.throttle_enabled,
#                 "weekly_topic_limit": e.course.weekly_topic_limit,
#                 "monthly_topic_limit": e.course.monthly_topic_limit,
#             } if e.course else None,
#         }
#         for e in enrollments
#     ]


# @router.get("/my-paths")
# async def my_path_enrollments(
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     path_enrollments = db.query(PathEnrollment).filter(
#         PathEnrollment.user_id == user.id, PathEnrollment.is_active == True,
#     ).options(joinedload(PathEnrollment.path)).all()

#     return [
#         {
#             "path_enrollment_id": pe.id,
#             "path_id": pe.path_id,
#             "status": pe.status,
#             "progress_pct": pe.progress_pct,
#             "completed_at": pe.completed_at,
#             "path": {
#                 "id": pe.path.id, "title": pe.path.title, "slug": pe.path.slug,
#                 "thumbnail": pe.path.thumbnail,
#                 "courses_count": len(pe.path.courses),
#             } if pe.path else None,
#         }
#         for pe in path_enrollments
#     ]


# # ═══════════════════════════════════════════════════════════════════════════════
# # PROGRESS & THROTTLE
# # ═══════════════════════════════════════════════════════════════════════════════

# @router.post("/progress")
# async def mark_topic_complete(
#     payload: ProgressUpdate,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     topic = db.query(Topic).filter(Topic.id == payload.topic_id).first()
#     if not topic:
#         raise HTTPException(status_code=404, detail="Topic not found")

#     enrollment = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id, Enrollment.course_id == topic.course_id,
#     ).first()
#     if not enrollment:
#         raise HTTPException(status_code=403, detail="Not enrolled in this course")

#     if enrollment.status == EnrollmentStatus.suspended:
#         raise HTTPException(status_code=403, detail="Enrollment suspended — please renew your subscription")

#     course = db.query(Course).filter(Course.id == topic.course_id).first()

#     if payload.completed:
#         existing_progress = db.execute(
#             text("SELECT completed FROM user_topic_progress WHERE user_id=:uid AND topic_id=:tid"),
#             {"uid": user.id, "tid": payload.topic_id},
#         ).fetchone()

#         if not existing_progress or not existing_progress.completed:
#             allowed, reason = _check_throttle(enrollment, course, db)
#             if not allowed:
#                 raise HTTPException(status_code=429, detail=reason)
#             enrollment.topics_accessed_this_week += 1
#             enrollment.topics_accessed_this_month += 1

#     # Upsert topic progress
#     existing = db.execute(
#         text("SELECT * FROM user_topic_progress WHERE user_id=:uid AND topic_id=:tid"),
#         {"uid": user.id, "tid": payload.topic_id},
#     ).fetchone()

#     if existing:
#         db.execute(
#             text("UPDATE user_topic_progress SET completed=:c, completed_at=:ts WHERE user_id=:uid AND topic_id=:tid"),
#             {"c": payload.completed, "ts": datetime.now(timezone.utc), "uid": user.id, "tid": payload.topic_id},
#         )
#     else:
#         db.execute(
#             text("INSERT INTO user_topic_progress(user_id, topic_id, completed, completed_at) VALUES(:uid,:tid,:c,:ts)"),
#             {"uid": user.id, "tid": payload.topic_id, "c": payload.completed, "ts": datetime.now(timezone.utc)},
#         )

#     # Recalculate progress
#     total = db.query(Topic).filter(Topic.course_id == topic.course_id).count()
#     completed_count = db.execute(
#         text("""
#             SELECT COUNT(*) FROM user_topic_progress utp
#             JOIN topics t ON utp.topic_id = t.id
#             WHERE utp.user_id=:uid AND t.course_id=:cid AND utp.completed=true
#         """),
#         {"uid": user.id, "cid": topic.course_id},
#     ).scalar()

#     pct = round((completed_count / total) * 100, 1) if total > 0 else 0.0
#     enrollment.progress_pct = pct
#     enrollment.completed_topics = completed_count

#     if pct >= 100 and not enrollment.completed_at:
#         enrollment.status = EnrollmentStatus.completed
#         enrollment.completed_at = datetime.now(timezone.utc)
#         cert = await _issue_certificate(user, topic.course_id, None, db)

#     db.commit()
#     return {
#         "progress_pct": pct,
#         "completed_topics": completed_count,
#         "total_topics": total,
#         "topics_accessed_this_week": enrollment.topics_accessed_this_week,
#         "topics_accessed_this_month": enrollment.topics_accessed_this_month,
#         "weekly_limit": course.weekly_topic_limit,
#         "monthly_limit": course.monthly_topic_limit,
#     }


# @router.get("/check-throttle/{course_id}")
# async def check_throttle_status(
#     course_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     enrollment = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id, Enrollment.course_id == course_id,
#     ).first()
#     if not enrollment:
#         raise HTTPException(status_code=404, detail="Not enrolled")
#     course = db.query(Course).filter(Course.id == course_id).first()
#     allowed, reason = _check_throttle(enrollment, course, db)
#     return {
#         "throttle_enabled": course.throttle_enabled,
#         "weekly_limit": course.weekly_topic_limit,
#         "monthly_limit": course.monthly_topic_limit,
#         "topics_this_week": enrollment.topics_accessed_this_week,
#         "topics_this_month": enrollment.topics_accessed_this_month,
#         "can_access": allowed,
#         "reason": reason,
#     }


# async def _issue_certificate(user: User, course_id: int, path_id: Optional[int], db: Session):
#     existing = db.query(Certificate).filter(
#         Certificate.user_id == user.id,
#         Certificate.course_id == course_id,
#     ).first()
#     if existing:
#         return existing
#     cert_num = f"ILT-{_uuid.uuid4().hex[:12].upper()}"
#     cert = Certificate(
#         cert_number=cert_num, user_id=user.id,
#         course_id=course_id, path_id=path_id,
#         status=CertStatus.issued,
#     )
#     db.add(cert)
#     db.flush()
#     return cert


# @router.get("/certificates")
# async def my_certificates(
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     certs = db.query(Certificate).filter(
#         Certificate.user_id == user.id, Certificate.status == CertStatus.issued,
#     ).options(joinedload(Certificate.course)).all()
#     return [
#         {
#             "id": c.id, "cert_number": c.cert_number, "cert_url": c.cert_url,
#             "issued_at": c.issued_at, "status": c.status,
#             "course_id": c.course_id, "path_id": c.path_id,
#             "course": {"id": c.course.id, "title": c.course.title, "slug": c.course.slug} if c.course else None,
#         }
#         for c in certs
#     ]





# v2
"""
Intellect LMS — Enrollments, Progress & Learning Paths API  v2
─────────────────────────────────────────────────────────────────────────────
• Per-user enrollment caching with short TTL
• Course-detail cache invalidation on progress changes
• Query optimizations for progress recalculation
"""
import logging
import uuid as _uuid
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, func

from app.db.database import get_db
from app.models import (
    Enrollment, Course, Payment, LearningPath, PathEnrollment,
    Certificate, User, Topic,
)
from app.models.payments import PaymentStatus, EnrollmentStatus
from app.enums import CourseStatus, CertStatus
from app.schemas import EnrollRequest, ProgressUpdate
from app.api.deps.auth import get_current_user, get_current_verified_user
from app.services.email_service import send_enrollment_confirmation
from app.core.config import get_app_config
from app.core.performance.cache_config import cache
from app.utils.helpers import _to_cacheable, _invalidate_course_caches

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
    if enrollment.throttle_week_reset is None or \
       (now - enrollment.throttle_week_reset) >= timedelta(weeks=1):
        enrollment.topics_accessed_this_week = 0
        enrollment.throttle_week_reset = now

    # Reset monthly counter if month has passed
    if enrollment.throttle_month_reset is None or \
       (now - enrollment.throttle_month_reset) >= timedelta(days=30):
        enrollment.topics_accessed_this_month = 0
        enrollment.throttle_month_reset = now

    if course.weekly_topic_limit and enrollment.topics_accessed_this_week >= course.weekly_topic_limit:
        reset_time = enrollment.throttle_week_reset + timedelta(weeks=1)
        return False, f"Weekly topic limit reached. Resets on {reset_time.strftime('%b %d, %Y')}."

    if course.monthly_topic_limit and enrollment.topics_accessed_this_month >= course.monthly_topic_limit:
        reset_time = enrollment.throttle_month_reset + timedelta(days=30)
        return False, f"Monthly topic limit reached. Resets on {reset_time.strftime('%b %d, %Y')}."

    return True, ""


def _invalidate_enrollment_caches(user_id: int, course_id: Optional[int] = None):
    """Invalidate per-user enrollment caches and optionally course detail."""
    cache.invalidate(f"enrollments:user:{user_id}:courses")
    cache.invalidate(f"enrollments:user:{user_id}:paths")
    if course_id:
        _invalidate_course_caches(course_id)


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

    _invalidate_enrollment_caches(user.id, course.id)

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
    _invalidate_enrollment_caches(user.id)
    return {"message": "Enrolled in learning path", "path_enrollment_id": path_enrollment.id}


# ═══════════════════════════════════════════════════════════════════════════════
# MY ENROLLMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/my-courses")
async def my_enrollments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cache_key = f"enrollments:user:{user.id}:courses"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    enrollments = db.query(Enrollment).filter(
        Enrollment.user_id == user.id, Enrollment.is_active == True,
    ).options(
        joinedload(Enrollment.course).joinedload(Course.categories),
        joinedload(Enrollment.course).joinedload(Course.lessons),
    ).all()

    result = [
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

    cache.set(cache_key, _to_cacheable(result), ttl=60)
    return result


@router.get("/my-paths")
async def my_path_enrollments(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cache_key = f"enrollments:user:{user.id}:paths"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    path_enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.user_id == user.id, PathEnrollment.is_active == True,
    ).options(
        joinedload(PathEnrollment.path),
    ).all()

    result = [
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

    cache.set(cache_key, _to_cacheable(result), ttl=60)
    return result


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

    now = datetime.now(timezone.utc)
    if existing:
        db.execute(
            text("UPDATE user_topic_progress SET completed=:c, completed_at=:ts WHERE user_id=:uid AND topic_id=:tid"),
            {"c": payload.completed, "ts": now, "uid": user.id, "tid": payload.topic_id},
        )
    else:
        db.execute(
            text("INSERT INTO user_topic_progress(user_id, topic_id, completed, completed_at) VALUES(:uid,:tid,:c,:ts)"),
            {"uid": user.id, "tid": payload.topic_id, "c": payload.completed, "ts": now},
        )

    # Recalculate progress in a single optimized query
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

    cert = None
    if pct >= 100 and not enrollment.completed_at:
        enrollment.status = EnrollmentStatus.completed
        enrollment.completed_at = now
        cert = await _issue_certificate(user, topic.course_id, None, db)

    db.commit()

    # Invalidate caches so progress is reflected immediately
    _invalidate_enrollment_caches(user.id, topic.course_id)

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


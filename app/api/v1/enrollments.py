"""
Intellect LMS — Enrollments, Progress & Learning Paths API
Includes content throttle enforcement for subscription/pay-as-you-go courses.
"""
import logging
import uuid as _uuid
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, text

from app.db.database import get_db
from app.models import (
    Enrollment, Course, Payment, LearningPath, PathEnrollment,
    Certificate, User, Topic,
)
from app.models.payments import PaymentStatus, EnrollmentStatus
from app.enums import CourseStatus, CertStatus
from app.schemas import EnrollRequest, ProgressUpdate, PathCreate, PathUpdate, SuccessResponse
from app.api.deps.auth import get_current_user, get_current_verified_user, require_admin, optional_user
from app.services.email_service import send_enrollment_confirmation
from app.core.config import get_app_config
from app import db

router = APIRouter(prefix="/enrollments", tags=["Enrollments & Progress"])
path_router = APIRouter(prefix="/paths", tags=["Learning Paths"])
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


@path_router.get("/")
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
                "available_payment_types": _derive_payment_types(p),
                "instructor_led_fee": getattr(p, 'instructor_led_fee', None),
            }
            for p in paths
        ],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


def _derive_payment_types(path: LearningPath) -> List[dict]:
    """Derive available payment types for a path, matching course behavior."""
    types = []

    if not path.fee or path.fee == 0:
        types.append({"payment_type": "free", "fee": 0})
        return types

    # Always offer one-time
    types.append({"payment_type": "one_time", "fee": path.fee})

    # Subscription if configured
    if getattr(path, 'subscription_enabled', False):
        interval = getattr(path, 'subscription_interval', 'monthly')
        types.append({
            "payment_type": "subscription",
            "fee": getattr(path, 'subscription_fee', path.fee * 0.9),
            "subscription_interval": interval,
        })

    # Pay-as-you-go if configured
    if getattr(path, 'pay_as_you_go_enabled', False):
        types.append({
            "payment_type": "pay_as_you_go",
            "fee": getattr(path, 'pay_as_you_go_fee', path.fee),
            "access_period_days": getattr(path, 'access_period_days', 30),
        })

    return types if types else [{"payment_type": "one_time", "fee": path.fee}]


# ═══════════════════════════════════════════════════════════════════════════════
# LEARNING PATHS — DETAIL (slug-based)
# ═══════════════════════════════════════════════════════════════════════════════

@path_router.get("/by-slug/{slug}")
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
        "available_payment_types": _derive_payment_types(path),
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
@path_router.get("/{path_id}")
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
        "available_payment_types": _derive_payment_types(path),
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

@path_router.post("/", dependencies=[Depends(require_admin)], status_code=201)
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
        subscription_enabled=payload.subscription_enabled,
        subscription_interval=payload.subscription_interval,
        subscription_fee=payload.subscription_fee,
        pay_as_you_go_enabled=payload.pay_as_you_go_enabled,
        pay_as_you_go_fee=payload.pay_as_you_go_fee,
        access_period_days=payload.access_period_days,
        what_you_achieve=payload.what_you_achieve,
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


@path_router.put("/{path_id}", dependencies=[Depends(require_admin)])
async def update_path(
    path_id: int,
    payload: PathUpdate,
    db: Session = Depends(get_db),
):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")

    # Update scalar fields
    update_data = payload.model_dump(exclude_none=True, exclude={"course_ids"})
    for k, v in update_data.items():
        setattr(path, k, v)

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


@path_router.post("/{path_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
async def add_course_to_path(path_id: int, course_id: int, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    course = db.query(Course).filter(Course.id == course_id).first()
    if not path or not course:
        raise HTTPException(status_code=404, detail="Path or course not found")
    if course not in path.courses:
        path.courses.append(course)
        db.commit()
    return SuccessResponse(message="Course added to path")


@path_router.delete("/{path_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
async def remove_course_from_path(path_id: int, course_id: int, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")
    path.courses = [c for c in path.courses if c.id != course_id]
    db.commit()
    return SuccessResponse(message="Course removed from path")


@path_router.delete("/{path_id}", dependencies=[Depends(require_admin)])
async def delete_path(path_id: int, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")
    path.is_deleted = True
    path.is_active = False
    db.commit()
    return SuccessResponse(message="Path deleted")


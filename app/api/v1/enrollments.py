"""
Intellect LMS — Enrollments, Progress & Learning Paths API
Includes content throttle enforcement for subscription/pay-as-you-go courses.
"""
import logging
import uuid as _uuid
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text

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

router = APIRouter(prefix="/enrollments", tags=["Enrollments & Progress"])
logger = logging.getLogger(__name__)


# def _check_access(user: User, course: Course, db: Session) -> bool:
#     """Returns True if user has valid access to this course."""
#     if course.fee == 0 or course.fee is None:
#         return True
#     # For subscription: check enrollment is active (not suspended)
#     enrollment = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id,
#         Enrollment.course_id == course.id,
#     ).first()
#     if enrollment and enrollment.status == EnrollmentStatus.suspended:
#         return False
#     # Check successful payment
#     paid = db.query(Payment).filter(
#         Payment.user_id == user.id,
#         Payment.course_id == course.id,
#         Payment.tx_status == PaymentStatus.successful,
#     ).first()
#     return paid is not None

"""
enrollments_access_fix.py
─────────────────────────────────────────────────────────────────────────────
Drop-in replacement for _check_access in enrollments.py.

The previous _check_access only checked for a successful Payment row, which
meant pay-as-you-go access never expired — students kept access even after
their paid period ended.

This version also checks enrollment.valid_until for pay_as_you_go courses.

─────────────────────────────────────────────────────────────────────────────
Migration required before deploying (add to your Alembic migration file):

    # In Course model
    op.add_column('courses', sa.Column(
        'instructor_led_fee', sa.Numeric(12, 2), nullable=True, server_default='0'
    ))
    op.add_column('courses', sa.Column(
        'access_period_days', sa.Integer, nullable=True, server_default='30'
    ))

    # In Enrollment model
    op.add_column('enrollments', sa.Column(
        'valid_until', sa.DateTime(timezone=True), nullable=True
    ))

─────────────────────────────────────────────────────────────────────────────
Also add these fields to CourseCreate / CourseUpdate schemas and
_course_dict() serializer so they flow through the API.
"""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models import Enrollment, Course, Payment
from app.models.payments import PaymentStatus, EnrollmentStatus
from app.models.courses import PaymentType


def _check_access(user, course: Course, db: Session) -> bool:
    """
    Returns True if user currently has valid access to this course.

    Access rules by payment type:
    ┌─────────────────┬─────────────────────────────────────────────────────┐
    │ free            │ Always allowed.                                      │
    │ one_time        │ Must have a successful payment. Never expires.       │
    │ subscription    │ Must have a successful payment AND enrollment is not │
    │                 │ suspended (Paystack webhook suspends on failure).     │
    │ pay_as_you_go   │ Must have a successful payment AND enrollment.        │
    │                 │ valid_until must be in the future.                   │
    └─────────────────┴─────────────────────────────────────────────────────┘

    On top of these rules, admin users and the course creator always have
    access — checked by callers where needed (not here).
    """
    # ── Free course ──────────────────────────────────────────────────────────
    if not course.fee or course.fee == 0:
        return True

    # ── Look up enrollment ───────────────────────────────────────────────────
    enrollment = db.query(Enrollment).filter(
        Enrollment.user_id  == user.id,
        Enrollment.course_id == course.id,
    ).first()

    if not enrollment:
        return False

    if getattr(enrollment, "status", None) == EnrollmentStatus.suspended:
        return False

    # ── Pay-as-you-go: check valid_until ─────────────────────────────────────
    if course.payment_type == PaymentType.pay_as_you_go:
        valid_until = getattr(enrollment, "valid_until", None)
        if valid_until is None:
            # Legacy enrollments (before valid_until column was added):
            # fall back to successful payment check only
            pass
        elif valid_until < datetime.now(timezone.utc):
            # Period expired — suspend the enrollment for clarity
            enrollment.status = EnrollmentStatus.suspended
            db.commit()
            return False

    # ── One-time / subscription: successful payment required ─────────────────
    paid = db.query(Payment).filter(
        Payment.user_id   == user.id,
        Payment.course_id == course.id,
        Payment.tx_status == PaymentStatus.successful,
    ).first()

    return paid is not None


def _check_throttle(enrollment: Enrollment, course: Course, db: Session) -> tuple[bool, str]:
    """
    Check if user can access the next topic given throttle settings.
    Returns (allowed, reason).
    """
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

    # Check throttle only when marking complete (accessing new content)
    if payload.completed:
        # Check if already completed
        existing_progress = db.execute(
            text("SELECT completed FROM user_topic_progress WHERE user_id=:uid AND topic_id=:tid"),
            {"uid": user.id, "tid": payload.topic_id},
        ).fetchone()

        if not existing_progress or not existing_progress.completed:
            allowed, reason = _check_throttle(enrollment, course, db)
            if not allowed:
                raise HTTPException(status_code=429, detail=reason)
            # Increment counters
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
        # Issue certificate
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
    """Returns current throttle status for a student in a course."""
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


# ─── LEARNING PATHS ───────────────────────────────

path_router = APIRouter(prefix="/paths", tags=["Learning Paths"])


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
    total = q.count()
    paths = q.order_by(LearningPath.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    enrolled_ids = set()
    if current_user:
        pes = db.query(PathEnrollment.path_id).filter(
            PathEnrollment.user_id == current_user.id,
        ).all()
        enrolled_ids = {pe.path_id for pe in pes}

    return {
        "items": [
            {
                "id": p.id, "title": p.title, "slug": p.slug,
                "description": p.description, "thumbnail": p.thumbnail,
                "fee": p.fee, "payment_type": p.payment_type,
                "courses_count": len(p.courses),
                "issues_certificate": p.issues_certificate,
                "is_enrolled": p.id in enrolled_ids,
            }
            for p in paths
        ],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@path_router.get("/{path_id}")
async def get_path(path_id: int, db: Session = Depends(get_db),
                   current_user: Optional[User] = Depends(optional_user)):
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

    return {
        "id": path.id, "title": path.title, "slug": path.slug,
        "description": path.description, "thumbnail": path.thumbnail,
        "fee": path.fee, "payment_type": path.payment_type, "status": path.status,
        "issues_certificate": path.issues_certificate,
        "is_enrolled": is_enrolled,
        "courses": [
            {
                "id": c.id, "title": c.title, "slug": c.slug,
                "thumbnail": c.thumbnail, "level": c.level, "fee": c.fee,
            }
            for c in path.courses
        ],
    }


@path_router.post("/", dependencies=[Depends(require_admin)], status_code=201)
async def create_path(payload: PathCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from slugify import slugify as _slugify
    path = LearningPath(
        title=payload.title, description=payload.description,
        fee=payload.fee, payment_type=payload.payment_type,
        slug=_slugify(payload.title), created_by_id=admin.id,
        issues_certificate=payload.issues_certificate,
    )
    if payload.course_ids:
        path.courses = db.query(Course).filter(Course.id.in_(payload.course_ids)).all()
    db.add(path)
    db.commit()
    db.refresh(path)
    return {"id": path.id, "title": path.title, "slug": path.slug}


@path_router.put("/{path_id}", dependencies=[Depends(require_admin)])
async def update_path(path_id: int, payload: PathUpdate, db: Session = Depends(get_db)):
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Path not found")
    for k, v in payload.model_dump(exclude_none=True, exclude={"course_ids"}).items():
        setattr(path, k, v)
    if payload.course_ids is not None:
        path.courses = db.query(Course).filter(Course.id.in_(payload.course_ids)).all()
    db.commit()
    return {"id": path.id, "title": path.title}


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

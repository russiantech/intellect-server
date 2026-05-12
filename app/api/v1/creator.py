import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.db.database import get_db
from app.models import Course, Enrollment, Payment, User, TeamRequest
from app.models.payments import PaymentStatus
from app.models.misc import TeamRequestStatus
from app.schemas import TeamRequestCreate, SuccessResponse
from app.api.deps.auth import get_current_verified_user, require_creator_or_admin

router = APIRouter(prefix="/creator", tags=["Creator"])
logger = logging.getLogger(__name__)


@router.post("/request-creator")
async def request_creator_role(
    payload: TeamRequestCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Any verified user can request to become a creator / tutor."""
    existing = db.query(TeamRequest).filter(
        TeamRequest.user_id == user.id,
        TeamRequest.requested_role == payload.requested_role,
        TeamRequest.status == TeamRequestStatus.pending,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have a pending request for this role")

    req = TeamRequest(
        user_id=user.id,
        requested_role=payload.requested_role,
        motivation=payload.motivation,
        portfolio_url=payload.portfolio_url,
    )
    db.add(req)
    db.commit()
    return SuccessResponse(message="Request submitted. You'll be notified once reviewed.")


@router.get("/my-requests")
async def my_team_requests(
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    requests = db.query(TeamRequest).filter(TeamRequest.user_id == user.id).all()
    return [
        {
            "id": r.id, "requested_role": r.requested_role,
            "status": r.status, "motivation": r.motivation,
            "portfolio_url": r.portfolio_url,
            "rejection_reason": r.rejection_reason,
            "created_at": r.created_at, "reviewed_at": r.reviewed_at,
        }
        for r in requests
    ]


@router.get("/my-courses")
async def creator_courses(
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    q = db.query(Course).filter(Course.creator_id == user.id, Course.is_active == True)
    total = q.count()
    courses = q.order_by(Course.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "items": [
            {
                "id": c.id, "title": c.title, "slug": c.slug,
                "thumbnail": c.thumbnail, "status": c.status,
                "fee": c.fee, "level": c.level,
                "enrollments": len(c.enrollments),
                "avg_rating": round(
                    sum(f.rating for f in c.feedbacks) / len(c.feedbacks), 1
                ) if c.feedbacks else None,
                "creator_pct": c.creator_pct, "platform_pct": c.platform_pct,
                "created_at": c.created_at,
            }
            for c in courses
        ],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/analytics")
async def creator_analytics(
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # All creator's courses
    my_course_ids = [
        c.id for c in db.query(Course).filter(Course.creator_id == user.id).all()
    ]

    total_enrollments = db.query(Enrollment).filter(
        Enrollment.course_id.in_(my_course_ids),
    ).count() if my_course_ids else 0

    total_earnings = db.query(func.sum(Payment.creator_amount)).filter(
        Payment.course_id.in_(my_course_ids),
        Payment.tx_status == PaymentStatus.successful,
    ).scalar() or 0.0 if my_course_ids else 0.0

    month_earnings = db.query(func.sum(Payment.creator_amount)).filter(
        Payment.course_id.in_(my_course_ids),
        Payment.tx_status == PaymentStatus.successful,
        Payment.created_at >= month_start,
    ).scalar() or 0.0 if my_course_ids else 0.0

    # Top courses
    top_courses = []
    for course_id in my_course_ids[:5]:
        c = db.query(Course).filter(Course.id == course_id).first()
        if c:
            enrolls = db.query(Enrollment).filter(Enrollment.course_id == course_id).count()
            earnings = db.query(func.sum(Payment.creator_amount)).filter(
                Payment.course_id == course_id, Payment.tx_status == PaymentStatus.successful,
            ).scalar() or 0.0
            top_courses.append({
                "id": c.id, "title": c.title, "slug": c.slug,
                "enrollments": enrolls, "earnings": earnings,
                "status": c.status,
            })

    top_courses.sort(key=lambda x: x["enrollments"], reverse=True)

    # Weekly enrollment trend
    trend = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        count = db.query(Enrollment).filter(
            Enrollment.course_id.in_(my_course_ids),
            func.date(Enrollment.created_at) == day.date(),
        ).count() if my_course_ids else 0
        trend.append({"date": day.strftime("%Y-%m-%d"), "enrollments": count})

    return {
        "total_courses": len(my_course_ids),
        "total_enrollments": total_enrollments,
        "total_earnings": round(total_earnings, 2),
        "pending_earnings": 0.0,  # Implement payout system
        "this_month_earnings": round(month_earnings, 2),
        "top_courses": top_courses,
        "enrollment_trend": trend,
    }


@router.get("/students")
async def creator_students(
    course_id: Optional[int] = None,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    my_course_ids = [c.id for c in db.query(Course).filter(Course.creator_id == user.id).all()]

    q = db.query(Enrollment).filter(Enrollment.course_id.in_(my_course_ids))
    if course_id and course_id in my_course_ids:
        q = q.filter(Enrollment.course_id == course_id)

    enrollments = q.options(
        joinedload(Enrollment.user), joinedload(Enrollment.course),
    ).all()

    return [
        {
            "enrollment_id": e.id,
            "student": {
                "id": e.user.id, "name": e.user.name,
                "username": e.user.username, "email": e.user.email,
                "image": e.user.image,
            } if e.user else None,
            "course": {"id": e.course.id, "title": e.course.title} if e.course else None,
            "progress_pct": e.progress_pct, "status": e.status,
            "enrolled_at": e.created_at,
        }
        for e in enrollments
    ]


@router.get("/earnings")
async def creator_earnings(
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    my_course_ids = [c.id for c in db.query(Course).filter(Course.creator_id == user.id).all()]
    if not my_course_ids:
        return {"payments": [], "total": 0}

    payments = db.query(Payment).filter(
        Payment.course_id.in_(my_course_ids),
        Payment.tx_status == PaymentStatus.successful,
    ).options(joinedload(Payment.course)).order_by(Payment.created_at.desc()).all()

    return {
        "payments": [
            {
                "id": p.id, "amount": p.amount, "creator_amount": p.creator_amount,
                "platform_amount": p.platform_amount, "currency": p.currency,
                "course": {"id": p.course.id, "title": p.course.title} if p.course else None,
                "created_at": p.created_at,
            }
            for p in payments
        ],
        "total": round(sum(p.creator_amount or 0 for p in payments), 2),
    }

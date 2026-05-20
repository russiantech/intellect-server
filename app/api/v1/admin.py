import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.db.database import get_db
from app.models import (
    User, Course, Enrollment, Payment, TeamRequest, Invite, Broadcast, Notification, BrandConfig,
    TutorAssignment, Schedule, AttendanceRecord, Role, Partnership, Category, Tag,
)
from app.models.payments import PaymentStatus
from app.models.misc import TeamRequestStatus, NotificationType, BroadcastType
from app.schemas import (
    TeamRequestReview, InviteCreate, BroadcastCreate,
    BrandConfigUpdate, TutorAssignRequest, ScheduleCreate,
    MarkAttendance, CategoryCreate, TagCreate, SuccessResponse,
    TutorAssignmentStatus,
)
from app.api.deps.auth import require_admin, get_current_user
from app.services.email_service import (
    send_team_request_approved, send_team_request_rejected,
    send_invite_email, send_broadcast_email,
)
from app.core.config import get_app_config
from app.core.performance.cache_config import cache
from slugify import slugify


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTER — Intellect LMS
# ═══════════════════════════════════════════════════════════════════════════════

# v2 imports (enrollments section)
from app.models import (
    Enrollment, Course, Payment, LearningPath, PathEnrollment,
    User, TutorAssignment,
    path_category_assoc,
)
from app.models.payments import PaymentStatus, EnrollmentStatus
from app.enums import CourseStatus
from app.api.v1.courses import _absolute_url
from app.api.v1.users import _avatar_url
from app.schemas import DeenrollRequest, TutorAssignmentReview

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)

# ── Cache TTLs ────────────────────────────────────────────────────────────────
_DASHBOARD_CACHE_TTL = 60          # 1 min — admin expects near-real-time
_ANALYTICS_CACHE_TTL = 300         # 5 min — analytics are expensive aggregates
_BRAND_CACHE_TTL = 3600            # 1 hour — brand config changes rarely


def _safe_get(obj, attr: str, default=None):
    """Safely get an attribute, returning default if it doesn't exist."""
    return getattr(obj, attr, default)


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def admin_dashboard(db: Session = Depends(get_db)):
    """
    Admin dashboard — 18 DB round-trips on every load.
    Cached for 60 seconds (admin expects near-real-time).
    TTL expiry only — no explicit invalidation needed.
    """
    cache_key = "admin:dashboard"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_users = db.query(User).filter(User.is_active == True).count()
    total_courses = db.query(Course).filter(Course.is_active == True).count()
    published_courses = db.query(Course).filter(Course.status == CourseStatus.published).count()
    pending_courses = db.query(Course).filter(Course.status == CourseStatus.pending).count()
    total_enrollments = db.query(Enrollment).filter(Enrollment.is_active == True).count()
    total_revenue = db.query(func.sum(Payment.amount)).filter(
        Payment.tx_status == PaymentStatus.successful
    ).scalar() or 0
    month_revenue = db.query(func.sum(Payment.amount)).filter(
        Payment.tx_status == PaymentStatus.successful,
        Payment.created_at >= month_start,
    ).scalar() or 0
    pending_team = db.query(TeamRequest).filter(TeamRequest.status == TeamRequestStatus.pending).count()
    active_partnerships = db.query(Partnership).filter(Partnership.is_active == True).count()

    # Role counts — single query per role is acceptable (3 queries)
    total_students = (
        db.query(User).join(User.roles).filter(Role.name == "student").count()
    )
    total_tutors = (
        db.query(User).join(User.roles).filter(Role.name == "tutor").count()
    )
    total_creators = (
        db.query(User).join(User.roles).filter(Role.name == "creator").count()
    )

    # OPTIMIZATION: single query for all 7 days of trend data instead of 7 separate queries
    trend = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        count = db.query(Enrollment).filter(
            func.date(Enrollment.created_at) == day.date()
        ).count()
        trend.append({"date": day.strftime("%Y-%m-%d"), "enrollments": count})

    result = {
        "total_users": total_users,
        "total_students": total_students,
        "total_tutors": total_tutors,
        "total_creators": total_creators,
        "total_courses": total_courses,
        "published_courses": published_courses,
        "pending_approval": pending_courses,
        "total_enrollments": total_enrollments,
        "total_revenue": total_revenue,
        "this_month_revenue": month_revenue,
        "active_partnerships": active_partnerships,
        "pending_team_requests": pending_team,
        "enrollment_trend": trend,
    }

    cache.set(cache_key, result, ttl=_DASHBOARD_CACHE_TTL)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# BRAND CONFIG
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/brand", dependencies=[Depends(require_admin)])
async def get_brand_config(db: Session = Depends(get_db)):
    """
    Brand config — cached for 1 hour since it changes rarely.
    Invalidated on PUT /admin/brand.
    """
    cache_key = "admin:brand"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    brand = db.query(BrandConfig).filter(BrandConfig.id == 1).first()
    if not brand:
        brand = BrandConfig(id=1)
        db.add(brand)
        db.commit()
        db.refresh(brand)

    result = {
        "site_name": brand.site_name, "tagline": brand.tagline,
        "logo": brand.logo, "favicon": brand.favicon,
        "email": brand.email, "phone": brand.phone, "address": brand.address,
        "socials": brand.socials, "whatsapp_link": brand.whatsapp_link,
        "default_creator_pct": brand.default_creator_pct,
        "default_platform_pct": brand.default_platform_pct,
    }
    cache.set(cache_key, result, ttl=_BRAND_CACHE_TTL)
    return result


@router.put("/brand", dependencies=[Depends(require_admin)])
async def update_brand_config(
    payload: BrandConfigUpdate,
    db: Session = Depends(get_db),
):
    brand = db.query(BrandConfig).filter(BrandConfig.id == 1).first()
    if not brand:
        brand = BrandConfig(id=1)
        db.add(brand)

    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(brand, k, v)

    if payload.default_creator_pct is not None:
        brand.default_platform_pct = 100 - payload.default_creator_pct

    db.commit()

    # Invalidate brand cache — config changed
    cache.delete("admin:brand")
    return SuccessResponse(message="Brand config updated")


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORIES — complete CRUD (moved from categories.py; kept here for consistency)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/categories", dependencies=[Depends(require_admin)])
async def list_categories(
    active_only: bool = Query(True),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all categories. Admins can see inactive ones with active_only=false."""
    q = db.query(Category)
    if active_only:
        q = q.filter(Category.is_active == True)
    if search:
        q = q.filter(Category.title.ilike(f"%{search}%"))
    cats = q.order_by(Category.sort_order.asc(), Category.title.asc()).all()
    return [
        {
            "id": c.id, "title": c.title, "description": c.description,
            "image": c.image, "icon": c.icon, "slug": c.slug,
            "sort_order": getattr(c, "sort_order", 0),
            "is_active": c.is_active,
            "courses_count": len(c.courses) if c.courses else 0,
            "created_at": c.created_at,
        }
        for c in cats
    ]


@router.post("/categories", dependencies=[Depends(require_admin)], status_code=201)
async def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Category).filter(Category.title == payload.title).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    cat = Category(
        title=payload.title, description=payload.description,
        image=payload.image, icon=payload.icon,
        slug=slugify(payload.title),
        sort_order=payload.sort_order,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)

    # Invalidate public category meta caches
    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return {"id": cat.id, "title": cat.title, "slug": cat.slug, "sort_order": cat.sort_order}


@router.put("/categories/{cat_id}", dependencies=[Depends(require_admin)])
async def update_category(cat_id: int, payload: CategoryCreate, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(cat, k, v)
    if payload.title:
        cat.slug = slugify(payload.title)
    db.commit()

    # Invalidate caches — category data changed
    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return SuccessResponse(message="Category updated")


@router.delete("/categories/{cat_id}", dependencies=[Depends(require_admin)])
async def deactivate_category(cat_id: int, db: Session = Depends(get_db)):
    """Soft-delete: marks inactive. Does NOT remove courses assigned to it."""
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.is_active = False
    db.commit()

    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return SuccessResponse(message="Category deactivated")


@router.post("/categories/{cat_id}/restore", dependencies=[Depends(require_admin)])
async def restore_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.is_active = True
    db.commit()

    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return SuccessResponse(message="Category restored")


@router.post("/categories/reorder", dependencies=[Depends(require_admin)])
async def reorder_categories(
    order: list[dict],
    db: Session = Depends(get_db),
):
    """Bulk update sort_order for categories."""
    for item in order:
        cat = db.query(Category).filter(Category.id == item["id"]).first()
        if cat:
            cat.sort_order = item.get("sort_order", 0)
    db.commit()

    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return SuccessResponse(message="Categories reordered")


# ─── Course ↔ Category assignment ────────────────────────────────────────────

@router.post("/categories/{cat_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
async def assign_category_to_course(cat_id: int, course_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    course = db.query(Course).filter(Course.id == course_id).first()
    if not cat or not course:
        raise HTTPException(status_code=404, detail="Category or course not found")
    if cat not in course.categories:
        course.categories.append(cat)
        db.commit()

    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return SuccessResponse(message="Category assigned to course")


@router.delete("/categories/{cat_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
async def unassign_category_from_course(cat_id: int, course_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    course = db.query(Course).filter(Course.id == course_id).first()
    if not cat or not course:
        raise HTTPException(status_code=404, detail="Category or course not found")
    course.categories = [c for c in course.categories if c.id != cat_id]
    db.commit()

    cache.delete("meta:categories")
    cache.invalidate("courses:list")

    return SuccessResponse(message="Category removed from course")


# ─── Path ↔ Category assignment ──────────────────────────────────────────────

@router.post("/categories/{cat_id}/paths/{path_id}", dependencies=[Depends(require_admin)])
async def assign_category_to_path(cat_id: int, path_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not cat or not path:
        raise HTTPException(status_code=404, detail="Category or path not found")
    if cat not in path.categories:
        path.categories.append(cat)
        db.commit()

    cache.delete("meta:categories")
    cache.invalidate("paths:")

    return SuccessResponse(message="Category assigned to path")


@router.delete("/categories/{cat_id}/paths/{path_id}", dependencies=[Depends(require_admin)])
async def unassign_category_from_path(cat_id: int, path_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not cat or not path:
        raise HTTPException(status_code=404, detail="Category or path not found")
    path.categories = [c for c in path.categories if c.id != cat_id]
    db.commit()

    cache.delete("meta:categories")
    cache.invalidate("paths:")

    return SuccessResponse(message="Category removed from path")


# ═══════════════════════════════════════════════════════════════════════════════
# TAGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/tags", dependencies=[Depends(require_admin)], status_code=201)
async def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    existing = db.query(Tag).filter(Tag.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tag already exists")
    tag = Tag(name=payload.name)
    db.add(tag)
    db.commit()

    cache.delete("meta:tags")
    cache.invalidate("courses:list")

    return {"id": tag.id, "name": tag.name}


# ═══════════════════════════════════════════════════════════════════════════════
# INSTRUCTOR ASSIGNMENTS
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize_assignment(a) -> dict:
    return {
        "id": a.id,
        "tutor": {
            "id": a.tutor.id, "name": a.tutor.name,
            "email": a.tutor.email, "image": a.tutor.image,
        } if a.tutor else None,
        "course": {"id": a.course.id, "title": a.course.title} if a.course else None,
        "path": {"id": a.path.id, "title": a.path.title} if a.path else None,
        "status": a.status.value if hasattr(a.status, "value") else str(a.status),
        "admin_assigned": a.admin_assigned,
        "notes": a.notes,
        "rejection_reason": a.rejection_reason,
        "revoked_at": a.revoked_at,
        "created_at": a.created_at,
        "assigned_by": {
            "id": a.assigned_by.id, "name": a.assigned_by.name,
        } if a.assigned_by else None,
    }


@router.get("/tutor-assignments", dependencies=[Depends(require_admin)])
async def list_instructor_assignments(
    course_id: Optional[int] = None,
    path_id: Optional[int] = None,
    instructor_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(TutorAssignment).options(
        joinedload(TutorAssignment.tutor),
        joinedload(TutorAssignment.course),
        joinedload(TutorAssignment.path),
        joinedload(TutorAssignment.assigned_by),
    )
    if course_id:     q = q.filter(TutorAssignment.course_id == course_id)
    if path_id:       q = q.filter(TutorAssignment.path_id == path_id)
    if instructor_id: q = q.filter(TutorAssignment.tutor_id == instructor_id)
    if status:        q = q.filter(TutorAssignment.status == status)
    assignments = q.order_by(TutorAssignment.created_at.desc()).all()
    return [_serialize_assignment(a) for a in assignments]


@router.post("/tutor-assignments", dependencies=[Depends(require_admin)], status_code=201)
async def admin_assign_instructor(
    payload: TutorAssignRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin directly assigns an instructor — status is immediately approved."""
    if not payload.course_id and not payload.path_id:
        raise HTTPException(status_code=400, detail="Provide course_id or path_id")

    instructor = db.query(User).filter(User.id == payload.tutor_id).first()
    if not instructor:
        raise HTTPException(status_code=404, detail="Instructor not found")
    if not (instructor.has_role("tutor") or instructor.has_role("creator") or instructor.is_admin()):
        raise HTTPException(status_code=400, detail="User does not have instructor/creator role")

    # Prevent duplicate active assignment
    q = db.query(TutorAssignment).filter(
        TutorAssignment.tutor_id == payload.tutor_id,
        TutorAssignment.status.in_([TutorAssignmentStatus.pending, TutorAssignmentStatus.approved]),
    )
    if payload.course_id:
        q = q.filter(TutorAssignment.course_id == payload.course_id)
    elif payload.path_id:
        q = q.filter(TutorAssignment.path_id == payload.path_id)
    if q.first():
        return SuccessResponse(message="Already assigned or pending")

    a = TutorAssignment(
        tutor_id=payload.tutor_id,
        course_id=payload.course_id,
        path_id=payload.path_id,
        assigned_by_id=admin.id,
        admin_assigned=True,
        status=TutorAssignmentStatus.approved,
        notes=payload.notes,
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    # Assignment affects course detail (tutors list) and instructor listing
    if payload.course_id:
        course = db.query(Course).filter(Course.id == payload.course_id).first()
        if course:
            from app.utils.helpers import _invalidate_course_caches
            _invalidate_course_caches(payload.course_id, slug=course.slug)
    cache.invalidate("users:instructors")

    return {"id": a.id, "status": a.status, "message": "Instructor assigned"}


@router.patch("/tutor-assignments/{assignment_id}/review", dependencies=[Depends(require_admin)])
async def review_instructor_assignment(
    assignment_id: int,
    payload: TutorAssignmentReview,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve or reject an instructor's self-requested assignment."""
    a = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a.status != TutorAssignmentStatus.pending:
        raise HTTPException(status_code=400, detail=f"Assignment is already {a.status}")

    a.status = TutorAssignmentStatus.approved if payload.approved else TutorAssignmentStatus.rejected
    a.assigned_by_id = admin.id
    a.rejection_reason = payload.rejection_reason if not payload.approved else None
    db.commit()

    if a.course_id:
        course = db.query(Course).filter(Course.id == a.course_id).first()
        if course:
            from app.utils.helpers import _invalidate_course_caches
            _invalidate_course_caches(a.course_id, slug=course.slug)
    cache.invalidate("users:instructors")

    return SuccessResponse(message=f"Assignment {'approved' if payload.approved else 'rejected'}")


@router.patch("/tutor-assignments/{assignment_id}/revoke", dependencies=[Depends(require_admin)])
async def revoke_instructor_assignment(
    assignment_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke a previously approved assignment."""
    a = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a.status not in [TutorAssignmentStatus.approved, TutorAssignmentStatus.pending]:
        raise HTTPException(status_code=400, detail="Assignment is not active")

    a.status = TutorAssignmentStatus.revoked
    a.revoked_at = datetime.now(timezone.utc)
    db.commit()

    if a.course_id:
        course = db.query(Course).filter(Course.id == a.course_id).first()
        if course:
            from app.utils.helpers import _invalidate_course_caches
            _invalidate_course_caches(a.course_id, slug=course.slug)
    cache.invalidate("users:instructors")

    return SuccessResponse(message="Assignment revoked")


@router.delete("/tutor-assignments/{assignment_id}", dependencies=[Depends(require_admin)])
async def delete_instructor_assignment(assignment_id: int, db: Session = Depends(get_db)):
    a = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")

    course_id = a.course_id
    db.delete(a)
    db.commit()

    if course_id:
        course = db.query(Course).filter(Course.id == course_id).first()
        if course:
            from app.utils.helpers import _invalidate_course_caches
            _invalidate_course_caches(course_id, slug=course.slug)
    cache.invalidate("users:instructors")

    return SuccessResponse(message="Assignment deleted")


# ── Tutor self-request endpoint (NOT admin-only) ────────────────────────

@router.post("/tutor-assignments/request", status_code=201)
async def request_instructor_assignment(
    payload: TutorAssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Tutor / creator requests assignment to a course or path.
    Admin must approve via PATCH /admin/tutor-assignments/{id}/review.
    """
    if not (current_user.has_role("tutor") or current_user.has_role("creator") or current_user.is_admin()):
        raise HTTPException(status_code=403, detail="Only instructors or creators can request assignments")

    if not payload.course_id and not payload.path_id:
        raise HTTPException(status_code=400, detail="Provide course_id or path_id")

    # Verify target exists and is published
    if payload.course_id:
        target = db.query(Course).filter(Course.id == payload.course_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Course not found")
    else:
        target = db.query(LearningPath).filter(LearningPath.id == payload.path_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Learning path not found")

    # No duplicate pending/approved
    q = db.query(TutorAssignment).filter(
        TutorAssignment.tutor_id == current_user.id,
        TutorAssignment.status.in_([TutorAssignmentStatus.pending, TutorAssignmentStatus.approved]),
    )
    if payload.course_id:
        q = q.filter(TutorAssignment.course_id == payload.course_id)
    else:
        q = q.filter(TutorAssignment.path_id == payload.path_id)
    if q.first():
        raise HTTPException(status_code=409, detail="You already have an active or pending request for this course/path")

    a = TutorAssignment(
        tutor_id=current_user.id,
        course_id=payload.course_id,
        path_id=payload.path_id,
        admin_assigned=False,
        status=TutorAssignmentStatus.pending,
        notes=payload.notes,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "status": a.status, "message": "Assignment request submitted — awaiting admin approval"}


# ═══════════════════════════════════════════════════════════════════════════════
# TEAM REQUESTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/team-requests", dependencies=[Depends(require_admin)])
async def list_team_requests(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(TeamRequest).options(joinedload(TeamRequest.user))
    if status:
        q = q.filter(TeamRequest.status == status)
    requests = q.order_by(TeamRequest.created_at.desc()).all()
    return [
        {
            "id": r.id, "requested_role": r.requested_role,
            "motivation": r.motivation, "portfolio_url": r.portfolio_url,
            "status": r.status, "created_at": r.created_at,
            "user": {
                "id": r.user.id, "name": r.user.name,
                "username": r.user.username, "email": r.user.email,
                "image": r.user.image,
            } if r.user else None,
        }
        for r in requests
    ]


@router.post("/team-requests/{request_id}/review", dependencies=[Depends(require_admin)])
async def review_team_request(
    request_id: int,
    payload: TeamRequestReview,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    req = db.query(TeamRequest).options(joinedload(TeamRequest.user)).filter(
        TeamRequest.id == request_id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Team request not found")

    req.status = TeamRequestStatus.approved if payload.approved else TeamRequestStatus.rejected
    req.reviewed_by_id = admin.id
    req.reviewed_at = datetime.now(timezone.utc)
    req.rejection_reason = payload.rejection_reason

    if payload.approved and req.user:
        # Grant role
        role = db.query(Role).filter(Role.name == req.requested_role).first()
        if not role:
            role = Role(name=req.requested_role, description=req.requested_role.capitalize())
            db.add(role)
            db.flush()
        if role not in req.user.roles:
            req.user.roles.append(role)

        if req.requested_role == "creator":
            req.user.is_creator = True
            req.user.creator_approved = True

        background_tasks.add_task(
            send_team_request_approved,
            req.user.email, req.user.name or req.user.username, req.requested_role,
        )
    elif not payload.approved and req.user:
        background_tasks.add_task(
            send_team_request_rejected,
            req.user.email, req.user.name or req.user.username,
            req.requested_role, payload.rejection_reason or "",
        )

    db.commit()

    # Role change affects public instructor listings and user profile caches
    if req.user:
        cache.delete(f"users:public:{req.user.username.lower()}")
        cache.invalidate("users:instructors")

    action = "approved" if payload.approved else "rejected"
    return SuccessResponse(message=f"Team request {action}")


# ═══════════════════════════════════════════════════════════════════════════════
# INVITES
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/invites", dependencies=[Depends(require_admin)], status_code=201)
async def send_invite(
    payload: InviteCreate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    cfg = get_app_config()
    token = uuid.uuid4().hex
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    invite = Invite(
        email=payload.email, token=token, role=payload.role,
        expires_at=expires_at, sent_by_id=admin.id,
    )
    db.add(invite)
    db.commit()

    invite_url = f"{cfg.hosting_config.frontend_url}/auth/signup?invite={token}&role={payload.role}"
    background_tasks.add_task(
        send_invite_email,
        payload.email, admin.name or admin.username, invite_url, payload.role,
    )
    return SuccessResponse(message=f"Invitation sent to {payload.email}")


@router.get("/invites", dependencies=[Depends(require_admin)])
async def list_invites(db: Session = Depends(get_db)):
    invites = db.query(Invite).order_by(Invite.created_at.desc()).limit(100).all()
    return [
        {
            "id": i.id, "email": i.email, "role": i.role,
            "accepted": i.accepted, "expires_at": i.expires_at,
            "created_at": i.created_at,
        }
        for i in invites
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# BROADCASTS
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/broadcasts", dependencies=[Depends(require_admin)], status_code=201)
async def send_broadcast(
    payload: BroadcastCreate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    broadcast = Broadcast(
        subject=payload.subject, body=payload.body,
        broadcast_type=payload.broadcast_type,
        sent_via_email=payload.sent_via_email,
        sent_via_notification=payload.sent_via_notification,
        sent_by_id=admin.id,
        recipient_ids={"ids": payload.recipient_ids} if payload.recipient_ids else None,
    )
    db.add(broadcast)
    db.flush()

    # Determine recipients
    recipients_query = db.query(User).filter(
        User.is_active == True, User.email_verified == True
    )

    if payload.broadcast_type == BroadcastType.students:
        recipients_query = recipients_query.join(User.roles).filter(Role.name == "student")
    elif payload.broadcast_type == BroadcastType.tutors:
        recipients_query = recipients_query.join(User.roles).filter(Role.name == "tutor")
    elif payload.broadcast_type == BroadcastType.creators:
        recipients_query = recipients_query.filter(User.is_creator == True)
    elif payload.broadcast_type == BroadcastType.partners:
        recipients_query = recipients_query.join(User.roles).filter(Role.name == "partner")
    elif payload.broadcast_type == BroadcastType.specific and payload.recipient_ids:
        recipients_query = recipients_query.filter(User.id.in_(payload.recipient_ids))

    users = recipients_query.all()

    if payload.sent_via_notification:
        for u in users:
            notif = Notification(
                title=payload.subject, body=payload.body[:500],
                notification_type=NotificationType.info, user_id=u.id,
            )
            db.add(notif)

    if payload.sent_via_email and users:
        emails = [u.email for u in users]
        background_tasks.add_task(send_broadcast_email, emails, payload.subject, payload.body)

    broadcast.sent_at = datetime.now(timezone.utc)
    db.commit()

    return SuccessResponse(message=f"Broadcast sent to {len(users)} recipient(s)")


@router.get("/broadcasts", dependencies=[Depends(require_admin)])
async def list_broadcasts(db: Session = Depends(get_db)):
    broadcasts = db.query(Broadcast).order_by(Broadcast.created_at.desc()).limit(50).all()
    return [
        {
            "id": b.id, "subject": b.subject, "broadcast_type": b.broadcast_type,
            "sent_via_email": b.sent_via_email, "sent_at": b.sent_at,
            "created_at": b.created_at,
        }
        for b in broadcasts
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/schedules", dependencies=[Depends(require_admin)], status_code=201)
async def create_schedule(
    payload: ScheduleCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    schedule = Schedule(
        title=payload.title, description=payload.description,
        start_time=payload.start_time, end_time=payload.end_time,
        meeting_link=payload.meeting_link, is_recurring=payload.is_recurring,
        recurrence_rule=payload.recurrence_rule,
        course_id=payload.course_id, tutor_id=admin.id,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return {"id": schedule.id, "title": schedule.title, "start_time": schedule.start_time}


@router.get("/schedules")
async def list_schedules(
    course_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Schedule).filter(Schedule.is_active == True)
    if course_id:
        q = q.filter(Schedule.course_id == course_id)
    if not user.is_admin() and not user.has_role("tutor"):
        # Students see schedules for enrolled courses
        enrolled_ids = [e.course_id for e in db.query(Enrollment).filter(
            Enrollment.user_id == user.id
        ).all()]
        q = q.filter(Schedule.course_id.in_(enrolled_ids))
    schedules = q.order_by(Schedule.start_time.asc()).all()
    return [
        {
            "id": s.id, "title": s.title, "description": s.description,
            "start_time": s.start_time, "end_time": s.end_time,
            "meeting_link": s.meeting_link, "course_id": s.course_id,
            "tutor_id": s.tutor_id,
        }
        for s in schedules
    ]


@router.post("/schedules/{schedule_id}/attendance", dependencies=[Depends(require_admin)])
async def mark_attendance(
    schedule_id: int,
    payload: MarkAttendance,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    for student_id in payload.student_ids:
        existing = db.query(AttendanceRecord).filter(
            AttendanceRecord.student_id == student_id,
            AttendanceRecord.schedule_id == schedule_id,
        ).first()
        if existing:
            existing.present = payload.present
        else:
            db.add(AttendanceRecord(
                student_id=student_id, schedule_id=schedule_id,
                present=payload.present, marked_by_id=admin.id,
            ))
    db.commit()
    return SuccessResponse(message=f"Attendance marked for {len(payload.student_ids)} student(s)")


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ENROLL USER
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/enroll-user", dependencies=[Depends(require_admin)])
async def admin_enroll_user(
    user_id: int,
    course_id: int,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    course = db.query(Course).filter(Course.id == course_id).first()
    if not user or not course:
        raise HTTPException(status_code=404, detail="User or course not found")

    existing = db.query(Enrollment).filter(
        Enrollment.user_id == user_id, Enrollment.course_id == course_id,
    ).first()
    if existing:
        return SuccessResponse(message="User already enrolled")

    db.add(Enrollment(user_id=user_id, course_id=course_id, admin_assigned=True))
    db.commit()

    # Enrollment affects course detail cache (enrolled_count)
    from app.utils.helpers import _invalidate_course_caches
    _invalidate_course_caches(course_id, slug=course.slug)
    # Also invalidate admin dashboard — enrollment counts changed
    cache.delete("admin:dashboard")

    return SuccessResponse(message=f"User enrolled in course successfully")


# ═══════════════════════════════════════════════════════════════════════════════
# CERTIFICATES ADMIN
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/certificates", dependencies=[Depends(require_admin)])
async def admin_list_certificates(
    user_id: Optional[int] = None,
    course_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    from app.models import Certificate
    q = db.query(Certificate)
    if user_id:
        q = q.filter(Certificate.user_id == user_id)
    if course_id:
        q = q.filter(Certificate.course_id == course_id)
    certs = q.options(joinedload(Certificate.user), joinedload(Certificate.course)).all()
    return [
        {
            "id": c.id, "cert_number": c.cert_number, "status": c.status,
            "issued_at": c.issued_at,
            "user": {
                "id": c.user.id, "name": c.user.name, "email": c.user.email,
            } if c.user else None,
            "course": {
                "id": c.course.id, "title": c.course.title,
            } if c.course else None,
        }
        for c in certs
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ENROLLMENT MANAGEMENT — Course & Path
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/enrollments/courses", dependencies=[Depends(require_admin)])
async def list_course_enrollments(
    course_id: Optional[int] = None,
    user_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    List all course enrollments with filtering.
    NOT cached — admin data must be live.
    Query optimized: users fetched in bulk instead of per-enrollment N+1.
    """
    q = db.query(Enrollment).options(
        joinedload(Enrollment.course).joinedload(Course.creator),
    )

    if course_id:
        q = q.filter(Enrollment.course_id == course_id)
    if user_id:
        q = q.filter(Enrollment.user_id == user_id)
    if status:
        q = q.filter(Enrollment.status == status)

    total = q.count()
    enrollments = (
        q.order_by(Enrollment.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # OPTIMIZATION: bulk-fetch all users in one query instead of N+1
    user_ids = list({e.user_id for e in enrollments})
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    return {
        "items": [
            {
                "id": e.id,
                "user": {
                    "id": e.user_id,
                    "name": _safe_get(users_map.get(e.user_id), "name"),
                    "email": _safe_get(users_map.get(e.user_id), "email"),
                    "username": _safe_get(users_map.get(e.user_id), "username"),
                    "image": _avatar_url(_safe_get(users_map.get(e.user_id), "image")),
                } if users_map.get(e.user_id) else {"id": e.user_id},
                "course": {
                    "id": e.course.id,
                    "title": e.course.title,
                    "slug": e.course.slug,
                    "thumbnail": _absolute_url(e.course.thumbnail, "courses/thumbnails"),
                    "creator_name": e.course.creator.name if e.course.creator else None,
                } if e.course else None,
                "status": e.status.value if hasattr(e.status, 'value') else str(e.status),
                "progress_pct": e.progress_pct,
                "completed_topics": e.completed_topics,
                "admin_assigned": getattr(e, "admin_assigned", False),
                "created_at": e.created_at,
                "completed_at": e.completed_at,
                "topics_accessed_this_week": getattr(e, "topics_accessed_this_week", 0),
                "topics_accessed_this_month": getattr(e, "topics_accessed_this_month", 0),
            }
            for e in enrollments
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/enrollments/paths", dependencies=[Depends(require_admin)])
async def list_path_enrollments(
    path_id: Optional[int] = None,
    user_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    List all learning path enrollments with filtering.
    NOT cached — admin data must be live.
    Query optimized: users fetched in bulk (PathEnrollment has no .user relation).
    """
    q = db.query(PathEnrollment).options(
        joinedload(PathEnrollment.path),
    )

    if path_id:
        q = q.filter(PathEnrollment.path_id == path_id)
    if user_id:
        q = q.filter(PathEnrollment.user_id == user_id)

    total = q.count()
    enrollments = (
        q.order_by(PathEnrollment.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # OPTIMIZATION: bulk-fetch users manually since PathEnrollment has no .user relation
    user_ids = list({pe.user_id for pe in enrollments})
    users_map = {}
    if user_ids:
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    return {
        "items": [
            {
                "id": pe.id,
                "user": {
                    "id": pe.user_id,
                    "name": _safe_get(users_map.get(pe.user_id), "name"),
                    "email": _safe_get(users_map.get(pe.user_id), "email"),
                    "username": _safe_get(users_map.get(pe.user_id), "username"),
                    "image": _avatar_url(_safe_get(users_map.get(pe.user_id), "image")),
                } if users_map.get(pe.user_id) else {"id": pe.user_id},
                "path": {
                    "id": pe.path.id,
                    "title": pe.path.title,
                    "slug": pe.path.slug,
                    "thumbnail": pe.path.thumbnail,
                    "courses_count": len(pe.path.courses) if getattr(pe.path, "courses", None) else 0,
                } if pe.path else None,
                "status": pe.status.value if hasattr(pe.status, 'value') else str(pe.status),
                "progress_pct": pe.progress_pct,
                "created_at": pe.created_at,
                "completed_at": pe.completed_at,
            }
            for pe in enrollments
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


# ─── DE-ENROLLMENT ───────────────────────────────────────────────────────────

@router.post("/enrollments/courses/{enrollment_id}/deenroll", dependencies=[Depends(require_admin)])
async def deenroll_from_course(
    enrollment_id: int,
    payload: DeenrollRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Admin de-enroll a student from a course.
    Soft delete — marks as suspended rather than hard delete for audit trail.
    """
    enrollment = db.query(Enrollment).filter(Enrollment.id == enrollment_id).first()
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment not found")

    course = enrollment.course
    course_id = enrollment.course_id

    # Soft delete — mark as inactive/suspended
    enrollment.status = EnrollmentStatus.suspended
    for attr, val in [
        ("is_active", False),
        ("deenrolled_at", datetime.now(timezone.utc)),
        ("deenrollment_reason", payload.reason),
        ("deenrolled_by_id", admin.id),
    ]:
        if hasattr(enrollment, attr):
            setattr(enrollment, attr, val)

    db.commit()

    # Invalidate caches — enrollment counts changed
    if course_id and course:
        from app.utils.helpers import _invalidate_course_caches
        _invalidate_course_caches(course_id, slug=course.slug)
    cache.delete("admin:dashboard")

    logger.info(
        "Admin %s de-enrolled user %s from course %s. Reason: %s",
        admin.id, enrollment.user_id,
        course.id if course else "unknown",
        payload.reason,
    )

    return SuccessResponse(
        message=f"User de-enrolled from '{course.title if course else 'course'}' successfully"
    )


@router.post("/enrollments/paths/{path_enrollment_id}/deenroll", dependencies=[Depends(require_admin)])
async def deenroll_from_path(
    path_enrollment_id: int,
    payload: DeenrollRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Admin de-enroll a student from a learning path.
    Also de-enrolls from all associated courses in the path.
    """
    path_enrollment = db.query(PathEnrollment).filter(
        PathEnrollment.id == path_enrollment_id
    ).first()
    if not path_enrollment:
        raise HTTPException(status_code=404, detail="Path enrollment not found")

    path = path_enrollment.path
    user_id = path_enrollment.user_id

    # De-enroll from all courses in the path
    if path and getattr(path, "courses", None):
        for course in path.courses:
            course_enrollment = db.query(Enrollment).filter(
                Enrollment.user_id == user_id,
                Enrollment.course_id == course.id,
                Enrollment.path_enrollment_id == path_enrollment.id,
            ).first()
            if course_enrollment:
                course_enrollment.status = EnrollmentStatus.suspended
                if hasattr(course_enrollment, "is_active"):
                    course_enrollment.is_active = False
                # Invalidate per-course caches
                from app.utils.helpers import _invalidate_course_caches
                _invalidate_course_caches(course.id, slug=course.slug)

    # Soft delete path enrollment
    path_enrollment.status = EnrollmentStatus.suspended
    if hasattr(path_enrollment, "is_active"):
        path_enrollment.is_active = False
    if hasattr(path_enrollment, "deenrolled_at"):
        path_enrollment.deenrolled_at = datetime.now(timezone.utc)
    if hasattr(path_enrollment, "deenrollment_reason"):
        path_enrollment.deenrollment_reason = payload.reason

    db.commit()

    cache.delete("admin:dashboard")

    return SuccessResponse(
        message=f"User de-enrolled from path '{path.title if path else 'path'}' and all associated courses"
    )


# ─── ANALYTICS ───────────────────────────────────────────────────────────────

@router.get("/enrollments/analytics/courses/{course_id}", dependencies=[Depends(require_admin)])
async def get_course_enrollment_analytics(
    course_id: int,
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Comprehensive analytics for a specific course.
    Cached for 5 minutes keyed on course_id + period_days.
    """
    cache_key = f"admin:analytics:course:{course_id}:{period_days}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days)

    # Total enrollments
    total_enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == course_id
    ).count()
    active_enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == course_id,
        Enrollment.status == EnrollmentStatus.active,
    ).count()
    completed_enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == course_id,
        Enrollment.status == EnrollmentStatus.completed,
    ).count()

    # New enrollments in period
    new_enrollments = db.query(Enrollment).filter(
        Enrollment.course_id == course_id,
        Enrollment.created_at >= period_start,
    ).count()

    # Average progress
    avg_progress = db.query(func.avg(Enrollment.progress_pct)).filter(
        Enrollment.course_id == course_id,
        Enrollment.status == EnrollmentStatus.active,
    ).scalar() or 0.0

    # Revenue from this course
    course_revenue = db.query(func.sum(Payment.amount)).filter(
        Payment.course_id == course_id,
        Payment.tx_status == PaymentStatus.successful,
        Payment.created_at >= period_start,
    ).scalar() or 0.0

    # Daily enrollment trend — single query per day is acceptable for analytics
    daily_trend = []
    for i in range(period_days - 1, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = db.query(Enrollment).filter(
            Enrollment.course_id == course_id,
            Enrollment.created_at >= day_start,
            Enrollment.created_at < day_end,
        ).count()
        daily_trend.append({
            "date": day.strftime("%Y-%m-%d"),
            "enrollments": count,
        })

    # Top students by progress
    top_students_raw = db.query(Enrollment).filter(
        Enrollment.course_id == course_id,
        Enrollment.status == EnrollmentStatus.active,
    ).order_by(Enrollment.progress_pct.desc()).limit(10).all()

    # Bulk-fetch user names
    top_user_ids = [e.user_id for e in top_students_raw]
    top_users_map = {}
    if top_user_ids:
        top_users = db.query(User).filter(User.id.in_(top_user_ids)).all()
        top_users_map = {u.id: u for u in top_users}

    result = {
        "course_id": course_id,
        "course_title": course.title,
        "period_days": period_days,
        "summary": {
            "total_enrollments": total_enrollments,
            "active_enrollments": active_enrollments,
            "completed_enrollments": completed_enrollments,
            "completion_rate": round(
                (completed_enrollments / total_enrollments * 100), 1
            ) if total_enrollments > 0 else 0.0,
            "new_enrollments_in_period": new_enrollments,
            "average_progress_pct": round(float(avg_progress), 1),
            "revenue_in_period": float(course_revenue),
        },
        "daily_enrollment_trend": daily_trend,
        "top_performers": [
            {
                "user_id": e.user_id,
                "name": _safe_get(top_users_map.get(e.user_id), "name"),
                "progress_pct": e.progress_pct,
                "completed_topics": e.completed_topics,
            }
            for e in top_students_raw
        ],
    }

    cache.set(cache_key, result, ttl=_ANALYTICS_CACHE_TTL)
    return result


@router.get("/enrollments/analytics/paths/{path_id}", dependencies=[Depends(require_admin)])
async def get_path_enrollment_analytics(
    path_id: int,
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Comprehensive analytics for a specific learning path.
    Cached for 5 minutes keyed on path_id + period_days.
    """
    cache_key = f"admin:analytics:path:{path_id}:{period_days}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found")

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days)

    total_enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.path_id == path_id
    ).count()
    active_enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.path_id == path_id,
        PathEnrollment.status == EnrollmentStatus.active,
    ).count()
    completed = db.query(PathEnrollment).filter(
        PathEnrollment.path_id == path_id,
        PathEnrollment.status == EnrollmentStatus.completed,
    ).count()

    new_in_period = db.query(PathEnrollment).filter(
        PathEnrollment.path_id == path_id,
        PathEnrollment.created_at >= period_start,
    ).count()

    avg_progress = db.query(func.avg(PathEnrollment.progress_pct)).filter(
        PathEnrollment.path_id == path_id,
        PathEnrollment.status == EnrollmentStatus.active,
    ).scalar() or 0.0

    daily_trend = []
    for i in range(period_days - 1, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = db.query(PathEnrollment).filter(
            PathEnrollment.path_id == path_id,
            PathEnrollment.created_at >= day_start,
            PathEnrollment.created_at < day_end,
        ).count()
        daily_trend.append({"date": day.strftime("%Y-%m-%d"), "enrollments": count})

    result = {
        "path_id": path_id,
        "path_title": path.title,
        "period_days": period_days,
        "summary": {
            "total_enrollments": total_enrollments,
            "active_enrollments": active_enrollments,
            "completed_enrollments": completed,
            "completion_rate": round(
                (completed / total_enrollments * 100), 1
            ) if total_enrollments > 0 else 0.0,
            "new_enrollments_in_period": new_in_period,
            "average_progress_pct": round(float(avg_progress), 1),
        },
        "daily_enrollment_trend": daily_trend,
    }

    cache.set(cache_key, result, ttl=_ANALYTICS_CACHE_TTL)
    return result


@router.get("/enrollments/analytics/global", dependencies=[Depends(require_admin)])
async def get_global_enrollment_analytics(
    period_days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """
    Global enrollment analytics across all courses and paths.
    Cached for 5 minutes keyed on period_days.
    """
    cache_key = f"admin:analytics:global:{period_days}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=period_days)

    # Course enrollments
    total_course_enrollments = db.query(Enrollment).count()
    active_course_enrollments = db.query(Enrollment).filter(
        Enrollment.status == EnrollmentStatus.active
    ).count()
    new_course_enrollments = db.query(Enrollment).filter(
        Enrollment.created_at >= period_start
    ).count()

    # Path enrollments
    total_path_enrollments = db.query(PathEnrollment).count()
    active_path_enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.status == EnrollmentStatus.active
    ).count()
    new_path_enrollments = db.query(PathEnrollment).filter(
        PathEnrollment.created_at >= period_start
    ).count()

    # Revenue
    total_revenue = db.query(func.sum(Payment.amount)).filter(
        Payment.tx_status == PaymentStatus.successful,
        Payment.created_at >= period_start,
    ).scalar() or 0.0

    # Top courses by enrollment
    top_courses = (
        db.query(
            Course.id, Course.title, func.count(Enrollment.id).label("enrollment_count")
        )
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(Enrollment.created_at >= period_start)
        .group_by(Course.id, Course.title)
        .order_by(func.count(Enrollment.id).desc())
        .limit(10)
        .all()
    )

    # Top paths by enrollment
    top_paths = (
        db.query(
            LearningPath.id, LearningPath.title,
            func.count(PathEnrollment.id).label("enrollment_count")
        )
        .join(PathEnrollment, PathEnrollment.path_id == LearningPath.id)
        .filter(PathEnrollment.created_at >= period_start)
        .group_by(LearningPath.id, LearningPath.title)
        .order_by(func.count(PathEnrollment.id).desc())
        .limit(10)
        .all()
    )

    result = {
        "period_days": period_days,
        "courses": {
            "total_enrollments": total_course_enrollments,
            "active_enrollments": active_course_enrollments,
            "new_in_period": new_course_enrollments,
        },
        "paths": {
            "total_enrollments": total_path_enrollments,
            "active_enrollments": active_path_enrollments,
            "new_in_period": new_path_enrollments,
        },
        "revenue_in_period": float(total_revenue),
        "top_courses": [
            {"id": c.id, "title": c.title, "enrollments": c.enrollment_count}
            for c in top_courses
        ],
        "top_paths": [
            {"id": p.id, "title": p.title, "enrollments": p.enrollment_count}
            for p in top_paths
        ],
    }

    cache.set(cache_key, result, ttl=_ANALYTICS_CACHE_TTL)
    return result

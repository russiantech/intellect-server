import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.db.database import get_db
from app.models import (
    User, Course, Enrollment, Payment, TeamRequest, Invite, Broadcast, Notification, BrandConfig,
    TutorAssignment, Schedule, AttendanceRecord, Role, Partnership, Category, Tag,
)
from app.models.courses import CourseStatus
from app.models.payments import PaymentStatus
from app.models.misc import TeamRequestStatus, NotificationType, BroadcastType
from app.schemas import (
    TeamRequestReview, InviteCreate, BroadcastCreate,
    BrandConfigUpdate, TutorAssignRequest, ScheduleCreate,
    MarkAttendance, CategoryCreate, TagCreate, SuccessResponse,
)
from app.api.deps.auth import require_admin, get_current_user
from app.services.email_service import (
    send_team_request_approved, send_team_request_rejected,
    send_invite_email, send_broadcast_email,
)
from app.core.config import get_app_config
from slugify import slugify

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


# ─── DASHBOARD ───────────────────────────────────

@router.get("/dashboard", dependencies=[Depends(require_admin)])
async def admin_dashboard(db: Session = Depends(get_db)):
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

    # Role counts
    student_role = db.query(Role).filter(Role.name == "student").first()
    tutor_role = db.query(Role).filter(Role.name == "tutor").first()
    creator_role = db.query(Role).filter(Role.name == "creator").first()

    total_students = db.query(User).join(User.roles).filter(Role.name == "student").count()
    total_tutors = db.query(User).join(User.roles).filter(Role.name == "tutor").count()
    total_creators = db.query(User).join(User.roles).filter(Role.name == "creator").count()

    # Recent enrollments trend (last 7 days)
    trend = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        count = db.query(Enrollment).filter(
            func.date(Enrollment.created_at) == day.date()
        ).count()
        trend.append({"date": day.strftime("%Y-%m-%d"), "enrollments": count})

    return {
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


# ─── BRAND CONFIG ────────────────────────────────

@router.get("/brand", dependencies=[Depends(require_admin)])
async def get_brand_config(db: Session = Depends(get_db)):
    brand = db.query(BrandConfig).filter(BrandConfig.id == 1).first()
    if not brand:
        brand = BrandConfig(id=1)
        db.add(brand)
        db.commit()
        db.refresh(brand)
    return {
        "site_name": brand.site_name, "tagline": brand.tagline,
        "logo": brand.logo, "favicon": brand.favicon,
        "email": brand.email, "phone": brand.phone, "address": brand.address,
        "socials": brand.socials, "whatsapp_link": brand.whatsapp_link,
        "default_creator_pct": brand.default_creator_pct,
        "default_platform_pct": brand.default_platform_pct,
    }


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
    return SuccessResponse(message="Brand config updated")


# ─── CATEGORIES ──────────────────────────────────

@router.post("/categories", dependencies=[Depends(require_admin)], status_code=201)
async def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Category).filter(Category.title == payload.title).first()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    cat = Category(
        title=payload.title, description=payload.description,
        image=payload.image, icon=payload.icon,
        slug=slugify(payload.title),
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "title": cat.title, "slug": cat.slug}


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
    return SuccessResponse(message="Category updated")


@router.delete("/categories/{cat_id}", dependencies=[Depends(require_admin)])
async def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.is_active = False
    db.commit()
    return SuccessResponse(message="Category deleted")


@router.post("/tags", dependencies=[Depends(require_admin)], status_code=201)
async def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    existing = db.query(Tag).filter(Tag.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Tag already exists")
    tag = Tag(name=payload.name)
    db.add(tag)
    db.commit()
    return {"id": tag.id, "name": tag.name}


# ─── TEAM REQUESTS ───────────────────────────────

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
    action = "approved" if payload.approved else "rejected"
    return SuccessResponse(message=f"Team request {action}")


# ─── INVITES ─────────────────────────────────────

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


# ─── BROADCASTS ──────────────────────────────────

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
    recipients_query = db.query(User).filter(User.is_active == True, User.email_verified == True)

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


# ─── TUTOR ASSIGNMENTS ────────────────────────────

@router.post("/tutor-assignments", dependencies=[Depends(require_admin)], status_code=201)
async def assign_tutor(
    payload: TutorAssignRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tutor = db.query(User).filter(User.id == payload.tutor_id).first()
    if not tutor or not (tutor.has_role("tutor") or tutor.is_admin()):
        raise HTTPException(status_code=400, detail="User is not a tutor")
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    existing = db.query(TutorAssignment).filter(
        TutorAssignment.tutor_id == payload.tutor_id,
        TutorAssignment.course_id == payload.course_id,
        TutorAssignment.student_id == payload.student_id,
    ).first()
    if existing:
        return SuccessResponse(message="Already assigned")

    assignment = TutorAssignment(
        tutor_id=payload.tutor_id, course_id=payload.course_id,
        student_id=payload.student_id, assigned_by_id=admin.id,
    )
    db.add(assignment)
    db.commit()
    return SuccessResponse(message="Tutor assigned successfully")


@router.delete("/tutor-assignments/{assignment_id}", dependencies=[Depends(require_admin)])
async def unassign_tutor(assignment_id: int, db: Session = Depends(get_db)):
    assignment = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment)
    db.commit()
    return SuccessResponse(message="Tutor unassigned")


@router.get("/tutor-assignments", dependencies=[Depends(require_admin)])
async def list_tutor_assignments(
    course_id: Optional[int] = None,
    tutor_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(TutorAssignment)
    if course_id:
        q = q.filter(TutorAssignment.course_id == course_id)
    if tutor_id:
        q = q.filter(TutorAssignment.tutor_id == tutor_id)
    assignments = q.options(
        joinedload(TutorAssignment.tutor), joinedload(TutorAssignment.course),
    ).all()
    return [
        {
            "id": a.id,
            "tutor": {"id": a.tutor.id, "name": a.tutor.name, "email": a.tutor.email} if a.tutor else None,
            "course": {"id": a.course.id, "title": a.course.title} if a.course else None,
            "student_id": a.student_id,
        }
        for a in assignments
    ]


# ─── SCHEDULES ───────────────────────────────────

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
        enrolled_ids = [e.course_id for e in db.query(Enrollment).filter(Enrollment.user_id == user.id).all()]
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


@router.post("/schedules/{schedule_id}/attendance", dependencies=[Depends(require_tutor_or_admin := require_admin)])
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


# ─── ADMIN ENROLL USER ────────────────────────────

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
    return SuccessResponse(message=f"User enrolled in course successfully")


# ─── CERTIFICATES ADMIN ───────────────────────────

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
            "user": {"id": c.user.id, "name": c.user.name, "email": c.user.email} if c.user else None,
            "course": {"id": c.course.id, "title": c.course.title} if c.course else None,
        }
        for c in certs
    ]

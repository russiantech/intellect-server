import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.models import Partnership, PartnerStudent, User, Course, LearningPath, Enrollment, Role
from app.models.misc import PartnershipStatus
from app.schemas import PartnershipCreate, PartnershipUpdate, SuccessResponse
from app.api.deps.auth import require_admin, get_current_user

router = APIRouter(prefix="/partnerships", tags=["Partnerships"])
logger = logging.getLogger(__name__)


def _partner_dict(p: Partnership) -> dict:
    return {
        "id": p.id, "org_name": p.org_name, "org_email": p.org_email,
        "org_phone": p.org_phone, "org_logo": p.org_logo,
        "contact_person": p.contact_person, "status": p.status,
        "price_per_student": p.price_per_student,
        "max_students": p.max_students, "active_students": p.active_students,
        "contract_start": p.contract_start, "contract_end": p.contract_end,
        "courses": [
            {"id": c.id, "title": c.title, "slug": c.slug, "thumbnail": c.thumbnail}
            for c in p.courses
        ],
        "paths": [
            {"id": pa.id, "title": pa.title, "slug": pa.slug}
            for pa in p.paths
        ],
        "student_count": len(p.students),
        "created_at": p.created_at,
    }


@router.get("/", dependencies=[Depends(require_admin)])
async def list_partnerships(
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(20),
    db: Session = Depends(get_db),
):
    q = db.query(Partnership)
    if status:
        q = q.filter(Partnership.status == status)
    total = q.count()
    partnerships = q.options(
        joinedload(Partnership.courses),
        joinedload(Partnership.paths),
        joinedload(Partnership.students),
    ).order_by(Partnership.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [_partner_dict(p) for p in partnerships],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{partnership_id}")
async def get_partnership(
    partnership_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = db.query(Partnership).options(
        joinedload(Partnership.courses), joinedload(Partnership.paths), joinedload(Partnership.students),
    ).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partnership not found")
    if not user.is_admin() and p.partner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return _partner_dict(p)


@router.post("/", dependencies=[Depends(require_admin)], status_code=201)
async def create_partnership(
    payload: PartnershipCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    p = Partnership(
        org_name=payload.org_name, org_email=payload.org_email,
        org_phone=payload.org_phone, contact_person=payload.contact_person,
        price_per_student=payload.price_per_student,
        max_students=payload.max_students,
        contract_start=payload.contract_start, contract_end=payload.contract_end,
        managed_by_id=admin.id, status=PartnershipStatus.pending,
    )
    if payload.course_ids:
        p.courses = db.query(Course).filter(Course.id.in_(payload.course_ids)).all()
    if payload.path_ids:
        p.paths = db.query(LearningPath).filter(LearningPath.id.in_(payload.path_ids)).all()
    db.add(p)
    db.commit()
    db.refresh(p)

    # Create partner user account if not exists
    partner_user = db.query(User).filter(User.email == payload.org_email).first()
    if not partner_user:
        from app.core.security.security import hash_password
        import uuid
        partner_user = User(
            name=payload.org_name,
            username=f"partner_{uuid.uuid4().hex[:8]}",
            email=payload.org_email,
            password_hash=hash_password(uuid.uuid4().hex),
            email_verified=True,
        )
        partner_role = db.query(Role).filter(Role.name == "partner").first()
        if not partner_role:
            partner_role = Role(name="partner", description="Partner Organization")
            db.add(partner_role)
            db.flush()
        partner_user.roles.append(partner_role)
        db.add(partner_user)
        db.flush()

    p.partner_user_id = partner_user.id
    db.commit()
    return _partner_dict(p)


@router.put("/{partnership_id}", dependencies=[Depends(require_admin)])
async def update_partnership(
    partnership_id: int,
    payload: PartnershipUpdate,
    db: Session = Depends(get_db),
):
    p = db.query(Partnership).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partnership not found")

    for k, v in payload.model_dump(exclude_none=True, exclude={"course_ids", "path_ids"}).items():
        setattr(p, k, v)

    if payload.course_ids is not None:
        p.courses = db.query(Course).filter(Course.id.in_(payload.course_ids)).all()
    if payload.path_ids is not None:
        p.paths = db.query(LearningPath).filter(LearningPath.id.in_(payload.path_ids)).all()

    db.commit()
    return SuccessResponse(message="Partnership updated")


@router.post("/{partnership_id}/activate", dependencies=[Depends(require_admin)])
async def activate_partnership(partnership_id: int, db: Session = Depends(get_db)):
    p = db.query(Partnership).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partnership not found")
    p.status = PartnershipStatus.active
    db.commit()
    return SuccessResponse(message="Partnership activated")


@router.post("/{partnership_id}/suspend", dependencies=[Depends(require_admin)])
async def suspend_partnership(partnership_id: int, db: Session = Depends(get_db)):
    p = db.query(Partnership).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partnership not found")
    p.status = PartnershipStatus.suspended
    db.commit()
    return SuccessResponse(message="Partnership suspended")


@router.post("/{partnership_id}/enroll-student")
async def partner_enroll_student(
    partnership_id: int,
    student_email: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Partner admin enrolls a student into all partnership courses."""
    p = db.query(Partnership).options(
        joinedload(Partnership.courses), joinedload(Partnership.paths),
    ).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partnership not found")
    if not user.is_admin() and p.partner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    if p.status != PartnershipStatus.active:
        raise HTTPException(status_code=400, detail="Partnership is not active")
    if p.max_students and p.active_students >= p.max_students:
        raise HTTPException(status_code=400, detail="Maximum student limit reached")

    # Find or create student
    student = db.query(User).filter(User.email == student_email).first()
    if not student:
        from app.core.security.security import hash_password
        import uuid
        student = User(
            username=f"student_{uuid.uuid4().hex[:8]}",
            email=student_email,
            password_hash=hash_password(uuid.uuid4().hex),
            email_verified=True,
        )
        student_role = db.query(Role).filter(Role.name == "student").first()
        if student_role:
            student.roles.append(student_role)
        db.add(student)
        db.flush()

    # Add to partner students
    existing = db.query(PartnerStudent).filter(
        PartnerStudent.partnership_id == partnership_id,
        PartnerStudent.user_id == student.id,
    ).first()
    if not existing:
        db.add(PartnerStudent(partnership_id=partnership_id, user_id=student.id))
        p.active_students += 1

    # Enroll in all partnership courses
    for course in p.courses:
        if not db.query(Enrollment).filter(
            Enrollment.user_id == student.id, Enrollment.course_id == course.id,
        ).first():
            db.add(Enrollment(user_id=student.id, course_id=course.id))

    db.commit()
    return SuccessResponse(message=f"Student enrolled in {len(p.courses)} course(s)")


@router.get("/{partnership_id}/students")
async def list_partner_students(
    partnership_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p = db.query(Partnership).filter(Partnership.id == partnership_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Partnership not found")
    if not user.is_admin() and p.partner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    partner_students = db.query(PartnerStudent).options(
        joinedload(PartnerStudent.partnership),
    ).filter(PartnerStudent.partnership_id == partnership_id).all()

    result = []
    for ps in partner_students:
        student = db.query(User).filter(User.id == ps.user_id).first()
        if student:
            result.append({
                "id": student.id, "name": student.name,
                "username": student.username, "email": student.email,
                "image": student.image, "joined_at": ps.created_at,
            })
    return result

from datetime import datetime, timezone
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from slugify import slugify
from app.api.deps.auth import get_current_user, require_admin
from app.db.database import get_db
from app.models import (
    Category, Course, LearningPath, User
)
from app.schemas import (
    CategoryCreate, TutorAssignRequest, 
    SuccessResponse, TutorAssignmentReview
)
 
router = APIRouter(prefix="/categories", tags=["Admin"])
logger = logging.getLogger(__name__)

# # ══════════════════════════════════════════════════════════════════════════════
# # CATEGORIES — complete CRUD
# # ══════════════════════════════════════════════════════════════════════════════

# @router.get("/categories", dependencies=[Depends(require_admin)])
# async def list_categories(
#     active_only: bool = Query(True),
#     search: Optional[str] = None,
#     db: Session = Depends(get_db),
# ):
#     """List all categories. Admins can see inactive ones with active_only=false."""
#     q = db.query(Category)
#     if active_only:
#         q = q.filter(Category.is_active == True)
#     if search:
#         q = q.filter(Category.title.ilike(f"%{search}%"))
#     cats = q.order_by(Category.sort_order.asc(), Category.title.asc()).all()
#     return [
#         {
#             "id": c.id, "title": c.title, "description": c.description,
#             "image": c.image, "icon": c.icon, "slug": c.slug,
#             "sort_order": getattr(c, "sort_order", 0),
#             "is_active": c.is_active,
#             "courses_count": len(c.courses) if c.courses else 0,
#             "created_at": c.created_at,
#         }
#         for c in cats
#     ]


# @router.post("/categories", dependencies=[Depends(require_admin)], status_code=201)
# async def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
#     existing = db.query(Category).filter(Category.title == payload.title).first()
#     if existing:
#         raise HTTPException(status_code=400, detail="Category already exists")
#     cat = Category(
#         title=payload.title, description=payload.description,
#         image=payload.image, icon=payload.icon,
#         slug=slugify(payload.title),
#         sort_order=payload.sort_order,
#     )
#     db.add(cat)
#     db.commit()
#     db.refresh(cat)
#     return {"id": cat.id, "title": cat.title, "slug": cat.slug, "sort_order": cat.sort_order}
 
 
# @router.put("/categories/{cat_id}", dependencies=[Depends(require_admin)])
# async def update_category(cat_id: int, payload: CategoryCreate, db: Session = Depends(get_db)):
#     cat = db.query(Category).filter(Category.id == cat_id).first()
#     if not cat:
#         raise HTTPException(status_code=404, detail="Category not found")
#     for k, v in payload.model_dump(exclude_none=True).items():
#         setattr(cat, k, v)
#     if payload.title:
#         cat.slug = slugify(payload.title)
#     db.commit()
#     return SuccessResponse(message="Category updated")
 
 
# @router.delete("/categories/{cat_id}", dependencies=[Depends(require_admin)])
# async def deactivate_category(cat_id: int, db: Session = Depends(get_db)):
#     """Soft-delete: marks inactive. Does NOT remove courses assigned to it."""
#     cat = db.query(Category).filter(Category.id == cat_id).first()
#     if not cat:
#         raise HTTPException(status_code=404, detail="Category not found")
#     cat.is_active = False
#     db.commit()
#     return SuccessResponse(message="Category deactivated")
 

# @router.post("/categories/{cat_id}/restore", dependencies=[Depends(require_admin)])
# async def restore_category(cat_id: int, db: Session = Depends(get_db)):
#     cat = db.query(Category).filter(Category.id == cat_id).first()
#     if not cat:
#         raise HTTPException(status_code=404, detail="Category not found")
#     cat.is_active = True
#     db.commit()
#     return SuccessResponse(message="Category restored")
 
 
# @router.post("/categories/reorder", dependencies=[Depends(require_admin)])
# async def reorder_categories(
#     order: list[dict],   # [{"id": 1, "sort_order": 0}, ...]
#     db: Session = Depends(get_db),
# ):
#     """Bulk update sort_order for categories."""
#     for item in order:
#         cat = db.query(Category).filter(Category.id == item["id"]).first()
#         if cat:
#             cat.sort_order = item.get("sort_order", 0)
#     db.commit()
#     return SuccessResponse(message="Categories reordered")
 

# # ─── Course ↔ Category assignment ────────────────────────────────────────────
 
# @router.post("/categories/{cat_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
# async def assign_category_to_course(cat_id: int, course_id: int, db: Session = Depends(get_db)):
#     cat    = db.query(Category).filter(Category.id == cat_id).first()
#     course = db.query(Course).filter(Course.id == course_id).first()
#     if not cat or not course:
#         raise HTTPException(status_code=404, detail="Category or course not found")
#     if cat not in course.categories:
#         course.categories.append(cat)
#         db.commit()
#     return SuccessResponse(message="Category assigned to course")
 

# @router.delete("/categories/{cat_id}/courses/{course_id}", dependencies=[Depends(require_admin)])
# async def unassign_category_from_course(cat_id: int, course_id: int, db: Session = Depends(get_db)):
#     cat    = db.query(Category).filter(Category.id == cat_id).first()
#     course = db.query(Course).filter(Course.id == course_id).first()
#     if not cat or not course:
#         raise HTTPException(status_code=404, detail="Category or course not found")
#     course.categories = [c for c in course.categories if c.id != cat_id]
#     db.commit()
#     return SuccessResponse(message="Category removed from course")
 
 
# # ─── Path ↔ Category assignment ──────────────────────────────────────────────
 
# @router.post("/categories/{cat_id}/paths/{path_id}", dependencies=[Depends(require_admin)])
# async def assign_category_to_path(cat_id: int, path_id: int, db: Session = Depends(get_db)):
#     cat  = db.query(Category).filter(Category.id == cat_id).first()
#     path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
#     if not cat or not path:
#         raise HTTPException(status_code=404, detail="Category or path not found")
#     if cat not in path.categories:
#         path.categories.append(cat)
#         db.commit()
#     return SuccessResponse(message="Category assigned to path")
 
 
# @router.delete("/categories/{cat_id}/paths/{path_id}", dependencies=[Depends(require_admin)])
# async def unassign_category_from_path(cat_id: int, path_id: int, db: Session = Depends(get_db)):
#     cat  = db.query(Category).filter(Category.id == cat_id).first()
#     path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
#     if not cat or not path:
#         raise HTTPException(status_code=404, detail="Category or path not found")
#     path.categories = [c for c in path.categories if c.id != cat_id]
#     db.commit()
#     return SuccessResponse(message="Category removed from path")


# ══════════════════════════════════════════════════════════════════════════════
# INSTRUCTOR ASSIGNMENTS
# ══════════════════════════════════════════════════════════════════════════════
 
def _serialize_assignment(a) -> dict:
    return {
        "id": a.id,
        "tutor": {
            "id": a.tutor.id, "name": a.tutor.name,
            "email": a.tutor.email, "image": a.tutor.image,
        } if a.tutor else None,
        "course": {"id": a.course.id, "title": a.course.title} if a.course else None,
        "path":   {"id": a.path.id,   "title": a.path.title}   if a.path   else None,
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
    course_id:     Optional[int] = None,
    path_id:       Optional[int] = None,
    instructor_id: Optional[int] = None,
    status:        Optional[str] = None,
    db: Session = Depends(get_db),
):
    from app.models import TutorAssignment
    q = db.query(TutorAssignment).options(
        joinedload(TutorAssignment.tutor),
        joinedload(TutorAssignment.course),
        joinedload(TutorAssignment.path),
        joinedload(TutorAssignment.assigned_by),
    )
    if course_id:     q = q.filter(TutorAssignment.course_id == course_id)
    if path_id:       q = q.filter(TutorAssignment.path_id   == path_id)
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
    from app.models import TutorAssignment
    from app.schemas import TutorAssignmentStatus
 
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
    return {"id": a.id, "status": a.status, "message": "Instructor assigned"}
 
 
@router.patch("/tutor-assignments/{assignment_id}/review", dependencies=[Depends(require_admin)])
async def review_instructor_assignment(
    assignment_id: int,
    payload: TutorAssignmentReview,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve or reject an instructor's self-requested assignment."""
    from app.models import TutorAssignment
    from app.schemas import TutorAssignmentStatus
 
    a = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a.status != TutorAssignmentStatus.pending:
        raise HTTPException(status_code=400, detail=f"Assignment is already {a.status}")
 
    a.status = TutorAssignmentStatus.approved if payload.approved else TutorAssignmentStatus.rejected
    a.assigned_by_id = admin.id
    a.rejection_reason = payload.rejection_reason if not payload.approved else None
    db.commit()
    return SuccessResponse(message=f"Assignment {'approved' if payload.approved else 'rejected'}")
 
 
@router.patch("/tutor-assignments/{assignment_id}/revoke", dependencies=[Depends(require_admin)])
async def revoke_instructor_assignment(
    assignment_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Revoke a previously approved assignment."""
    from app.models import TutorAssignment
    from app.schemas import TutorAssignmentStatus
 
    a = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if a.status not in [TutorAssignmentStatus.approved, TutorAssignmentStatus.pending]:
        raise HTTPException(status_code=400, detail="Assignment is not active")
 
    a.status = TutorAssignmentStatus.revoked
    a.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return SuccessResponse(message="Assignment revoked")
 
 
@router.delete("/tutor-assignments/{assignment_id}", dependencies=[Depends(require_admin)])
async def delete_instructor_assignment(assignment_id: int, db: Session = Depends(get_db)):
    from app.models import TutorAssignment
    a = db.query(TutorAssignment).filter(TutorAssignment.id == assignment_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(a)
    db.commit()
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
    from app.models import TutorAssignment
    from app.schemas import TutorAssignmentStatus
 
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
        from app.models.courses import LearningPath
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
        tutor_id=current_user.tutor_id,
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
 

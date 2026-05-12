# v2
import os
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.db.database import get_db
from app.models import User, Role
from app.schemas import UserUpdateRequest, AdminUpdateUser
from app.api.deps.auth import get_current_user, require_admin
from app.core.config import get_app_config

router = APIRouter(prefix="/users", tags=["Users"])
logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Roles that are publicly listable as instructors/creators
PUBLIC_INSTRUCTOR_ROLES = {"tutor", "creator", "instructor"}

def _avatar_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("http"):
        return path
    cfg = get_app_config()
    base = cfg.hosting_config.api_url.rstrip("/")
    return f"{base}/uploads/avatars/{path}"


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "username": user.username,
        "email": user.email, "phone": user.phone, "image": _avatar_url(user.image),
        "title": user.title, "gender": user.gender, "city": user.city,
        "country": user.country, "lang": user.lang, "about": user.about,
        "socials": user.socials, "education": user.education, "expertise": user.expertise,
        "projects": getattr(user, "projects", None),
        "is_creator": user.is_creator, "creator_bio": user.creator_bio,
        "creator_approved": user.creator_approved, "email_verified": user.email_verified,
        "is_online": user.is_online, "last_seen": user.last_seen,
        "roles": [r.name for r in user.roles], "primary_role": user.primary_role(),
        "bank_name": user.bank_name, "bank_account_number": user.bank_account_number,
        "bank_account_name": user.bank_account_name,
        "active": user.is_active, "created_at": user.created_at,
    }


def _public_instructor_dict(user: User) -> dict:
    """Curated public profile — no sensitive fields."""
    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        # "image": user.image,
        "image": _avatar_url(user.image),
        "title": user.title,
        "city": user.city,
        "country": user.country,
        "about": user.about,
        "creator_bio": user.creator_bio,
        "expertise": user.expertise,
        "education": user.education,
        "socials": user.socials,
        "projects": getattr(user, "projects", None),
        "is_creator": user.is_creator,
        "creator_approved": user.creator_approved,
        "is_online": user.is_online,
        "last_seen": user.last_seen,
        "roles": [r.name for r in user.roles],
        "primary_role": user.primary_role(),
        "created_at": user.created_at,
    }


# ─────────────────────────────────────────────────────────────
#  PUBLIC ENDPOINTS  (no authentication required)
# ─────────────────────────────────────────────────────────────

@router.get("/instructors")
async def list_instructors(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,          # 'tutor' | 'creator' | None (all)
    db: Session = Depends(get_db),
):
    """
    Public endpoint — lists approved instructors and creators.
    No authentication required. Safe fields only.
    """
    # Base: active users with at least one instructor-class role
    # q = (
    #     db.query(User)
    #     .join(User.roles)
    #     .filter(
    #         User.is_active == True,
    #         Role.name.in_(PUBLIC_INSTRUCTOR_ROLES),
    #     )
    #     .distinct()
    # )
    
    from sqlalchemy import distinct

    q = (
    db.query(User)
    .join(User.roles)
    .filter(
        User.is_active == True,
        Role.name.in_(PUBLIC_INSTRUCTOR_ROLES),
    )
    .group_by(User.id)
)

    if role and role in PUBLIC_INSTRUCTOR_ROLES:
        q = q.filter(Role.name == role)

    if search:
        q = q.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.username.ilike(f"%{search}%"),
                User.title.ilike(f"%{search}%"),
                User.expertise.ilike(f"%{search}%"),
                User.city.ilike(f"%{search}%"),
            )
        )

    total = q.count()
    users = (
        q.order_by(User.creator_approved.desc(), User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "items": [_public_instructor_dict(u) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/public/{username}")
async def get_public_profile(username: str, db: Session = Depends(get_db)):
    """Public profile — available for any active user; richer data for instructors."""
    user = db.query(User).filter(
        User.username == username,
        User.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _public_instructor_dict(user)


# ─────────────────────────────────────────────────────────────
#  AUTHENTICATED USER ENDPOINTS
# ─────────────────────────────────────────────────────────────

@router.get("/profile")
async def get_my_profile(user: User = Depends(get_current_user)):
    return _user_to_dict(user)


@router.put("/profile")
async def update_profile(
    payload: UserUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    for field, val in payload.model_dump(exclude_none=True).items():
        setattr(user, field, val)
    db.commit()
    db.refresh(user)
    return _user_to_dict(user)


@router.post("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    cfg = get_app_config()
    upload_dir = os.path.join(cfg.hosting_config.content_delivery.filesystem_base_path, "avatars")
    os.makedirs(upload_dir, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_dir, filename)

    content = await file.read()
    if len(content) > cfg.hosting_config.content_delivery.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large")

    with open(filepath, "wb") as f:
        f.write(content)

    if user.image and user.image != "default.svg":
        old = os.path.join(upload_dir, user.image)
        if os.path.exists(old):
            os.remove(old)

    user.image = filename
    db.commit()
    # return {"image": filename, "url": f"/uploads/avatars/{filename}"}
    return {
        "image": _avatar_url(filename),   # ← full absolute URL
        "url": _avatar_url(filename),     # ← full absolute URL
    }


# ─────────────────────────────────────────────────────────────
#  ADMIN ENDPOINTS
# ─────────────────────────────────────────────────────────────

@router.get("/", dependencies=[Depends(require_admin)])
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    active: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if search:
        q = q.filter(or_(
            User.name.ilike(f"%{search}%"),
            User.email.ilike(f"%{search}%"),
            User.username.ilike(f"%{search}%"),
        ))
    if role:
        q = q.join(User.roles).filter(Role.name == role)
    if active is not None:
        q = q.filter(User.is_active == active)

    total = q.count()
    users = q.order_by(User.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

    return {
        "items": [_user_to_dict(u) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/{user_id}", dependencies=[Depends(require_admin)])
async def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _user_to_dict(user)


@router.put("/{user_id}/admin", dependencies=[Depends(require_admin)])
async def admin_update_user(
    user_id: int,
    payload: AdminUpdateUser,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    for field, val in payload.model_dump(exclude_none=True, exclude={"roles"}).items():
        setattr(user, field, val)

    if payload.roles is not None:
        roles = db.query(Role).filter(Role.name.in_(payload.roles)).all()
        user.roles = roles

    db.commit()
    db.refresh(user)
    return _user_to_dict(user)


@router.post("/{user_id}/toggle-active", dependencies=[Depends(require_admin)])
async def toggle_user_active(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    db.commit()
    return {"active": user.is_active, "message": f"User {'activated' if user.is_active else 'deactivated'}"}


@router.post("/{user_id}/assign-role", dependencies=[Depends(require_admin)])
async def assign_role(user_id: int, role_name: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role = db.query(Role).filter(Role.name == role_name).first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
    if role not in user.roles:
        user.roles.append(role)
        db.commit()
    return {"message": f"Role '{role_name}' assigned", "roles": [r.name for r in user.roles]}


@router.delete("/{user_id}/remove-role/{role_name}", dependencies=[Depends(require_admin)])
async def remove_role(user_id: int, role_name: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.roles = [r for r in user.roles if r.name != role_name]
    db.commit()
    
    data = {"message": f"Role '{role_name}' removed", "roles": [r.name for r in user.roles]}
    return data

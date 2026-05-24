"""
Intellect LMS — Learning Paths API  v2
─────────────────────────────────────────────────────────────────────────────
• Anonymous detail & list caching (two-layer) with user-specific overlay
• Cache invalidation on all mutating operations
• N+1 eliminated via bulk topic-count queries and eager loading
• Absolute URLs for all media (thumbnails)
• Full serializer reused across every endpoint
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.performance.cache_config import cache
from app.utils.responses import api_response, PageSerializer
from app.db.database import get_db
from app.models import (
    Course,
    LearningPath,
    User,
)
from app.utils.paths import (
    _ALLOWED_IMAGE_TYPES,
    _serialize_path,
    _base_path_query,
    _bulk_topic_counts,
    _invalidate_path_caches,
    _save_upload_file,
)
from app.api.deps.auth import require_admin, optional_user

router = APIRouter(prefix="/paths", tags=["Learning Paths"])

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Public / Read
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/")
async def list_paths(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    """
    List all active learning paths.

    Two-layer caching strategy:
      Layer 1 — anonymous list stored under ``paths:list``.
      Layer 2 — user-specific enrollment overlay applied in-process
                so personalised fields never pollute the shared cache.
    """
    # Build a stable cache key that accounts for pagination + search
    anon_key = f"paths:list:p{page}:pp{per_page}:s{search or ''}"
    cached_anon = cache.get(anon_key)

    if cached_anon and not current_user:
        # Fully anonymous hit — return immediately
        return api_response(success=True, message="Paths retrieved.", data=cached_anon)

    # ── Database query ────────────────────────────────────────────────────────
    q = _base_path_query(db)

    if search:
        from sqlalchemy import or_

        term = f"%{search}%"
        q = q.filter(
            or_(
                LearningPath.title.ilike(term),
                LearningPath.description.ilike(term),
            )
        )

    total = q.count()
    paths = (
        q.order_by(LearningPath.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    # Bulk topic counts — one query for all courses across all paths
    all_course_ids = [c.id for p in paths for c in p.courses]
    topic_counts = _bulk_topic_counts(db, all_course_ids)

    # ── Serialize (anonymous baseline) ────────────────────────────────────────
    anon_items = [
        _serialize_path(p, topic_counts=topic_counts, include_stats=True)
        for p in paths
    ]

    anon_ps = PageSerializer(request=request, obj=anon_items, page=page, page_size=per_page)
    anon_payload = {"page_meta": anon_ps.data, "items": anon_ps.items}

    # Store anonymous payload only when there is no search term to avoid
    # caching highly specific queries that are unlikely to be repeated.
    if not search:
        cache.set(anon_key, anon_payload, ttl=300)  # 5-minute TTL

    if not current_user:
        return api_response(success=True, message="Paths retrieved.", data=anon_payload)

    # ── User overlay — apply enrollment fields on top of cached baseline ──────
    user_items = [
        _serialize_path(
            p,
            user=current_user,
            topic_counts=topic_counts,
            include_stats=True,
        )
        for p in paths
    ]

    user_ps = PageSerializer(request=request, obj=user_items, page=page, page_size=per_page)
    user_payload = {"page_meta": user_ps.data, "items": user_ps.items}

    return api_response(success=True, message="Paths retrieved.", data=user_payload)


@router.get("/{path_id_or_slug}")
async def get_path(
    path_id_or_slug: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    """
    Get a single learning path by integer ID or slug.

    Cache behaviour mirrors the list endpoint:
      • Anonymous responses are cached under ``paths:detail:<id|slug>``.
      • Authenticated responses skip the cache write (user data must not leak).
      • A cache hit for an anonymous caller is returned without touching the DB.
    """
    anon_key = f"paths:detail:{path_id_or_slug}"

    # Anonymous fast-path
    if not current_user:
        cached = cache.get(anon_key)
        if cached:
            return api_response(success=True, message="Path retrieved.", data=cached)

    # ── Resolve path ──────────────────────────────────────────────────────────
    q = (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
    )

    try:
        path_id = int(path_id_or_slug)
        path = q.filter(LearningPath.id == path_id).first()
    except ValueError:
        path = q.filter(LearningPath.slug == path_id_or_slug).first()

    if not path or path.is_deleted:
        raise HTTPException(status_code=404, detail="Learning path not found.")

    course_ids = [c.id for c in path.courses]
    topic_counts = _bulk_topic_counts(db, course_ids)

    # ── Serialize ─────────────────────────────────────────────────────────────
    if not current_user:
        anon_data = _serialize_path(path, topic_counts=topic_counts)
        cache.set(anon_key, anon_data, ttl=300)
        return api_response(success=True, message="Path retrieved.", data=anon_data)

    user_data = _serialize_path(path, user=current_user, topic_counts=topic_counts)
    return api_response(success=True, message="Path retrieved.", data=user_data)


# ─────────────────────────────────────────────────────────────────────────────
# Routes — Admin / Write
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/")
async def create_path(
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Create a new learning path (admin only)."""
    path = LearningPath(**{
        k: v for k, v in payload.items()
        if hasattr(LearningPath, k) and k not in ("id", "created_at", "updated_at")
    })
    db.add(path)
    db.commit()
    db.refresh(path)

    # Eager-load relationships for serialization
    path = (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
        .filter(LearningPath.id == path.id)
        .first()
    )

    _invalidate_path_caches(path)

    return api_response(
        success=True,
        message="Learning path created.",
        data=_serialize_path(path, topic_counts={}),
        status_code=201,
    )


@router.put("/{path_id}")
async def update_path(
    path_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Update an existing learning path (admin only)."""
    path = db.query(LearningPath).filter(
        LearningPath.id == path_id,
        LearningPath.is_deleted.is_(False),
    ).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found.")

    immutable = {"id", "created_at", "updated_at", "thumbnail"}
    for key, value in payload.items():
        if key not in immutable and hasattr(path, key):
            setattr(path, key, value)

    db.commit()
    db.refresh(path)

    # Re-fetch with relationships
    path = (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
        .filter(LearningPath.id == path.id)
        .first()
    )

    course_ids = [c.id for c in path.courses]
    topic_counts = _bulk_topic_counts(db, course_ids)

    _invalidate_path_caches(path)

    return api_response(
        success=True,
        message="Learning path updated.",
        data=_serialize_path(path, topic_counts=topic_counts),
    )



# # ─────────────────────────────────────────────────────────────────────────────
# # Thumbnail upload
# # ─────────────────────────────────────────────────────────────────────────────


# @router.post("/{path_id}/thumbnail")
# async def upload_path_thumbnail(
#     path_id: int,
#     file: UploadFile = File(...),
#     db: Session = Depends(get_db),
#     admin: User = Depends(require_admin),
# ):
#     """Upload or replace the thumbnail for a learning path (admin only)."""
#     path = db.query(LearningPath).filter(
#         LearningPath.id == path_id,
#         LearningPath.is_deleted.is_(False),
#     ).first()

#     if not path:
#         raise HTTPException(status_code=404, detail="Learning path not found.")

#     filename = await _save_upload_file(
#         file,
#         subfolder="paths/thumbnails",
#         old_filename=path.thumbnail,
#         allowed_types=_ALLOWED_IMAGE_TYPES,
#         max_mb=5,
#     )

#     path.thumbnail = filename
#     db.commit()
#     db.refresh(path)

#     # Re-fetch with full relationships for serialization
#     path = (
#         db.query(LearningPath)
#         .options(
#             joinedload(LearningPath.courses).joinedload(Course.lessons),
#             joinedload(LearningPath.path_enrollments),
#         )
#         .filter(LearningPath.id == path.id)
#         .first()
#     )

#     course_ids = [c.id for c in path.courses]
#     topic_counts = _bulk_topic_counts(db, course_ids)

#     _invalidate_path_caches(path)

#     return api_response(
#         data=_serialize_path(path, topic_counts=topic_counts),
#         message="Thumbnail uploaded.",
#     )


@router.delete("/{path_id}")
async def delete_path(
    path_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Soft-delete a learning path (admin only)."""
    path = db.query(LearningPath).filter(
        LearningPath.id == path_id,
        LearningPath.is_deleted.is_(False),
    ).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found.")

    path.is_deleted = True
    path.is_active = False
    db.commit()

    _invalidate_path_caches(path)

    return api_response(success=True, message="Learning path deleted.")


# ─────────────────────────────────────────────────────────────────────────────
# Thumbnail upload
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{path_id}/thumbnail")
async def upload_path_thumbnail(
    path_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Upload or replace the thumbnail for a learning path (admin only)."""
    path = db.query(LearningPath).filter(
        LearningPath.id == path_id,
        LearningPath.is_deleted.is_(False),
    ).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found.")

    filename = await _save_upload_file(
        file,
        subfolder="paths/thumbnails",
        old_filename=path.thumbnail,
        allowed_types=_ALLOWED_IMAGE_TYPES,
        max_mb=5,
    )

    path.thumbnail = filename
    db.commit()
    db.refresh(path)

    # Re-fetch with full relationships for serialization
    path = (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
        .filter(LearningPath.id == path.id)
        .first()
    )

    course_ids = [c.id for c in path.courses]
    topic_counts = _bulk_topic_counts(db, course_ids)

    _invalidate_path_caches(path)

    return api_response(
        success=True,
        message="Thumbnail uploaded.",
        data=_serialize_path(path, topic_counts=topic_counts),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Course membership management
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{path_id}/courses")
async def set_path_courses(
    path_id: int,
    payload: dict,  # expects: {"course_ids": [1, 2, 3]}
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Set (replace) the ordered list of courses for a learning path.

    Accepts ``{"course_ids": [<id>, …]}`` — the order of IDs determines
    the display order.  Existing associations are replaced atomically.
    """
    path = db.query(LearningPath).filter(
        LearningPath.id == path_id,
        LearningPath.is_deleted.is_(False),
    ).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found.")

    course_ids: list[int] = payload.get("course_ids", [])

    # Validate all supplied IDs exist and fetch ORM objects in one shot
    if course_ids:
        courses = (
            db.query(Course)
            .filter(Course.id.in_(course_ids), Course.is_deleted.is_(False))
            .all()
        )
        found_ids = {c.id for c in courses}
        missing = set(course_ids) - found_ids
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Course IDs not found: {sorted(missing)}",
            )
    else:
        courses = []

    # Replace the association atomically through the ORM relationship
    path.courses = courses
    db.commit()

    # Re-fetch with fresh relationships
    path = (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
        .filter(LearningPath.id == path_id)
        .first()
    )

    all_course_ids = [c.id for c in path.courses]
    topic_counts = _bulk_topic_counts(db, all_course_ids)

    _invalidate_path_caches(path)

    return api_response(
        success=True,
        message="Path courses updated.",
        data=_serialize_path(path, topic_counts=topic_counts),
    )


@router.delete("/{path_id}/courses/{course_id}")
async def remove_course_from_path(
    path_id: int,
    course_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Remove a single course from a learning path (admin only)."""
    path = db.query(LearningPath).filter(
        LearningPath.id == path_id,
        LearningPath.is_deleted.is_(False),
    ).first()

    if not path:
        raise HTTPException(status_code=404, detail="Learning path not found.")

    if course_id not in {c.id for c in path.courses}:
        raise HTTPException(
            status_code=404, detail="Course is not part of this learning path."
        )

    # Remove via the ORM relationship — no separate join-table model needed
    path.courses = [c for c in path.courses if c.id != course_id]
    db.commit()

    # Re-fetch updated path
    path = (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
        .filter(LearningPath.id == path_id)
        .first()
    )

    all_course_ids = [c.id for c in path.courses]
    topic_counts = _bulk_topic_counts(db, all_course_ids)

    _invalidate_path_caches(path)

    return api_response(
        success=True,
        message="Course removed from path.",
        data=_serialize_path(path, topic_counts=topic_counts),
    )

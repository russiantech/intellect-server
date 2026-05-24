"""
Intellect LMS — Learning Paths API  v2
─────────────────────────────────────────────────────────────────────────────
• Anonymous detail & list caching (two-layer) with user-specific overlay
• Cache invalidation on all mutating operations
• N+1 eliminated via bulk topic-count queries and eager loading
• Absolute URLs for all media (thumbnails)
• Full serializer reused across every endpoint
"""

import os
import uuid
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.v1.courses import _absolute_url  # shared URL resolver
from app.core.config import get_app_config
from app.core.performance.cache_config import cache
from app.models import (
    Course,
    LearningPath,
    Topic,
    User,
)

# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _path_thumbnail_url(thumbnail: Optional[str]) -> Optional[str]:
    """Resolve a path thumbnail filename to its absolute URL."""
    return _absolute_url(thumbnail, "paths/thumbnails")


def _calculate_path_duration(path: LearningPath) -> int:
    """
    Return the path's duration in weeks.
    Prefers the explicit `duration_weeks` field; falls back to summing
    the duration of every enrolled course.
    """
    if path.duration_weeks and path.duration_weeks > 0:
        return path.duration_weeks
    return sum(c.duration_weeks or 0 for c in path.courses)


def _bulk_topic_counts(db: Session, course_ids: list[int]) -> dict[int, int]:
    """
    Return {course_id: topic_count} for every supplied course ID in one query.
    Eliminates N+1 when serializing paths with many courses.
    """
    if not course_ids:
        return {}
    rows = (
        db.query(Topic.course_id, func.count(Topic.id))
        .filter(Topic.course_id.in_(course_ids))
        .group_by(Topic.course_id)
        .all()
    )
    return {course_id: count for course_id, count in rows}


def _calculate_path_stats(
    path: LearningPath,
    topic_counts: dict[int, int],
) -> dict:
    """
    Return aggregated lesson / topic / duration stats for a path using
    data that has already been eagerly loaded and bulk-fetched.
    """
    total_lessons = 0
    total_topics = 0
    total_duration = 0

    for course in path.courses:
        total_lessons += len(course.lessons) if course.lessons else 0
        total_topics += topic_counts.get(course.id, 0)
        total_duration += course.duration_weeks or 0

    return {
        "lessons_count": total_lessons,
        "topics_count": total_topics,
        "duration_weeks": path.duration_weeks or total_duration,
    }


def _invalidate_path_caches(path: LearningPath) -> None:
    """Purge every cached variant that could contain stale path data."""
    cache.invalidate("paths:list")
    cache.invalidate(f"paths:detail:{path.id}")
    if path.slug:
        cache.invalidate(f"paths:detail:{path.slug}")


# ─────────────────────────────────────────────────────────────────────────────
# Upload helper (DRY — mirrors the pattern in courses.py)
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_IMAGE_TYPES: set[str] = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}
_ALLOWED_IMAGE_EXTS: set[str] = {"jpg", "jpeg", "png", "gif", "webp", "svg"}


async def _save_upload_file(
    file: UploadFile,
    *,
    subfolder: str,
    old_filename: Optional[str] = None,
    allowed_types: Optional[set[str]] = None,
    max_mb: int = 5,
) -> str:
    """
    Persist an uploaded file under `<content_delivery_root>/<subfolder>/`.
    Returns the generated filename (not the full path).
    Deletes the previous file when `old_filename` is supplied and is a local
    reference (not an external URL).
    """
    if allowed_types and file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File type not allowed: {file.content_type}. "
                f"Allowed: {', '.join(sorted(allowed_types))}"
            ),
        )

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        *subfolder.split("/"),
    )
    os.makedirs(upload_dir, exist_ok=True)

    raw_ext = (file.filename or "").rsplit(".", 1)
    ext = raw_ext[-1].lower() if len(raw_ext) == 2 else ""
    if ext not in _ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="Invalid file extension.")

    content = await file.read()
    max_bytes = max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400, detail=f"File too large (max {max_mb} MB)."
        )

    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, "wb") as fh:
        fh.write(content)

    # Remove old file — non-fatal; never delete external URLs
    if old_filename and not old_filename.startswith("http"):
        old_path = os.path.join(upload_dir, old_filename)
        try:
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError:
            pass

    return filename


# ─────────────────────────────────────────────────────────────────────────────
# Master serializer  (single source of truth — reused by every endpoint)
# ─────────────────────────────────────────────────────────────────────────────


def _serialize_path(
    path: LearningPath,
    *,
    user: Optional[User] = None,
    topic_counts: Optional[dict[int, int]] = None,
    include_stats: bool = True,
) -> dict:
    """
    Serialize a LearningPath to a response dict with:
      • Absolute URLs for path and course thumbnails
      • All payment / subscription / installment fields
      • Aggregated lesson / topic / duration stats
      • User-specific enrollment overlay (when `user` is supplied)
      • Optional topic-count injection (pass pre-fetched dict to avoid N+1)

    Parameters
    ----------
    path         : the ORM instance (courses must be eagerly loaded)
    user         : authenticated user for personalised fields; None for anon
    topic_counts : {course_id: topic_count} from `_bulk_topic_counts()`
    include_stats: set False to skip the aggregation pass (e.g. list endpoints
                   that don't need per-path stats for performance)
    """
    topic_counts = topic_counts or {}

    # ── Core fields ──────────────────────────────────────────────────────────
    d: dict = {
        "id": path.id,
        "title": path.title,
        "slug": path.slug,
        "description": path.description,
        "thumbnail": _path_thumbnail_url(path.thumbnail),
        "status": (
            path.status.value
            if hasattr(path.status, "value")
            else str(path.status)
        ),
        "is_active": path.is_active,
        "is_deleted": path.is_deleted,
        "duration_weeks": _calculate_path_duration(path),
        "what_you_achieve": path.what_you_achieve,
        "issues_certificate": path.issues_certificate,
        "access_period_days": path.access_period_days,
        "created_at": path.created_at,
        "updated_at": path.updated_at,
        "courses_count": len(path.courses) if path.courses else 0,
    }

    # ── Payment fields ────────────────────────────────────────────────────────
    d["payment_type"] = (
        path.payment_type.value
        if hasattr(path.payment_type, "value")
        else str(path.payment_type)
    )
    d["fee"] = path.fee

    # Optional payment variants — only emitted when present on the model so
    # the serializer stays forward-compatible as new fields are added.
    for attr in (
        "instructor_led_fee",
        "instructor_led_only",
        "subscription_fee",
        "subscription_interval",
        "subscription_enabled",
        "pay_as_you_go_fee",
        "pay_as_you_go_enabled",
        "installment_enabled",
        "installment_count",
        "installment_fee",
    ):
        if hasattr(path, attr):
            d[attr] = getattr(path, attr)

    # ── Aggregated stats ──────────────────────────────────────────────────────
    if include_stats:
        stats = _calculate_path_stats(path, topic_counts)
        d["lessons_count"] = stats["lessons_count"]
        d["topics_count"] = stats["topics_count"]
        # duration_weeks already set above; keep the aggregated fallback value
        # only when the path-level field is absent
        if not path.duration_weeks:
            d["duration_weeks"] = stats["duration_weeks"]

    # ── Nested courses ────────────────────────────────────────────────────────
    if path.courses:
        d["courses"] = [
            {
                "id": c.id,
                "title": c.title,
                "slug": c.slug,
                "thumbnail": _absolute_url(c.thumbnail, "courses/thumbnails"),
                "level": (
                    getattr(c.level, "value", str(c.level)) if c.level else None
                ),
                "fee": c.fee,
                "duration_weeks": c.duration_weeks,
                "lessons_count": len(c.lessons) if c.lessons else 0,
                "topics_count": topic_counts.get(c.id, 0),
            }
            for c in path.courses
        ]
        d["course_ids"] = [c.id for c in path.courses]
    else:
        d["courses"] = []
        d["course_ids"] = []

    # ── User-specific overlay ─────────────────────────────────────────────────
    if user:
        enrollment = next(
            (pe for pe in (path.path_enrollments or []) if pe.user_id == user.id),
            None,
        )
        d["is_enrolled"] = enrollment is not None
        d["progress_pct"] = enrollment.progress_pct if enrollment else 0
        d["enrollment_id"] = enrollment.id if enrollment else None
    else:
        d["is_enrolled"] = False
        d["progress_pct"] = 0
        d["enrollment_id"] = None

    return d


# ─────────────────────────────────────────────────────────────────────────────
# Query builder  (shared between list & search)
# ─────────────────────────────────────────────────────────────────────────────


def _base_path_query(db: Session):
    """
    Return a query for active, non-deleted paths with courses and their
    lessons eagerly loaded to prevent N+1 across all list endpoints.
    """
    return (
        db.query(LearningPath)
        .options(
            joinedload(LearningPath.courses).joinedload(Course.lessons),
            joinedload(LearningPath.path_enrollments),
        )
        .filter(
            LearningPath.is_active.is_(True),
            LearningPath.is_deleted.is_(False),
        )
    )


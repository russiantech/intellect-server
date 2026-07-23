# app/api/v1/courses.py

import copy
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from slugify import slugify
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session, joinedload, subqueryload

from app.api.deps.auth import (
    get_current_user,
    get_current_verified_user,
    optional_user,
    require_admin,
    require_creator_or_admin,
)

from app.core.performance.cache_config import cache
from app.services.storage import create_signed_url

from app.services.storage import upload_file, delete_file
from app.core.config import get_app_config
from app.db.database import get_db
from app.models import (
    Category,
    Course,
    Enrollment,
    Feedback,
    Lesson,
    LessonAssessment,
    Quiz,
    Tag,
    Topic,
    TopicContent,
    TutorAssignment,
    User,
)
from app.schemas import (
    ContentReorderItem,
    CourseApproval,
    CourseCreate,
    CourseUpdate,
    FeedbackCreate,
    LessonCreate,
    LessonUpdate,
    SuccessResponse,
    TopicCreate,
    TopicTextContentCreate,
    TopicUpdate,
)
from app.schemas import ContentType as CT
from app.schemas import CourseStatus
from app.services.email_service import send_course_approved_email, send_course_rejected_email
from app.utils.helpers import _to_cacheable, _invalidate_course_caches
from app.utils.courses import (
    ALLOWED_MEDIA,
    _absolute_url,
    _course_dict,
    _make_content_token_url,
    _make_slug,
    _mini_user,
    _verify_content_token,
)


router = APIRouter(prefix="/courses", tags=["Courses"])
logger = logging.getLogger(__name__)



# ── Secure content serving ────────────────────────────────────────────────────

# @router.get("/serve/{token}")
# async def serve_content(
#     token: str,
#     db: Session = Depends(get_db),
# ):
#     """
#     Token-gated file delivery.

#     The client never sees the real filesystem path. The HMAC token is verified
#     (signature + expiry + embedded user_id) before any file is read from disk.

#     For production at scale, replace FileResponse with a redirect to a private
#     S3/GCS pre-signed URL for zero-latency streaming without touching the app server.
#     """
#     content_id, user_id = _verify_content_token(token)

#     tc = db.query(TopicContent).filter(TopicContent.id == content_id).first()
#     if not tc:
#         raise HTTPException(status_code=404, detail="Content not found")

#     topic = db.query(Topic).filter(Topic.id == tc.topic_id).first()
#     if not topic:
#         raise HTTPException(status_code=404, detail="Topic not found")

#     if not topic.is_free_preview:
#         enrolled = db.query(Enrollment).filter(
#             Enrollment.user_id == user_id,
#             Enrollment.course_id == topic.course_id,
#         ).first()
#         user = db.query(User).filter(User.id == user_id).first()
#         is_admin = user and user.is_admin()
#         is_creator = topic.course and topic.course.creator_id == user_id
#         if not enrolled and not is_admin and not is_creator:
#             raise HTTPException(status_code=403, detail="Access denied")

#     if tc.body is not None:
#         return {"content_type": "text", "title": tc.title, "body": tc.body}

#     if not tc.file_path:
#         raise HTTPException(status_code=404, detail="No file attached to this content")

#     cfg = get_app_config()
#     file_path = os.path.join(
#         cfg.hosting_config.content_delivery.filesystem_base_path,
#         "courses", "content", tc.file_path,
#     )
#     if not os.path.exists(file_path):
#         raise HTTPException(status_code=404, detail="File not found on server")

#     return FileResponse(
#         path=file_path,
#         media_type=tc.mime_type or "application/octet-stream",
#         filename=tc.title or tc.file_path,
#         headers={
#             "Cache-Control": "no-store, no-cache, must-revalidate, private",
#             "Pragma": "no-cache",
#             "X-Frame-Options": "SAMEORIGIN",
#             "Content-Security-Policy": "default-src 'self'",
#             "X-Content-Type-Options": "nosniff",
#         },
#     )

# v2
@router.get("/serve/{token}")
async def serve_content(token: str, db: Session = Depends(get_db)):
    content_id, user_id = _verify_content_token(token)

    tc = db.query(TopicContent).filter(TopicContent.id == content_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")

    topic = db.query(Topic).filter(Topic.id == tc.topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not topic.is_free_preview:
        enrolled = db.query(Enrollment).filter(
            Enrollment.user_id == user_id, Enrollment.course_id == topic.course_id,
        ).first()
        user = db.query(User).filter(User.id == user_id).first()
        is_admin = user and user.is_admin()
        is_creator = topic.course and topic.course.creator_id == user_id
        if not enrolled and not is_admin and not is_creator:
            raise HTTPException(status_code=403, detail="Access denied")

    if tc.body is not None:
        return {"content_type": "text", "title": tc.title, "body": tc.body}

    if not tc.file_path:
        raise HTTPException(status_code=404, detail="No file attached to this content")

    # New cloud-stored content: file_path is the provider URL — sign + redirect.
    # The HMAC token above is the entitlement check; this signed URL is the
    # short-lived (5 min) transport layer so it can't be shared/cached.
    if tc.file_path.startswith("http"):
        signed = create_signed_url(tc.file_path, folder="courses/content", expires_in=300)
        return RedirectResponse(url=signed, status_code=302)

    # Legacy local-disk rows only (pre-migration) — unchanged behavior
    cfg = get_app_config()
    file_path = os.path.join(cfg.storage_config.filesystem_base_path, "courses", "content", tc.file_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
    return FileResponse(
        path=file_path,
        media_type=tc.mime_type or "application/octet-stream",
        filename=tc.title or tc.file_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": "default-src 'self'",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ── Topic content ─────────────────────────────────────────────────────────────

@router.get("/{course_id}/topics/{topic_id}/content")
async def get_topic_content(
    course_id: int,
    topic_id: int,
    user: Optional[User] = Depends(optional_user),
    db: Session = Depends(get_db),
):
    """
    Return the content items for a topic.
    Free previews are accessible anonymously; paid content requires enrollment.
    Anonymous users receive direct (unsigned) URLs for preview files.
    Authenticated users receive short-lived HMAC-signed token URLs.
    """
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not topic.is_free_preview:
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        enrolled = db.query(Enrollment).filter(
            Enrollment.user_id == user.id,
            Enrollment.course_id == course_id,
        ).first()
        if not enrolled and not user.is_admin():
            raise HTTPException(status_code=403, detail="Enrollment required")

    def _item(c: TopicContent) -> dict:
        is_text = c.content_type == CT.text or (
            getattr(c, "body", None) is not None and not c.file_path
        )
        if user is None:
            url = None if is_text else _absolute_url(c.file_path, "courses/content")
        else:
            url = None if is_text else _make_content_token_url(c, user.id)
        return {
            "id": c.id,
            "title": c.title,
            "content_type": c.content_type,
            "url": url,
            "body": getattr(c, "body", None) if is_text else None,
            "duration_seconds": getattr(c, "duration_seconds", None),
            "order_index": c.order_index,
        }

    return {
        "id": topic.id,
        "title": topic.title,
        "description": topic.description,
        "contents": [_item(c) for c in sorted(topic.contents, key=lambda x: x.order_index)],
    }


# ── Text content authoring ────────────────────────────────────────────────────

@router.post("/{course_id}/topics/{topic_id}/content/text", status_code=201)
async def add_text_content(
    course_id: int,
    topic_id: int,
    payload: TopicTextContentCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Store text/article content directly in the DB — no file upload required."""
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    course = topic.course
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    if not payload.title.strip() or not payload.body.strip():
        raise HTTPException(status_code=422, detail="Title and body are required")

    tc = TopicContent(
        title=payload.title.strip(),
        content_type=CT.text,
        body=payload.body,
        topic_id=topic_id,
        order_index=len(topic.contents),
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)

    # Course structure changed — invalidate detail cache
    _invalidate_course_caches(course_id, slug=course.slug)

    return {
        "id": tc.id,
        "title": tc.title,
        "content_type": "text",
        "body": tc.body,
        "order_index": tc.order_index,
        "url": None,
    }


@router.patch("/{course_id}/topics/{topic_id}/content/{content_id}/text")
async def update_text_content(
    course_id: int,
    topic_id: int,
    content_id: int,
    payload: TopicTextContentCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    tc = db.query(TopicContent).filter(
        TopicContent.id == content_id,
        TopicContent.topic_id == topic_id,
    ).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")

    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    course = db.query(Course).filter(Course.id == course_id).first()
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if payload.title is not None:
        tc.title = payload.title.strip()
    if payload.body is not None:
        tc.body = payload.body

    db.commit()
    db.refresh(tc)

    # Content body changed — detail cache is stale
    _invalidate_course_caches(course_id, slug=course.slug)

    return {
        "id": tc.id,
        "title": tc.title,
        "content_type": "text",
        "body": getattr(tc, "body", None),
        "url": None,
        "order_index": tc.order_index,
    }


# ── Reorder operations ────────────────────────────────────────────────────────

@router.put("/{course_id}/lessons/reorder")
async def reorder_lessons(
    course_id: int,
    items: list[ContentReorderItem],
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Bulk-update lesson order_index after drag-and-drop."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    for lesson in db.query(Lesson).filter(
        Lesson.course_id == course_id, Lesson.id.in_(id_map.keys()),
    ).all():
        lesson.order_index = id_map[lesson.id]

    db.commit()

    # Lesson order is part of the cached course structure
    _invalidate_course_caches(course_id, slug=course.slug)
    return SuccessResponse(message="Lessons reordered")


@router.put("/{course_id}/lessons/{lesson_id}/topics/reorder")
async def reorder_topics(
    course_id: int,
    lesson_id: int,
    items: list[ContentReorderItem],
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Bulk-update topic order_index within a lesson after drag-and-drop."""
    lesson = db.query(Lesson).filter(
        Lesson.id == lesson_id, Lesson.course_id == course_id,
    ).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    for topic in db.query(Topic).filter(
        Topic.lesson_id == lesson_id, Topic.id.in_(id_map.keys()),
    ).all():
        topic.order_index = id_map[topic.id]

    db.commit()

    _invalidate_course_caches(course_id, slug=lesson.course.slug)
    return SuccessResponse(message="Topics reordered")


@router.put("/{course_id}/topics/{topic_id}/content/reorder")
async def reorder_topic_content(
    course_id: int,
    topic_id: int,
    items: list[ContentReorderItem],
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    course = db.query(Course).filter(Course.id == course_id).first()
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    for tc in topic.contents:
        if tc.id in id_map:
            tc.order_index = id_map[tc.id]

    db.commit()

    _invalidate_course_caches(course_id, slug=course.slug)
    return SuccessResponse(message="Content reordered")


# ── Assessments ───────────────────────────────────────────────────────────────

@router.get("/{course_id}/lessons/{lesson_id}/assessments")
async def get_lesson_assessments(
    course_id: int,
    lesson_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List assessments for a lesson with this user's latest submission status."""
    from app.models import Assessment, AssessmentSubmission

    assessments = db.query(Assessment).filter(
        Assessment.course_id == course_id,
        Assessment.lesson_id == lesson_id,
    ).all()

    result = []
    for a in assessments:
        sub = (
            db.query(AssessmentSubmission)
            .filter(
                AssessmentSubmission.assessment_id == a.id,
                AssessmentSubmission.user_id == user.id,
            )
            .order_by(AssessmentSubmission.attempt_number.desc())
            .first()
        )
        result.append({
            "id": a.id,
            "title": a.title,
            "assessment_type": a.assessment_type,
            "total_marks": a.total_marks,
            "pass_mark": a.pass_mark,
            "time_limit_minutes": a.time_limit_minutes,
            "due_date": a.due_date,
            "attempts_allowed": a.attempts_allowed,
            "questions_count": len(a.questions),
            "my_submission": {
                "id": sub.id,
                "status": sub.status,
                "score": sub.score,
                "percentage": sub.percentage,
                "passed": sub.passed,
                "attempt_number": sub.attempt_number,
                "submitted_at": sub.submitted_at,
            } if sub else None,
        })

    return result


# ── PUBLIC BROWSE ─────────────────────────────────────────────────────────────

# @router.get("/")
# async def list_courses(
#     page: int = Query(1, ge=1),
#     per_page: int = Query(20, ge=1, le=100),
#     search: Optional[str] = None,
#     category: Optional[str] = None,
#     level: Optional[str] = None,
#     payment_type: Optional[str] = None,
#     featured: Optional[bool] = None,
#     status: Optional[str] = "published",
#     creator_id: Optional[int] = None,
#     sort: Optional[str] = "newest",
#     db: Session = Depends(get_db),
#     current_user: Optional[User] = Depends(optional_user),
# ):
#     """
#     Public course listing with filtering, pagination, and sorting.

#     Cache strategy:
#       - Anonymous requests are cached for 5 minutes, keyed on all query params.
#         All filter combinations are independently cached — a search for "python"
#         is a different key from no search.
#       - Authenticated requests are never cached because _course_dict includes
#         per-user is_enrolled and progress_pct, which differ between users.
#       - Invalidated by: course publish, update, approve, delete, create.
#     """
#     # ── Cache check (anonymous only) ──────────────────────────────
#     cache_key: Optional[str] = None
#     if current_user is None:
#         cache_key = cache.make_key(
#             "courses:list",
#             page, per_page, search, category, level,
#             payment_type, featured, status, creator_id, sort,
#         )
#         hit = cache.get(cache_key)
#         if hit is not None:
#             return hit

#     # ── Build filtered query ──────────────────────────────────────
#     def _apply_filters(q):
#         if status:
#             q = q.filter(Course.status == status)
#         if search:
#             q = q.filter(or_(
#                 Course.title.ilike(f"%{search}%"),
#                 Course.description.ilike(f"%{search}%"),
#             ))
#         if category:
#             raw = [s.strip() for s in category.split(",") if s.strip()]
#             if raw:
#                 try:
#                     cat_ids = [int(c) for c in raw]
#                     cat_sq = (
#                         db.query(Course.id)
#                         .join(Course.categories)
#                         .filter(Category.id.in_(cat_ids))
#                         .subquery()
#                     )
#                     q = q.filter(Course.id.in_(cat_sq))
#                 except ValueError:
#                     cat_sq = (
#                         db.query(Course.id)
#                         .join(Course.categories)
#                         .filter(Category.slug.in_(raw))
#                         .subquery()
#                     )
#                     q = q.filter(Course.id.in_(cat_sq))
#         if level:
#             raw_levels = [s.strip() for s in level.split(",") if s.strip()]
#             if raw_levels:
#                 q = q.filter(Course.level.in_(raw_levels))
#         if payment_type:
#             raw_types = [s.strip() for s in payment_type.split(",") if s.strip()]
#             if raw_types:
#                 q = q.filter(Course.payment_type.in_(raw_types))
#         if featured is not None:
#             q = q.filter(Course.featured == featured)
#         if creator_id:
#             q = q.filter(Course.creator_id == creator_id)
#         return q

#     # ── Count ─────────────────────────────────────────────────────
#     count_q = _apply_filters(db.query(Course.id))
#     if sort == "rating":
#         count_q = count_q.outerjoin(Course.feedbacks).group_by(Course.id)
#     total = count_q.count()

#     if total == 0:
#         empty = {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}
#         if cache_key:
#             cache.set(cache_key, empty, ttl=300)
#         return empty

#     # ── Paginate ──────────────────────────────────────────────────
#     if sort == "popular":
#         page_q = _apply_filters(
#             db.query(Course.id, Course.views)
#         ).order_by(Course.views.desc(), Course.id)
#     elif sort == "rating":
#         avg_rating = func.coalesce(func.avg(Feedback.rating), 0).label("avg_rating")
#         page_q = (
#             _apply_filters(db.query(Course.id, avg_rating))
#             .outerjoin(Course.feedbacks)
#             .group_by(Course.id)
#             .order_by(avg_rating.desc(), Course.id)
#         )
#     else:
#         page_q = _apply_filters(
#             db.query(Course.id, Course.created_at)
#         ).order_by(Course.created_at.desc(), Course.id)

#     rows = page_q.offset((page - 1) * per_page).limit(per_page).all()
#     matching_ids = [r[0] for r in rows]

#     if not matching_ids:
#         partial = {
#             "items": [], "total": total, "page": page,
#             "per_page": per_page,
#             "pages": (total + per_page - 1) // per_page,
#         }
#         if cache_key:
#             cache.set(cache_key, partial, ttl=300)
#         return partial

#     # ── Fetch full objects (all relations in one query) ───────────
#     order_map = case({id_: idx for idx, id_ in enumerate(matching_ids)}, value=Course.id)
#     courses = (
#         db.query(Course)
#         .options(
#             subqueryload(Course.categories),
#             subqueryload(Course.tags),
#             joinedload(Course.creator),
#             subqueryload(Course.enrollments),
#             subqueryload(Course.feedbacks),
#         )
#         .filter(Course.id.in_(matching_ids))
#         .order_by(order_map)
#         .all()
#     )

#     response = {
#         "items": [_course_dict(c, current_user) for c in courses],
#         "total": total,
#         "page": page,
#         "per_page": per_page,
#         "pages": (total + per_page - 1) // per_page,
#     }

#     # ── Store anonymous response in cache ─────────────────────────
#     if cache_key:
#         cache.set(cache_key, _to_cacheable(response), ttl=300)

#     return response

# v2
@router.get("/")
async def list_courses(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category: Optional[str] = None,
    level: Optional[str] = None,
    payment_type: Optional[str] = None,
    featured: Optional[bool] = None,
    status: Optional[str] = "published",
    creator_id: Optional[int] = None,
    sort: Optional[str] = "newest",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    # ── Cache check (anonymous only) ──────────────────────────────
    cache_key: Optional[str] = None
    if current_user is None:
        cache_key = cache.make_key(
            "courses:list",
            page, per_page, search, category, level,
            payment_type, featured, status, creator_id, sort,
        )
        hit = cache.get(cache_key)
        if hit is not None:
            return hit

    # ── Build filtered query ──────────────────────────────────────
    def _apply_filters(q):
        if status:
            q = q.filter(Course.status == status)
        if search:
            q = q.filter(or_(
                Course.title.ilike(f"%{search}%"),
                Course.description.ilike(f"%{search}%"),
            ))
        if category:
            raw = [s.strip() for s in category.split(",") if s.strip()]
            if raw:
                try:
                    cat_ids = [int(c) for c in raw]
                    
                    # cat_sq = (
                    #     db.query(Course.id)
                    #     .join(Course.categories)
                    #     .filter(Category.id.in_(cat_ids))
                    #     .subquery()
                    # )
                    
                    # SAWarning: Coercing Subquery object into a select() for use in IN(); please pass a select() construct explicitly q = q.filter(Course.id.in_(cat_sq))
                    
                    # v2
                    # Option 2: Use scalar_subquery() (cleaner, 1.4+ compatible)
                    cat_sq = (
                        db.query(Course.id)
                        .join(Course.categories)
                        .filter(Category.id.in_(cat_ids))
                        .scalar_subquery()
                    )
                    q = q.filter(Course.id.in_(cat_sq))

                    q = q.filter(Course.id.in_(cat_sq))
                except ValueError:
                    cat_sq = (
                        db.query(Course.id)
                        .join(Course.categories)
                        .filter(Category.id.in_(cat_ids))
                        .scalar_subquery()
                    )
                    q = q.filter(Course.id.in_(cat_sq))
        if level:
            raw_levels = [s.strip() for s in level.split(",") if s.strip()]
            if raw_levels:
                q = q.filter(Course.level.in_(raw_levels))
        if payment_type:
            raw_types = [s.strip() for s in payment_type.split(",") if s.strip()]
            if raw_types:
                q = q.filter(Course.payment_type.in_(raw_types))
        if featured is not None:
            q = q.filter(Course.featured == featured)
        if creator_id:
            q = q.filter(Course.creator_id == creator_id)
        return q

    # ── Count ─────────────────────────────────────────────────────
    count_q = _apply_filters(db.query(Course.id))
    if sort == "rating":
        count_q = count_q.outerjoin(Course.feedbacks).group_by(Course.id)
    total = count_q.count()

    if total == 0:
        empty = {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}
        if cache_key:
            cache.set(cache_key, empty, ttl=300)
        return empty

    # ── Paginate ──────────────────────────────────────────────────
    if sort == "popular":
        page_q = _apply_filters(
            db.query(Course.id, Course.views)
        ).order_by(Course.views.desc(), Course.id)
    elif sort == "rating":
        avg_rating = func.coalesce(func.avg(Feedback.rating), 0).label("avg_rating")
        page_q = (
            _apply_filters(db.query(Course.id, avg_rating))
            .outerjoin(Course.feedbacks)
            .group_by(Course.id)
            .order_by(avg_rating.desc(), Course.id)
        )
    else:
        page_q = _apply_filters(
            db.query(Course.id, Course.created_at)
        ).order_by(Course.created_at.desc(), Course.id)

    rows = page_q.offset((page - 1) * per_page).limit(per_page).all()
    matching_ids = [r[0] for r in rows]

    if not matching_ids:
        partial = {
            "items": [], "total": total, "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page,
        }
        if cache_key:
            cache.set(cache_key, partial, ttl=300)
        return partial

    # ── Fetch full objects with all relations in one query ─────────
    order_map = case({id_: idx for idx, id_ in enumerate(matching_ids)}, value=Course.id)
    courses = (
        db.query(Course)
        .options(
            subqueryload(Course.categories),
            subqueryload(Course.tags),
            joinedload(Course.creator),
            subqueryload(Course.lessons).subqueryload(Lesson.topics),  # Eager load lessons+topics
            subqueryload(Course.enrollments),
            subqueryload(Course.feedbacks),
        )
        .filter(Course.id.in_(matching_ids))
        .order_by(order_map)
        .all()
    )

    # ── BULK PRE-COMPUTE STATS (eliminates N+1 in _course_dict) ───
    course_ids = matching_ids
    
    # Pre-compute user's enrollments for all courses in one dict
    enrollment_map = {}
    if current_user:
        enrollment_map = {
            e.course_id: e 
            for e in db.query(Enrollment).filter(
                Enrollment.user_id == current_user.id,
                Enrollment.course_id.in_(course_ids),
            ).all()
        }
    
    # Pre-compute feedback stats (avg_rating, count) for all courses
    feedback_stats = dict(
        db.query(
            Feedback.course_id,
            func.avg(Feedback.rating).label("avg"),
            func.count(Feedback.id).label("cnt")
        )
        .filter(Feedback.course_id.in_(course_ids))
        .group_by(Feedback.course_id)
        .all()
    )
    feedback_stats = {
        cid: (round(avg, 1) if avg else None, cnt)
        for cid, avg, cnt in feedback_stats
    }
    
    # Pre-compute topic counts for all courses
    topic_counts = dict(
        db.query(Topic.course_id, func.count(Topic.id))
        .join(Lesson, Topic.lesson_id == Lesson.id)
        .filter(Lesson.course_id.in_(course_ids))
        .group_by(Topic.course_id)
        .all()
    )

    # ── Build response ────────────────────────────────────────────
    response = {
        "items": [
            _course_dict(
                c, 
                current_user,
                _enrollment_map=enrollment_map,
                _feedback_stats=feedback_stats,
                _topic_counts=topic_counts,
            ) 
            for c in courses
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }

    # ── Store anonymous response in cache ─────────────────────────
    if cache_key:
        cache.set(cache_key, _to_cacheable(response), ttl=300)

    return response


@router.get("/meta/categories")
async def list_categories(db: Session = Depends(get_db)):
    """
    Active categories used to populate the browse filter.

    Cached for 30 minutes — categories change only on admin write.
    Invalidated by: admin category create/update/delete (in categories.py).
    """
    hit = cache.get("meta:categories")
    if hit is not None:
        return hit

    cats = db.query(Category).filter(Category.is_active == True).all()
    result = [
        {"id": c.id, "title": c.title, "slug": c.slug, "image": c.image, "icon": c.icon}
        for c in cats
    ]
    cache.set("meta:categories", result, ttl=1800)
    return result


@router.get("/meta/tags")
async def list_tags(db: Session = Depends(get_db)):
    """
    All active tags.

    Cached for 30 minutes — tags change only on admin write.
    Invalidated by: admin tag create/delete (in admin.py or categories.py).
    """
    hit = cache.get("meta:tags")
    if hit is not None:
        return hit

    tags = db.query(Tag).filter(Tag.is_active == True).all()
    result = [{"id": t.id, "name": t.name} for t in tags]
    cache.set("meta:tags", result, ttl=1800)
    return result


@router.get("/{course_id_or_slug}")
async def get_course(
    course_id_or_slug: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    """
    Full course detail including lessons, topics, feedbacks, and tutors.

    Cache strategy — two-layer approach:
      Layer 1 (cached, TTL 10 min): the anonymous course structure.
        Contains all structural data: lessons, topics, contents_count, quiz/assessment
        flags, feedbacks, tutors, creator. User-specific fields default to False/0.
        Keyed by course_id_or_slug so both /courses/42 and /courses/python-101
        hit the same cached struct if the slug matches the ID lookup.

      Layer 2 (always live): user-specific overlay.
        When a user is authenticated, we fetch their enrollment (1 query) and
        derive their completed topic IDs from the already-loaded topic_progress
        relation. These are overlaid onto a deep copy of the cached struct —
        no second full course load needed.

    View count:
      On cache hit: a lightweight single-column UPDATE by ID (no full load).
      On cache miss: incremented directly on the loaded ORM object.

    Invalidated by: course update, approve, thumbnail upload, lesson/topic reorder,
                    lesson/topic CRUD, text content add/edit, feedback submit.
    """
    struct_key = f"courses:detail:{course_id_or_slug}"
    course_struct = cache.get(struct_key)

    if course_struct is not None:
        # ── Cache hit ─────────────────────────────────────────────
        # Increment view count with a lightweight targeted UPDATE.
        try:
            db.query(Course).filter(
                Course.id == course_struct["id"]
            ).update({"views": Course.views + 1}, synchronize_session=False)
            db.commit()
        except Exception as exc:
            logger.warning("View count increment failed on cache hit: %s", exc)

        if current_user is None:
            return course_struct

        # Overlay user-specific data without reloading the full course
        result = copy.deepcopy(course_struct)

        enrollment = db.query(Enrollment).filter(
            Enrollment.user_id == current_user.id,
            Enrollment.course_id == course_struct["id"],
        ).first()
        result["is_enrolled"] = enrollment is not None
        result["progress_pct"] = enrollment.progress_pct if enrollment else 0.0

        # completed_topic_ids from the user's already-loaded topic_progress relation
        if hasattr(current_user, "topic_progress") and current_user.topic_progress:
            completed_ids = {t.id for t in current_user.topic_progress}
            for lesson in result["lessons"]:
                for topic in lesson["topics"]:
                    topic["is_completed"] = topic["id"] in completed_ids

        return result

    # ── Cache miss: full load ─────────────────────────────────────
    base_q = db.query(Course).options(
        joinedload(Course.categories),
        joinedload(Course.tags),
        joinedload(Course.creator),
        joinedload(Course.enrollments),
        joinedload(Course.feedbacks).joinedload(Feedback.author),
        joinedload(Course.lessons)
            .joinedload(Lesson.topics)
            .joinedload(Topic.contents),
        joinedload(Course.tutor_assignments)
            .joinedload(TutorAssignment.tutor),
    )

    try:
        course = base_q.filter(Course.id == int(course_id_or_slug)).first()
    except ValueError:
        course = base_q.filter(Course.slug == course_id_or_slug).first()

    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    course.views += 1
    db.commit()

    # ── Bulk quiz / assessment presence (avoids N+1 per topic) ────
    all_topic_ids = [t.id for l in course.lessons for t in l.topics]
    all_lesson_ids = [l.id for l in course.lessons]

    topic_ids_with_quiz: set[int] = set()
    if all_topic_ids:
        topic_ids_with_quiz = {
            row.topic_id
            for row in db.query(Quiz.topic_id)
            .filter(Quiz.topic_id.in_(all_topic_ids), Quiz.is_active == True)
            .all()
        }

    lesson_ids_with_assessment: set[int] = set()
    if all_lesson_ids:
        lesson_ids_with_assessment = {
            row.lesson_id
            for row in db.query(LessonAssessment.lesson_id)
            .filter(
                LessonAssessment.lesson_id.in_(all_lesson_ids),
                LessonAssessment.is_active == True,
            )
            .all()
        }

    # ── Build anonymous struct (user=None → is_enrolled=False, progress=0) ──
    d = _course_dict(course, user=None)

    d["lessons"] = [
        {
            "id": lesson.id,
            "title": lesson.title,
            "description": lesson.description,
            "order_index": lesson.order_index,
            "slug": lesson.slug,
            "has_assessment": lesson.id in lesson_ids_with_assessment,
            "topics": [
                {
                    "id": topic.id,
                    "title": topic.title,
                    "order_index": topic.order_index,
                    "slug": topic.slug,
                    "duration_minutes": topic.duration_minutes,
                    "is_free_preview": topic.is_free_preview,
                    "is_completed": False,          # always False in cached struct
                    "has_quiz": topic.id in topic_ids_with_quiz,
                    "contents_count": len(topic.contents),
                }
                for topic in sorted(lesson.topics, key=lambda t: t.order_index)
            ],
        }
        for lesson in sorted(course.lessons, key=lambda l: l.order_index)
    ]

    d["feedbacks"] = [
        {
            "id": fb.id,
            "rating": fb.rating,
            "comment": fb.comment,
            "author": _mini_user(fb.author) if fb.author else None,
            "created_at": fb.created_at,
        }
        for fb in course.feedbacks
    ]

    d["tutors"] = [
        _mini_user(a.tutor)
        for a in course.tutor_assignments
        if a.tutor
    ]

    # ── Cache the anonymous struct ────────────────────────────────
    # _to_cacheable() converts datetimes/enums to strings so json.dumps
    # in RedisService doesn't raise on serialisation.
    cache.set(struct_key, _to_cacheable(d), ttl=600)

    if current_user is None:
        return d

    # ── Overlay user-specific data (authenticated path) ───────────
    result = copy.deepcopy(d)

    enrollment = next(
        (e for e in course.enrollments if e.user_id == current_user.id), None
    )
    result["is_enrolled"] = enrollment is not None
    result["progress_pct"] = enrollment.progress_pct if enrollment else 0.0

    completed_topic_ids: set[int] = set()
    if hasattr(current_user, "topic_progress") and current_user.topic_progress:
        course_topic_ids = {t.id for l in course.lessons for t in l.topics}
        completed_topic_ids = {
            t.id for t in current_user.topic_progress if t.id in course_topic_ids
        }

    for lesson in result["lessons"]:
        for topic in lesson["topics"]:
            topic["is_completed"] = topic["id"] in completed_topic_ids

    return result


# ── CREATOR / ADMIN COURSE MANAGEMENT ────────────────────────────────────────

@router.post("/", status_code=201)
async def create_course(
    payload: CourseCreate,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    slug = _make_slug(payload.title, db)
    course = Course(
        title=payload.title, slug=slug,
        description=payload.description,
        short_description=payload.short_description,
        fee=payload.fee, payment_type=payload.payment_type,
        subscription_interval=payload.subscription_interval,
        subscription_installments=payload.subscription_installments,
        lang=payload.lang, duration_weeks=payload.duration_weeks,
        level=payload.level, requirements=payload.requirements,
        what_you_learn=payload.what_you_learn,
        creator_id=user.id,
        status=CourseStatus.draft,
        throttle_enabled=payload.throttle_enabled,
        weekly_topic_limit=payload.weekly_topic_limit,
        monthly_topic_limit=payload.monthly_topic_limit,
    )
    if payload.category_ids:
        course.categories = db.query(Category).filter(
            Category.id.in_(payload.category_ids)
        ).all()
    if payload.tag_ids:
        course.tags = db.query(Tag).filter(Tag.id.in_(payload.tag_ids)).all()

    db.add(course)
    db.commit()
    db.refresh(course)

    # New course may appear in listing once published — bust listing cache now
    # so any pre-existing cached empty results don't persist.
    cache.invalidate("courses:list")

    return _course_dict(course, user)


@router.put("/{course_id}")
async def update_course(
    course_id: int,
    payload: CourseUpdate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")

    update_data = payload.model_dump(
        exclude_none=True,
        exclude={"category_ids", "tag_ids", "status"},
    )

    for field, val in update_data.items():
        setattr(course, field, val)

    if "title" in update_data:
        course.slug = _make_slug(payload.title, db, exclude_id=course_id)

    if payload.category_ids is not None:
        course.categories = db.query(Category).filter(
            Category.id.in_(payload.category_ids)
        ).all()

    if payload.tag_ids is not None:
        course.tags = db.query(Tag).filter(Tag.id.in_(payload.tag_ids)).all()

    if payload.status is not None:
        if user.is_admin():
            course.status = payload.status
        elif payload.status == CourseStatus.pending:
            course.status = CourseStatus.pending

    # Auto-derive feature flags from fee columns
    if "subscription_fee" in update_data and "subscription_enabled" not in update_data:
        course.subscription_enabled = bool(
            course.subscription_fee and float(course.subscription_fee) > 0
        )
    if "pay_as_you_go_fee" in update_data and "pay_as_you_go_enabled" not in update_data:
        course.pay_as_you_go_enabled = bool(
            course.pay_as_you_go_fee and float(course.pay_as_you_go_fee) > 0
        )
    if "installment_fee" in update_data and "installment_enabled" not in update_data:
        course.installment_enabled = bool(
            course.installment_fee
            and float(course.installment_fee) > 0
            and course.installment_count
            and int(course.installment_count) > 1
        )

    db.commit()
    db.refresh(course)

    # Invalidate both the detail cache (by ID and slug) and all listing caches
    _invalidate_course_caches(course_id, slug=course.slug)

    return _course_dict(course, user)


@router.post("/{course_id}/submit-for-approval")
async def submit_for_approval(
    course_id: int,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Not your course")

    course.status = CourseStatus.pending
    db.commit()

    # Status change affects listing (pending filter) and detail badge
    _invalidate_course_caches(course_id, slug=course.slug)
    return SuccessResponse(message="Course submitted for admin approval")


@router.post("/{course_id}/approve", dependencies=[Depends(require_admin)])
async def approve_course(
    course_id: int,
    payload: CourseApproval,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if payload.approved:
        course.status = CourseStatus.published
        course.approved_by_id = admin.id
        course.approved_at = datetime.now(timezone.utc)
        course.rejection_reason = None
        if course.creator:
            cfg = get_app_config()
            url = f"{cfg.hosting_config.frontend_url}/courses/{course.slug}"
            background_tasks.add_task(
                send_course_approved_email,
                course.creator.email, course.creator.name, course.title, url,
            )
    else:
        course.status = CourseStatus.rejected
        course.rejection_reason = payload.rejection_reason
        if course.creator:
            background_tasks.add_task(
                send_course_rejected_email,
                course.creator.email, course.creator.name,
                course.title, payload.rejection_reason or "",
            )

    db.commit()

    # Approval changes status and approved_at — both cached; invalidate both
    _invalidate_course_caches(course_id, slug=course.slug)

    return SuccessResponse(
        message=f"Course {'approved' if payload.approved else 'rejected'} successfully"
    )


@router.delete("/{course_id}", dependencies=[Depends(require_admin)])
async def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    course.is_deleted = True
    course.is_active = False
    db.commit()

    _invalidate_course_caches(course_id, slug=course.slug)
    return SuccessResponse(message="Course deleted")


# ── MEDIA UPLOAD ──────────────────────────────────────────────────────────────

# @router.post("/{course_id}/upload-thumbnail")
# async def upload_thumbnail(
#     course_id: int,
#     file: UploadFile = File(...),
#     user: User = Depends(get_current_verified_user),
#     db: Session = Depends(get_db),
# ):
#     course = db.query(Course).filter(Course.id == course_id).first()
#     if not course:
#         raise HTTPException(status_code=404, detail="Course not found")
#     if course.creator_id != user.id and not user.is_admin():
#         raise HTTPException(status_code=403, detail="Access denied")

#     cfg = get_app_config()
#     upload_dir = os.path.join(
#         cfg.hosting_config.content_delivery.filesystem_base_path,
#         "courses", "thumbnails",
#     )
#     os.makedirs(upload_dir, exist_ok=True)

#     ext = file.filename.rsplit(".", 1)[-1].lower()
#     filename = f"{uuid.uuid4().hex}.{ext}"
#     content = await file.read()

#     with open(os.path.join(upload_dir, filename), "wb") as fh:
#         fh.write(content)

#     # Remove old file (non-fatal)
#     if course.thumbnail and not course.thumbnail.startswith("http"):
#         old_path = os.path.join(upload_dir, course.thumbnail)
#         try:
#             if os.path.isfile(old_path):
#                 os.remove(old_path)
#         except OSError:
#             pass

#     course.thumbnail = filename
#     db.commit()

#     # Thumbnail URL is part of the cached course struct
#     _invalidate_course_caches(course_id, slug=course.slug)

#     return {
#         "thumbnail": filename,
#         "url": _absolute_url(filename, "courses/thumbnails"),
#     }


@router.post("/{course_id}/upload-thumbnail")
async def upload_thumbnail(
    course_id: int,
    file: UploadFile = File(...),
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    content = await file.read()
    url = upload_file(content, file.filename, folder="courses/thumbnails")

    if course.thumbnail:
        delete_file(course.thumbnail, folder="courses/thumbnails")

    course.thumbnail = url
    db.commit()
    _invalidate_course_caches(course_id, slug=course.slug)

    return {"thumbnail": url, "url": url}


# @router.post("/{course_id}/topics/{topic_id}/upload-content")
# async def upload_topic_content(
#     course_id: int,
#     topic_id: int,
#     file: UploadFile = File(...),
#     content_type_hint: Optional[str] = Query(None),
#     user: User = Depends(get_current_verified_user),
#     db: Session = Depends(get_db),
# ):
#     topic = db.query(Topic).filter(
#         Topic.id == topic_id, Topic.course_id == course_id,
#     ).first()
#     if not topic:
#         raise HTTPException(status_code=404, detail="Topic not found")

#     course = topic.course
#     if course.creator_id != user.id and not user.is_admin():
#         raise HTTPException(status_code=403, detail="Access denied")

#     if file.content_type not in ALLOWED_MEDIA:
#         raise HTTPException(
#             status_code=400, detail=f"File type not allowed: {file.content_type}"
#         )

#     cfg = get_app_config()
#     upload_dir = os.path.join(
#         cfg.hosting_config.content_delivery.filesystem_base_path,
#         "courses", "content",
#     )
#     os.makedirs(upload_dir, exist_ok=True)

#     ext = file.filename.rsplit(".", 1)[-1].lower()
#     filename = f"{uuid.uuid4().hex}.{ext}"
#     content = await file.read()

#     max_bytes = cfg.hosting_config.content_delivery.max_file_size_mb * 1024 * 1024
#     if len(content) > max_bytes:
#         raise HTTPException(status_code=400, detail="File too large")

#     with open(os.path.join(upload_dir, filename), "wb") as fh:
#         fh.write(content)

#     mime = file.content_type
#     from app.models.courses import ContentType as CT_model
#     if "video" in mime:        ct = CT_model.video
#     elif "pdf" in mime:        ct = CT_model.pdf
#     elif "image" in mime:      ct = CT_model.image
#     elif "powerpoint" in mime or "presentation" in mime: ct = CT_model.ppt
#     elif "audio" in mime:      ct = CT_model.audio
#     else:                      ct = CT_model.doc

#     tc = TopicContent(
#         title=file.filename, content_type=ct,
#         file_path=filename, mime_type=mime,
#         file_size_bytes=len(content),
#         topic_id=topic_id,
#         order_index=len(topic.contents),
#     )
#     db.add(tc)
#     db.commit()
#     db.refresh(tc)

#     # New content item changes contents_count in the cached struct
#     _invalidate_course_caches(course_id, slug=course.slug)

#     return {
#         "id": tc.id,
#         "title": file.filename,
#         "content_type": ct,
#         "url": _make_content_token_url(tc, user.id),
#         "mime_type": mime,
#         "order_index": tc.order_index,
#     }


# @router.delete("/{course_id}/topics/{topic_id}/content/{content_id}")
# async def delete_topic_content(
#     course_id: int,
#     topic_id: int,
#     content_id: int,
#     user: User = Depends(get_current_verified_user),
#     db: Session = Depends(get_db),
# ):
#     """Delete a single content item from a topic."""
#     tc = db.query(TopicContent).filter(
#         TopicContent.id == content_id,
#         TopicContent.topic_id == topic_id,
#     ).first()
#     if not tc:
#         raise HTTPException(status_code=404, detail="Content not found")

#     topic = db.query(Topic).filter(
#         Topic.id == topic_id, Topic.course_id == course_id,
#     ).first()
#     if not topic:
#         raise HTTPException(status_code=404, detail="Topic not found")

#     if topic.course.creator_id != user.id and not user.is_admin():
#         raise HTTPException(status_code=403, detail="Access denied")

#     if tc.file_path:
#         cfg = get_app_config()
#         full_path = os.path.join(
#             cfg.hosting_config.content_delivery.filesystem_base_path,
#             "courses", "content", tc.file_path,
#         )
#         if os.path.exists(full_path):
#             os.remove(full_path)

#     db.delete(tc)
#     db.commit()

#     _invalidate_course_caches(course_id, slug=topic.course.slug)
#     return SuccessResponse(message="Content deleted")


# v2
@router.post("/{course_id}/topics/{topic_id}/upload-content")
async def upload_topic_content(
    course_id: int,
    topic_id: int,
    file: UploadFile = File(...),
    content_type_hint: Optional[str] = Query(None),
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    course = topic.course
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    if file.content_type not in ALLOWED_MEDIA:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {file.content_type}")

    content = await file.read()
    cfg = get_app_config()
    max_bytes = cfg.storage_config.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    url = upload_file(content, file.filename, folder="courses/content")

    mime = file.content_type
    from app.models.courses import ContentType as CT_model
    if "video" in mime: ct = CT_model.video
    elif "pdf" in mime: ct = CT_model.pdf
    elif "image" in mime: ct = CT_model.image
    elif "powerpoint" in mime or "presentation" in mime: ct = CT_model.ppt
    elif "audio" in mime: ct = CT_model.audio
    else: ct = CT_model.doc

    tc = TopicContent(
        title=file.filename, content_type=ct,
        file_path=url, mime_type=mime,           # file_path now holds the URL
        file_size_bytes=len(content),
        topic_id=topic_id, order_index=len(topic.contents),
    )
    db.add(tc); db.commit(); db.refresh(tc)
    _invalidate_course_caches(course_id, slug=course.slug)

    return {
        "id": tc.id, "title": file.filename, "content_type": ct,
        "url": url, "mime_type": mime, "order_index": tc.order_index,
    }

@router.delete("/{course_id}/topics/{topic_id}/content/{content_id}")
async def delete_topic_content(
    course_id: int, topic_id: int, content_id: int,
        user: User = Depends(get_current_verified_user),
        db: Session = Depends(get_db)):
    tc = db.query(TopicContent).filter(TopicContent.id == content_id, TopicContent.topic_id == topic_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    if tc.file_path:
        delete_file(tc.file_path, folder="courses/content")

    db.delete(tc); db.commit()
    _invalidate_course_caches(course_id, slug=topic.course.slug)
    return SuccessResponse(message="Content deleted")


# ── LESSONS ───────────────────────────────────────────────────────────────────

@router.post("/{course_id}/lessons", status_code=201)
async def create_lesson(
    course_id: int,
    payload: LessonCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    lesson = Lesson(
        title=payload.title, description=payload.description,
        order_index=payload.order_index, course_id=course_id,
        slug=slugify(payload.title),
    )
    db.add(lesson)
    db.commit()
    db.refresh(lesson)

    _invalidate_course_caches(course_id, slug=course.slug)
    return {
        "id": lesson.id, "title": lesson.title,
        "order_index": lesson.order_index, "topics": [],
    }


@router.put("/{course_id}/lessons/{lesson_id}")
async def update_lesson(
    course_id: int,
    lesson_id: int,
    payload: LessonUpdate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    lesson = db.query(Lesson).filter(
        Lesson.id == lesson_id, Lesson.course_id == course_id,
    ).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(lesson, k, v)
    db.commit()

    _invalidate_course_caches(course_id, slug=lesson.course.slug)
    return {"id": lesson.id, "title": lesson.title}


@router.delete("/{course_id}/lessons/{lesson_id}")
async def delete_lesson(
    course_id: int,
    lesson_id: int,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    lesson = db.query(Lesson).filter(
        Lesson.id == lesson_id, Lesson.course_id == course_id,
    ).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    slug = lesson.course.slug
    db.delete(lesson)
    db.commit()

    _invalidate_course_caches(course_id, slug=slug)
    return SuccessResponse(message="Lesson deleted")


# ── TOPICS ────────────────────────────────────────────────────────────────────

@router.post("/{course_id}/topics", status_code=201)
async def create_topic(
    course_id: int,
    payload: TopicCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    lesson = db.query(Lesson).filter(
        Lesson.id == payload.lesson_id, Lesson.course_id == course_id,
    ).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    topic = Topic(
        title=payload.title, description=payload.description,
        order_index=payload.order_index, lesson_id=payload.lesson_id,
        course_id=course_id, duration_minutes=payload.duration_minutes,
        is_free_preview=payload.is_free_preview,
        slug=slugify(payload.title),
    )
    db.add(topic)
    db.commit()
    db.refresh(topic)

    _invalidate_course_caches(course_id, slug=lesson.course.slug)
    return {
        "id": topic.id, "title": topic.title,
        "order_index": topic.order_index,
        "is_free_preview": topic.is_free_preview,
        "duration_minutes": topic.duration_minutes,
    }


@router.put("/{course_id}/topics/{topic_id}")
async def update_topic(
    course_id: int,
    topic_id: int,
    payload: TopicUpdate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(topic, k, v)
    db.commit()

    _invalidate_course_caches(course_id, slug=topic.course.slug)
    return {"id": topic.id, "title": topic.title}


@router.delete("/{course_id}/topics/{topic_id}")
async def delete_topic(
    course_id: int,
    topic_id: int,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id,
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    slug = topic.course.slug
    db.delete(topic)
    db.commit()

    _invalidate_course_caches(course_id, slug=slug)
    return SuccessResponse(message="Topic deleted")


# ── FEEDBACK ──────────────────────────────────────────────────────────────────

@router.post("/{course_id}/feedback")
async def submit_feedback(
    course_id: int,
    payload: FeedbackCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    enrolled = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.course_id == course_id,
    ).first()
    if not enrolled:
        raise HTTPException(
            status_code=403, detail="You must be enrolled to leave feedback"
        )

    course = db.query(Course).filter(Course.id == course_id).first()

    existing = db.query(Feedback).filter(
        Feedback.user_id == user.id, Feedback.course_id == course_id,
    ).first()
    if existing:
        existing.rating = payload.rating
        existing.comment = payload.comment
        db.commit()
        # Rating changed — cached avg_rating and feedbacks list are stale
        _invalidate_course_caches(course_id, slug=course.slug if course else None)
        return SuccessResponse(message="Feedback updated")

    db.add(Feedback(
        rating=payload.rating, comment=payload.comment,
        user_id=user.id, course_id=course_id,
    ))
    db.commit()

    # New feedback changes feedbacks list and avg_rating in the cached struct
    _invalidate_course_caches(course_id, slug=course.slug if course else None)
    return SuccessResponse(message="Feedback submitted")


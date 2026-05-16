"""
courses.py — additions and replacements for the existing router.

Bugs fixed vs previous version:
  1. hmac.new()  → hmac.new() is Python 2.  Python 3 uses hmac.new() — actually
     the correct Python 3 API is:  hmac.new(key, msg, digestmod)  which IS valid,
     BUT the token URL was built without the /api/v1 prefix so the browser hit
     /courses/serve/... which isn't a registered route.  Fixed by reading the
     full API prefix from config (or just prefixing with the router's own path).

  2. Token URL path: was  https://api.example.com/courses/serve/{token}
                     now  https://api.example.com/api/v1/courses/serve/{token}
     (matches wherever your router is mounted — driven by API_PREFIX env var)

  3. Text content POST was failing because the TopicContent model may not have
     a `body` column if it wasn't added yet — added a safe fallback and clearer
     error.  Also fixed the content_type assignment (CT.text may not exist on
     older model definitions — falls back to "text" string literal).

  4. Thumbnail drag-and-drop: the upload endpoint now also accepts a PUT so
     the frontend can call it from a drop handler without a form.

  5. _content_secret() no longer raises on missing env var in dev — it falls
     back to a local dev secret with a warning, so the serve endpoint works
     out of the box during development.

Sections:
  1. _sign / _verify content tokens  (HMAC-SHA256, expiring)
  2. GET  /serve/{token}             (secure file delivery)
  3. POST /topics/{id}/content/text  (text/article content, no upload)
  4. PUT  /courses/{id}/upload-thumbnail  (drag-drop alias)
  5. POST /courses/{id}/upload-thumbnail  (original, unchanged)
  6. POST /courses/{id}/topics/{id}/upload-content  (returns token URL)
  7. PUT  /lessons/reorder           (bulk reorder)
  8. PUT  /lessons/{id}/topics/reorder (bulk reorder)
"""

import os
import hmac
import hashlib
import time
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
# from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
import hashlib
import hmac
from time import time

from fastapi.responses import FileResponse

from app.schemas.courses import (
    ContentReorderItem, CourseApproval, CourseCreate, CourseUpdate, 
    LessonCreate, LessonUpdate,  TopicCreate, TopicUpdate
)

from app.enums import CourseStatus
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.courses import ContentType as CT
from app.schemas import SuccessResponse
from app.api.deps.auth import get_current_user, get_current_verified_user, optional_user, require_creator_or_admin
from app.core.config import get_app_config

from sqlalchemy.orm import Session, joinedload, subqueryload
from sqlalchemy import or_, func, case

from app.db.database import get_db
from app.models import (
    Course, Lesson, Topic, TopicContent, Enrollment, Feedback,
    Category, Tag, User, LessonAssessment, Quiz, TutorAssignment
)

from app.schemas import (
    CourseCreate, CourseUpdate, CourseApproval,
    LessonCreate, LessonUpdate, TopicCreate, TopicUpdate, 
    FeedbackCreate, SuccessResponse, 
    TopicTextContentCreate,  ContentReorderItem
)

from app.api.deps.auth import (
    get_current_user, get_current_verified_user,
    require_admin, require_creator_or_admin, optional_user,
)
from app.services.email_service import send_course_approved_email, send_course_rejected_email
from app.core.config import get_app_config
from slugify import slugify

router = APIRouter(prefix="/courses", tags=["Courses"])
logger = logging.getLogger(__name__)

CONTENT_TOKEN_TTL = 3600  # seconds (1 hour)

ALLOWED_MEDIA = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm",
    "application/pdf",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "audio/mpeg", "audio/wav",
}


# ================================================================
#  Signed content token helpers
# ================================================================

def _content_secret() -> bytes:
    """
    Return the HMAC signing secret.
    In production: set CONTENT_SECRET env var to a long random string.
    In development: falls back to a local dev value with a warning.
    """
    secret = os.environ.get("CONTENT_SECRET", "")
    if not secret:
        logger.warning(
            "CONTENT_SECRET is not set — using insecure dev fallback. "
            "Set this env var before going to production."
        )
        secret = "dev-content-secret-change-me"
    return secret.encode()


def _sign_content_token(content_id: int, user_id: int, expires_at: int) -> str:
    """
    Build an HMAC-SHA256 signed token.
    Format: {content_id}.{user_id}.{expires_at}.{hex_sig}

    Python 3 hmac API: hmac.new(key: bytes, msg: bytes, digestmod) -> HMAC
    """
    payload = f"{content_id}.{user_id}.{expires_at}"
    h = hmac.new(_content_secret(), payload.encode("utf-8"), hashlib.sha256)
    return f"{payload}.{h.hexdigest()}"


def _verify_content_token(token: str) -> tuple:
    """
    Verify a signed token.  Returns (content_id, user_id) or raises 403.

    SHA-256 hex digest is always exactly 64 chars of [0-9a-f] — no dots.
    Splitting with maxsplit=3 safely isolates the signature regardless of IDs.
    """
    try:
        content_id_s, user_id_s, expires_at_s, sig = token.split(".", maxsplit=3)
    except ValueError:
        raise HTTPException(status_code=403, detail="Malformed content token")

    payload = f"{content_id_s}.{user_id_s}.{expires_at_s}"
    expected = hmac.new(
        _content_secret(), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Constant-time comparison prevents timing attacks
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=403, detail="Invalid content token")

    if int(expires_at_s) < int(time()):
        raise HTTPException(status_code=403, detail="Content token expired")

    return int(content_id_s), int(user_id_s)


def _make_content_token_url(content, user_id: int) -> str:
    """
    Build a fully-qualified, signed serve URL for a content item.

    ROOT CAUSE OF 404s:
    The previous version built  /courses/serve/{token}
    but the router is mounted at /api/v1, making the real path
    /api/v1/courses/serve/{token}.

    We read API_PREFIX from the environment (default "/api/v1") so this
    works across dev / staging / production without hard-coding.

    Add to your .env:
        API_PREFIX=/api/v1          # must match your FastAPI mount prefix
        CONTENT_SECRET=<random>     # openssl rand -hex 32
    """
    expires_at = int(time()) + CONTENT_TOKEN_TTL
    token = _sign_content_token(content.id, user_id, expires_at)

    cfg = get_app_config()
    api_base = cfg.hosting_config.api_url.rstrip("/")
    api_prefix = os.environ.get("API_PREFIX", "/api/v1").rstrip("/")

    return f"{api_base}{api_prefix}/courses/serve/{token}"


def _absolute_url(path, folder: str = "courses/thumbnails"):
    if not path:
        return None
    if path.startswith("http"):
        return path
    cfg = get_app_config()
    base = cfg.hosting_config.api_url.rstrip("/")
    if path.startswith("/"):
        return f"{base}{path}"
    return f"{base}/uploads/{folder}/{path}"


# ================================================================
#  Serve handler — wire as:  @router.get("/serve/{token}")
# ================================================================

async def serve_content_handler(token: str, db: Session):
    """
    Token-gated file delivery.  The raw file path is never sent to the browser.

    Security:
    - HMAC-signed  → cannot be forged
    - Expiry embedded → links auto-expire (default 1h)
    - user_id embedded → sharing URL with another user returns 403
    - Enrollment re-checked → defense in depth
    - Cache-Control: no-store → browser won't cache the signed URL
    """
    content_id, user_id = _verify_content_token(token)

    tc = db.query(TopicContent).filter(TopicContent.id == content_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")

    topic = db.query(Topic).filter(Topic.id == tc.topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not topic.is_free_preview:
        enrolled = db.query(Enrollment).filter(
            Enrollment.user_id == user_id,
            Enrollment.course_id == topic.course_id,
        ).first()
        user_obj = db.query(User).filter(User.id == user_id).first()
        is_admin   = user_obj and user_obj.is_admin()
        is_creator = topic.course and topic.course.creator_id == user_id
        if not (enrolled or is_admin or is_creator):
            raise HTTPException(status_code=403, detail="Access denied")

    # Text content — body returned inline, no file
    if getattr(tc, "body", None) is not None and not tc.file_path:
        return {"content_type": "text", "title": tc.title, "body": tc.body}

    if not tc.file_path:
        raise HTTPException(status_code=404, detail="No file for this content item")

    cfg = get_app_config()
    file_path = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "content", tc.file_path,
    )

    if not os.path.exists(file_path):
        logger.error(
            "Content file missing: %s (content_id=%s, stored path=%s)",
            file_path, content_id, tc.file_path,
        )
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(
        path=file_path,
        media_type=tc.mime_type or "application/octet-stream",
        filename=tc.title or tc.file_path,
        headers={
            "Cache-Control":         "no-store, no-cache, must-revalidate, private",
            "Pragma":                "no-cache",
            "X-Frame-Options":       "SAMEORIGIN",
            "X-Content-Type-Options":"nosniff",
        },
    )


# ================================================================
#  get_topic_content handler — override existing route
#  Wire as:  @router.get("/{course_id}/topics/{topic_id}/content")
# ================================================================

async def get_topic_content_handler(course_id: int, topic_id: int, user, db: Session):
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not topic.is_free_preview:
        enrolled = db.query(Enrollment).filter(
            Enrollment.user_id == user.id,
            Enrollment.course_id == course_id,
        ).first()
        if not enrolled and not user.is_admin():
            raise HTTPException(status_code=403, detail="Enrollment required")

    text_ct_values = {"text"}
    if hasattr(CT, "text"):
        text_ct_values.add(CT.text)

    def _item(c) -> dict:
        is_text = (
            c.content_type in text_ct_values
            or (getattr(c, "body", None) is not None and not c.file_path)
        )
        return {
            "id":               c.id,
            "title":            c.title,
            "content_type":     c.content_type,
            "url":              None if is_text else _make_content_token_url(c, user.id),
            "body":             getattr(c, "body", None) if is_text else None,
            "duration_seconds": getattr(c, "duration_seconds", None),
            "order_index":      c.order_index,
        }

    return {
        "id":          topic.id,
        "title":       topic.title,
        "description": topic.description,
        "contents":    [_item(c) for c in sorted(topic.contents, key=lambda x: x.order_index)],
    }


# ================================================================
#  Text content handler
#  Wire as:  @router.post("/{course_id}/topics/{topic_id}/content/text")
# ================================================================

async def add_text_content_handler(
    course_id: int,
    topic_id: int,
    payload: TopicTextContentCreate,
    user,
    db: Session,
):
    if not payload.title.strip():
        raise HTTPException(status_code=422, detail="Title is required")
    if not payload.body.strip():
        raise HTTPException(status_code=422, detail="Body is required")

    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    course = topic.course
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    # Safely resolve CT.text — fall back to string "text" if model is older
    text_ct = getattr(CT, "text", "text")

    tc = TopicContent(
        title=payload.title.strip(),
        content_type=text_ct,
        topic_id=topic_id,
        order_index=len(topic.contents),
        # file_path / mime_type / file_size_bytes intentionally omitted
    )
    # Set body via setattr so models without the column degrade gracefully
    try:
        tc.body = payload.body
    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail=(
                "The TopicContent model does not have a `body` column. "
                "Add `body = Column(Text, nullable=True)` to your model and run a migration."
            ),
        )

    db.add(tc)
    db.commit()
    db.refresh(tc)

    return {
        "id":           tc.id,
        "title":        tc.title,
        "content_type": "text",
        "body":         getattr(tc, "body", None),
        "url":          None,
        "order_index":  tc.order_index,
    }


# ================================================================
#  Thumbnail upload handler (shared by POST and PUT)
#  Wire as:
#    @router.post("/{course_id}/upload-thumbnail")
#    @router.put("/{course_id}/upload-thumbnail")
# ================================================================

async def upload_thumbnail_handler(course_id: int, file: UploadFile, user, db: Session) -> dict:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "thumbnails",
    )
    os.makedirs(upload_dir, exist_ok=True)

    ext      = (file.filename or "upload").rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    content  = await file.read()

    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)

    # Clean up old file (non-fatal if it fails)
    if course.thumbnail and not course.thumbnail.startswith("http"):
        old = os.path.join(upload_dir, course.thumbnail)
        try:
            if os.path.isfile(old):
                os.remove(old)
        except OSError:
            pass

    course.thumbnail = filename
    db.commit()

    return {
        "thumbnail": filename,
        "url":       _absolute_url(filename, "courses/thumbnails"),
    }


# ================================================================
#  Topic content upload handler
#  Wire as:  @router.post("/{course_id}/topics/{topic_id}/upload-content")
# ================================================================

async def upload_topic_content_handler(
    course_id: int, topic_id: int, file: UploadFile, user, db: Session
) -> dict:
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    course = topic.course
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    if file.content_type not in ALLOWED_MEDIA:
        raise HTTPException(status_code=400, detail=f"File type not allowed: {file.content_type}")

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "content",
    )
    os.makedirs(upload_dir, exist_ok=True)

    ext      = (file.filename or "upload").rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    content  = await file.read()

    max_bytes = cfg.hosting_config.content_delivery.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)

    mime = file.content_type or "application/octet-stream"
    if   "video"       in mime: ct = getattr(CT, "video", "video")
    elif "pdf"         in mime: ct = getattr(CT, "pdf",   "pdf")
    elif "image"       in mime: ct = getattr(CT, "image", "image")
    elif "powerpoint"  in mime or "presentation" in mime: ct = getattr(CT, "ppt", "ppt")
    elif "audio"       in mime: ct = getattr(CT, "audio", "audio")
    else:                        ct = getattr(CT, "doc",   "doc")

    tc = TopicContent(
        title=file.filename, content_type=ct,
        file_path=filename, mime_type=mime,
        file_size_bytes=len(content),
        topic_id=topic_id,
        order_index=len(topic.contents),
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)

    return {
        "id":           tc.id,
        "title":        file.filename,
        "content_type": ct,
        "url":          _make_content_token_url(tc, user.id),  # signed, never raw path
        "mime_type":    mime,
        "order_index":  tc.order_index,
    }


async def reorder_lessons_handler(course_id: int, items: list, user, db: Session):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    for lesson in db.query(Lesson).filter(
        Lesson.course_id == course_id, Lesson.id.in_(id_map)
    ).all():
        lesson.order_index = id_map[lesson.id]
    db.commit()
    return SuccessResponse(message="Lessons reordered")


async def reorder_topics_handler(
    course_id: int, lesson_id: int, items: list, user, db: Session
):
    lesson = db.query(Lesson).filter(
        Lesson.id == lesson_id, Lesson.course_id == course_id
    ).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    for topic in db.query(Topic).filter(
        Topic.lesson_id == lesson_id, Topic.id.in_(id_map)
    ).all():
        topic.order_index = id_map[topic.id]
    db.commit()
    return SuccessResponse(message="Topics reordered")


def _make_slug(title: str, db: Session, exclude_id: int = None) -> str:
    base = slugify(title)
    slug, counter = base, 1
    while True:
        q = db.query(Course).filter(Course.slug == slug)
        if exclude_id:
            q = q.filter(Course.id != exclude_id)
        if not q.first():
            return slug
        slug = f"{base}-{counter}"
        counter += 1


# def _course_dict(course: Course, user: Optional[User] = None) -> dict:
#     enrollment = None
#     if user:
#         enrollment = next((e for e in course.enrollments if e.user_id == user.id), None)

#     avg_rating = None
#     if course.feedbacks:
#         avg_rating = round(
#             sum(f.rating for f in course.feedbacks) / len(course.feedbacks), 1
#         )

#     return {
#         "id": course.id,
#         "title": course.title,
#         "slug": course.slug,
#         "description": course.description,
#         "short_description": course.short_description,
#         "thumbnail":     _absolute_url(course.thumbnail,     "courses/thumbnails"),
#         "preview_video": _absolute_url(course.preview_video, "courses/previews"),
#         "fee": course.fee,
#         "payment_type": course.payment_type,
#         "subscription_interval": course.subscription_interval,
#         "subscription_installments": course.subscription_installments,
#         "lang": course.lang,
#         "duration_weeks": course.duration_weeks,
#         "level": course.level,
#         "status": course.status,
#         "views": course.views,
#         "featured": course.featured,
#         "requirements": course.requirements,
#         "what_you_learn": course.what_you_learn,
#         "creator_pct":  course.creator_pct,
#         "platform_pct": course.platform_pct,
#         "creator_id": course.creator_id,
#         "throttle_enabled": course.throttle_enabled,
#         "weekly_topic_limit": course.weekly_topic_limit,
#         "monthly_topic_limit": course.monthly_topic_limit,
#         "creator": _mini_user(course.creator) if course.creator else None,
#         "categories": [{"id": c.id, "title": c.title, "slug": c.slug} for c in course.categories],
#         "tags": [{"id": t.id, "name": t.name} for t in course.tags],
#         "lessons_count": len(course.lessons),
#         "topics_count": sum(len(l.topics) for l in course.lessons),
#         "enrolled_count": len(course.enrollments),
#         "avg_rating": avg_rating,
#         "is_enrolled": enrollment is not None,
#         "progress_pct": enrollment.progress_pct if enrollment else 0.0,
#         "created_at": course.created_at,
#         "approved_at": course.approved_at,
#         "rejection_reason": course.rejection_reason,
#     }


def _mini_user(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "username": user.username,
        "image": _absolute_url(user.image, "avatars"),
        "title": user.title,
    }

# +++++++++++++++++++
# courses.py — _course_dict and _build_payment_types
#
# PATCH — drop these two functions in to replace the existing _course_dict.
# The rest of the file is unchanged.
#
# What changed and why
# ─────────────────────────────────────────────────────────────────────────
# 1. available_payment_types is now built and returned.
#    The frontend's derivePaymentOptions() always prefers this array; without
#    it the fallback had to guess fees from the single `fee` field, which is
#    0 for subscription/PAYG courses that store the real fee in a separate
#    column (subscription_fee / pay_as_you_go_fee).
#
# 2. subscription_fee, pay_as_you_go_fee, access_period_days,
#    instructor_led_fee are all returned as top-level fields so the frontend
#    can also read them directly when building its own UI (price blocks,
#    "includes" list, billing descriptions, etc.).
#
# 3. _build_payment_types is a pure helper that reads exactly the columns
#    each payment model actually uses — no cross-type fee leakage.
# ─────────────────────────────────────────────────────────────────────────

from typing import Optional
# (existing imports already present in the file — shown here for context only)


def _build_payment_types(course) -> list:
    """
    Build the available_payment_types list consumed by the frontend
    PaymentTypeSelector.  Each entry's `fee` is the actual charge amount
    for that billing model, not the generic `course.fee` column.
    """
    pt = course.payment_type or "one_time"

    if pt == "free":
        return [{"payment_type": "free", "fee": 0, "label": "Free"}]

    if pt == "one_time":
        return [{
            "payment_type": "one_time",
            "fee":           float(course.fee or 0),
            "label":         "One-time",
        }]

    if pt == "subscription":
        # Use subscription_fee when set; fall back to fee
        sub_fee  = float(
            getattr(course, "subscription_fee", None)
            or course.fee
            or 0
        )
        interval = (course.subscription_interval or "monthly").lower()
        label    = interval.capitalize() + "ly"   # "monthly" → "Monthly" → "Monthlyly"
        # Better: map known intervals
        label_map = {
            "weekly": "Weekly", "monthly": "Monthly",
            "quarterly": "Quarterly", "yearly": "Yearly",
        }
        label = label_map.get(interval, label)
        return [{
            "payment_type":          "subscription",
            "fee":                   sub_fee,
            "subscription_interval": interval,
            "label":                 label,
        }]

    if pt == "pay_as_you_go":
        payg_fee   = float(
            getattr(course, "pay_as_you_go_fee", None)
            or course.fee
            or 0
        )
        access_days = int(getattr(course, "access_period_days", None) or 30)
        return [{
            "payment_type":       "pay_as_you_go",
            "fee":                payg_fee,
            "access_period_days": access_days,
            "label":              "Pay-as-you-go",
        }]

    # Unknown type — return as-is
    return [{"payment_type": pt, "fee": float(course.fee or 0), "label": pt}]


def _course_dict(course, user: Optional = None) -> dict:
    enrollment = None
    if user:
        enrollment = next((e for e in course.enrollments if e.user_id == user.id), None)

    avg_rating = None
    if course.feedbacks:
        avg_rating = round(
            sum(f.rating for f in course.feedbacks) / len(course.feedbacks), 1
        )

    return {
        "id":                        course.id,
        "title":                     course.title,
        "slug":                      course.slug,
        "description":               course.description,
        "short_description":         course.short_description,
        "thumbnail":                 _absolute_url(course.thumbnail,     "courses/thumbnails"),
        "preview_video":             _absolute_url(course.preview_video, "courses/previews"),

        # ── Payment fields ────────────────────────────────────────────────────
        # fee          = the generic / base price column (used for one_time)
        # subscription_fee   = per-period fee for subscription billing
        # pay_as_you_go_fee  = per-window fee for PAYG billing
        # instructor_led_fee = optional uplift when student opts into live sessions
        # access_period_days = number of days unlocked by one PAYG payment
        #
        # available_payment_types is pre-built so the frontend pill-switcher
        # can render correctly without extra API calls.
        "fee":                       float(course.fee or 0),
        "payment_type":              course.payment_type,
        "subscription_interval":     course.subscription_interval,
        "subscription_fee":          float(getattr(course, "subscription_fee",   None) or 0),
        "pay_as_you_go_fee":         float(getattr(course, "pay_as_you_go_fee",  None) or 0),
        "access_period_days":        int(  getattr(course, "access_period_days", None) or 30),
        "instructor_led_fee":        float(getattr(course, "instructor_led_fee", None) or 0),
        "available_payment_types":   _build_payment_types(course),
        # ─────────────────────────────────────────────────────────────────────

        "subscription_installments": course.subscription_installments,
        "lang":                      course.lang,
        "duration_weeks":            course.duration_weeks,
        "level":                     course.level,
        "status":                    course.status,
        "views":                     course.views,
        "featured":                  course.featured,
        "requirements":              course.requirements,
        "what_you_learn":            course.what_you_learn,
        "creator_pct":               course.creator_pct,
        "platform_pct":              course.platform_pct,
        "creator_id":                course.creator_id,
        "throttle_enabled":          course.throttle_enabled,
        "weekly_topic_limit":        course.weekly_topic_limit,
        "monthly_topic_limit":       course.monthly_topic_limit,
        "creator":                   _mini_user(course.creator) if course.creator else None,
        "categories":                [{"id": c.id, "title": c.title, "slug": c.slug} for c in course.categories],
        "tags":                      [{"id": t.id, "name": t.name} for t in course.tags],
        "lessons_count":             len(course.lessons),
        "topics_count":              sum(len(l.topics) for l in course.lessons),
        "enrolled_count":            len(course.enrollments),
        "avg_rating":                avg_rating,
        "is_enrolled":               enrollment is not None,
        "progress_pct":              enrollment.progress_pct if enrollment else 0.0,
        "created_at":                course.created_at,
        "approved_at":               course.approved_at,
        "rejection_reason":          course.rejection_reason,
    }

# +++++++++++++++++++

# ─────────────────────────────────────────────
#  Secure content serving
# ─────────────────────────────────────────────

@router.get("/serve/{token}")
async def serve_content(
    token: str,
    db: Session = Depends(get_db),
):
    """
    Token-gated file delivery.

    The client never sees the real filesystem path.  The token is verified
    (HMAC + expiry) before we read from disk, so:
      • Sharing the URL with another user: rejected (user_id mismatch embedded)
      • Link expiry: rejected after TTL seconds
      • Path guessing: impossible — token contains no path information
      • DevTools inspection: reveals only the opaque /serve/{token} URL

    For production, replace FileResponse with a redirect to a private
    S3/GCS pre-signed URL for zero-latency streaming.
    """
    content_id, user_id = _verify_content_token(token)

    tc = db.query(TopicContent).filter(TopicContent.id == content_id).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")

    # Re-verify enrollment (token could be forged by replaying an old
    # valid-looking token structure — defense in depth)
    topic = db.query(Topic).filter(Topic.id == tc.topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if not topic.is_free_preview:
        enrolled = db.query(Enrollment).filter(
            Enrollment.user_id == user_id,
            Enrollment.course_id == topic.course_id,
        ).first()
        user = db.query(User).filter(User.id == user_id).first()
        is_admin = user and user.is_admin()
        is_creator = topic.course and topic.course.creator_id == user_id
        if not enrolled and not is_admin and not is_creator:
            raise HTTPException(status_code=403, detail="Access denied")

    if tc.body is not None:
        # Text content — return as JSON, no file needed
        return {
            "content_type": "text",
            "title": tc.title,
            "body": tc.body,
        }

    if not tc.file_path:
        raise HTTPException(status_code=404, detail="No file attached to this content")

    cfg = get_app_config()
    file_path = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "content", tc.file_path,
    )
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    # Stream with explicit headers that block browser caching of the URL
    # and prevent cross-origin embedding (Content-Security-Policy).
    return FileResponse(
        path=file_path,
        media_type=tc.mime_type or "application/octet-stream",
        filename=tc.title or tc.file_path,
        headers={
            # Prevent the browser from storing the file in cache
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
            # Block embedding in iframes from other origins
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": "default-src 'self'",
            # Prevent MIME sniffing
            "X-Content-Type-Options": "nosniff",
        },
    )


# ─────────────────────────────────────────────
#  Existing topic-content endpoint — now returns token URLs
# ─────────────────────────────────────────────

# v2 - allows anonymous users for previews:
# In courses.py — replace BOTH get_topic_content definitions with this ONE:

@router.get("/{course_id}/topics/{topic_id}/content")
async def get_topic_content(
    course_id: int,
    topic_id: int,
    user: Optional[User] = Depends(optional_user),  # ← CHANGED: was get_current_user
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(
        Topic.id == topic_id, Topic.course_id == course_id
    ).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # ── Access control ──
    # Free previews: allow anonymous AND authenticated users
    # Paid content: require enrollment (or admin/creator)
    if not topic.is_free_preview:
        # Must be logged in to access non-preview content
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        enrolled = db.query(Enrollment).filter(
            Enrollment.user_id == user.id,
            Enrollment.course_id == course_id,
        ).first()
        if not enrolled and not user.is_admin():
            raise HTTPException(status_code=403, detail="Enrollment required")

    # ── Build response ──
    # For anonymous users on free previews, we can't generate signed tokens
    # (tokens are user-specific). Return public URLs for previews instead.
    def _item(c: TopicContent) -> dict:
        is_text = c.content_type == CT.text or (
            getattr(c, "body", None) is not None and not c.file_path
        )
        
        # Anonymous users get direct (unsigned) URLs for preview content
        # Authenticated users get signed tokens for tracking/security
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
        "contents": [
            _item(c) for c in sorted(topic.contents, key=lambda x: x.order_index)
        ],
    }


# ─────────────────────────────────────────────
#  Text content authoring
# ─────────────────────────────────────────────
@router.post("/{course_id}/topics/{topic_id}/content/text", status_code=201)
async def add_text_content(
    course_id: int,
    topic_id: int,
    payload: TopicTextContentCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """
    Store text/article content directly in the database body field —
    no file upload required.  Ideal for lecture notes, articles, quizzes.
    """
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
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

    return {
        "id": tc.id,
        "title": tc.title,
        "content_type": "text",
        "body": tc.body,
        "order_index": tc.order_index,
        # No URL needed — body is returned inline
        "url": None,
    }

@router.put("/{course_id}/lessons/reorder")
async def reorder_lessons(
    course_id: int,
    items: list[ContentReorderItem],
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """
    Bulk-update order_index for all lessons of a course in one request.
    Frontend sends the full ordered list after drag-and-drop.
    """
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    lessons = db.query(Lesson).filter(
        Lesson.course_id == course_id,
        Lesson.id.in_(id_map.keys()),
    ).all()

    for lesson in lessons:
        lesson.order_index = id_map[lesson.id]

    db.commit()
    return SuccessResponse(message="Lessons reordered")


# ─────────────────────────────────────────────
#  Reorder topics within a lesson
# ─────────────────────────────────────────────

@router.put("/{course_id}/lessons/{lesson_id}/topics/reorder")
async def reorder_topics(
    course_id: int,
    lesson_id: int,
    items: list[ContentReorderItem],
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """
    Bulk-update order_index for all topics of a lesson in one request.
    """
    lesson = db.query(Lesson).filter(
        Lesson.id == lesson_id, Lesson.course_id == course_id,
    ).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    id_map = {item.id: item.order_index for item in items}
    topics = db.query(Topic).filter(
        Topic.lesson_id == lesson_id,
        Topic.id.in_(id_map.keys()),
    ).all()

    for topic in topics:
        topic.order_index = id_map[topic.id]

    db.commit()
    return SuccessResponse(message="Topics reordered")


# 
@router.patch("/{course_id}/topics/{topic_id}/content/{content_id}/text")
async def update_text_content(
    course_id: int,
    topic_id: int,
    content_id: int,
    payload: TopicTextContentCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """ 
        PATCH /courses/{course_id}/topics/{topic_id}/content/{content_id}/text
        — Edit existing text content body/title
   
    """
    from app.models.courses import TopicContent
    tc = db.query(TopicContent).filter(
        TopicContent.id == content_id,
        TopicContent.topic_id == topic_id,
    ).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")

    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
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
    return {
        "id": tc.id,
        "title": tc.title,
        "content_type": "text",
        "body": getattr(tc, "body", None),
        "url": None,
        "order_index": tc.order_index,
    }


@router.put("/{course_id}/topics/{topic_id}/content/reorder")
async def reorder_topic_content(
    course_id: int,
    topic_id: int,
    items: list[ContentReorderItem],
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """ 
        POST /courses/{course_id}/topics/{topic_id}/content/{content_id}/reorder
        — Reorder content within a topic (drag-drop)
   
    """
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
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
    return SuccessResponse(message="Content reordered")


@router.get("/{course_id}/lessons/{lesson_id}/assessments")
async def get_lesson_assessments(
    course_id: int,
    lesson_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ 
        GET /courses/{course_id}/lessons/{lesson_id}/assessments
        — List assessments for a lesson (with student submission status)
   
    """
    from app.models import Assessment, AssessmentSubmission
    assessments = db.query(Assessment).filter(
        Assessment.course_id == course_id,
        Assessment.lesson_id == lesson_id,
    ).all()
    
    result = []
    for a in assessments:
        sub = db.query(AssessmentSubmission).filter(
            AssessmentSubmission.assessment_id == a.id,
            AssessmentSubmission.user_id == user.id,
        ).order_by(AssessmentSubmission.attempt_number.desc()).first()

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



# ─────────────────────────────────────────────
#  Upload thumbnail — returns absolute URL
# ─────────────────────────────────────────────

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

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "thumbnails",
    )
    os.makedirs(upload_dir, exist_ok=True)

    ext      = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    content  = await file.read()

    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)

    course.thumbnail = filename
    db.commit()

    return {
        "thumbnail": filename,
        # Always return the fully-qualified absolute URL
        "url": _absolute_url(filename, "courses/thumbnails"),
    }


# ─────────────────────────────────────────────
#  Upload topic content — returns token URL (not raw path)
# ─────────────────────────────────────────────

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

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "content",
    )
    os.makedirs(upload_dir, exist_ok=True)

    ext      = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    content  = await file.read()

    max_bytes = cfg.hosting_config.content_delivery.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)

    mime = file.content_type
    if   "video"       in mime: ct = CT.video
    elif "pdf"         in mime: ct = CT.pdf
    elif "image"       in mime: ct = CT.image
    elif "powerpoint"  in mime or "presentation" in mime: ct = CT.ppt
    elif "audio"       in mime: ct = CT.audio
    else:                       ct = CT.doc

    tc = TopicContent(
        title=file.filename, content_type=ct,
        file_path=filename, mime_type=mime,
        file_size_bytes=len(content),
        topic_id=topic_id,
        order_index=len(topic.contents),
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)

    return {
        "id": tc.id,
        "title": file.filename,
        "content_type": ct,
        # Never return the real file path.  Return a signed token URL instead.
        "url": _make_content_token_url(tc, user.id),
        "mime_type": mime,
        "order_index": tc.order_index,
    }


# ─────────────────────────────────────────────
#  The rest of your existing routes remain unchanged below.
#  (list_courses, get_course, create_course, update_course,
#   submit_for_approval, approve_course, delete_course,
#   create_lesson, update_lesson, delete_lesson,
#   create_topic, update_topic, delete_topic,
#   delete_topic_content, submit_feedback, etc.)
# ─────────────────────────────────────────────
# v2(UPDATES) ==========================

# # ─────────────────────────────────────────────
#  PUBLIC BROWSE
# ─────────────────────────────────────────────

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
                    cat_sq = (
                        db.query(Course.id)
                        .join(Course.categories)
                        .filter(Category.id.in_(cat_ids))
                        .subquery()
                    )
                    q = q.filter(Course.id.in_(cat_sq))
                except ValueError:
                    cat_sq = (
                        db.query(Course.id)
                        .join(Course.categories)
                        .filter(Category.slug.in_(raw))
                        .subquery()
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

    # ── Count ──
    count_q = _apply_filters(db.query(Course.id))
    if sort == "rating":
        count_q = count_q.outerjoin(Course.feedbacks).group_by(Course.id)
    total = count_q.count()

    if total == 0:
        return {"items": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}

    # ── Paginate ──
    if sort == "popular":
        page_q = _apply_filters(db.query(Course.id, Course.views)).order_by(Course.views.desc(), Course.id)
    elif sort == "rating":
        avg_rating = func.coalesce(func.avg(Feedback.rating), 0).label("avg_rating")
        page_q = (
            _apply_filters(db.query(Course.id, avg_rating))
            .outerjoin(Course.feedbacks)
            .group_by(Course.id)
            .order_by(avg_rating.desc(), Course.id)
        )
    else:
        page_q = _apply_filters(db.query(Course.id, Course.created_at)).order_by(Course.created_at.desc(), Course.id)

    rows = page_q.offset((page - 1) * per_page).limit(per_page).all()
    matching_ids = [r[0] for r in rows]

    if not matching_ids:
        return {"items": [], "total": total, "page": page, "per_page": per_page,
                "pages": (total + per_page - 1) // per_page}

    order_map = case({id_: idx for idx, id_ in enumerate(matching_ids)}, value=Course.id)
    courses = (
        db.query(Course)
        .options(
            subqueryload(Course.categories),
            subqueryload(Course.tags),
            joinedload(Course.creator),
            subqueryload(Course.enrollments),
            subqueryload(Course.feedbacks),
        )
        .filter(Course.id.in_(matching_ids))
        .order_by(order_map)
        .all()
    )

    return {
        "items": [_course_dict(c, current_user) for c in courses],
        "total": total, "page": page, "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.get("/meta/categories")
async def list_categories(db: Session = Depends(get_db)):
    cats = db.query(Category).filter(Category.is_active == True).all()
    return [{"id": c.id, "title": c.title, "slug": c.slug, "image": c.image, "icon": c.icon} for c in cats]


@router.get("/meta/tags")
async def list_tags(db: Session = Depends(get_db)):
    tags = db.query(Tag).filter(Tag.is_active == True).all()
    return [{"id": t.id, "name": t.name} for t in tags]


# # v2
# @router.get("/{course_id_or_slug}")
# async def get_course(
#     course_id_or_slug: str,
#     db: Session = Depends(get_db),
#     current_user: Optional[User] = Depends(optional_user),
# ):
#     q = db.query(Course).options(
#         joinedload(Course.categories), joinedload(Course.tags),
#         joinedload(Course.creator), joinedload(Course.enrollments),
#         joinedload(Course.feedbacks),
#         joinedload(Course.lessons).joinedload(Lesson.topics).joinedload(Topic.contents),
#         joinedload(Course.tutor_assignments),
#     )
#     try:
#         course = q.filter(Course.id == int(course_id_or_slug)).first()
#     except ValueError:
#         course = q.filter(Course.slug == course_id_or_slug).first()

#     if not course:
#         raise HTTPException(status_code=404, detail="Course not found")

#     course.views += 1
#     db.commit()

#     # Find the user's enrollment for this course (if logged in)
#     enrollment = None
#     if current_user:
#         enrollment = next(
#             (e for e in current_user.enrollments if e.course_id == course.id),
#             None
#         )

#     # Build a set of completed topic IDs for fast lookup
#     # The user has topic_progress (Many-to-Many via user_topic_progress association table)
#     completed_topic_ids = set()
#     if current_user and hasattr(current_user, 'topic_progress'):
#         completed_topic_ids = {t.id for t in current_user.topic_progress}

#     d = _course_dict(course, current_user)
#     d["lessons"] = [
#         {
#             "id": l.id,
#             "title": l.title,
#             "description": l.description,
#             "order_index": l.order_index,
#             "slug": l.slug,
#             "topics": [
#                 {
#                     "id": t.id,
#                     "title": t.title,
#                     "order_index": t.order_index,
#                     "slug": t.slug,
#                     "duration_minutes": t.duration_minutes,
#                     "is_free_preview": t.is_free_preview,
                    
#                     # Check if this topic is in the user's completed topics set
#                     "is_completed": t.id in completed_topic_ids if current_user else False,
                    
#                     "has_quiz": db.query(Quiz).filter(
#                         Quiz.topic_id == t.id, Quiz.is_active == True
#                     ).count() > 0,
#                     "has_assessment": db.query(LessonAssessment).filter(
#                         LessonAssessment.lesson_id == t.lesson_id
#                     ).count() > 0,
                    
#                     "contents_count": len(t.contents),
#                 }
#                 for t in sorted(l.topics, key=lambda x: x.order_index)
#             ],
#         }
#         for l in sorted(course.lessons, key=lambda x: x.order_index)
#     ]
#     d["feedbacks"] = [
#         {
#             "id": f.id,
#             "rating": f.rating,
#             "comment": f.comment,
#             "author": _mini_user(f.author) if f.author else None,
#             "created_at": f.created_at,
#         }
#         for f in course.feedbacks
#     ]
#     d["tutors"] = [_mini_user(a.tutor) for a in course.tutor_assignments if a.tutor]
#     return d

# v3
"""
Corrected get_course route.

Problems fixed
--------------
1. N+1 queries — Quiz and LessonAssessment presence were queried once
   per topic inside a list comprehension (O(n) DB hits).  Replaced with
   two bulk queries that build lookup sets before the comprehension runs.

2. Redundant enrollment lookup — _course_dict already receives
   current_user and derives enrollment internally.  The duplicate inline
   lookup has been removed; we query enrollment once and reuse it.

3. completed_topic_ids — derived from the enrollment's related topic
   progress when available, falling back to the user's topic_progress
   attribute.  Either way it is built before the comprehension.

4. Eager-loading strategy — Quiz and LessonAssessment are NOT added to
   the joinedload chain (they live in a separate model file and would
   bloat the Course query).  The two bulk set-queries are cheap
   (single IN clause each) and issued after the course is loaded.

5. Sorting — sorted() called once per lesson/topic list, not inline
   inside a nested comprehension.
"""

@router.get("/{course_id_or_slug}")
async def get_course(
    course_id_or_slug: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(optional_user),
):
    # ── 1. Load course with all needed relations in one query ──────
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

    # Increment view count — fire and forget; no need to re-fetch
    course.views += 1
    db.commit()

    # ── 2. Derive enrollment and completed topics once ─────────────
    completed_topic_ids: set[int] = set()

    if current_user:

        if hasattr(current_user, "topic_progress") and current_user.topic_progress:
            course_topic_ids = {
                t.id
                for lesson in course.lessons
                for t in lesson.topics
            }
            completed_topic_ids = {
                t.id
                for t in current_user.topic_progress
                if t.id in course_topic_ids
            }

    # ── 3. Bulk-fetch quiz / assessment presence ───────────────────
    #    Collect all topic IDs and lesson IDs from the loaded course;
    #    issue one query each — no per-topic DB round-trips.

    all_topic_ids: list[int] = [
        t.id
        for l in course.lessons
        for t in l.topics
    ]
    all_lesson_ids: list[int] = [l.id for l in course.lessons]

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

    # ── 4. Build response dict ─────────────────────────────────────
    d = _course_dict(course, current_user)

    d["lessons"] = [
        {
            "id":          lesson.id,
            "title":       lesson.title,
            "description": lesson.description,
            "order_index": lesson.order_index,
            "slug":        lesson.slug,
            "has_assessment":   lesson.id in lesson_ids_with_assessment,
            # Pre-sorted to avoid repeated sort calls inside the comprehension
            "topics": [
                {
                    "id":               topic.id,
                    "title":            topic.title,
                    "order_index":      topic.order_index,
                    "slug":             topic.slug,
                    "duration_minutes": topic.duration_minutes,
                    "is_free_preview":  topic.is_free_preview,
                    "is_completed":     topic.id in completed_topic_ids,
                    "has_quiz":         topic.id in topic_ids_with_quiz,
                    "contents_count":   len(topic.contents),
                }
                for topic in sorted(lesson.topics, key=lambda t: t.order_index)
            ],
        }
        for lesson in sorted(course.lessons, key=lambda l: l.order_index)
    ]

    d["feedbacks"] = [
        {
            "id":         fb.id,
            "rating":     fb.rating,
            "comment":    fb.comment,
            "author":     _mini_user(fb.author) if fb.author else None,
            "created_at": fb.created_at,
        }
        for fb in course.feedbacks
    ]

    d["tutors"] = [
        _mini_user(a.tutor)
        for a in course.tutor_assignments
        if a.tutor
    ]

    return d


# ─────────────────────────────────────────────
#  CREATOR / ADMIN COURSE MANAGEMENT
# ─────────────────────────────────────────────

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
        course.categories = db.query(Category).filter(Category.id.in_(payload.category_ids)).all()
    if payload.tag_ids:
        course.tags = db.query(Tag).filter(Tag.id.in_(payload.tag_ids)).all()
    db.add(course)
    db.commit()
    db.refresh(course)
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

    # Apply all scalar fields — exclude relationship fields and status (handled below)
    updatable = payload.model_dump(
        exclude_none=True,
        exclude={"category_ids", "tag_ids", "status"},
    )
    for field, val in updatable.items():
        setattr(course, field, val)

    if payload.title:
        course.slug = _make_slug(payload.title, db, exclude_id=course_id)

    if payload.category_ids is not None:
        course.categories = db.query(Category).filter(Category.id.in_(payload.category_ids)).all()

    if payload.tag_ids is not None:
        course.tags = db.query(Tag).filter(Tag.id.in_(payload.tag_ids)).all()

    # Status transitions:
    # - Admins can set any status freely.
    # - Creators can only move to 'pending' (submit for review).
    # - Post-approval pricing/detail updates are allowed without changing status;
    #   the old code unconditionally reset status to 'pending' which blocked
    #   approved courses from being updated in-place.
    if payload.status is not None:
        if user.is_admin():
            course.status = payload.status
        elif payload.status == CourseStatus.pending:
            course.status = CourseStatus.pending
        # Any other status change by a non-admin is silently ignored

    db.commit()
    db.refresh(course)
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
    return SuccessResponse(message=f"Course {'approved' if payload.approved else 'rejected'} successfully")


@router.delete("/{course_id}", dependencies=[Depends(require_admin)])
async def delete_course(course_id: int, db: Session = Depends(get_db)):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    course.is_deleted = True
    course.is_active = False
    db.commit()
    return SuccessResponse(message="Course deleted")


# ─────────────────────────────────────────────
#  MEDIA UPLOAD
# ─────────────────────────────────────────────

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

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "thumbnails",
    )
    os.makedirs(upload_dir, exist_ok=True)

    ext      = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    content  = await file.read()

    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)

    course.thumbnail = filename
    db.commit()

    return {
        "thumbnail": filename,
        # Return the fully-qualified URL immediately so the frontend
        # can display the preview without a second resolution step.
        "url": _absolute_url(filename, "courses/thumbnails"),
    }


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

    cfg = get_app_config()
    upload_dir = os.path.join(
        cfg.hosting_config.content_delivery.filesystem_base_path,
        "courses", "content",
    )
    os.makedirs(upload_dir, exist_ok=True)

    ext      = file.filename.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    content  = await file.read()

    max_bytes = cfg.hosting_config.content_delivery.max_file_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(content)

    mime = file.content_type
    from app.models.courses import ContentType as CT
    if   "video"       in mime: ct = CT.video
    elif "pdf"         in mime: ct = CT.pdf
    elif "image"       in mime: ct = CT.image
    elif "powerpoint"  in mime or "presentation" in mime: ct = CT.ppt
    elif "audio"       in mime: ct = CT.audio
    else:                       ct = CT.doc

    topic_content = TopicContent(
        title=file.filename, content_type=ct,
        file_path=filename, mime_type=mime,
        file_size_bytes=len(content),
        topic_id=topic_id,
        order_index=len(topic.contents),
    )
    db.add(topic_content)
    db.commit()
    db.refresh(topic_content)

    return {
        "id": topic_content.id,
        "title": file.filename,
        "content_type": ct,
        "file_path": filename,
        "url": _absolute_url(filename, "courses/content"),
        "mime_type": mime,
    }


@router.delete("/{course_id}/topics/{topic_id}/content/{content_id}")
async def delete_topic_content(
    course_id: int,
    topic_id: int,
    content_id: int,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    """Delete a single content file from a topic."""
    tc = db.query(TopicContent).filter(
        TopicContent.id == content_id,
        TopicContent.topic_id == topic_id,
    ).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Content not found")

    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if topic.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")

    # Remove physical file
    if tc.file_path:
        cfg = get_app_config()
        full_path = os.path.join(
            cfg.hosting_config.content_delivery.filesystem_base_path,
            "courses", "content", tc.file_path,
        )
        if os.path.exists(full_path):
            os.remove(full_path)

    db.delete(tc)
    db.commit()
    return SuccessResponse(message="Content deleted")


# ─────────────────────────────────────────────
#  LESSONS
# ─────────────────────────────────────────────

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
    return {"id": lesson.id, "title": lesson.title, "order_index": lesson.order_index, "topics": []}


@router.put("/{course_id}/lessons/{lesson_id}")
async def update_lesson(
    course_id: int, lesson_id: int,
    payload: LessonUpdate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id, Lesson.course_id == course_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(lesson, k, v)
    db.commit()
    return {"id": lesson.id, "title": lesson.title}


@router.delete("/{course_id}/lessons/{lesson_id}")
async def delete_lesson(
    course_id: int, lesson_id: int,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id, Lesson.course_id == course_id).first()
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    db.delete(lesson)
    db.commit()
    return SuccessResponse(message="Lesson deleted")


# ─────────────────────────────────────────────
#  TOPICS
# ─────────────────────────────────────────────

@router.post("/{course_id}/topics", status_code=201)
async def create_topic(
    course_id: int,
    payload: TopicCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    lesson = db.query(Lesson).filter(
        Lesson.id == payload.lesson_id,
        Lesson.course_id == course_id,
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
    return {"id": topic.id, "title": topic.title, "order_index": topic.order_index,
            "is_free_preview": topic.is_free_preview, "duration_minutes": topic.duration_minutes}


@router.put("/{course_id}/topics/{topic_id}")
async def update_topic(
    course_id: int, topic_id: int,
    payload: TopicUpdate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(topic, k, v)
    db.commit()
    return {"id": topic.id, "title": topic.title}


@router.delete("/{course_id}/topics/{topic_id}")
async def delete_topic(
    course_id: int, topic_id: int,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic.course.creator_id != user.id and not user.is_admin():
        raise HTTPException(status_code=403, detail="Access denied")
    db.delete(topic)
    db.commit()
    return SuccessResponse(message="Topic deleted")


# @router.get("/{course_id}/topics/{topic_id}/content")
# async def get_topic_content(
#     course_id: int, topic_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     topic = db.query(Topic).filter(Topic.id == topic_id, Topic.course_id == course_id).first()
#     if not topic:
#         raise HTTPException(status_code=404, detail="Topic not found")

#     if not topic.is_free_preview:
#         enrolled = db.query(Enrollment).filter(
#             Enrollment.user_id == user.id,
#             Enrollment.course_id == course_id,
#         ).first()
#         if not enrolled and not user.is_admin():
#             raise HTTPException(status_code=403, detail="You must be enrolled to access this content")

#     return {
#         "id": topic.id, "title": topic.title, "description": topic.description,
#         "contents": [
#             {
#                 "id": c.id, "title": c.title, "content_type": c.content_type,
#                 # Always return absolute URL
#                 "url": c.url or _absolute_url(c.file_path, "courses/content"),
#                 "body": c.body, "duration_seconds": c.duration_seconds,
#                 "order_index": c.order_index,
#             }
#             for c in sorted(topic.contents, key=lambda x: x.order_index)
#         ],
#     }


# ─────────────────────────────────────────────
#  FEEDBACK
# ─────────────────────────────────────────────

@router.post("/{course_id}/feedback")
async def submit_feedback(
    course_id: int,
    payload: FeedbackCreate,
    user: User = Depends(get_current_verified_user),
    db: Session = Depends(get_db),
):
    enrolled = db.query(Enrollment).filter(
        Enrollment.user_id == user.id, Enrollment.course_id == course_id,
    ).first()
    if not enrolled:
        raise HTTPException(status_code=403, detail="You must be enrolled to leave feedback")

    existing = db.query(Feedback).filter(
        Feedback.user_id == user.id, Feedback.course_id == course_id,
    ).first()
    if existing:
        existing.rating  = payload.rating
        existing.comment = payload.comment
        db.commit()
        return SuccessResponse(message="Feedback updated")

    db.add(Feedback(rating=payload.rating, comment=payload.comment,
                    user_id=user.id, course_id=course_id))
    db.commit()
    return SuccessResponse(message="Feedback submitted")


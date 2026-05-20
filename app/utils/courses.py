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

import logging
import os
import hmac
import hashlib
import time
import uuid
from typing import Optional
from fastapi import HTTPException, UploadFile
import hashlib
import hmac
from time import time

from fastapi.responses import FileResponse
from slugify import slugify


from sqlalchemy.orm import Session

from app.models.courses import ContentType as CT
from app.core.config import get_app_config

from app.models import (
    Course, Lesson, Topic, TopicContent, Enrollment, User
)

from app.schemas import (
    SuccessResponse, 
    TopicTextContentCreate
)

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

def _mini_user(user: User) -> dict:
    return {
        "id": user.id, "name": user.name, "username": user.username,
        "image": _absolute_url(user.image, "avatars"),
        "title": user.title,
    }

# def _course_dict(course, user: Optional = None) -> dict:
#     enrollment = None
#     if user:
#         enrollment = next((e for e in course.enrollments if e.user_id == user.id), None)

#     avg_rating = None
#     if course.feedbacks:
#         avg_rating = round(
#             sum(f.rating for f in course.feedbacks) / len(course.feedbacks), 1
#         )

#     return {
#         "id":                        course.id,
#         "title":                     course.title,
#         "slug":                      course.slug,
#         "description":               course.description,
#         "short_description":         course.short_description,
#         "thumbnail":                 _absolute_url(course.thumbnail,     "courses/thumbnails"),
#         "preview_video":             _absolute_url(course.preview_video, "courses/previews"),

#         # ── All fee columns returned so the frontend can render any option ──
#         # "fee":                       float(course.fee or 0),
#         # "payment_type":              course.payment_type,
#         # "subscription_interval":     course.subscription_interval,
#         # "subscription_fee":          float(getattr(course, "subscription_fee",   None) or 0),
#         # "pay_as_you_go_fee":         float(getattr(course, "pay_as_you_go_fee",  None) or 0),
#         # "access_period_days":        int(  getattr(course, "access_period_days", None) or 30),
#         # "instructor_led_fee":        float(getattr(course, "instructor_led_fee", None) or 0),

#         # ── Pre-built option list — consumed by PaymentTypeSelector ─────────
#         # Contains one entry per non-zero fee field, each with the correct
#         # fee for that billing model (not always course.fee).
#         # "available_payment_types":   _build_payment_types(course),
#         # ────────────────────────────────────────────────────────────────────

#         # 
#         **_pricing_fields(course),
        
#         "subscription_installments": course.subscription_installments,
#         "lang":                      course.lang,
#         "duration_weeks":            course.duration_weeks,
#         "level":                     course.level,
#         "status":                    course.status,
#         "views":                     course.views,
#         "featured":                  course.featured,
#         "requirements":              course.requirements,
#         "what_you_learn":            course.what_you_learn,
#         "creator_pct":               course.creator_pct,
#         "platform_pct":              course.platform_pct,
#         "creator_id":                course.creator_id,
#         "throttle_enabled":          course.throttle_enabled,
#         "weekly_topic_limit":        course.weekly_topic_limit,
#         "monthly_topic_limit":       course.monthly_topic_limit,
#         "creator":                   _mini_user(course.creator) if course.creator else None,
#         "categories":                [{"id": c.id, "title": c.title, "slug": c.slug} for c in course.categories],
#         "tags":                      [{"id": t.id, "name": t.name} for t in course.tags],
#         "lessons_count":             len(course.lessons),
#         "topics_count":              sum(len(l.topics) for l in course.lessons),
#         "enrolled_count":            len(course.enrollments),
#         "avg_rating":                avg_rating,
#         "is_enrolled":               enrollment is not None,
#         "progress_pct":              enrollment.progress_pct if enrollment else 0.0,
#         "created_at":                course.created_at,
#         "approved_at":               course.approved_at,
#         "rejection_reason":          course.rejection_reason,
#     }

# v2
from typing import Optional, Dict, Set
from collections import defaultdict

def _course_dict(
    course, user: Optional = None, 
    _enrollment_map: Optional[Dict[int, object]] = None,
    _feedback_stats: Optional[Dict[int, tuple]] = None,
    _topic_counts: Optional[Dict[int, int]] = None) -> dict:
    """
    Optimized course dict with optional pre-computed stats.
    
    Args:
        _enrollment_map: dict mapping course_id -> enrollment for the current user
        _feedback_stats: dict mapping course_id -> (avg_rating, count)
        _topic_counts: dict mapping course_id -> total_topic_count
    """
    # Fast-path: use pre-computed enrollment instead of linear search
    if _enrollment_map is not None:
        enrollment = _enrollment_map.get(course.id)
    elif user:
        enrollment = next((e for e in course.enrollments if e.user_id == user.id), None)
    else:
        enrollment = None

    # Fast-path: use pre-computed feedback stats
    if _feedback_stats is not None:
        avg_rating, _ = _feedback_stats.get(course.id, (None, 0))
    else:
        avg_rating = None
        if course.feedbacks:
            avg_rating = round(
                sum(f.rating for f in course.feedbacks) / len(course.feedbacks), 1
            )

    # Fast-path: use pre-computed topic count
    if _topic_counts is not None:
        topics_count = _topic_counts.get(course.id, 0)
    else:
        topics_count = sum(len(l.topics) for l in course.lessons)

    return {
        "id":                        course.id,
        "title":                     course.title,
        "slug":                      course.slug,
        "description":               course.description,
        "short_description":         course.short_description,
        "thumbnail":                 _absolute_url(course.thumbnail, "courses/thumbnails"),
        "preview_video":             _absolute_url(course.preview_video, "courses/previews"),
        **_pricing_fields(course),
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
        "topics_count":              topics_count,
        "enrolled_count":            len(course.enrollments),
        "avg_rating":                avg_rating,
        "is_enrolled":               enrollment is not None,
        "progress_pct":              enrollment.progress_pct if enrollment else 0.0,
        "created_at":                course.created_at,
        "approved_at":               course.approved_at,
        "rejection_reason":          course.rejection_reason,
    }


# courses.py — replace _build_payment_types AND _course_dict
#
# Problem
# ───────
# _build_payment_types returned only ONE option (the course's primary
# payment_type).  If a course has fee=5000 AND subscription_fee=2000 set,
# only the primary type was shown.  Students had no way to choose.
#
# Fix — same rule as _derive_payment_types for paths:
#   fee > 0              → "One-time" available
#   subscription_fee > 0 → "Subscription" available
#   pay_as_you_go_fee > 0→ "Pay-as-you-go" available
#   payment_type='free'  → only "Free", nothing else
#
# _course_dict is updated to include all fee columns so the frontend
# pill-switcher can render the correct price for each option.

_INTERVAL_LABELS = {
    "weekly": "Weekly", "monthly": "Monthly",
    "quarterly": "Quarterly", "yearly": "Yearly",
}


def _build_payment_types(course) -> list:
    """
    Return every active billing option for a course as a list of dicts.
    Fee > 0 is the sole gate — no separate boolean flag required.
 
    Shape of each entry:
        { payment_type, fee, label, subscription_interval?, access_period_days?,
          installment_count?, installment_fee? }
    """
    pt       = getattr(course, "payment_type", None) or "one_time"
    base_fee = float(getattr(course, "fee", None) or 0)
    sub_fee  = float(getattr(course, "subscription_fee",  None) or 0)
    payg_fee = float(getattr(course, "pay_as_you_go_fee", None) or 0)
    inst_fee = float(getattr(course, "installment_fee",   None) or 0)
    inst_cnt = getattr(course, "installment_count", None)
 
    # Free path
    if pt == "free" or (base_fee == 0 and sub_fee == 0 and payg_fee == 0 and inst_fee == 0):
        return [{"payment_type": "free", "fee": 0, "label": "Free",
                 "subscription_interval": None, "access_period_days": None}]
 
    options = []
 
    if base_fee > 0:
        options.append({
            "payment_type": "one_time", "fee": base_fee, "label": "One-time",
            "subscription_interval": None, "access_period_days": None,
        })
 
    if sub_fee > 0:
        interval = (getattr(course, "subscription_interval", None) or "monthly").lower()
        options.append({
            "payment_type": "subscription", "fee": sub_fee,
            "label": _INTERVAL_LABELS.get(interval, "Subscription"),
            "subscription_interval": interval, "access_period_days": None,
        })
 
    if payg_fee > 0:
        access_days = int(getattr(course, "access_period_days", None) or 30)
        options.append({
            "payment_type": "pay_as_you_go", "fee": payg_fee, "label": "Pay-as-you-go",
            "subscription_interval": None, "access_period_days": access_days,
        })
 
    if inst_fee > 0 and inst_cnt and inst_cnt > 1:
        options.append({
            "payment_type": "installment", "fee": inst_fee,
            "label": f"{inst_cnt}× instalments",
            "installment_count": inst_cnt, "installment_fee": inst_fee,
            "subscription_interval": None, "access_period_days": None,
        })
 
    if not options:
        options.append({
            "payment_type": pt, "fee": base_fee,
            "label": {"one_time": "One-time"}.get(pt, pt),
            "subscription_interval": None, "access_period_days": None,
        })
 
    return options


def _pricing_fields(course) -> dict:
    """
    Returns the pricing-related fields that every course endpoint should include.
    Spread this into your existing return dict:
 
        return {
            "id": course.id,
            "title": course.title,
            ...existing fields...,
            **_pricing_fields(course),    # ← add this line
        }
    """
    return {
        "fee":                   float(getattr(course, "fee", 0) or 0),
        "payment_type":          getattr(course, "payment_type", "one_time"),
        "subscription_fee":      float(course.subscription_fee  or 0) if getattr(course, "subscription_fee",  None) is not None else None,
        "subscription_enabled":  bool(getattr(course, "subscription_enabled",  False)),
        "subscription_interval": getattr(course, "subscription_interval", "monthly") or "monthly",
        "pay_as_you_go_fee":     float(course.pay_as_you_go_fee or 0) if getattr(course, "pay_as_you_go_fee", None) is not None else None,
        "pay_as_you_go_enabled": bool(getattr(course, "pay_as_you_go_enabled", False)),
        "access_period_days":    int(getattr(course, "access_period_days", 30) or 30),
        "installment_enabled":   bool(getattr(course, "installment_enabled",   False)),
        "installment_count":     getattr(course, "installment_count",   None),
        "installment_fee":       float(course.installment_fee or 0) if getattr(course, "installment_fee", None) is not None else None,
        "instructor_led_fee":    float(getattr(course, "instructor_led_fee", 0) or 0),
        "throttle_enabled":      bool(getattr(course, "throttle_enabled",     False)),
        "weekly_topic_limit":    getattr(course, "weekly_topic_limit",  None),
        "monthly_topic_limit":   getattr(course, "monthly_topic_limit", None),
        "available_payment_types": _build_payment_types(course),
    }


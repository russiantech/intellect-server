# """app/services/storage_service.py — Supabase Storage integration."""
# import logging
# import uuid
# from pathlib import Path
# from typing import Optional

# from supabase import create_client, Client

# from app.core.config import get_app_config

# logger = logging.getLogger(__name__)

# _client: Optional[Client] = None
# _bucket_checked = False


# def get_supabase() -> Client:
#     global _client
#     if _client is None:
#         cfg = get_app_config().storage_config.supabase
#         _client = create_client(cfg.url, cfg.service_role_key)
#     return _client


# def ensure_bucket_exists() -> None:
#     """Creates the configured bucket if it doesn't already exist.
#     Safe to call multiple times — checks first, no-ops if present.
#     Intended to be run once per environment via scripts/setup_supabase.py,
#     not on every app startup (see notes from earlier discussion)."""
#     global _bucket_checked
#     if _bucket_checked:
#         return

#     cfg = get_app_config().storage_config.supabase
#     client = get_supabase()

#     try:
#         existing = client.storage.list_buckets()
#         names = {b.name if hasattr(b, "name") else b["name"] for b in existing}
#     except Exception as exc:
#         logger.error("Could not list Supabase buckets: %s", exc)
#         _bucket_checked = True
#         return

#     if cfg.bucket_name in names:
#         logger.info("Supabase bucket '%s' already exists.", cfg.bucket_name)
#     else:
#         try:
#             client.storage.create_bucket(
#                 cfg.bucket_name,
#                 options={
#                     "public": cfg.public,
#                     "file_size_limit": "10MB",
#                     "allowed_mime_types": ["image/png", "image/jpeg", "image/webp", "video/mp4"],
#                 },
#             )
#             logger.info(
#                 "Created Supabase bucket '%s' (public=%s).",
#                 cfg.bucket_name, cfg.public,
#             )
#         except Exception as exc:
#             # Bucket might've been created by a concurrent worker/request — not fatal.
#             logger.warning("Could not create Supabase bucket '%s': %s", cfg.bucket_name, exc)

#     _bucket_checked = True


# def upload_file(contents: bytes, filename_hint: str, folder: str = "products") -> str:
#     """Uploads bytes to Supabase Storage, returns the public (or signed) URL."""
#     cfg = get_app_config().storage_config.supabase
#     ext = Path(filename_hint).suffix.lower()
#     key = f"{folder}/{uuid.uuid4().hex}{ext}"

#     client = get_supabase()
#     content_type = _guess_content_type(ext)

#     client.storage.from_(cfg.bucket_name).upload(
#         path=key,
#         file=contents,
#         file_options={"content-type": content_type, "upsert": "false"},
#     )

#     if cfg.public:
#         return client.storage.from_(cfg.bucket_name).get_public_url(key)
#     else:
#         signed = client.storage.from_(cfg.bucket_name).create_signed_url(key, 60 * 60 * 24 * 365)
#         return signed["signedURL"]


# def delete_file(key_or_url: str, folder: str = "products") -> None:
#     """Accepts either the storage key or a full URL and deletes the object."""
#     cfg = get_app_config().storage_config.supabase
#     key = key_or_url
#     if key_or_url.startswith("http"):
#         # extract the path portion after the bucket name in the URL
#         key = key_or_url.split(f"/{cfg.bucket_name}/")[-1]
#     try:
#         get_supabase().storage.from_(cfg.bucket_name).remove([key])
#     except Exception as exc:
#         logger.warning("Could not delete storage object %s: %s", key, exc)


# def _guess_content_type(ext: str) -> str:
#     return {
#         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
#         ".webp": "image/webp", ".gif": "image/gif",
#         ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
#     }.get(ext, "application/octet-stream")





# v2
"""
app/services/storage.py
─────────────────────────────────────────────────────────────────────────────
Provider-agnostic file storage for Intellect LMS.

Reads `app_config.storage_config.provider` (supabase | s3 | cloudinary |
filesystem) and dispatches accordingly, so every route calls the same
`upload_file()` / `delete_file()` regardless of backend — same pattern as
Stitch's `upload_file(contents, filename, folder=...)`.

`filesystem` is kept only as a local-dev fallback. It is NOT safe on
serverless hosts (Vercel, Lambda, etc.) since the filesystem is read-only
outside /tmp and non-persistent even there.
"""
import logging
import mimetypes
import os
import uuid
from pathlib import Path

from app.core.config import get_app_config

logger = logging.getLogger(__name__)

_supabase_client = None
_s3_client = None


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _unique_name(filename: str) -> str:
    ext = _ext(filename)
    return f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex


def _guess_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _get_supabase_client():
    global _supabase_client
    if _supabase_client is None:
        from supabase import create_client
        cfg = get_app_config().storage_config.supabase
        if not cfg.url or not cfg.service_role_key:
            raise RuntimeError(
                "Supabase storage not configured — set APP_SUPABASE_URL and "
                "APP_SUPABASE_SERVICE_ROLE_KEY."
            )
        _supabase_client = create_client(cfg.url, cfg.service_role_key)
    return _supabase_client


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        import boto3
        cfg = get_app_config().storage_config.s3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=cfg.endpoint_url,
            region_name=cfg.region,
            aws_access_key_id=cfg.access_key_id,
            aws_secret_access_key=cfg.secret_access_key,
            use_ssl=cfg.use_ssl,
        )
    return _s3_client


def ensure_bucket_exists() -> None:
    """
    One-off provisioning check. Run this as a standalone script per
    environment when you provision — NOT from the request-serving lifespan.
    Calling it on every cold start just adds latency and hits the provider's
    API for something that only needs to happen once. (Same call you already
    made in Stitch's main.py, left commented for the same reason.)
    """
    cfg = get_app_config().storage_config
    if cfg.provider == "supabase":
        client = _get_supabase_client()
        buckets = {b.name for b in client.storage.list_buckets()}
        if cfg.supabase.bucket_name not in buckets:
            client.storage.create_bucket(
                cfg.supabase.bucket_name, options={"public": cfg.supabase.public}
            )
            logger.info("Created Supabase bucket '%s'", cfg.supabase.bucket_name)
    elif cfg.provider == "s3":
        client = _get_s3_client()
        try:
            client.head_bucket(Bucket=cfg.s3.bucket_name)
        except Exception:
            client.create_bucket(Bucket=cfg.s3.bucket_name)
            logger.info("Created S3 bucket '%s'", cfg.s3.bucket_name)


def upload_file(contents: bytes, filename: str, *, folder: str = "misc") -> str:
    """
    Persist `contents` under `<folder>/` and return a public URL.
    Always generates a fresh uuid-based filename — never trusts the
    caller's original filename for the stored key.
    """
    cfg = get_app_config().storage_config
    stored_name = _unique_name(filename)
    key = f"{folder}/{stored_name}"
    mime = _guess_mime(filename)

    if cfg.provider == "supabase":
        client = _get_supabase_client()
        client.storage.from_(cfg.supabase.bucket_name).upload(
            key, contents, {"content-type": mime}
        )
        return client.storage.from_(cfg.supabase.bucket_name).get_public_url(key)

    if cfg.provider == "s3":
        client = _get_s3_client()
        client.put_object(
            Bucket=cfg.s3.bucket_name, Key=key, Body=contents, ContentType=mime
        )
        if cfg.s3.endpoint_url:
            return f"{cfg.s3.endpoint_url.rstrip('/')}/{cfg.s3.bucket_name}/{key}"
        return f"https://{cfg.s3.bucket_name}.s3.{cfg.s3.region}.amazonaws.com/{key}"

    if cfg.provider == "cloudinary":
        import cloudinary
        import cloudinary.uploader
        cloudinary.config(
            cloud_name=cfg.cloudinary.cloud_name,
            api_key=cfg.cloudinary.api_key,
            api_secret=cfg.cloudinary.api_secret,
        )
        public_id = f"{cfg.cloudinary.folder}/{folder}/{stored_name.rsplit('.', 1)[0]}"
        result = cloudinary.uploader.upload(
            contents, public_id=public_id, resource_type="auto"
        )
        return result["secure_url"]

    # ── filesystem fallback (local dev only) ──────────────────────────────
    base_dir = os.path.abspath(cfg.filesystem_base_path)
    dest_dir = os.path.join(base_dir, folder)
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, stored_name), "wb") as fh:
        fh.write(contents)
    api_url = get_app_config().hosting_config.api_url.rstrip("/")
    return f"{api_url}/uploads/{folder}/{stored_name}"


def _extract_key(url_or_key: str, folder: str) -> str:
    """Recover the storage key (`folder/name.ext`) from either a stored URL
    or an already-bare key, so delete/sign helpers work with either."""
    if url_or_key.startswith("http"):
        marker = f"/{folder}/"
        if marker in url_or_key:
            return f"{folder}/{url_or_key.split(marker)[-1]}"
        return f"{folder}/{url_or_key.rsplit('/', 1)[-1]}"
    return url_or_key if "/" in url_or_key else f"{folder}/{url_or_key}"


def create_signed_url(url_or_key: str, *, folder: str = "misc", expires_in: int = 300) -> str:
    """
    Short-lived signed URL for gated/private content (course content,
    project submissions). Use this instead of streaming bytes through the
    app server — the provider's CDN serves the file directly, and the URL
    expires (`expires_in` seconds) so it can't be shared/cached indefinitely.
    Auth/entitlement checks belong BEFORE calling this, not after.
    """
    cfg = get_app_config().storage_config
    key = _extract_key(url_or_key, folder)

    if cfg.provider == "supabase":
        client = _get_supabase_client()
        result = client.storage.from_(cfg.supabase.bucket_name).create_signed_url(key, expires_in)
        return result.get("signedURL") or result.get("signed_url") or result["signedUrl"]

    if cfg.provider == "s3":
        client = _get_s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": cfg.s3.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )

    if cfg.provider == "cloudinary":
        import cloudinary.utils
        url, _ = cloudinary.utils.cloudinary_url(
            key.rsplit(".", 1)[0], resource_type="auto",
            type="authenticated", sign_url=True,
        )
        return url

    # filesystem fallback — nothing to sign; caller should FileResponse locally
    return url_or_key


def delete_file(url_or_key: str, *, folder: str = "misc") -> None:
    """Best-effort delete. Never raises — cleanup failures shouldn't break requests."""
    if not url_or_key:
        return
    cfg = get_app_config().storage_config
    try:
        key = _extract_key(url_or_key, folder)

        if cfg.provider == "supabase":
            _get_supabase_client().storage.from_(cfg.supabase.bucket_name).remove([key])
        elif cfg.provider == "s3":
            _get_s3_client().delete_object(Bucket=cfg.s3.bucket_name, Key=key)
        elif cfg.provider == "cloudinary":
            import cloudinary.uploader
            cloudinary.uploader.destroy(key.rsplit(".", 1)[0], resource_type="auto")
        else:
            base_dir = os.path.abspath(cfg.filesystem_base_path)
            path = os.path.join(base_dir, key)
            if os.path.isfile(path):
                os.remove(path)
    except Exception as exc:
        logger.warning("delete_file failed for %s: %s", url_or_key, exc)
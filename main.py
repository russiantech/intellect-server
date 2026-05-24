"""
main.py — Intellect LMS API entry point  v3
=============================================
Fixes:
- setup_exception_handlers(app) takes 1 arg, not 2
- Routers registered BEFORE middleware wraps app
- Pure ASGI middleware applied at the end without breaking FastAPI methods
"""

import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_app_config
from app.core.exceptions import setup_exception_handlers
# from app.core.performance.middleware import add_performance_middleware

app_config = get_app_config()
LOG_LEVEL = logging.DEBUG if app_config.general_config.development_mode else logging.INFO
LOG_DIR = os.environ.get("LOG_DIR", "/tmp/logs" if os.environ.get("VERCEL") else "logs")
os.makedirs(LOG_DIR, exist_ok=True)


# 
# print(f"DEBUG api_url_override={app_config.hosting_config.api_url_override!r}")
print(f"DEBUG computed api_url={app_config.hosting_config.api_url!r}")

def setup_logging():
    root = logging.getLogger()
    root.setLevel(LOG_LEVEL)
    if root.handlers:
        return
    
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    
    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
    )
    fh.setFormatter(fmt)
    
    root.addHandler(ch)
    root.addHandler(fh)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


setup_logging()
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s API...", app_config.general_config.site_name)
    
    uploads_dir = os.path.abspath(app_config.hosting_config.content_delivery.filesystem_base_path)
    for subdir in ("", "courses/thumbnails", "courses/content", "courses/previews", "avatars"):
        os.makedirs(os.path.join(uploads_dir, subdir), exist_ok=True)
    
    try:
        from app.db.database import create_tables
        create_tables()
        logger.info("Database tables verified.")
    except Exception as exc:
        logger.warning("Database setup issue: %s", exc)
    
    try:
        from app.core.performance.cache_config import cache
        from app.services.redis_service import RedisService
        _redis_url = app_config.redis_config.redis_connection_string
        _redis_for_cache = RedisService(_redis_url) if _redis_url else None
        cache.init(_redis_for_cache)
    except Exception as exc:
        logger.warning("Cache init failed — falling back to in-memory LRU: %s", exc)
    
    if not app_config.oauth_provider_config:
        logger.warning("No OAuth providers enabled.")
    else:
        logger.info("OAuth providers active: %s", list(app_config.oauth_provider_config.keys()))
    
    yield
    
    try:
        from app.db.database import close_db
        close_db()
    except Exception as exc:
        logger.warning("DB pool close error: %s", exc)
    
    try:
        from app.core.performance.cache_config import cache
        cache.clear()
    except Exception:
        pass
    
    logger.info("Shutdown complete.")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CREATE FASTAPI APP (with lifespan)
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title=app_config.general_config.site_name,
    description=app_config.general_config.site_description,
    version=app_config.general_config.api_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. STATIC FILES (mount before middleware so middleware can intercept)
# ═══════════════════════════════════════════════════════════════════════════════

_uploads_dir = os.path.abspath(app_config.hosting_config.content_delivery.filesystem_base_path)
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")

_static_dir = Path("static")
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
logger.info("Serving uploads from %s at /uploads", _uploads_dir)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EXCEPTION HANDLERS (register early)
# ═══════════════════════════════════════════════════════════════════════════════

setup_exception_handlers(app)  # ← Only 1 argument: app


# ═══════════════════════════════════════════════════════════════════════════════
# 4. FASTAPI-NATIVE MIDDLEWARE (CORS, Gzip — safe to use add_middleware)
# ═══════════════════════════════════════════════════════════════════════════════

_cors_origins = app_config.security_config.cors_allowed_origins
if isinstance(_cors_origins, str):
    _cors_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
elif not isinstance(_cors_origins, list):
    _cors_origins = ["http://localhost:5173"]
if app_config.general_config.development_mode and not _cors_origins:
    _cors_origins = ["*"]

logger.info("CORS allowed origins: %s", _cors_origins)
logger.info("DB URI: %s", app_config.database_config.sql_connection_string)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ROUTERS (register BEFORE wrapping with pure ASGI middleware)
# ═══════════════════════════════════════════════════════════════════════════════

from app.api.root_router import root_router, health_router
app.include_router(root_router)
app.include_router(health_router)

from app.api.v1_router import v1_router
app.include_router(v1_router)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PURE ASGI MIDDLEWARE WRAP (outermost layer)
# ═══════════════════════════════════════════════════════════════════════════════
# CRITICAL: This must happen AFTER all routers are registered.
# The returned object is an ASGI app, but we keep the original FastAPI
# app reference for uvicorn. The middleware wraps app.__call__ instead.

# Option A: Wrap app.__call__ directly (recommended — keeps app as FastAPI instance)
_original_call = app.__call__

async def _wrapped_call(scope, receive, send):
    # Build middleware stack around the original call
    from app.core.performance.middleware import (
        TimingMiddleware,
        RequestCoalescingMiddleware,
        ResponseCacheMiddleware,
        ETagMiddleware,
        StaticCacheMiddleware,
    )
    
    # Innermost: the original FastAPI app
    asgi_app = _original_call
    
    # Wrap with middleware (inner → outer)
    asgi_app = StaticCacheMiddleware(asgi_app)
    asgi_app = ETagMiddleware(asgi_app)
    asgi_app = ResponseCacheMiddleware(
        asgi_app,
        ttl=300,
        paths=["/api/v1/courses", "/api/v1/categories", "/api/v1/paths"],
        exclude_paths=[
            "/api/v1/auth",
            "/api/v1/enroll",
            "/api/v1/payments",
            "/api/v1/progress",
            "/api/v1/admin",
        ],
    )
    asgi_app = RequestCoalescingMiddleware(asgi_app)
    asgi_app = TimingMiddleware(asgi_app)
    
    await asgi_app(scope, receive, send)

app.__call__ = _wrapped_call


# ═══════════════════════════════════════════════════════════════════════════════
# 7. ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", app_config.hosting_config.port))
    host = "0.0.0.0" if os.getenv("DOCKER_CONTAINER") else "localhost"
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=app_config.general_config.development_mode,
        log_level="debug" if app_config.general_config.development_mode else "info",
    )


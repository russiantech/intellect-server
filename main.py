# main.py — Intellect LMS API entry point
#
# Integration points for all core modules produced in this session:
#
#   app/db/database.py        →  create_tables(), close_db()          [lifespan]
#   app/core/performance/cache_config.py  →  cache.init(redis), cache.clear()     [lifespan]
#   app/core/performance/middleware.py    →  TimingMiddleware, ETagMiddleware,
#                                ResponseCacheMiddleware,
#                                RequestCoalescingMiddleware            [middleware stack]
#   app/api/root.py           →  root_router, health_router            [routers]
#   app/api/router.py         →  v1_router                             [routers]
#
# Middleware execution order (outermost → innermost):
#   TimingMiddleware  →  RequestCoalescing  →  ResponseCache
#   →  ETag  →  StaticCache  →  Gzip  →  CORS  →  route handler

import logging
import os
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_app_config
from app.core.exceptions import setup_exception_handlers

# ── Config ────────────────────────────────────────────────────────────────────
app_config = get_app_config()
LOG_LEVEL = logging.DEBUG if app_config.general_config.development_mode else logging.INFO
LOG_DIR = os.environ.get(
    "LOG_DIR",
    "/tmp/logs" if os.environ.get("VERCEL") else "logs",
)
os.makedirs(LOG_DIR, exist_ok=True)


# ── Logging ───────────────────────────────────────────────────────────────────
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


# ── Static cache headers ───────────────────────────────────────────────────────
class StaticCacheMiddleware(BaseHTTPMiddleware):
    """
    Long-lived cache headers for static assets served directly by FastAPI.
    In production, delegate static serving to nginx/CloudFront instead.

    UUID-named files (thumbnails, avatars) — immutable, 1-year cache.
    Named assets (CSS, JS bundles) — 1-hour cache with revalidation.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path

        if path.startswith(("/uploads/", "/static/")):
            if len(os.path.basename(path)) > 32:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
            response.headers["X-Content-Type-Options"] = "nosniff"

        return response


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s API...", app_config.general_config.site_name)

    # ── Upload directories ────────────────────────────────────────
    uploads_dir = os.path.abspath(
        app_config.hosting_config.content_delivery.filesystem_base_path
    )
    for subdir in ("", "courses/thumbnails", "courses/content", "courses/previews", "avatars"):
        os.makedirs(os.path.join(uploads_dir, subdir), exist_ok=True)

    # ── Database ──────────────────────────────────────────────────
    # create_tables() is idempotent — safe on every startup.
    # close_db() is called in shutdown to drain the connection pool.
    try:
        from app.db.database import create_tables
        create_tables()
        logger.info("Database tables verified.")
    except Exception as exc:
        logger.warning("Database setup issue: %s", exc)

    # ── Cache (Redis → in-memory LRU fallback) ────────────────────
    # Lifespan cannot use FastAPI Depends(), so we construct RedisService
    # directly here using the same env var that get_redis_service() reads.
    # Route handlers still get their own RedisService via get_redis_service()
    # — both point at the same Upstash instance; no double-connection cost
    # because RedisService uses a connection pool internally.
    try:
        from app.core.performance.cache_config import cache
        from app.services.redis_service import RedisService

        _redis_url = os.getenv("APP_REDIS_URL") or os.getenv("REDIS_URL")
        _redis_for_cache = RedisService(_redis_url) if _redis_url else None
        cache.init(_redis_for_cache)
    except Exception as exc:
        logger.warning("Cache init failed — falling back to in-memory LRU: %s", exc)

    # ── OAuth providers ───────────────────────────────────────────
    if not app_config.oauth_provider_config:
        logger.warning(
            "No OAuth providers enabled. "
            "Add APP_*_CLIENT_ID / APP_*_CLIENT_SECRET to .env to activate them."
        )
    else:
        logger.info("OAuth providers active: %s", list(app_config.oauth_provider_config.keys()))

    yield

    # ── Shutdown ──────────────────────────────────────────────────
    try:
        from app.db.database import close_db
        close_db()
    except Exception as exc:
        logger.warning("DB pool close error: %s", exc)

    try:
        from app.core.performance.cache_config import cache
        cache.clear()                   # flush in-memory LRU only; Redis persists
    except Exception:
        pass

    logger.info("Shutdown complete.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=app_config.general_config.site_name,
    description=app_config.general_config.site_description,
    version=app_config.general_config.api_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── Static file mounts ────────────────────────────────────────────────────────
# Mount before middleware so StaticCacheMiddleware can intercept the responses.
_uploads_dir = os.path.abspath(
    app_config.hosting_config.content_delivery.filesystem_base_path
)
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")
logger.info("Serving uploads from %s at /uploads", _uploads_dir)

_static_dir = Path("static")
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ── Middleware stack ──────────────────────────────────────────────────────────
# Starlette processes middleware in REVERSE registration order.
# Register innermost (closest to handler) first, outermost last.

# 1. CORS — innermost; every preflight must resolve before anything else runs
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

# 2. Gzip — compress the response body before ETag hashes it
app.add_middleware(GZipMiddleware, minimum_size=1000)

# 3. Static cache headers — injects Cache-Control on /uploads and /static
app.add_middleware(StaticCacheMiddleware)

# 4. ETag — adds ETag header; returns 304 if client's If-None-Match matches
from app.core.performance.middleware import ETagMiddleware
app.add_middleware(ETagMiddleware)

# 5. Response cache — serves whitelisted public GET paths from memory
#    Excluded: anything requiring auth, mutation, or user-specific data.
from app.core.performance.middleware import ResponseCacheMiddleware
app.add_middleware(
    ResponseCacheMiddleware,
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

# 6. Request coalescing — collapses identical concurrent GETs into one DB hit
#    Most effective on single-process deployments (cPanel / single Uvicorn worker).
from app.core.performance.middleware import RequestCoalescingMiddleware
app.add_middleware(RequestCoalescingMiddleware)

# 7. Timing — outermost; X-Response-Time covers the entire pipeline
from app.core.performance.middleware import TimingMiddleware
app.add_middleware(TimingMiddleware)


# ── Exception handlers ────────────────────────────────────────────────────────
setup_exception_handlers(app, app_config)


# ── Routers ───────────────────────────────────────────────────────────────────
from app.api.root_router import root_router, health_router, debug_router
app.include_router(root_router)       # GET /,  POST /deploy-webhook
app.include_router(health_router)     # GET /health, /health/deep, /health/ready, /health/metrics
app.include_router(debug_router)     # GET /debug, /debug/.., /debuug/..., /debug/metrics

from app.api.v1_router import v1_router
app.include_router(v1_router)


# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", app_config.hosting_config.port))
    host = "0.0.0.0" if os.getenv("DOCKER_CONTAINER") else "localhost"

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=app_config.general_config.development_mode,
        log_level="debug" if app_config.general_config.development_mode else "info",
        # Production: run multiple workers via gunicorn, not here:
        workers=4 if not app_config.general_config.development_mode else 1
    )


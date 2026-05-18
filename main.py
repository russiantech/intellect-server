import os
from pathlib import Path
import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_app_config
from app.core.exceptions import setup_exception_handlers

# ── Config ───────────────────────────────────────────────────────────────────
app_config = get_app_config()

LOG_LEVEL = logging.DEBUG if app_config.general_config.development_mode else logging.INFO
# LOG_DIR = os.path.abspath("logs")
# Use /tmp on Vercel, local logs/ for development
LOG_DIR = os.environ.get("LOG_DIR", "/tmp/logs" if os.environ.get("VERCEL") else "logs")

os.makedirs(LOG_DIR, exist_ok=True)


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)
    if logger.handlers:
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
    logger.addHandler(ch)
    logger.addHandler(fh)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)


setup_logging()
logger = logging.getLogger(__name__)


# ── Static file cache headers (production performance) ───────────────────────
class StaticCacheMiddleware(BaseHTTPMiddleware):
    """
    Add long-lived cache headers to static assets.
    UUID-named files (thumbnails, avatars) are immutable — cache for 1 year.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        
        # Only cache actual static/upload paths
        if path.startswith(("/uploads/", "/static/")):
            # Immutable content (UUID filenames) → 1 year
            if len(os.path.basename(path)) > 32:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                # Named assets (CSS, JS bundles) → 1 hour with revalidate
                response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
            
            # Security headers for all static responses
            response.headers["X-Content-Type-Options"] = "nosniff"
            
        return response


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {app_config.general_config.site_name} API...")
    
    # Ensure upload directories exist (absolute paths)
    uploads_dir = os.path.abspath(app_config.hosting_config.content_delivery.filesystem_base_path)
    os.makedirs(uploads_dir, exist_ok=True)
    
    # Subdirectories for different content types
    for subdir in ("courses/thumbnails", "courses/content", "courses/previews", "avatars"):
        os.makedirs(os.path.join(uploads_dir, subdir), exist_ok=True)
    
    try:
        from app.db.database import create_tables
        create_tables()
        logger.info("Database tables verified.")
    except Exception as e:
        logger.warning(f"Database setup issue: {e}")
    
    # check oauth config
    if not app_config.oauth_provider_config:
        logger.warning("No OAuth providers enabled — add APP_*_CLIENT_ID / APP_*_CLIENT_SECRET to .env")
    else:
        logger.info(f"OAuth providers active: {list(app_config.oauth_provider_config.keys())}")
    
    yield
    logger.info("Shutdown complete.")


# ── App init ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title=app_config.general_config.site_name,
    description=app_config.general_config.site_description,
    version=app_config.general_config.api_version,
    lifespan=lifespan,
    docs_url="/docs" if app_config.general_config.development_mode else None,
    redoc_url="/redoc" if app_config.general_config.development_mode else None,
)

# ── Static file serving ──────────────────────────────────────────────────────
#
# PROFESSIONAL NOTE:
#   In production, static files should be served by nginx, CloudFront, or 
#   Cloudflare — NOT by FastAPI. Uvicorn workers are for dynamic API traffic.
#   
#   However, for development and small deployments, FastAPI StaticFiles is fine.
#   The mounts below use ABSOLUTE paths to avoid cwd ambiguity.

# 1. User uploads (courses, avatars, content) — mounted at /uploads
_uploads_dir = os.path.abspath(app_config.hosting_config.content_delivery.filesystem_base_path)
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")
logger.info("Serving uploads from %s at /uploads", _uploads_dir)

# 2. Static assets (CSS, JS, logos) — mounted at /static
# Use absolute path; if /app/static exists, use it, else fallback to ./static
# _static_dir = "/app/static" if os.path.isdir("/app/static") else os.path.abspath("static")
# os.makedirs(_static_dir, exist_ok=True)
# app.mount("/static", StaticFiles(directory=_static_dir), name="static")
# logger.info("Serving static assets from %s at /static", _static_dir)


_static_dir = Path("static")
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# 3. Cache header middleware (after mounts so it wraps static responses)
app.add_middleware(StaticCacheMiddleware)

# ── CORS ─────────────────────────────────────────────────────────────────────
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=(
#         ["*"] if app_config.general_config.development_mode
#         else app_config.security_config.cors_allowed_origins
#     ),
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
# v2
# ── CORS ─────────────────────────────────────────────────────────────────────
_cors_origins = app_config.security_config.cors_allowed_origins

if isinstance(_cors_origins, str):
    _cors_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
elif not isinstance(_cors_origins, list):
    _cors_origins = ["http://localhost:5173"]

if app_config.general_config.development_mode and not _cors_origins:
    _cors_origins = ["*"]

logger.info("CORS allowed origins: %s", _cors_origins)
logger.info("App db uri %s", app_config.database_config.sql_connection_string)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)


# # ── Global exception handler ─────────────────────────────────────────────────
# @app.exception_handler(Exception)
# async def global_exception_handler(request: Request, exc: Exception):
#     error_id = str(uuid.uuid4())
#     logger.error(
#         f"[{error_id}] Unhandled exception on {request.method} {request.url.path}\n"
#         f"[{error_id}] {type(exc).__name__}: {exc}\n"
#         f"[{error_id}] Traceback:\n{traceback.format_exc()}"
#     )
#     return JSONResponse(
#         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#         content={
#             "success": False,
#             "message": "An unexpected error occurred. Please try again or contact support.",
#             "error_id": error_id,
#             "timestamp": datetime.now(timezone.utc).isoformat(),
#         },
#     )


# ── Routers ──────────────────────────────────────────────────────────────────
setup_exception_handlers(app, app_config)

from app.api.root import root_router
app.include_router(root_router)

from app.api.router import v1_router
app.include_router(v1_router)


# ── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", app_config.hosting_config.port))
    
    # PRODUCTION: bind to 0.0.0.0 so Docker/nginx can reach us
    # DEVELOPMENT: localhost is fine
    host = "0.0.0.0" if os.getenv("DOCKER_CONTAINER") else "localhost"
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=app_config.general_config.development_mode,
        log_level="debug" if app_config.general_config.development_mode else "info",
        # Production: run multiple workers via gunicorn, not here
        # workers=4 if not app_config.general_config.development_mode else 1,
    )


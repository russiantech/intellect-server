# """
# app/core/middleware.py — Production performance middleware.
# Add these to your FastAPI app in main.py.
# """

# import time
# import gzip
# import hashlib
# from typing import Callable

# from fastapi import Request, Response
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.middleware.gzip import GZipMiddleware
# from starlette.middleware.base import BaseHTTPMiddleware

# # ── 1. Response Cache Middleware ───────────────────────────────
# class ResponseCacheMiddleware(BaseHTTPMiddleware):
#     """Cache GET responses for configured paths.

#     Add to main.py:
#         app.add_middleware(ResponseCacheMiddleware, ttl=300, paths=["/api/v1/courses"])
#     """

#     def __init__(self, app, ttl: int = 300, paths: list = None, exclude_paths: list = None):
#         super().__init__(app)
#         self.ttl = ttl
#         self.paths = paths or ["/api/"]
#         self.exclude_paths = exclude_paths or ["/api/v1/auth", "/api/v1/enroll", "/api/v1/payments"]
#         self._cache = {}

#     async def dispatch(self, request: Request, call_next):
#         # Only cache safe methods
#         if request.method != "GET":
#             return await call_next(request)

#         path = request.url.path

#         # Check exclusions
#         if any(path.startswith(ex) for ex in self.exclude_paths):
#             return await call_next(request)

#         # Check inclusions
#         if not any(path.startswith(p) for p in self.paths):
#             return await call_next(request)

#         # Build cache key
#         cache_key = f"{request.method}:{path}:{request.query_params}"
#         cache_hash = hashlib.sha256(cache_key.encode()).hexdigest()

#         # Check cache
#         now = time.time()
#         if cache_hash in self._cache:
#             cached_response, expires = self._cache[cache_hash]
#             if now < expires:
#                 return Response(
#                     content=cached_response["body"],
#                     status_code=cached_response["status"],
#                     headers=cached_response["headers"],
#                 )

#         # Fetch and cache
#         response = await call_next(request)

#         # Only cache successful responses
#         if response.status_code == 200:
#             body = b""
#             async for chunk in response.body_iterator:
#                 body += chunk

#             self._cache[cache_hash] = {
#                 "body": body,
#                 "status": response.status_code,
#                 "headers": dict(response.headers),
#             }, now + self.ttl

#             return Response(content=body, status_code=response.status_code, headers=dict(response.headers))

#         return response

# # ── 2. Timing & Compression Middleware ─────────────────────────
# class TimingMiddleware(BaseHTTPMiddleware):
#     """Add X-Response-Time header for monitoring."""

#     async def dispatch(self, request: Request, call_next):
#         start = time.time()
#         response = await call_next(request)
#         duration = (time.time() - start) * 1000
#         response.headers["X-Response-Time"] = f"{duration:.2f}ms"

#         # Log slow requests
#         if duration > 1000:
#             from app.core.performance.cache_config import cache
#             import logging
#             logger = logging.getLogger("slow_request")
#             logger.warning(f"Slow request: {request.method} {request.url.path} took {duration:.0f}ms")

#         return response

# # ── 3. ETag & Conditional Response Middleware ────────────────
# class ETagMiddleware(BaseHTTPMiddleware):
#     """Add ETag headers for cache validation."""

#     async def dispatch(self, request: Request, call_next):
#         response = await call_next(request)

#         if response.status_code == 200 and "etag" not in response.headers:
#             body = b""
#             async for chunk in response.body_iterator:
#                 body += chunk

#             etag = hashlib.md5(body).hexdigest()
#             response.headers["ETag"] = f'"{etag}"'

#             # Check If-None-Match
#             if request.headers.get("if-none-match") == f'"{etag}"':
#                 return Response(status_code=304, headers=dict(response.headers))

#             return Response(content=body, status_code=response.status_code, headers=dict(response.headers))

#         return response

# # ── 4. Request Coalescing (Thundering Herd Prevention) ────────
# class RequestCoalescingMiddleware(BaseHTTPMiddleware):
#     """Collapse identical concurrent requests into one backend call.

#     Prevents cache stampede when cache expires and 100 users hit same endpoint.
#     """

#     def __init__(self, app):
#         super().__init__(app)
#         self._in_flight = {}  # key: asyncio.Future

#     async def dispatch(self, request: Request, call_next):
#         if request.method != "GET":
#             return await call_next(request)

#         key = f"{request.method}:{request.url.path}:{request.query_params}"

#         # Check if identical request is in flight
#         if key in self._in_flight:
#             return await self._in_flight[key]

#         # Create future for this request
#         future = asyncio.Future()
#         self._in_flight[key] = future

#         try:
#             response = await call_next(request)
#             future.set_result(response)
#             return response
#         except Exception as e:
#             future.set_exception(e)
#             raise
#         finally:
#             del self._in_flight[key]

# # ── FastAPI Setup Helper ─────────────────────────────────────
# def add_performance_middleware(app):
#     """Add all performance middleware in correct order."""

#     # 1. CORS first (before any processing)
#     from app.core.config import get_app_config
#     config = get_app_config()

#     app.add_middleware(
#         CORSMiddleware,
#         allow_origins=config.security_config.cors_allowed_origins,
#         allow_credentials=True,
#         allow_methods=["*"],
#         allow_headers=["*"],
#     )

#     # 2. Gzip compression
#     app.add_middleware(GZipMiddleware, minimum_size=1000)

#     # 3. ETag for cache validation
#     app.add_middleware(ETagMiddleware)

#     # 4. Response cache for API endpoints
#     app.add_middleware(
#         ResponseCacheMiddleware,
#         ttl=300,
#         paths=["/api/v1/courses", "/api/v1/categories", "/api/v1/content"],
#         exclude_paths=["/api/v1/auth", "/api/v1/enroll", "/api/v1/payments", "/api/v1/progress"],
#     )

#     # 5. Request coalescing (prevents stampede)
#     app.add_middleware(RequestCoalescingMiddleware)

#     # 6. Timing last (measures total pipeline)
#     app.add_middleware(TimingMiddleware)


# v2
# app/core/performance/middleware.py
#
# Production middleware stack for Intellect LMS.
#
# Register everything in one call from main.py:
#
#   from app.core.middleware import add_performance_middleware
#   add_performance_middleware(app)
#
# Middleware executes in REVERSE registration order (last added = outermost).
# The helper registers them so the final execution order is:
#
#   TimingMiddleware          ← measures total pipeline time
#   RequestCoalescingMiddleware
#   ResponseCacheMiddleware
#   ETagMiddleware
#   GZipMiddleware
#   CORSMiddleware            ← innermost (closest to route handler)

import hashlib
import logging
import time
from typing import List, Optional

from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ── 1. Timing ─────────────────────────────────────────────────────

class TimingMiddleware(BaseHTTPMiddleware):
    """
    Adds an X-Response-Time header (milliseconds) to every response.
    Logs a warning for any request that exceeds SLOW_REQUEST_MS.
    """

    SLOW_REQUEST_MS: float = 1000.0

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = (time.perf_counter() - start) * 1000
        response.headers["X-Response-Time"] = f"{elapsed:.2f}ms"

        if elapsed > self.SLOW_REQUEST_MS:
            logger.warning(
                "Slow request: %s %s — %.0fms",
                request.method,
                request.url.path,
                elapsed,
            )

        return response


# ── 2. ETag ───────────────────────────────────────────────────────

class ETagMiddleware(BaseHTTPMiddleware):
    """
    Computes an ETag for every 200 GET response and injects it into
    the response headers. Returns 304 Not Modified when the client's
    If-None-Match header matches, saving bandwidth on repeat requests.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if response.status_code != 200 or "etag" in response.headers:
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        etag = f'"{hashlib.md5(body).hexdigest()}"'
        response.headers["ETag"] = etag

        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=dict(response.headers))

        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
        )


# ── 3. Response Cache ─────────────────────────────────────────────

class ResponseCacheMiddleware(BaseHTTPMiddleware):
    """
    In-process cache for successful GET responses on whitelisted paths.
    Cache entries expire after `ttl` seconds.

    Excluded automatically:
      - Non-GET methods
      - Any path in `exclude_paths`
      - Any path not under `paths`

    Not a substitute for a proper CDN or Redis response cache — intended
    for short-lived hot-path protection on cPanel / single-process deploys.
    """

    def __init__(
        self,
        app,
        ttl: int = 300,
        paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.ttl = ttl
        self.paths = paths or ["/api/"]
        self.exclude_paths = exclude_paths or [
            "/api/v1/auth",
            "/api/v1/enroll",
            "/api/v1/payments",
            "/api/v1/progress",
        ]
        # {cache_hash: (entry_dict, expires_at)}
        self._cache: dict = {}

    def _cache_key(self, request: Request) -> str:
        raw = f"{request.method}:{request.url.path}:{request.query_params}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def dispatch(self, request: Request, call_next):
        if request.method != "GET":
            return await call_next(request)

        path = request.url.path

        if any(path.startswith(ex) for ex in self.exclude_paths):
            return await call_next(request)

        if not any(path.startswith(p) for p in self.paths):
            return await call_next(request)

        key = self._cache_key(request)
        now = time.monotonic()

        if key in self._cache:
            entry, expires = self._cache[key]
            if now < expires:
                return Response(
                    content=entry["body"],
                    status_code=entry["status"],
                    headers=entry["headers"],
                )
            else:
                del self._cache[key]

        response = await call_next(request)

        if response.status_code == 200:
            body = b"".join([chunk async for chunk in response.body_iterator])
            self._cache[key] = (
                {
                    "body": body,
                    "status": response.status_code,
                    "headers": dict(response.headers),
                },
                now + self.ttl,
            )
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
            )

        return response


# ── 4. Request Coalescing ─────────────────────────────────────────

class RequestCoalescingMiddleware(BaseHTTPMiddleware):
    """
    Collapses identical concurrent GET requests into a single backend call.
    Subsequent identical requests in-flight wait for the first to complete
    and share its response, preventing thundering-herd on cache expiry.

    Note: only effective on a single-process server (Uvicorn with 1 worker).
    Multi-worker deployments should use Redis-backed coalescing instead.
    """

    def __init__(self, app):
        super().__init__(app)
        self._in_flight: dict = {}      # key → asyncio.Future

    async def dispatch(self, request: Request, call_next):
        import asyncio

        if request.method != "GET":
            return await call_next(request)

        key = f"{request.url.path}:{request.query_params}"

        if key in self._in_flight:
            return await self._in_flight[key]

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._in_flight[key] = future

        try:
            response = await call_next(request)
            future.set_result(response)
            return response
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            self._in_flight.pop(key, None)


# ── Registration helper ───────────────────────────────────────────

def add_performance_middleware(app) -> None:
    """
    Register all middleware onto a FastAPI app instance.

    Call this before any router is included and before starting the server.
    Starlette processes middleware in reverse-addition order, so the order
    below produces: CORS → Gzip → ETag → ResponseCache → Coalescing → Timing.
    """
    from app.core.config import get_app_config

    config = get_app_config()

    # 6. CORS — innermost: evaluated last, closest to the route handler
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.security_config.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 5. Gzip compression (min 1 KB to avoid overhead on tiny responses)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 4. ETag — attach after gzip so the hash reflects the compressed body
    app.add_middleware(ETagMiddleware)

    # 3. Response cache — only caches public read endpoints
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

    # 2. Request coalescing — prevents thundering herd on cache misses
    app.add_middleware(RequestCoalescingMiddleware)

    # 1. Timing — outermost: measures the entire middleware + handler pipeline
    app.add_middleware(TimingMiddleware)

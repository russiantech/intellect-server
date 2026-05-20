"""
app/core/performance/middleware.py  v3 — PURE ASGI
===================================================
Eliminates BaseHTTPMiddleware to fix:
- RuntimeError: Response content shorter than Content-Length
- RuntimeError: anext(): asynchronous generator is already running
"""

import hashlib
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TIMING MIDDLEWARE (Pure ASGI)
# ═══════════════════════════════════════════════════════════════════════════════

class TimingMiddleware:
    """Adds X-Response-Time header. Logs slow requests."""
    
    SLOW_MS: float = 1000.0
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        start = time.perf_counter()
        method = scope.get("method", "")
        path = scope.get("path", "")
        
        async def wrapped_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                elapsed = (time.perf_counter() - start) * 1000
                headers = list(message.get("headers", []))
                headers.append([b"x-response-time", f"{elapsed:.2f}ms".encode()])
                message["headers"] = headers
                
                if elapsed > self.SLOW_MS:
                    logger.warning("Slow request: %s %s — %.0fms", method, path, elapsed)
            await send(message)
        
        await self.app(scope, receive, wrapped_send)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RESPONSE CACHE MIDDLEWARE (Pure ASGI)
# ═══════════════════════════════════════════════════════════════════════════════

class ResponseCacheMiddleware:
    """
    In-process cache for GET 200 responses.
    Pure ASGI — collects body via send() interception, never touches body_iterator.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        ttl: int = 300,
        paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
    ):
        self.app = app
        self.ttl = ttl
        self.paths = paths or ["/api/"]
        self.exclude_paths = exclude_paths or [
            "/api/v1/auth",
            "/api/v1/enroll",
            "/api/v1/payments",
            "/api/v1/progress",
        ]
        self._cache: Dict[str, Tuple[bytes, int, List, float]] = {}
    
    def _should_cache(self, scope: Scope) -> bool:
        if scope.get("method") != "GET":
            return False
        path = scope.get("path", "")
        if any(path.startswith(ex) for ex in self.exclude_paths):
            return False
        if not any(path.startswith(p) for p in self.paths):
            return False
        return True
    
    def _cache_key(self, scope: Scope) -> str:
        path = scope.get("path", "")
        query = scope.get("query_string", b"")
        if isinstance(query, bytes):
            query = query.decode("utf-8")
        return hashlib.sha256(f"GET:{path}:{query}".encode()).hexdigest()
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._should_cache(scope):
            await self.app(scope, receive, send)
            return
        
        key = self._cache_key(scope)
        now = time.monotonic()
        
        # Cache hit
        if key in self._cache:
            body, status, headers, expires = self._cache[key]
            if now < expires:
                headers = [list(h) for h in headers]
                headers.append([b"x-cache", b"HIT"])
                await send({"type": "http.response.start", "status": status, "headers": headers})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            del self._cache[key]
        
        # Cache miss — collect response
        status_code = 200
        response_headers: List = []
        body_chunks: List[bytes] = []
        
        async def caching_send(message: Message) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    full_body = b"".join(body_chunks)
                    if status_code == 200:
                        store_headers = [list(h) for h in response_headers]
                        store_headers.append([b"x-cache", b"MISS"])
                        self._cache[key] = (full_body, status_code, store_headers, now + self.ttl)
                    await send({"type": "http.response.start", "status": status_code, "headers": response_headers})
                    await send({"type": "http.response.body", "body": full_body, "more_body": False})
        
        await self.app(scope, receive, caching_send)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ETAG MIDDLEWARE (Pure ASGI)
# ═══════════════════════════════════════════════════════════════════════════════

class ETagMiddleware:
    """Computes ETag for 200 GET responses. Returns 304 on match."""
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        
        # Check If-None-Match header
        headers = scope.get("headers", [])
        if_none_match = b""
        for name, value in headers:
            if name.lower() == b"if-none-match":
                if_none_match = value.decode("utf-8") if isinstance(value, bytes) else value
                break
        
        status_code = 200
        response_headers: List = []
        body_chunks: List[bytes] = []
        
        async def etag_send(message: Message) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    full_body = b"".join(body_chunks)
                    
                    if status_code == 200 and full_body:
                        etag = f'"{hashlib.md5(full_body).hexdigest()}"'
                        response_headers.append([b"etag", etag.encode()])
                        
                        if if_none_match == etag:
                            # 304 Not Modified — no body
                            await send({"type": "http.response.start", "status": 304, "headers": response_headers})
                            await send({"type": "http.response.body", "body": b"", "more_body": False})
                            return
                    
                    await send({"type": "http.response.start", "status": status_code, "headers": response_headers})
                    await send({"type": "http.response.body", "body": full_body, "more_body": False})
        
        await self.app(scope, receive, etag_send)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. REQUEST COALESCING MIDDLEWARE (Pure ASGI)
# ═══════════════════════════════════════════════════════════════════════════════

class RequestCoalescingMiddleware:
    """
    Collapses identical concurrent GET requests.
    Uses asyncio.Event instead of BaseHTTPMiddleware + Future.
    """
    
    def __init__(self, app: ASGIApp):
        self.app = app
        self._in_flight: Dict[str, Tuple[bytes, int, List]] = {}
        self._events: Dict[str, any] = {}
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        
        import asyncio
        
        path = scope.get("path", "")
        query = scope.get("query_string", b"")
        if isinstance(query, bytes):
            query = query.decode("utf-8")
        key = f"{path}:{query}"
        
        # Wait for in-flight request
        if key in self._in_flight:
            event = self._events[key]
            await event.wait()
            body, status, headers = self._in_flight[key]
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return
        
        # First request — set up coalescing
        event = asyncio.Event()
        self._events[key] = event
        
        status_code = 200
        response_headers: List = []
        body_chunks: List[bytes] = []
        
        async def collecting_send(message: Message) -> None:
            nonlocal status_code, response_headers
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
                response_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    full_body = b"".join(body_chunks)
                    self._in_flight[key] = (full_body, status_code, response_headers)
                    event.set()
                    await send({"type": "http.response.start", "status": status_code, "headers": response_headers})
                    await send({"type": "http.response.body", "body": full_body, "more_body": False})
        
        try:
            await self.app(scope, receive, collecting_send)
        except Exception:
            event.set()
            raise
        finally:
            self._in_flight.pop(key, None)
            self._events.pop(key, None)


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC CACHE MIDDLEWARE (Pure ASGI)
# ═══════════════════════════════════════════════════════════════════════════════

class StaticCacheMiddleware:
    """Cache-Control headers for static assets. Pure ASGI."""
    
    def __init__(self, app: ASGIApp):
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        
        path = scope.get("path", "")
        
        async def static_send(message: Message) -> None:
            if message["type"] == "http.response.start" and path.startswith(("/uploads/", "/static/")):
                headers = list(message.get("headers", []))
                basename = __import__("os").path.basename(path)
                if len(basename) > 32:
                    headers.append([b"cache-control", b"public, max-age=31536000, immutable"])
                else:
                    headers.append([b"cache-control", b"public, max-age=3600, must-revalidate"])
                headers.append([b"x-content-type-options", b"nosniff"])
                message["headers"] = headers
            await send(message)
        
        await self.app(scope, receive, static_send)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def add_performance_middleware(app) -> ASGIApp:
    """
    Build pure ASGI middleware stack.
    
    Returns the wrapped ASGI app. Use this in main.py:
    
        from app.core.performance.middleware import add_performance_middleware
        app = add_performance_middleware(app)
    
    Order (outermost → innermost):
    Timing → Coalescing → Cache → ETag → StaticCache → (app routes)
    """
    
    asgi_app = app
    
    # Wrap from innermost to outermost
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
    
    return asgi_app


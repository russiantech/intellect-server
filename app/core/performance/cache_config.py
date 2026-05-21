# """
# app/core/cache_config.py — Centralized caching configuration.
# Import this in your main.py and routers.
# """

# import os
# import hashlib
# import json
# from functools import wraps
# from typing import Optional, Any, Callable
# import asyncio

# # ── Backend Selection ────────────────────────────────────────────
# # Priority: Redis > In-Memory (LRU) > None
# # Set APP_CACHE_BACKEND=redis and APP_REDIS_URL in your .env

# CACHE_BACKEND = os.getenv("APP_CACHE_BACKEND", "memory").lower()
# REDIS_URL = os.getenv("APP_REDIS_CONNECTION_STRING", "redis://localhost:6379/0")
# CACHE_TTL_DEFAULT = int(os.getenv("APP_CACHE_TTL", "300"))  # 5 minutes default
# CACHE_MAXSIZE = int(os.getenv("APP_CACHE_MAXSIZE", "10000"))  # LRU max items

# # ── Redis Backend ──────────────────────────────────────────────
# _redis_client = None

# def get_redis():
#     global _redis_client
#     if _redis_client is not None:
#         return _redis_client

#     if CACHE_BACKEND != "redis":
#         return None

#     try:
#         import redis.asyncio as aioredis
#         _redis_client = aioredis.from_url(
#             REDIS_URL,
#             encoding="utf-8",
#             decode_responses=True,
#             max_connections=50,
#             socket_keepalive=True,
#             socket_connect_timeout=5,
#             socket_timeout=5,
#             retry_on_timeout=True,
#         )
#         return _redis_client
#     except ImportError:
#         print("WARNING: redis not installed. Install: pip install redis")
#         return None
#     except Exception as e:
#         print(f"WARNING: Redis connection failed: {e}. Falling back to memory.")
#         return None

# # ── In-Memory LRU Cache ────────────────────────────────────────
# class LRUCache:
#     """Thread-safe/async-safe LRU cache with TTL."""

#     def __init__(self, maxsize: int = 10000):
#         self.maxsize = maxsize
#         self._cache = {}  # key: (value, expires_at)
#         self._lock = asyncio.Lock()

#     async def get(self, key: str) -> Optional[Any]:
#         async with self._lock:
#             if key not in self._cache:
#                 return None
#             value, expires = self._cache[key]
#             if expires and asyncio.get_event_loop().time() > expires:
#                 del self._cache[key]
#                 return None
#             # Move to end (LRU: most recently used)
#             self._cache[key] = self._cache.pop(key)
#             return value

#     async def set(self, key: str, value: Any, ttl: int = None):
#         async with self._lock:
#             if len(self._cache) >= self.maxsize and key not in self._cache:
#                 # Evict oldest
#                 self._cache.pop(next(iter(self._cache)))
#             expires = asyncio.get_event_loop().time() + ttl if ttl else None
#             self._cache[key] = (value, expires)

#     async def delete(self, key: str):
#         async with self._lock:
#             self._cache.pop(key, None)

#     async def delete_pattern(self, pattern: str):
#         """Delete keys matching pattern (simple contains match for memory)."""
#         async with self._lock:
#             keys = [k for k in self._cache if pattern in k]
#             for k in keys:
#                 del self._cache[k]
#             return len(keys)

#     async def clear(self):
#         async with self._lock:
#             self._cache.clear()

# # ── Cache Manager ──────────────────────────────────────────────
# class CacheManager:
#     """Unified cache interface. Auto-selects Redis or LRU."""

#     def __init__(self):
#         self.backend = None
#         self.lru = LRUCache(maxsize=CACHE_MAXSIZE)
#         self._initialized = False

#     async def init(self):
#         if self._initialized:
#             return

#         if CACHE_BACKEND == "redis":
#             redis = get_redis()
#             if redis:
#                 try:
#                     await redis.ping()
#                     self.backend = redis
#                     print("✅ Cache: Redis connected")
#                 except Exception:
#                     print("⚠️ Cache: Redis ping failed, using memory")
#                     self.backend = None
#             else:
#                 print("⚠️ Cache: Redis unavailable, using memory")

#         if self.backend is None:
#             print(f"✅ Cache: In-memory LRU (maxsize={CACHE_MAXSIZE})")

#         self._initialized = True

#     def _make_key(self, prefix: str, *args, **kwargs) -> str:
#         """Create deterministic cache key."""
#         data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
#         hash_part = hashlib.sha256(data.encode()).hexdigest()[:16]
#         return f"{prefix}:{hash_part}"

#     async def get(self, key: str) -> Optional[Any]:
#         if self.backend:
#             try:
#                 data = await self.backend.get(key)
#                 if data:
#                     return json.loads(data)
#             except Exception:
#                 pass
#         return await self.lru.get(key)

#     async def set(self, key: str, value: Any, ttl: int = None):
#         ttl = ttl or CACHE_TTL_DEFAULT
#         serialized = json.dumps(value, default=str)

#         if self.backend:
#             try:
#                 await self.backend.setex(key, ttl, serialized)
#                 return
#             except Exception:
#                 pass

#         await self.lru.set(key, json.loads(serialized), ttl)

#     async def delete(self, key: str):
#         if self.backend:
#             try:
#                 await self.backend.delete(key)
#             except Exception:
#                 pass
#         await self.lru.delete(key)

#     async def invalidate(self, pattern: str):
#         """Invalidate cache by key pattern."""
#         if self.backend:
#             try:
#                 # Redis SCAN + DELETE
#                 cursor = 0
#                 while True:
#                     cursor, keys = await self.backend.scan(cursor, match=f"*{pattern}*", count=100)
#                     if keys:
#                         await self.backend.delete(*keys)
#                     if cursor == 0:
#                         break
#             except Exception:
#                 pass

#         await self.lru.delete_pattern(pattern)

#     async def get_or_set(self, key: str, factory: Callable, ttl: int = None) -> Any:
#         """Get from cache or compute and store."""
#         cached = await self.get(key)
#         if cached is not None:
#             return cached

#         value = await factory() if asyncio.iscoroutinefunction(factory) else factory()
#         await self.set(key, value, ttl)
#         return value

# # ── Global Instance ────────────────────────────────────────────
# cache = CacheManager()

# # ── Decorator ──────────────────────────────────────────────────
# def cached(prefix: str, ttl: int = None, key_builder: Callable = None):
#     """Decorator to cache function results.

#     Usage:
#         @cached("courses", ttl=600)
#         async def get_course(course_id: int):
#             return await db.fetch_one(...)
#     """
#     def decorator(func):
#         @wraps(func)
#         async def async_wrapper(*args, **kwargs):
#             await cache.init()
#             if key_builder:
#                 cache_key = key_builder(*args, **kwargs)
#             else:
#                 cache_key = cache._make_key(prefix, *args, **kwargs)

#             cached_val = await cache.get(cache_key)
#             if cached_val is not None:
#                 return cached_val

#             result = await func(*args, **kwargs)
#             await cache.set(cache_key, result, ttl)
#             return result

#         @wraps(func)
#         def sync_wrapper(*args, **kwargs):
#             # For sync functions, run in event loop
#             try:
#                 loop = asyncio.get_event_loop()
#             except RuntimeError:
#                 loop = asyncio.new_event_loop()
#                 asyncio.set_event_loop(loop)
#             return loop.run_until_complete(async_wrapper(*args, **kwargs))

#         return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
#     return decorator


# def invalidate_cache(pattern: str):
#     """Invalidate cache entries matching pattern.

#     Usage:
#         @invalidate_cache("courses")
#         async def update_course(course_id: int, data: dict):
#             return await db.update(...)
#     """
#     def decorator(func):
#         @wraps(func)
#         async def async_wrapper(*args, **kwargs):
#             await cache.init()
#             result = await func(*args, **kwargs)
#             await cache.invalidate(pattern)
#             return result

#         @wraps(func)
#         def sync_wrapper(*args, **kwargs):
#             try:
#                 loop = asyncio.get_event_loop()
#             except RuntimeError:
#                 loop = asyncio.new_event_loop()
#                 asyncio.set_event_loop(loop)
#             return loop.run_until_complete(async_wrapper(*args, **kwargs))

#         return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
#     return decorator



# v2
# app/core/cache_config.py
#
# Unified sync cache layer for Intellect LMS.
#
# Backend priority:
#   APP_CACHE_BACKEND=redis  →  delegates to your existing RedisService
#   APP_CACHE_BACKEND=memory →  thread-safe in-process LRU (default)
#
# Initialise once at startup:
#
#   from app.core.cache_config import cache
#   from app.api.deps.storage import get_redis_service
#
#   @asynccontextmanager
#   async def lifespan(app):
#       cache.init(get_redis_service())   # pass None to force memory mode
#       yield
#       cache.clear()                     # optional — flushes LRU on shutdown

import hashlib
import json
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

CACHE_BACKEND = os.getenv("APP_CACHE_BACKEND", "memory").lower()
CACHE_TTL_DEFAULT = int(os.getenv("APP_CACHE_TTL", "600"))       # 10 minutes
CACHE_MAXSIZE = int(os.getenv("APP_CACHE_MAXSIZE", "20000"))


# ── In-Memory LRU Fallback ────────────────────────────────────────

class LRUCache:
    """
    Thread-safe in-memory LRU cache with per-entry TTL.
    Used when Redis is unavailable or not configured.
    """

    def __init__(self, maxsize: int = 10000):
        self.maxsize = maxsize
        self._cache: dict = {}          # key: (value, expires_at | None)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            value, expires = self._cache[key]
            if expires and time.monotonic() > expires:
                del self._cache[key]
                return None
            # Refresh position (most-recently-used moves to end)
            self._cache[key] = self._cache.pop(key)
            return value

    def set(self, key: str, value: Any, ttl: int = None):
        with self._lock:
            # Evict oldest entry when at capacity
            if len(self._cache) >= self.maxsize and key not in self._cache:
                self._cache.pop(next(iter(self._cache)))
            expires = (time.monotonic() + ttl) if ttl else None
            self._cache[key] = (value, expires)

    def delete(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys whose name contains `pattern`. Returns count deleted."""
        with self._lock:
            keys = [k for k in self._cache if pattern in k]
            for k in keys:
                del self._cache[k]
            return len(keys)

    def clear(self):
        with self._lock:
            self._cache.clear()


# ── Cache Manager ─────────────────────────────────────────────────

class CacheManager:
    """
    Unified sync cache interface for Intellect LMS.

    Wraps your existing RedisService as the primary backend.
    Falls back to an in-process LRU cache if Redis is absent or unreachable.
    All methods are synchronous — consistent with the sync SQLAlchemy stack.
    """

    def __init__(self):
        self._redis = None              # RedisService instance, if available
        self._lru = LRUCache(maxsize=CACHE_MAXSIZE)
        self._initialized = False

    def init(self, redis_service=None):
        """
        Initialise the cache backend. Call once in your app lifespan.

        Args:
            redis_service: An initialised RedisService instance, or None.
        """
        if self._initialized:
            return

        if CACHE_BACKEND == "redis" and redis_service is not None:
            if redis_service.ping():
                self._redis = redis_service
                logger.info("Cache backend: Redis.")
            else:
                logger.warning("Cache: Redis ping failed — using in-memory LRU.")
        else:
            logger.info("Cache backend: in-memory LRU (maxsize=%d).", CACHE_MAXSIZE)

        self._initialized = True

    # ── Key builder ───────────────────────────────────────────────

    @staticmethod
    def make_key(prefix: str, *args, **kwargs) -> str:
        """Build a deterministic, collision-resistant cache key."""
        raw = json.dumps({"a": args, "k": kwargs}, sort_keys=True, default=str)
        suffix = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"{prefix}:{suffix}"

    # ── Core operations ───────────────────────────────────────────

    def get(self, key: str) -> Optional[Any]:
        if self._redis:
            return self._redis.get(key, as_json=True)
        return self._lru.get(key)

    def set(self, key: str, value: Any, ttl: int = None):
        ttl = ttl or CACHE_TTL_DEFAULT
        if self._redis:
            self._redis.set(key, value, expiry=ttl)
        else:
            self._lru.set(key, value, ttl=ttl)

    def delete(self, key: str):
        if self._redis:
            self._redis.delete(key)
        self._lru.delete(key)

    def clear(self):
        """Flush the LRU cache. Does not flush Redis (use invalidate() for that)."""
        self._lru.clear()

    # ── Pattern invalidation ──────────────────────────────────────

    def invalidate(self, pattern: str):
        """
        Delete all cached keys whose name contains `pattern`.

        Redis: uses SCAN + bulk DELETE (non-blocking, cursor-based).
        LRU:   substring match on the in-process dict.
        """
        if self._redis:
            try:
                client = self._redis.get_client()
                cursor, deleted = 0, 0
                while True:
                    cursor, keys = client.scan(cursor, match=f"*{pattern}*", count=100)
                    if keys:
                        client.delete(*keys)
                        deleted += len(keys)
                    if cursor == 0:
                        break
                if deleted:
                    logger.debug("Cache: invalidated %d key(s) matching '%s'.", deleted, pattern)
            except Exception as exc:
                logger.error("Cache invalidate error: %s", exc)

        self._lru.delete_pattern(pattern)

    # ── get-or-set helper ─────────────────────────────────────────

    def get_or_set(self, key: str, factory: Callable, ttl: int = None) -> Any:
        """
        Return the cached value for `key`, or compute it via `factory()`,
        cache the result, and return it.

        Args:
            key:     Cache key.
            factory: Zero-argument callable that produces the value.
            ttl:     TTL in seconds (uses CACHE_TTL_DEFAULT if omitted).
        """
        hit = self.get(key)
        if hit is not None:
            return hit
        value = factory()
        self.set(key, value, ttl)
        return value


# ── Global instance ───────────────────────────────────────────────

cache = CacheManager()


# ── Decorators ────────────────────────────────────────────────────

def cached(prefix: str, ttl: int = None, key_builder: Callable = None):
    """
    Cache the return value of a sync function in Intellect's cache layer.

    Args:
        prefix:      Namespace prefix for the cache key (e.g. "courses").
        ttl:         TTL in seconds. Falls back to CACHE_TTL_DEFAULT.
        key_builder: Optional callable((*args, **kwargs) → str) for custom keys.

    Usage:
        @cached("courses", ttl=600)
        def list_published_courses(db: Session) -> list:
            return db.query(Course).filter(Course.is_active == True).all()
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (
                key_builder(*args, **kwargs)
                if key_builder
                else cache.make_key(prefix, *args, **kwargs)
            )
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = func(*args, **kwargs)
            cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator


def invalidate_cache(pattern: str):
    """
    Invalidate all cache entries matching `pattern` after the decorated
    function returns (even if it returns an error value — not on exception).

    Usage:
        @invalidate_cache("courses")
        def update_course(course_id: int, payload: dict, db: Session):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            cache.invalidate(pattern)
            return result
        return wrapper
    return decorator


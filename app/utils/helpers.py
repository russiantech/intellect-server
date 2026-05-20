import secrets
import string
import json as _json
from datetime import datetime, timezone
from typing import Any
from fastapi import Request
from sqlalchemy import Enum
from app.core.performance.cache_config import cache

def generate_secure_code(length: int = 6) -> str:
    """Generate secure verification code (alphanumeric uppercase)"""
    characters = string.ascii_uppercase + string.digits
    # Remove ambiguous characters
    characters = characters.replace('0', '').replace('O', '').replace('1', '').replace('I', '')
    return ''.join(secrets.choice(characters) for _ in range(length))


def get_client_ip(request: Request) -> str:
    """Get client IP address with proxy support"""
    # Check X-Forwarded-For header first (for proxies/load balancers)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the first IP in the chain
        return forwarded.split(",")[0].strip()
    
    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fallback to direct client host
    return request.client.host if request.client else "unknown"

# ── Cache helpers ─────────────────────────────────────────────────────────────

# def _to_cacheable(data: dict) -> dict:
#     """
#     Convert a response dict to a JSON-safe form before storing in cache.

#     FastAPI serialises datetime/enum objects automatically when returning
#     from a route, but json.dumps (used by RedisService) does not.
#     Round-tripping through json with default=str converts all non-primitive
#     types to strings, making the dict safe for both the Redis and LRU backends.
#     """
#     return _json.loads(_json.dumps(data, default=str))


def _to_cacheable(data):
    
    """Fast-path for already-serializable objects."""
    if isinstance(data, dict) and all(isinstance(v, (str, int, float, bool, list, dict, type(None))) for v in data.values()):
        return data
    
    """
        Convert a response dict to a JSON-safe form before storing in cache.

        FastAPI serialises datetime/enum objects automatically when returning
        from a route, but json.dumps (used by RedisService) does not.
        Round-tripping through json with default=str converts all non-primitive
        types to strings, making the dict safe for both the Redis and LRU backends.
        """
    return _json.loads(_json.dumps(data, default=str))
    
# In app/utils/helpers.py — ensure this is sync
# def _to_cacheable(obj: Any) -> Any:
#     """
#     Convert SQLAlchemy models / datetimes / enums to plain JSON-serializable dicts.
#     Must be fully synchronous — no await inside.
#     """
#     if isinstance(obj, datetime):
#         return obj.isoformat()
#     if isinstance(obj, Enum):
#         return obj.value
#     if isinstance(obj, list):
#         return [_to_cacheable(i) for i in obj]
#     if isinstance(obj, dict):
#         return {k: _to_cacheable(v) for k, v in obj.items()}
#     return obj

def _invalidate_course_caches(course_id: int, slug: str = None) -> None:
    """
    Invalidate all cache entries that are affected when a course changes.

    Deletes:
      - courses:detail:{course_id}        exact key by ID
      - courses:detail:{slug}             exact key by slug (if slug known)
      - all keys matching "courses:list"  pattern — covers every paginated listing
    """
    cache.delete(f"courses:detail:{course_id}")
    if slug:
        cache.delete(f"courses:detail:{slug}")
    cache.invalidate("courses:list")


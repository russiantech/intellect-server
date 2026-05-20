"""
app/core/performance/__init__.py — Performance utilities.
"""

from .cache_config import cache, cached, invalidate_cache
from .db_pool import get_db_session, init_db, close_db, get_engine
# from .query_optimizer import QueryOptimizer, BulkInserter
from .query_optimizer import BulkInserter

__all__ = [
    "cache",
    "cached",
    "invalidate_cache",
    "get_db_session",
    "init_db",
    "close_db",
    "get_engine",
    # "QueryOptimizer",
    "BulkInserter",
]

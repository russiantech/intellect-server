# """
# app/core/query_optimizer.py — SQLAlchemy query optimization helpers.
# Use these in your repository/CRUD layers.
# """

# from typing import List, Optional, TypeVar, Generic
# from sqlalchemy import select, func
# from sqlalchemy.orm import joinedload, selectinload
# from sqlalchemy.ext.asyncio import AsyncSession

# T = TypeVar("T")

# class QueryOptimizer:
#     """Optimized query patterns for e-learning platform."""

#     @staticmethod
#     def eager_load_courses(query):
#         """Eager load all course relationships in one query."""
#         return query.options(
#             joinedload("instructor"),
#             joinedload("category"),
#             selectinload("lessons"),
#             selectinload("enrollments"),
#         )

#     @staticmethod
#     def eager_load_user_progress(query):
#         """Eager load user progress with course data."""
#         return query.options(
#             joinedload("user"),
#             joinedload("course"),
#             selectinload("course.lessons"),
#         )

#     @staticmethod
#     async def paginated(
#         session: AsyncSession,
#         query,
#         page: int = 1,
#         per_page: int = 20,
#     ) -> dict:
#         """Execute paginated query with total count.

#         Returns: {"items": [...], "total": N, "page": N, "pages": N}
#         """
#         # Get total count (optimized subquery)
#         count_query = select(func.count()).select_from(query.subquery())
#         total = await session.scalar(count_query)

#         # Execute paginated
#         offset = (page - 1) * per_page
#         result = await session.execute(query.offset(offset).limit(per_page))
#         items = result.scalars().all()

#         return {
#             "items": items,
#             "total": total,
#             "page": page,
#             "pages": (total + per_page - 1) // per_page,
#         }

#     @staticmethod
#     def apply_filters(query, model, filters: dict):
#         """Apply common filters dynamically."""
#         for key, value in filters.items():
#             if hasattr(model, key) and value is not None:
#                 column = getattr(model, key)
#                 if isinstance(value, list):
#                     query = query.where(column.in_(value))
#                 elif isinstance(value, str) and "%" in value:
#                     query = query.where(column.like(value))
#                 else:
#                     query = query.where(column == value)
#         return query

# # ── Bulk Operations ──────────────────────────────────────────────
# class BulkInserter:
#     """High-performance bulk inserts for seeding/analytics."""

#     def __init__(self, session: AsyncSession, batch_size: int = 1000):
#         self.session = session
#         self.batch_size = batch_size
#         self._buffer = []

#     async def add(self, obj):
#         self._buffer.append(obj)
#         if len(self._buffer) >= self.batch_size:
#             await self.flush()

#     async def flush(self):
#         if not self._buffer:
#             return
#         self.session.add_all(self._buffer)
#         await self.session.commit()
#         self._buffer.clear()

#     async def __aenter__(self):
#         return self

#     async def __aexit__(self, exc_type, exc, tb):
#         await self.flush()



# v2
# app/core/performance/query_optimizer.py
#
# Sync SQLAlchemy query helpers for Intellect LMS.
# Use these in route handlers or service/repository layers.
#
# All helpers accept and return plain sqlalchemy.orm.Session queries —
# consistent with the sync `get_db()` dependency used throughout the project.

import logging
from typing import Any, Optional, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Eager-load helpers ────────────────────────────────────────────

def with_course_relations(query):
    """
    Eager-load the standard set of Course relationships in a single query,
    avoiding N+1 on instructor, category, lessons, and enrollments.

    Usage:
        courses = with_course_relations(
            db.query(Course).filter(Course.is_active == True)
        ).all()
    """
    return query.options(
        joinedload("instructor"),
        joinedload("category"),
        selectinload("lessons"),
        selectinload("enrollments"),
    )


def with_user_progress(query):
    """
    Eager-load Enrollment records with their parent course and lesson list.

    Usage:
        enrollments = with_user_progress(
            db.query(Enrollment).filter(Enrollment.user_id == user_id)
        ).all()
    """
    return query.options(
        joinedload("user"),
        joinedload("course"),
        selectinload("course.lessons"),
    )


# ── Pagination ────────────────────────────────────────────────────

def paginate(
    db: Session,
    query,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """
    Execute a paginated query and return a standard pagination envelope.

    Args:
        db:       Active SQLAlchemy session.
        query:    A SQLAlchemy ORM query (not yet executed).
        page:     1-based page number.
        per_page: Number of items per page.

    Returns:
        {
            "items":    [...],
            "total":    int,
            "page":     int,
            "per_page": int,
            "pages":    int,
        }

    Usage:
        result = paginate(db, db.query(Course).filter(...), page=2, per_page=10)
    """
    total: int = query.count()
    offset = (page - 1) * per_page
    items = query.offset(offset).limit(per_page).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


# ── Dynamic filter builder ────────────────────────────────────────

def apply_filters(query, model, filters: dict):
    """
    Apply a dict of {column_name: value} filters to a query.

    Supports:
      - Exact match:        {"status": "active"}
      - IN list:            {"status": ["active", "pending"]}
      - LIKE pattern:       {"title": "%python%"}   (value must contain %)
      - None values are skipped (treated as "no filter").

    Args:
        query:   SQLAlchemy query object.
        model:   The ORM model class the query is based on.
        filters: Dict of filter conditions.

    Usage:
        q = apply_filters(
            db.query(Course),
            Course,
            {"is_active": True, "status": ["published", "pending"]},
        )
    """
    for key, value in filters.items():
        if value is None:
            continue
        if not hasattr(model, key):
            logger.debug("apply_filters: model %s has no column '%s' — skipped.", model.__name__, key)
            continue

        column = getattr(model, key)

        if isinstance(value, list):
            query = query.filter(column.in_(value))
        elif isinstance(value, str) and "%" in value:
            query = query.filter(column.like(value))
        else:
            query = query.filter(column == value)

    return query


# ── Bulk insert helper ────────────────────────────────────────────

class BulkInserter:
    """
    High-throughput batch inserter for seeding, imports, and analytics writes.
    Accumulates objects in an internal buffer and flushes to the DB in batches.

    Usage:
        inserter = BulkInserter(db, batch_size=500)
        for row in data:
            inserter.add(MyModel(**row))
        inserter.flush()        # commit any remaining items

    Or as a context manager:
        with BulkInserter(db, batch_size=500) as b:
            for row in data:
                b.add(MyModel(**row))
        # auto-flushed on __exit__
    """

    def __init__(self, db: Session, batch_size: int = 1000):
        self.db = db
        self.batch_size = batch_size
        self._buffer: list = []

    def add(self, obj: Any):
        """Stage an ORM object. Triggers a flush when the batch is full."""
        self._buffer.append(obj)
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """Commit all buffered objects to the database and reset the buffer."""
        if not self._buffer:
            return
        self.db.add_all(self._buffer)
        self.db.commit()
        self._buffer.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.flush()
        else:
            self.db.rollback()
            self._buffer.clear()

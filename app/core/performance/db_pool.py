"""
app/core/db_pool.py — Production database connection pooling.
Replace your database.py imports with this for async SQLAlchemy.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
    AsyncEngine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool

# ── Configuration ────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "")
# Convert sync postgres:// to async postgresql+asyncpg://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# Pool sizing: (2 × CPU) + 1 for workers, plus overflow for bursts
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))  # Recycle connections after 1 hour
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))

# ── Engine ─────────────────────────────────────────────────────
_engine: AsyncEngine = None
_session_maker = None
Base = declarative_base()

def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            DATABASE_URL,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_recycle=POOL_RECYCLE,
            pool_timeout=POOL_TIMEOUT,
            pool_pre_ping=True,  # Verify connections before use
            echo=False,  # Set True for debug
            # Performance optimizations
            future=True,
        )
    return _engine

def get_session_maker() -> async_sessionmaker:
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # Don't expire objects after commit (faster)
            autoflush=False,  # Manual flush control
        )
    return _session_maker

@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fast dependency injection for FastAPI."""
    session = get_session_maker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

async def init_db():
    """Create tables on startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def close_db():
    """Dispose engine on shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None

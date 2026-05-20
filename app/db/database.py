from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
import logging

from app.core.config import get_app_config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# ── Lazy singleton engine ─────────────────────────────────────────
# Engine is created on first use, not at import time.
# This prevents import-time crashes when the DB is unreachable on startup.
_engine = None
_session_maker = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    config = get_app_config()
    db_url = config.database_config.sql_connection_string

    if not db_url:
        raise ValueError("APP_SQL_CONNECTION_STRING not set in .env")

    _engine = create_engine(
        db_url,
        poolclass=QueuePool,
        pool_size=config.database_config.pool_size,
        max_overflow=config.database_config.max_overflow,
        pool_recycle=config.database_config.pool_recycle,
        pool_timeout=config.database_config.pool_timeout,
        echo=config.database_config.echo,
        pool_pre_ping=True,  # Drop and replace stale connections before use
        future=True,          # SQLAlchemy 2.x query style
    )

    @event.listens_for(_engine, "connect")
    def set_timezone(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET TIME ZONE 'Africa/Lagos'")
        cursor.close()

    logger.info("Database engine initialised.")
    return _engine


def get_session_maker() -> sessionmaker:
    global _session_maker
    if _session_maker is None:
        _session_maker = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,  # Avoids lazy-load hits after commit
        )
    return _session_maker


# ── Dependency ────────────────────────────────────────────────────

def get_db():
    """FastAPI dependency. Yields a session; rolls back on error."""
    db = get_session_maker()()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error("Database error: %s", e)
        raise
    finally:
        db.close()


# ── Lifecycle helpers ─────────────────────────────────────────────

def create_tables():
    """Create all tables. Call from your app startup hook."""
    Base.metadata.create_all(bind=get_engine())
    logger.info("Database tables created/verified.")


def close_db():
    """Dispose the connection pool. Call from your app shutdown hook."""
    global _engine, _session_maker
    if _engine:
        _engine.dispose()
        logger.info("Database connection pool closed.")
        _engine = None
        _session_maker = None


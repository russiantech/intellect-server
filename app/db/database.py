from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import QueuePool
import logging

from app.core.config import get_app_config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def get_engine():
    config = get_app_config()
    db_url = config.database_config.sql_connection_string

    if not db_url:
        raise ValueError("APP_SQL_CONNECTION_STRING not set in .env")

    engine = create_engine(
        db_url,
        poolclass=QueuePool,
        pool_size=config.database_config.pool_size,
        max_overflow=config.database_config.max_overflow,
        pool_recycle=config.database_config.pool_recycle,
        pool_timeout=config.database_config.pool_timeout,
        echo=config.database_config.echo,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET TIME ZONE 'Africa/Lagos'")
        cursor.close()

    return engine


engine = get_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        db.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        db.close()


def create_tables():
    """Create all tables. Used during startup."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified.")

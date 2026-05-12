"""
Redis dependency injection - BULLETPROOF version
Never crashes, always returns (even if None)
"""
import logging
from typing import Optional

from app.core.config import get_app_config
from app.services.redis_service import RedisService

logger = logging.getLogger(__name__)

# Global Redis instance (singleton)
_redis_instance: Optional[RedisService] = None


def get_redis_instance() -> Optional[RedisService]:
    """
    Get or create global Redis instance (singleton pattern).
    NEVER crashes - returns None if Redis unavailable.
    """
    global _redis_instance
    
    if _redis_instance is None:
        try:
            config = get_app_config()
            redis_url = config.redis_config.redis_connection_string
            
            if not redis_url:
                logger.warning("Redis connection string not configured")
                return None
            
            _redis_instance = RedisService(redis_url)
            logger.info("Redis instance initialized")
            
        except Exception as e:
            logger.error(f"Failed to create Redis instance: {e}")
            logger.info("App will continue without Redis")
            return None
    
    return _redis_instance

# v3
def get_redis_service() -> Optional[RedisService]:
    try:
        redis = get_redis_instance()
        if redis and redis.ping():
            return redis
        return None
    except Exception:
        return None


def close_redis():
    """
    Cleanup - close Redis connection pool.
    NEVER crashes.
    """
    global _redis_instance
    
    if _redis_instance:
        try:
            _redis_instance.close()
            _redis_instance = None
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis: {e}")


def init_redis_on_startup():
    """
    Initialize Redis eagerly on startup.
    NEVER crashes - just logs errors.
    """
    try:
        redis = get_redis_instance()
        if redis and redis.ping():
            logger.info("Redis startup check passed")
            return True
        else:
            logger.warning("Redis startup check failed (will retry on demand)")
            return False
    except Exception as e:
        logger.error(f"Redis startup failed: {e}")
        logger.info("App will continue - Redis will auto-connect when available")
        return False
        # NEVER RAISE

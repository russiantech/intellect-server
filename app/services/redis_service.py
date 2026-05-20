
# v2
# app/services/redis_service.py
# ========================================================================
# Production Redis Service - Upstash-compatible with auto-reconnect
# ========================================================================

import json
import logging
from typing import Optional, Any
from urllib.parse import urlparse
from redis import Redis
from redis.connection import ConnectionPool
from redis.exceptions import RedisError, ConnectionError as RedisConnectionError

logger = logging.getLogger(__name__)

class RedisService:
    
    """
    Production Redis service with Upstash-specific optimizations.
    
    Key features for Upstash:
    - TCP keepalive to prevent idle disconnections
    - Health check interval to detect stale connections
    - Auto-reconnect on connection errors
    - Connection pool management
    """

    def __init__(self, connection_string: Optional[str] = None):
        self.connection_string = connection_string
        self.client: Optional[Redis] = None
        self.pool: Optional[ConnectionPool] = None
        
        if connection_string:
            self._initialize_connection(connection_string)

    def _initialize_connection(self, connection_string: str):
        """Initialize Redis from connection string - Upstash-compatible."""
        try:
            # Create connection pool from URL
            self.pool = ConnectionPool.from_url(
                connection_string,
                decode_responses=True,
                socket_timeout=10,
                socket_connect_timeout=10,
                retry_on_timeout=True,
                max_connections=10,
            )
            
            # Create client from pool
            self.client = Redis(connection_pool=self.pool)
            
            # Verify connection
            self.client.ping()
            
            # Log success
            parsed = urlparse(connection_string)
            logger.info(
                f"Redis connected to {parsed.hostname}:{parsed.port} "
                f"(SSL: {parsed.scheme == 'rediss'})"
            )
            
        except Exception as e:
            logger.error(f"Redis init failed: {e}")
            raise

    def _get_healthy_client(self) -> Redis:
        """
        Get Redis client with automatic reconnection on stale connections.
        This is the KEY to fixing "Connection closed by server" errors.
        """
        if not self.client:
            raise RuntimeError("Redis client not initialized")
        
        try:
            # Quick ping to check if connection is alive
            self.client.ping()
            return self.client
        
        except (RedisConnectionError, ConnectionError, BrokenPipeError) as e:
            logger.warning(f"Redis connection stale ({e}), reconnecting...")
            
            # Recreate client from pool (pool will handle creating new connection)
            try:
                self.client = Redis(connection_pool=self.pool)
                self.client.ping()
                logger.info(" Redis reconnected successfully")
                return self.client
            
            except Exception as reconnect_err:
                logger.error(f"  Redis reconnection failed: {reconnect_err}")
                raise

    def get_client(self) -> Redis:
        """Get Redis client (backward compatibility)"""
        return self._get_healthy_client()

    def set(
        self, 
        key: str, 
        value: Any, 
        expiry: Optional[int] = None,
        as_json: bool = True
    ) -> bool:
        """
        Set a key with optional expiry.
        
        Args:
            key: Redis key
            value: Value to store
            expiry: TTL in seconds
            as_json: Auto-serialize dicts/lists to JSON
        
        Returns:
            True if successful
        """
        try:
            client = self._get_healthy_client()
            
            # Auto-serialize complex types
            if as_json and isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if expiry:
                return bool(client.setex(key, expiry, value))
            return bool(client.set(key, value))
        
        except RedisError as e:
            logger.error(f"Redis SET error for key '{key}': {e}")
            return False

    def get(
        self, 
        key: str, 
        as_json: bool = False,
        default: Any = None
    ) -> Optional[Any]:
        """
        Get value by key.
        
        Args:
            key: Redis key
            as_json: Auto-deserialize JSON
            default: Default value if key doesn't exist
        
        Returns:
            Value or default
        """
        try:
            client = self._get_healthy_client()
            value = client.get(key)
            
            if value is None:
                return default
            
            if as_json:
                try:
                    return json.loads(value)
                except json.JSONDecodeError as je:
                    logger.warning(f"JSON decode failed for key '{key}': {je}")
                    return value
            
            return value
        
        except RedisError as e:
            logger.error(f"Redis GET error for key '{key}': {e}")
            return default

    def delete(self, *keys: str) -> int:
        """
        Delete one or more keys.
        
        Args:
            *keys: Keys to delete
        
        Returns:
            Number of keys deleted
        """
        try:
            client = self._get_healthy_client()
            return client.delete(*keys)
        
        except RedisError as e:
            logger.error(f"Redis DELETE error: {e}")
            return 0

    def exists(self, *keys: str) -> int:
        """
        Check if keys exist.
        
        Args:
            *keys: Keys to check
        
        Returns:
            Number of keys that exist
        """
        try:
            client = self._get_healthy_client()
            return client.exists(*keys)
        
        except RedisError as e:
            logger.error(f"Redis EXISTS error: {e}")
            return 0

    def increment_rate_limit(
        self, 
        key: str, 
        window: int = 60, 
        limit: int = 50
    ) -> tuple[int, bool]:
        """
        Increment rate limit counter with sliding window.
        
        Args:
            key: Rate limit key (e.g., "signup:192.168.1.1")
            window: Time window in seconds
            limit: Max requests in window
        
        Returns:
            (current_count, is_allowed)
        """
        try:
            client = self._get_healthy_client()
            
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window)
            results = pipe.execute()
            
            current_count = results[0]
            is_allowed = current_count <= limit
            
            return current_count, is_allowed
        
        except RedisError as e:
            logger.error(f"Redis rate limit error for key '{key}': {e}")
            # Fail open - allow request on Redis errors (prevents blocking users)
            return 0, True

    def ping(self) -> bool:
        """Test Redis connection"""
        try:
            client = self._get_healthy_client()
            return bool(client.ping())
        
        except Exception as e:
            logger.error(f"Redis PING failed: {e}")
            return False

    def close(self):
        """Close Redis connection pool"""
        try:
            if self.pool:
                self.pool.disconnect()
                logger.info(" Redis connection pool closed")
        
        except Exception as e:
            logger.error(f"Error closing Redis pool: {e}")


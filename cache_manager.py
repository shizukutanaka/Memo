#!/usr/bin/env python3
"""
Memory-Efficient Cache Manager
==============================
Production-grade caching with LRU eviction, TTL support,
memory limits, and Redis fallback support.
"""

import time
import threading
from typing import Any, Optional, Dict, Tuple
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import pickle
import logging
import json

logger = logging.getLogger(__name__)

# Redis support (optional)
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_AVAILABLE = False


@dataclass
class CacheEntry:
    """Cache entry with metadata."""
    value: Any
    created_at: float
    accessed_at: float
    access_count: int
    ttl: Optional[float]
    size_bytes: int

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl


class HybridCache:
    """Hybrid cache combining memory cache with Redis fallback."""

    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 50.0,
        default_ttl: Optional[float] = 3600.0,
        redis_url: Optional[str] = None,
        redis_prefix: str = "memo_cache:"
    ):
        self.memory_cache = LRUCache(max_size, max_memory_mb, default_ttl)
        self.redis_client = None
        self.redis_prefix = redis_prefix

        if REDIS_AVAILABLE and redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()  # Test connection
                logger.info("Redis cache backend connected")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}")
                self.redis_client = None

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache (memory first, then Redis)."""
        # Try memory cache first
        value = self.memory_cache.get(key)
        if value is not None:
            return value

        # Try Redis if available
        if self.redis_client:
            try:
                redis_key = f"{self.redis_prefix}{key}"
                data = self.redis_client.get(redis_key)
                if data:
                    value = pickle.loads(data)
                    # Store in memory cache for faster access
                    self.memory_cache.set(key, value)
                    return value
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache (both memory and Redis)."""
        # Store in memory cache
        self.memory_cache.set(key, value, ttl)

        # Store in Redis if available
        if self.redis_client:
            try:
                redis_key = f"{self.redis_prefix}{key}"
                data = pickle.dumps(value)
                if ttl:
                    self.redis_client.setex(redis_key, int(ttl), data)
                else:
                    self.redis_client.set(redis_key, data)
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")

    def delete(self, key: str) -> bool:
        """Delete value from cache."""
        deleted_memory = False
        deleted_redis = False

        # Delete from memory cache
        with self.memory_cache._lock:
            if key in self.memory_cache._cache:
                self.memory_cache._remove_entry(key)
                deleted_memory = True

        # Delete from Redis if available
        if self.redis_client:
            try:
                redis_key = f"{self.redis_prefix}{key}"
                deleted_redis = bool(self.redis_client.delete(redis_key))
            except Exception as e:
                logger.warning(f"Redis delete failed: {e}")

        return deleted_memory or deleted_redis

    def clear(self) -> None:
        """Clear all cache entries."""
        # Clear memory cache
        with self.memory_cache._lock:
            self.memory_cache._cache.clear()
            self.memory_cache._current_memory_bytes = 0

        # Clear Redis if available
        if self.redis_client:
            try:
                keys_pattern = f"{self.redis_prefix}*"
                keys = self.redis_client.keys(keys_pattern)
                if keys:
                    self.redis_client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis clear failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        stats = self.memory_cache.get_stats()
        stats['redis_available'] = self.redis_client is not None
        return stats


class LRUCache:
    """Thread-safe LRU cache with TTL and memory limits."""

    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100.0,
        default_ttl: Optional[float] = 3600.0
    ):
        self.max_size = max_size
        self.max_memory_bytes = int(max_memory_mb * 1024 * 1024)
        self.default_ttl = default_ttl

        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._current_memory_bytes = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired():
                self._remove_entry(key)
                self._misses += 1
                return None

            # Update access metadata
            entry.accessed_at = time.time()
            entry.access_count += 1

            # Move to end (most recently used)
            self._cache.move_to_end(key)

            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Set value in cache."""
        with self._lock:
            # Calculate size
            try:
                size_bytes = len(pickle.dumps(value))
            except (pickle.PicklingError, TypeError):
                logger.warning(f"Cannot cache non-serializable value for key: {key}")
                return

            # Remove old entry if exists
            if key in self._cache:
                self._remove_entry(key)

            # Evict if necessary
            while (
                len(self._cache) >= self.max_size or
                self._current_memory_bytes + size_bytes > self.max_memory_bytes
            ):
                if not self._cache:
                    break
                self._evict_lru()

            # Add new entry
            entry = CacheEntry(
                value=value,
                created_at=time.time(),
                accessed_at=time.time(),
                access_count=0,
                ttl=ttl or self.default_ttl,
                size_bytes=size_bytes
            )

            self._cache[key] = entry
            self._current_memory_bytes += size_bytes

    def delete(self, key: str) -> bool:
        """Delete entry from cache."""
        with self._lock:
            if key in self._cache:
                self._remove_entry(key)
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._current_memory_bytes = 0

    def _remove_entry(self, key: str) -> None:
        """Remove entry and update memory tracking."""
        entry = self._cache.pop(key, None)
        if entry:
            self._current_memory_bytes -= entry.size_bytes

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if self._cache:
            key, _ = self._cache.popitem(last=False)
            self._evictions += 1
            logger.debug(f"Evicted cache key: {key}")

    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]

            for key in expired_keys:
                self._remove_entry(key)

            return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            return {
                'size': len(self._cache),
                'max_size': self.max_size,
                'memory_mb': self._current_memory_bytes / (1024 * 1024),
                'max_memory_mb': self.max_memory_bytes / (1024 * 1024),
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': hit_rate,
                'evictions': self._evictions,
                'total_requests': total_requests
            }


class QueryCache:
    """Specialized cache for database query results."""

    def __init__(self, cache: LRUCache):
        self.cache = cache

    def get_query_key(self, query: str, params: tuple) -> str:
        """Generate cache key for query."""
        key_data = f"{query}:{params}".encode('utf-8')
        return f"query:{hashlib.sha256(key_data).hexdigest()}"

    def get(self, query: str, params: tuple) -> Optional[Any]:
        """Get cached query result."""
        key = self.get_query_key(query, params)
        return self.cache.get(key)

    def set(self, query: str, params: tuple, result: Any, ttl: float = 300.0) -> None:
        """Cache query result with 5-minute default TTL."""
        key = self.get_query_key(query, params)
        self.cache.set(key, result, ttl=ttl)

    def invalidate_pattern(self, table: str) -> int:
        """Invalidate all queries involving a table."""
        # For simplicity, clear entire cache
        # In production, implement more sophisticated invalidation
        self.cache.clear()
        return 0


class SessionCache:
    """Specialized cache for user sessions."""

    def __init__(self, cache: LRUCache):
        self.cache = cache

    def get_session_key(self, session_id: str) -> str:
        """Generate cache key for session."""
        return f"session:{session_id}"

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get cached session data."""
        key = self.get_session_key(session_id)
        return self.cache.get(key)

    def set(self, session_id: str, session_data: Dict[str, Any], ttl: float = 1800.0) -> None:
        """Cache session data with 30-minute default TTL."""
        key = self.get_session_key(session_id)
        self.cache.set(key, session_data, ttl=ttl)

    def delete(self, session_id: str) -> bool:
        """Remove session from cache."""
        key = self.get_session_key(session_id)
        return self.cache.delete(key)


class CacheManager:
    """Unified cache management."""

    def __init__(
        self,
        max_size: int = 1000,
        max_memory_mb: float = 100.0,
        default_ttl: float = 3600.0
    ):
        self.lru_cache = LRUCache(max_size, max_memory_mb, default_ttl)
        self.query_cache = QueryCache(self.lru_cache)
        self.session_cache = SessionCache(self.lru_cache)
        self._cleanup_thread = None
        self._stop_cleanup = threading.Event()

    def start_cleanup_thread(self, interval: float = 300.0) -> None:
        """Start background thread to cleanup expired entries."""
        def cleanup_loop():
            while not self._stop_cleanup.wait(interval):
                try:
                    removed = self.lru_cache.cleanup_expired()
                    if removed > 0:
                        logger.info(f"Cleaned up {removed} expired cache entries")
                except Exception as e:
                    logger.error(f"Cache cleanup error: {e}")

        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def stop_cleanup_thread(self) -> None:
        """Stop background cleanup thread."""
        if self._cleanup_thread:
            self._stop_cleanup.set()
            self._cleanup_thread.join(timeout=5.0)

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        return self.lru_cache.get_stats()

    def clear_all(self) -> None:
        """Clear all caches."""
        self.lru_cache.clear()


# Global cache instance
_global_cache: Optional[CacheManager] = None
_cache_lock = threading.Lock()


def get_cache_manager() -> CacheManager:
    """Get global cache manager instance."""
    global _global_cache

    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:
                _global_cache = CacheManager()
                _global_cache.start_cleanup_thread()

    return _global_cache


__all__ = [
    'LRUCache',
    'HybridCache',
    'QueryCache',
    'SessionCache',
    'CacheManager',
    'get_cache_manager',
]

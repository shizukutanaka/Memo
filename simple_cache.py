#!/usr/bin/env python3
"""Simple in-memory cache with TTL support."""

import time
import threading
from typing import Any, Optional, Dict, Callable, TypeVar
from dataclasses import dataclass
from functools import wraps

T = TypeVar('T')


@dataclass
class CacheEntry:
    """Cache entry with value and expiration time."""
    value: Any
    expires_at: float
    hits: int = 0

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at


class SimpleCache:
    """Thread-safe in-memory cache with TTL."""

    def __init__(self, default_ttl: float = 300.0, max_items: int = 1000):
        """
        Initialize cache.

        Args:
            default_ttl: Default time-to-live in seconds
            max_items: Maximum number of items in cache
        """
        self.default_ttl = default_ttl
        self.max_items = max_items
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired
        """
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                return None

            entry.hits += 1
            self._hits += 1
            return entry.value

    def put(self, key: str, value: Any, ttl: Optional[float] = None):
        """
        Put value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time-to-live in seconds (uses default if None)
        """
        with self._lock:
            if len(self._cache) >= self.max_items and key not in self._cache:
                self._evict_expired()

                if len(self._cache) >= self.max_items:
                    self._evict_lru()

            ttl_seconds = ttl if ttl is not None else self.default_ttl
            expires_at = time.time() + ttl_seconds

            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    def delete(self, key: str) -> bool:
        """
        Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if key was deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self):
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def _evict_expired(self):
        """Remove expired entries."""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.expires_at < current_time
        ]
        for key in expired_keys:
            del self._cache[key]

    def _evict_lru(self):
        """Evict least recently used entry based on hits."""
        if not self._cache:
            return

        lru_key = min(self._cache.items(), key=lambda item: item[1].hits)[0]
        del self._cache[lru_key]

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            return {
                "size": len(self._cache),
                "max_items": self.max_items,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "total_requests": total_requests
            }

    def cleanup_expired(self):
        """Remove all expired entries."""
        with self._lock:
            self._evict_expired()


def cached(
    cache: SimpleCache,
    ttl: Optional[float] = None,
    key_func: Optional[Callable[..., str]] = None
):
    """
    Decorator to cache function results.

    Args:
        cache: Cache instance to use
        ttl: Time-to-live for cached results
        key_func: Optional function to generate cache key from arguments

    Example:
        cache = SimpleCache()

        @cached(cache, ttl=60)
        def expensive_function(x, y):
            time.sleep(1)
            return x + y
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{args}:{kwargs}"

            result = cache.get(cache_key)
            if result is not None:
                return result

            result = func(*args, **kwargs)
            cache.put(cache_key, result, ttl=ttl)
            return result

        wrapper.cache = cache
        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator


class LRUCache:
    """Simple LRU cache implementation."""

    def __init__(self, max_size: int = 128):
        """
        Initialize LRU cache.

        Args:
            max_size: Maximum number of items
        """
        self.max_size = max_size
        self._cache: Dict[str, Any] = {}
        self._access_order: list = []
        self._lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """Get value and update access order."""
        with self._lock:
            if key not in self._cache:
                return None

            self._access_order.remove(key)
            self._access_order.append(key)
            return self._cache[key]

    def put(self, key: str, value: Any):
        """Put value and evict LRU if needed."""
        with self._lock:
            if key in self._cache:
                self._access_order.remove(key)
            elif len(self._cache) >= self.max_size:
                lru_key = self._access_order.pop(0)
                del self._cache[lru_key]

            self._cache[key] = value
            self._access_order.append(key)

    def clear(self):
        """Clear cache."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()

    def size(self) -> int:
        """Get current cache size."""
        with self._lock:
            return len(self._cache)


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    cache = SimpleCache(default_ttl=2.0, max_items=3)

    cache.put("key1", "value1")
    cache.put("key2", "value2")
    cache.put("key3", "value3")

    print(f"key1: {cache.get('key1')}")
    print(f"key2: {cache.get('key2')}")

    cache.put("key4", "value4")
    print(f"Cache size: {cache.get_stats()['size']}")

    time.sleep(2.5)
    print(f"key1 after TTL: {cache.get('key1')}")

    print(f"Cache stats: {cache.get_stats()}")

    @cached(cache, ttl=5.0)
    def slow_function(x: int) -> int:
        time.sleep(0.1)
        return x * 2

    print(f"First call: {slow_function(5)}")
    print(f"Second call (cached): {slow_function(5)}")
    print(f"Final stats: {cache.get_stats()}")

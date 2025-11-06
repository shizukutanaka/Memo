#!/usr/bin/env python3
"""Advanced caching strategies with multi-layer approach."""

import hashlib
import json
import time
import threading
from typing import Dict, Any, Optional, List, Tuple, Callable
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pickle
import logging

logger = logging.getLogger(__name__)


class CacheEntry:
    """Represents a single cache entry with metadata."""

    def __init__(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        Initialize cache entry.

        Args:
            key: Cache key
            value: Cached value
            ttl: Time-to-live in seconds
        """
        self.key = key
        self.value = value
        self.created_at = time.time()
        self.accessed_at = time.time()
        self.access_count = 0
        self.ttl = ttl

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        if self.ttl is None:
            return False

        age = time.time() - self.created_at
        return age > self.ttl

    def touch(self) -> None:
        """Update access time and count."""
        self.accessed_at = time.time()
        self.access_count += 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "key": self.key,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "accessed_at": datetime.fromtimestamp(self.accessed_at).isoformat(),
            "access_count": self.access_count,
            "ttl": self.ttl
        }


class L1Cache:
    """Level 1 (In-Memory) Cache - Fastest, smallest."""

    def __init__(self, max_size: int = 1000):
        """
        Initialize L1 cache.

        Args:
            max_size: Maximum entries
        """
        self.max_size = max_size
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return None

            entry = self.cache[key]

            if entry.is_expired():
                del self.cache[key]
                self.misses += 1
                return None

            # Update access info and move to end (LRU)
            entry.touch()
            self.cache.move_to_end(key)
            self.hits += 1

            return entry.value

    def put(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Put value in cache."""
        with self.lock:
            # Remove oldest if at capacity and key not existing
            if len(self.cache) >= self.max_size and key not in self.cache:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]

            # Add or update entry
            entry = CacheEntry(key, value, ttl)
            self.cache[key] = entry
            self.cache.move_to_end(key)

    def invalidate(self, key: str) -> bool:
        """Invalidate cache entry."""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries."""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0

            return {
                "size": len(self.cache),
                "max_size": self.max_size,
                "usage_percent": (len(self.cache) / self.max_size) * 100,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": hit_rate
            }


class L2Cache:
    """Level 2 (Disk) Cache - Slower, larger."""

    def __init__(self, cache_dir: Path, max_size_mb: int = 100):
        """
        Initialize L2 cache.

        Args:
            cache_dir: Directory for cache files
            max_size_mb: Maximum cache size in MB
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.metadata_file = self.cache_dir / ".cache_metadata.json"
        self.metadata = self._load_metadata()
        self.lock = threading.Lock()

    def _load_metadata(self) -> Dict[str, Dict]:
        """Load cache metadata."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load cache metadata: {e}")

        return {}

    def _save_metadata(self) -> None:
        """Save cache metadata."""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(self.metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save cache metadata: {e}")

    def _get_cache_file(self, key: str) -> Path:
        """Get cache file path for key."""
        # Hash key to create safe filename
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.cache"

    def get(self, key: str) -> Optional[Any]:
        """Get value from L2 cache."""
        with self.lock:
            if key not in self.metadata:
                return None

            cache_file = self._get_cache_file(key)

            if not cache_file.exists():
                del self.metadata[key]
                self._save_metadata()
                return None

            # Check TTL
            entry_meta = self.metadata[key]
            if "ttl" in entry_meta and entry_meta["ttl"]:
                age = time.time() - entry_meta["created_at"]
                if age > entry_meta["ttl"]:
                    cache_file.unlink()
                    del self.metadata[key]
                    self._save_metadata()
                    return None

            try:
                with open(cache_file, "rb") as f:
                    value = pickle.load(f)

                # Update metadata
                entry_meta["accessed_at"] = time.time()
                entry_meta["access_count"] = entry_meta.get("access_count", 0) + 1
                self._save_metadata()

                return value

            except Exception as e:
                logger.error(f"Failed to read cache file: {e}")
                return None

    def put(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Put value in L2 cache."""
        with self.lock:
            cache_file = self._get_cache_file(key)

            # Check size limit
            current_size = sum(f.stat().st_size for f in self.cache_dir.glob("*.cache"))
            if current_size > self.max_size_bytes:
                self._evict_lru()

            try:
                with open(cache_file, "wb") as f:
                    pickle.dump(value, f)

                # Store metadata
                self.metadata[key] = {
                    "created_at": time.time(),
                    "accessed_at": time.time(),
                    "access_count": 0,
                    "ttl": ttl,
                    "file_size": cache_file.stat().st_size
                }
                self._save_metadata()

                return True

            except Exception as e:
                logger.error(f"Failed to write cache file: {e}")
                return False

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self.metadata:
            return

        # Find LRU entry
        lru_key = min(
            self.metadata.keys(),
            key=lambda k: self.metadata[k].get("accessed_at", 0)
        )

        cache_file = self._get_cache_file(lru_key)
        if cache_file.exists():
            cache_file.unlink()

        del self.metadata[lru_key]

    def invalidate(self, key: str) -> bool:
        """Invalidate cache entry."""
        with self.lock:
            if key in self.metadata:
                cache_file = self._get_cache_file(key)
                if cache_file.exists():
                    cache_file.unlink()

                del self.metadata[key]
                self._save_metadata()
                return True

            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get L2 cache statistics."""
        with self.lock:
            total_size = sum(
                f.stat().st_size for f in self.cache_dir.glob("*.cache")
            )

            return {
                "entries": len(self.metadata),
                "total_size_mb": total_size / (1024 * 1024),
                "max_size_mb": self.max_size_bytes / (1024 * 1024),
                "usage_percent": (total_size / self.max_size_bytes) * 100
            }


class MultiLayerCache:
    """Multi-layer caching system (L1 + L2)."""

    def __init__(
        self,
        l1_size: int = 1000,
        l2_dir: Optional[Path] = None,
        l2_size_mb: int = 100
    ):
        """
        Initialize multi-layer cache.

        Args:
            l1_size: L1 cache max entries
            l2_dir: L2 cache directory
            l2_size_mb: L2 cache max size
        """
        self.l1 = L1Cache(max_size=l1_size)
        self.l2 = L2Cache(l2_dir or Path.home() / ".memo" / "cache", l2_size_mb)

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache (L1 first, then L2)."""
        # Try L1
        value = self.l1.get(key)
        if value is not None:
            return value

        # Try L2
        value = self.l2.get(key)
        if value is not None:
            # Populate L1 for future accesses
            self.l1.put(key, value)
            return value

        return None

    def put(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Put value in both L1 and L2."""
        self.l1.put(key, value, ttl)
        self.l2.put(key, value, ttl)

    def invalidate(self, key: str) -> None:
        """Invalidate in both L1 and L2."""
        self.l1.invalidate(key)
        self.l2.invalidate(key)

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate entries matching pattern.

        Args:
            pattern: Pattern to match (simple substring matching)

        Returns:
            Number of entries invalidated
        """
        count = 0

        # Invalidate L1
        with self.l1.lock:
            keys_to_delete = [k for k in self.l1.cache.keys() if pattern in k]
            for key in keys_to_delete:
                del self.l1.cache[key]
                count += 1

        # Invalidate L2
        with self.l2.lock:
            keys_to_delete = [k for k in self.l2.metadata.keys() if pattern in k]
            for key in keys_to_delete:
                self.l2.invalidate(key)
                count += 1

        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics."""
        return {
            "l1": self.l1.get_stats(),
            "l2": self.l2.get_stats(),
            "combined_hit_rate": self._calculate_combined_hit_rate()
        }

    def _calculate_combined_hit_rate(self) -> float:
        """Calculate combined hit rate."""
        l1_stats = self.l1.get_stats()
        total_hits = l1_stats["hits"]
        total_requests = l1_stats["hits"] + l1_stats["misses"]

        if total_requests == 0:
            return 0

        return (total_hits / total_requests) * 100


class SearchResultCache:
    """Specialized cache for search results."""

    def __init__(self, multi_cache: MultiLayerCache):
        """
        Initialize search cache.

        Args:
            multi_cache: Multi-layer cache instance
        """
        self.cache = multi_cache

    def get_search_results(self, query: str, filters: Optional[Dict] = None) -> Optional[List[Dict]]:
        """
        Get cached search results.

        Args:
            query: Search query
            filters: Search filters

        Returns:
            Cached results or None
        """
        cache_key = self._make_key(query, filters)
        return self.cache.get(cache_key)

    def cache_search_results(
        self,
        query: str,
        results: List[Dict],
        filters: Optional[Dict] = None,
        ttl: int = 300
    ) -> None:
        """
        Cache search results.

        Args:
            query: Search query
            results: Search results
            filters: Search filters
            ttl: Time-to-live in seconds
        """
        cache_key = self._make_key(query, filters)
        self.cache.put(cache_key, results, ttl)

    def invalidate_search(self, query_pattern: str) -> int:
        """Invalidate searches matching pattern."""
        return self.cache.invalidate_pattern(f"search:{query_pattern}")

    @staticmethod
    def _make_key(query: str, filters: Optional[Dict] = None) -> str:
        """Create cache key from query and filters."""
        parts = [f"search:{query}"]

        if filters:
            filters_str = json.dumps(filters, sort_keys=True)
            parts.append(hashlib.md5(filters_str.encode()).hexdigest())

        return "|".join(parts)


class TagCache:
    """Specialized cache for tag suggestions."""

    def __init__(self, multi_cache: MultiLayerCache):
        """
        Initialize tag cache.

        Args:
            multi_cache: Multi-layer cache instance
        """
        self.cache = multi_cache

    def get_tag_suggestions(self, prefix: str) -> Optional[List[str]]:
        """Get cached tag suggestions."""
        cache_key = f"tags:{prefix}"
        return self.cache.get(cache_key)

    def cache_tag_suggestions(self, prefix: str, tags: List[str], ttl: int = 3600) -> None:
        """Cache tag suggestions."""
        cache_key = f"tags:{prefix}"
        self.cache.put(cache_key, tags, ttl)

    def invalidate_tags(self) -> None:
        """Invalidate all tag caches."""
        self.cache.invalidate_pattern("tags:")


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    # Test L1 cache
    print("=== L1 Cache Test ===")
    l1 = L1Cache(max_size=5)

    for i in range(10):
        l1.put(f"key_{i}", f"value_{i}")

    print(f"L1: {l1.get('key_5')}")
    print(f"L1 Stats: {l1.get_stats()}")

    # Test L2 cache
    print("\n=== L2 Cache Test ===")
    cache_dir = Path.home() / ".memo" / "test_cache"
    l2 = L2Cache(cache_dir, max_size_mb=10)

    l2.put("memo_001", {"content": "Test memo", "tags": ["test"]})
    print(f"L2: {l2.get('memo_001')}")
    print(f"L2 Stats: {l2.get_stats()}")

    # Test multi-layer cache
    print("\n=== Multi-Layer Cache Test ===")
    ml_cache = MultiLayerCache(l1_size=100, l2_dir=cache_dir)

    for i in range(50):
        ml_cache.put(f"memo_{i}", {"id": i, "content": f"Memo {i}"}, ttl=600)

    print(f"Get memo_25: {ml_cache.get('memo_25')}")
    print(f"Cache Stats: {ml_cache.get_stats()}")

    # Test search cache
    print("\n=== Search Cache Test ===")
    search_cache = SearchResultCache(ml_cache)

    results = [
        {"id": 1, "title": "Result 1"},
        {"id": 2, "title": "Result 2"}
    ]

    search_cache.cache_search_results("python", results, ttl=300)
    cached = search_cache.get_search_results("python")
    print(f"Cached search results: {cached}")

    # Test tag cache
    print("\n=== Tag Cache Test ===")
    tag_cache = TagCache(ml_cache)

    tags = ["python", "programming", "tutorial"]
    tag_cache.cache_tag_suggestions("py", tags)
    suggestions = tag_cache.get_tag_suggestions("py")
    print(f"Tag suggestions: {suggestions}")

    # Cleanup
    import shutil
    shutil.rmtree(cache_dir, ignore_errors=True)

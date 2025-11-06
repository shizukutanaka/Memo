#!/usr/bin/env python3
"""Performance optimizations for memo system."""

from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
from collections import OrderedDict
import json
import logging


class LRUCache:
    """Simple LRU (Least Recently Used) cache implementation."""

    def __init__(self, capacity: int = 1000):
        self.capacity = max(capacity, 1)
        self.cache: OrderedDict = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key in self.cache:
            self.hits += 1
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            return self.cache[key]

        self.misses += 1
        return None

    def put(self, key: str, value: Any) -> None:
        """Put value into cache."""
        if key in self.cache:
            # Update existing key
            self.cache.move_to_end(key)
        elif len(self.cache) >= self.capacity:
            # Remove oldest item
            self.cache.popitem(last=False)

        self.cache[key] = value

    def invalidate(self, key: Optional[str] = None) -> None:
        """Invalidate cache entry or entire cache."""
        if key:
            self.cache.pop(key, None)
        else:
            self.cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0

        return {
            'size': len(self.cache),
            'capacity': self.capacity,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': round(hit_rate, 2),
            'total_requests': total
        }


class MemoIndex:
    """In-memory index for fast memo lookups."""

    def __init__(self):
        self.by_id: Dict[str, Dict] = {}
        self.by_tag: Dict[str, List[str]] = {}  # tag -> [memo_ids]
        self.by_category: Dict[str, List[str]] = {}  # category -> [memo_ids]
        self.by_status: Dict[str, List[str]] = {}  # status -> [memo_ids]
        self.timestamp_sorted: List[tuple[datetime, str]] = []  # (timestamp, memo_id)
        self._dirty = False

    def add_memo(self, memo: Dict) -> None:
        """Add memo to index."""
        memo_id = memo.get('id')
        if not memo_id:
            return

        # Index by ID
        self.by_id[memo_id] = memo

        # Index by tags
        for tag in memo.get('tags', []):
            if tag not in self.by_tag:
                self.by_tag[tag] = []
            if memo_id not in self.by_tag[tag]:
                self.by_tag[tag].append(memo_id)

        # Index by category
        category = memo.get('category', 'default')
        if category not in self.by_category:
            self.by_category[category] = []
        if memo_id not in self.by_category[category]:
            self.by_category[category].append(memo_id)

        # Index by status
        status = memo.get('status', 'active')
        if status not in self.by_status:
            self.by_status[status] = []
        if memo_id not in self.by_status[status]:
            self.by_status[status].append(memo_id)

        # Add to timestamp index
        try:
            timestamp = datetime.fromisoformat(memo.get('timestamp', ''))
            self.timestamp_sorted.append((timestamp, memo_id))
            self._dirty = True
        except (ValueError, TypeError):
            pass

    def remove_memo(self, memo_id: str) -> None:
        """Remove memo from index."""
        memo = self.by_id.pop(memo_id, None)
        if not memo:
            return

        # Remove from tag index
        for tag in memo.get('tags', []):
            if tag in self.by_tag and memo_id in self.by_tag[tag]:
                self.by_tag[tag].remove(memo_id)
                if not self.by_tag[tag]:
                    del self.by_tag[tag]

        # Remove from category index
        category = memo.get('category', 'default')
        if category in self.by_category and memo_id in self.by_category[category]:
            self.by_category[category].remove(memo_id)
            if not self.by_category[category]:
                del self.by_category[category]

        # Remove from status index
        status = memo.get('status', 'active')
        if status in self.by_status and memo_id in self.by_status[status]:
            self.by_status[status].remove(memo_id)
            if not self.by_status[status]:
                del self.by_status[status]

        # Remove from timestamp index
        self.timestamp_sorted = [(ts, mid) for ts, mid in self.timestamp_sorted if mid != memo_id]
        self._dirty = True

    def get_by_id(self, memo_id: str) -> Optional[Dict]:
        """Get memo by ID."""
        return self.by_id.get(memo_id)

    def get_by_tag(self, tag: str) -> List[str]:
        """Get memo IDs for a tag."""
        return self.by_tag.get(tag, [])

    def get_by_category(self, category: str) -> List[str]:
        """Get memo IDs for a category."""
        return self.by_category.get(category, [])

    def get_by_status(self, status: str) -> List[str]:
        """Get memo IDs for a status."""
        return self.by_status.get(status, [])

    def get_recent(self, limit: int = 50) -> List[str]:
        """Get most recent memo IDs."""
        if self._dirty:
            self.timestamp_sorted.sort(reverse=True)
            self._dirty = False

        return [memo_id for _, memo_id in self.timestamp_sorted[:limit]]

    def get_all_tags(self) -> List[str]:
        """Get all unique tags."""
        return list(self.by_tag.keys())

    def get_all_categories(self) -> List[str]:
        """Get all unique categories."""
        return list(self.by_category.keys())

    def clear(self) -> None:
        """Clear entire index."""
        self.by_id.clear()
        self.by_tag.clear()
        self.by_category.clear()
        self.by_status.clear()
        self.timestamp_sorted.clear()
        self._dirty = False

    def rebuild_from_memos(self, memos: List[Dict]) -> None:
        """Rebuild index from list of memos."""
        self.clear()
        for memo in memos:
            self.add_memo(memo)

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            'total_memos': len(self.by_id),
            'total_tags': len(self.by_tag),
            'total_categories': len(self.by_category),
            'memos_by_status': {status: len(ids) for status, ids in self.by_status.items()}
        }


class BatchProcessor:
    """Batch operations processor for efficiency."""

    def __init__(self, batch_size: int = 100):
        self.batch_size = max(batch_size, 1)
        self.operations: List[tuple[str, Any]] = []

    def add_operation(self, op_type: str, data: Any) -> None:
        """Add operation to batch."""
        self.operations.append((op_type, data))

    def should_flush(self) -> bool:
        """Check if batch should be flushed."""
        return len(self.operations) >= self.batch_size

    def get_operations(self) -> List[tuple[str, Any]]:
        """Get and clear operations."""
        ops = self.operations
        self.operations = []
        return ops

    def clear(self) -> None:
        """Clear pending operations."""
        self.operations.clear()


class PerformanceMonitor:
    """Monitor performance metrics."""

    def __init__(self):
        self.metrics: Dict[str, List[float]] = {}
        self.logger = logging.getLogger('memo.performance')

    def record_operation(self, operation: str, duration_ms: float) -> None:
        """Record operation duration."""
        if operation not in self.metrics:
            self.metrics[operation] = []

        self.metrics[operation].append(duration_ms)

        # Keep only last 1000 measurements
        if len(self.metrics[operation]) > 1000:
            self.metrics[operation] = self.metrics[operation][-1000:]

    def get_stats(self, operation: Optional[str] = None) -> Dict[str, Any]:
        """Get performance statistics."""
        if operation:
            if operation not in self.metrics:
                return {}

            values = self.metrics[operation]
            return self._calculate_stats(operation, values)

        # Return stats for all operations
        return {
            op: self._calculate_stats(op, values)
            for op, values in self.metrics.items()
        }

    def _calculate_stats(self, operation: str, values: List[float]) -> Dict[str, Any]:
        """Calculate statistics for values."""
        if not values:
            return {}

        sorted_values = sorted(values)
        n = len(sorted_values)

        return {
            'operation': operation,
            'count': n,
            'min_ms': round(min(sorted_values), 2),
            'max_ms': round(max(sorted_values), 2),
            'avg_ms': round(sum(sorted_values) / n, 2),
            'p50_ms': round(sorted_values[n // 2], 2),
            'p95_ms': round(sorted_values[int(n * 0.95)], 2),
            'p99_ms': round(sorted_values[int(n * 0.99)], 2)
        }

    def log_stats(self) -> None:
        """Log performance statistics."""
        stats = self.get_stats()
        for operation, data in stats.items():
            self.logger.info(
                f"Operation '{operation}': "
                f"avg={data['avg_ms']}ms, "
                f"p95={data['p95_ms']}ms, "
                f"count={data['count']}"
            )

    def clear(self) -> None:
        """Clear all metrics."""
        self.metrics.clear()


# Global instances
_memo_cache = LRUCache(capacity=500)
_memo_index = MemoIndex()
_performance_monitor = PerformanceMonitor()


def get_cache() -> LRUCache:
    """Get global memo cache."""
    return _memo_cache


def get_index() -> MemoIndex:
    """Get global memo index."""
    return _memo_index


def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor."""
    return _performance_monitor

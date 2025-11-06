#!/usr/bin/env python3
"""Performance monitoring and profiling utilities."""

import os
import psutil
import sys
import time
import tracemalloc
import threading
from typing import Dict, Any, Optional, Callable
from functools import wraps
from datetime import datetime
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class MemoryTracker:
    """Track memory usage and detect leaks."""

    def __init__(self):
        """Initialize memory tracker."""
        self.snapshots: Dict[str, Any] = {}
        self.enabled = False
        self.lock = threading.Lock()

    def start(self) -> None:
        """Start memory tracking."""
        tracemalloc.start()
        self.enabled = True
        logger.info("Memory tracking started")

    def stop(self) -> None:
        """Stop memory tracking."""
        if self.enabled:
            tracemalloc.stop()
            self.enabled = False
            logger.info("Memory tracking stopped")

    def take_snapshot(self, label: str) -> None:
        """
        Take memory snapshot.

        Args:
            label: Snapshot label
        """
        if not self.enabled:
            self.start()

        with self.lock:
            snapshot = tracemalloc.take_snapshot()
            self.snapshots[label] = {
                "timestamp": datetime.now().isoformat(),
                "snapshot": snapshot,
                "top_stats": snapshot.statistics("lineno")[:10]
            }

    def compare_snapshots(self, label1: str, label2: str) -> Dict[str, Any]:
        """
        Compare two snapshots.

        Args:
            label1: First snapshot label
            label2: Second snapshot label

        Returns:
            Comparison results
        """
        if label1 not in self.snapshots or label2 not in self.snapshots:
            return {}

        snap1 = self.snapshots[label1]["snapshot"]
        snap2 = self.snapshots[label2]["snapshot"]

        top_stats = snap2.compare_to(snap1, "lineno")

        return {
            "label1": label1,
            "label2": label2,
            "differences": [
                {
                    "file": str(stat.traceback[0]) if stat.traceback else "unknown",
                    "size_diff": stat.size_diff,
                    "count_diff": stat.count_diff
                }
                for stat in top_stats[:10]
            ]
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get memory tracking summary."""
        if not self.enabled:
            return {}

        current, peak = tracemalloc.get_traced_memory()

        return {
            "current_mb": current / 1024 / 1024,
            "peak_mb": peak / 1024 / 1024,
            "snapshots": list(self.snapshots.keys())
        }


class ProcessMonitor:
    """Monitor process resource usage."""

    def __init__(self, process_id: Optional[int] = None):
        """
        Initialize process monitor.

        Args:
            process_id: Process ID (default: current process)
        """
        self.process_id = process_id or os.getpid()
        self.process = psutil.Process(self.process_id)
        self.baseline = None
        self.measurements = []
        self.lock = threading.Lock()

    def set_baseline(self) -> None:
        """Set baseline for relative measurements."""
        with self.lock:
            self.baseline = {
                "cpu_percent": self.process.cpu_percent(interval=0.1),
                "memory_info": self.process.memory_info(),
                "timestamp": time.time()
            }

    def measure(self) -> Dict[str, Any]:
        """
        Take a measurement.

        Returns:
            Measurement data
        """
        with self.lock:
            mem_info = self.process.memory_info()
            cpu_percent = self.process.cpu_percent(interval=0.1)

            measurement = {
                "timestamp": time.time(),
                "cpu_percent": cpu_percent,
                "memory_rss_mb": mem_info.rss / 1024 / 1024,
                "memory_vms_mb": mem_info.vms / 1024 / 1024
            }

            if self.baseline:
                measurement["cpu_delta"] = cpu_percent - self.baseline["cpu_percent"]
                measurement["memory_delta_mb"] = (
                    mem_info.rss - self.baseline["memory_info"].rss
                ) / 1024 / 1024

            self.measurements.append(measurement)
            return measurement

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregated statistics."""
        if not self.measurements:
            return {}

        memory_values = [m["memory_rss_mb"] for m in self.measurements]
        cpu_values = [m["cpu_percent"] for m in self.measurements]

        return {
            "memory_avg_mb": sum(memory_values) / len(memory_values),
            "memory_max_mb": max(memory_values),
            "memory_min_mb": min(memory_values),
            "cpu_avg_percent": sum(cpu_values) / len(cpu_values),
            "cpu_max_percent": max(cpu_values),
            "measurements_count": len(self.measurements)
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get process summary."""
        try:
            mem_info = self.process.memory_info()
            return {
                "pid": self.process_id,
                "status": self.process.status(),
                "cpu_num": self.process.cpu_num(),
                "memory_rss_mb": mem_info.rss / 1024 / 1024,
                "num_threads": self.process.num_threads(),
                "open_files": len(self.process.open_files())
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {}


class OperationTimer:
    """Context manager for measuring operation duration."""

    def __init__(self, name: str = "operation", log: bool = True):
        """
        Initialize timer.

        Args:
            name: Operation name
            log: Whether to log the result
        """
        self.name = name
        self.log = log
        self.start_time = None
        self.end_time = None
        self.duration = None

    def __enter__(self):
        """Start timing."""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop timing."""
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time

        if self.log:
            if exc_type:
                logger.warning(
                    f"Operation '{self.name}' failed after {self.duration:.3f}s: {exc_val}"
                )
            else:
                logger.info(f"Operation '{self.name}' completed in {self.duration:.3f}s")

    def get_duration_ms(self) -> float:
        """Get duration in milliseconds."""
        if self.duration is None:
            return 0
        return self.duration * 1000


class LRUCache:
    """Thread-safe LRU cache for memo operations."""

    def __init__(self, max_items: int = 1000, ttl_seconds: Optional[int] = None):
        """
        Initialize LRU cache.

        Args:
            max_items: Maximum items in cache
            ttl_seconds: Time-to-live for items in seconds
        """
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.access_times: Dict[str, float] = {}
        self.create_times: Dict[str, float] = {}
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None
        """
        with self.lock:
            if key not in self.cache:
                return None

            # Check TTL
            if self.ttl_seconds:
                age = time.time() - self.create_times[key]
                if age > self.ttl_seconds:
                    del self.cache[key]
                    del self.access_times[key]
                    del self.create_times[key]
                    return None

            # Update access time
            self.access_times[key] = time.time()
            return self.cache[key]

    def put(self, key: str, value: Any) -> None:
        """
        Put value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self.lock:
            # Remove oldest item if cache full
            if len(self.cache) >= self.max_items and key not in self.cache:
                lru_key = min(self.access_times.keys(), key=self.access_times.get)
                del self.cache[lru_key]
                del self.access_times[lru_key]
                del self.create_times[lru_key]

            # Add to cache
            now = time.time()
            self.cache[key] = value
            self.access_times[key] = now
            self.create_times[key] = now

    def clear(self) -> None:
        """Clear cache."""
        with self.lock:
            self.cache.clear()
            self.access_times.clear()
            self.create_times.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.lock:
            return {
                "size": len(self.cache),
                "max_items": self.max_items,
                "usage_percent": (len(self.cache) / self.max_items) * 100,
                "ttl_seconds": self.ttl_seconds
            }


def profile_operation(func: Callable) -> Callable:
    """
    Decorator to profile function execution.

    Args:
        func: Function to profile

    Returns:
        Wrapped function
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        monitor = ProcessMonitor()
        monitor.set_baseline()

        with OperationTimer(func.__name__):
            result = func(*args, **kwargs)

        stats = monitor.get_stats()
        if stats:
            logger.debug(f"Profiling {func.__name__}: {stats}")

        return result

    return wrapper


def memoize(cache: Optional[LRUCache] = None):
    """
    Decorator for memoization with LRU cache.

    Args:
        cache: LRU cache instance (default: new cache)

    Returns:
        Decorator function
    """
    if cache is None:
        cache = LRUCache(max_items=1000)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            # Check cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Compute and cache
            result = func(*args, **kwargs)
            cache.put(cache_key, result)

            return result

        return wrapper

    return decorator


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    # Test memory tracking
    print("=== Memory Tracking ===")
    tracker = MemoryTracker()
    tracker.start()
    tracker.take_snapshot("start")

    # Create some objects
    data = [i for i in range(100000)]

    tracker.take_snapshot("after_data")
    comparison = tracker.compare_snapshots("start", "after_data")
    print(f"Memory summary: {tracker.get_summary()}")

    tracker.stop()

    # Test process monitor
    print("\n=== Process Monitoring ===")
    monitor = ProcessMonitor()
    monitor.set_baseline()

    for _ in range(5):
        measurement = monitor.measure()
        print(f"Measurement: {measurement}")
        time.sleep(0.1)

    print(f"Stats: {monitor.get_stats()}")

    # Test LRU cache
    print("\n=== LRU Cache ===")
    cache = LRUCache(max_items=5)

    for i in range(10):
        cache.put(f"key_{i}", f"value_{i}")

    print(f"Cache stats: {cache.get_stats()}")
    print(f"Get key_5: {cache.get('key_5')}")
    print(f"Get key_0: {cache.get('key_0')}")  # May be evicted

    # Test operation timer
    print("\n=== Operation Timer ===")
    with OperationTimer("test_operation"):
        time.sleep(0.5)

    # Test memoize
    print("\n=== Memoization ===")
    call_count = 0

    @memoize()
    def expensive_operation(n):
        global call_count
        call_count += 1
        return n ** 2

    print(f"First call: {expensive_operation(5)}, call_count: {call_count}")
    print(f"Second call: {expensive_operation(5)}, call_count: {call_count}")
    print(f"Third call: {expensive_operation(6)}, call_count: {call_count}")

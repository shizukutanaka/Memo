#!/usr/bin/env python3
"""Rate limiting and throttling for memo application operations."""

import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Callable
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe rate limiter using token bucket algorithm."""

    def __init__(
        self,
        rate: int,
        period: int = 1,
        name: str = "default"
    ):
        """
        Initialize rate limiter.

        Args:
            rate: Number of operations allowed per period
            period: Time period in seconds
            name: Name for logging
        """
        self.rate = rate
        self.period = period
        self.name = name
        self.tokens = float(rate)
        self.last_update = time.time()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        """
        Check if operation is allowed.

        Returns:
            True if within rate limit, False otherwise
        """
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update

            # Refill tokens
            tokens_to_add = (elapsed / self.period) * self.rate
            self.tokens = min(self.rate, self.tokens + tokens_to_add)
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True

            return False

    def wait_if_needed(self) -> float:
        """
        Wait if needed until operation is allowed.

        Returns:
            Time waited in seconds
        """
        start_time = time.time()

        while not self.allow():
            time.sleep(0.01)

        return time.time() - start_time

    def get_status(self) -> Dict[str, Any]:
        """Get rate limiter status."""
        with self.lock:
            return {
                "name": self.name,
                "rate": self.rate,
                "period": self.period,
                "tokens_available": self.tokens,
                "last_update": self.last_update
            }


class AdaptiveThrottler:
    """Adaptive throttler that adjusts rate based on system load."""

    def __init__(
        self,
        initial_rate: int = 100,
        min_rate: int = 10,
        max_rate: int = 1000,
        period: int = 1
    ):
        """
        Initialize adaptive throttler.

        Args:
            initial_rate: Initial operations per period
            min_rate: Minimum operations per period
            max_rate: Maximum operations per period
            period: Time period in seconds
        """
        self.current_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.period = period
        self.limiter = RateLimiter(initial_rate, period, "adaptive")
        self.lock = threading.Lock()

        # Performance metrics
        self.success_count = 0
        self.error_count = 0
        self.last_adjustment = time.time()

    def record_success(self) -> None:
        """Record successful operation."""
        with self.lock:
            self.success_count += 1
            self._adjust_if_needed()

    def record_error(self) -> None:
        """Record failed operation."""
        with self.lock:
            self.error_count += 1
            self._adjust_if_needed()

    def _adjust_if_needed(self) -> None:
        """Adjust rate based on performance metrics."""
        now = time.time()
        if (now - self.last_adjustment) < 10:  # Adjust every 10 seconds
            return

        total = self.success_count + self.error_count
        if total == 0:
            return

        error_rate = self.error_count / total

        if error_rate > 0.1:  # More than 10% errors
            # Decrease rate
            new_rate = max(self.min_rate, int(self.current_rate * 0.8))
            if new_rate != self.current_rate:
                logger.warning(f"Throttling rate decreased to {new_rate} due to high error rate")
                self.current_rate = new_rate
                self.limiter = RateLimiter(new_rate, self.period, "adaptive")

        elif error_rate < 0.01 and self.success_count > 100:  # Less than 1% errors
            # Increase rate
            new_rate = min(self.max_rate, int(self.current_rate * 1.2))
            if new_rate != self.current_rate:
                logger.info(f"Throttling rate increased to {new_rate}")
                self.current_rate = new_rate
                self.limiter = RateLimiter(new_rate, self.period, "adaptive")

        # Reset metrics
        self.success_count = 0
        self.error_count = 0
        self.last_adjustment = now

    def allow(self) -> bool:
        """Check if operation is allowed."""
        return self.limiter.allow()

    def wait_if_needed(self) -> float:
        """Wait if needed."""
        return self.limiter.wait_if_needed()

    def get_status(self) -> Dict[str, Any]:
        """Get throttler status."""
        with self.lock:
            return {
                "current_rate": self.current_rate,
                "min_rate": self.min_rate,
                "max_rate": self.max_rate,
                "success_count": self.success_count,
                "error_count": self.error_count,
                "error_rate": (
                    self.error_count / (self.success_count + self.error_count)
                    if (self.success_count + self.error_count) > 0
                    else 0
                )
            }


class OperationQuota:
    """Track operation quotas with time windows."""

    def __init__(self, operations_per_window: int, window_seconds: int = 3600):
        """
        Initialize operation quota.

        Args:
            operations_per_window: Max operations in window
            window_seconds: Window duration in seconds
        """
        self.quota = operations_per_window
        self.window = window_seconds
        self.operations: Dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def is_allowed(self, operation_id: str) -> bool:
        """
        Check if operation is allowed.

        Args:
            operation_id: Unique identifier for operation type

        Returns:
            True if allowed, False if quota exceeded
        """
        with self.lock:
            now = time.time()
            operations = self.operations[operation_id]

            # Remove old operations outside window
            while operations and operations[0] < (now - self.window):
                operations.popleft()

            # Check quota
            return len(operations) < self.quota

    def record_operation(self, operation_id: str) -> None:
        """Record an operation."""
        with self.lock:
            self.operations[operation_id].append(time.time())

    def get_remaining(self, operation_id: str) -> int:
        """Get remaining quota for operation."""
        with self.lock:
            now = time.time()
            operations = self.operations[operation_id]

            # Count operations within window
            count = sum(1 for op_time in operations if op_time >= (now - self.window))
            return max(0, self.quota - count)

    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get quota statistics."""
        with self.lock:
            now = time.time()
            stats = {}

            for operation_id, operations in self.operations.items():
                # Count operations within window
                count = sum(1 for op_time in operations if op_time >= (now - self.window))
                stats[operation_id] = {
                    "used": count,
                    "remaining": max(0, self.quota - count),
                    "quota": self.quota,
                    "window_seconds": self.window
                }

            return stats


def rate_limit(rate: int, period: int = 1):
    """
    Decorator for rate limiting a function.

    Args:
        rate: Operations allowed per period
        period: Time period in seconds
    """
    limiter = RateLimiter(rate, period)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            limiter.wait_if_needed()
            return func(*args, **kwargs)

        return wrapper

    return decorator


def adaptive_throttle(initial_rate: int = 100):
    """
    Decorator for adaptive throttling.

    Args:
        initial_rate: Initial operations per second
    """
    throttler = AdaptiveThrottler(initial_rate)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            throttler.wait_if_needed()
            try:
                result = func(*args, **kwargs)
                throttler.record_success()
                return result
            except Exception as e:
                throttler.record_error()
                raise

        return wrapper

    return decorator


class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance."""

    class State:
        CLOSED = "closed"       # Normal operation
        OPEN = "open"          # Fail fast
        HALF_OPEN = "half_open"  # Testing recovery

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.success_count = 0
        self.state = self.State.CLOSED
        self.last_failure_time = None
        self.lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs):
        """
        Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args, **kwargs: Function arguments

        Returns:
            Function result

        Raises:
            Exception: If circuit is open or function fails
        """
        with self.lock:
            if self.state == self.State.OPEN:
                if self._should_attempt_reset():
                    self.state = self.State.HALF_OPEN
                    self.success_count = 0
                else:
                    raise RuntimeError("Circuit breaker is open")

        try:
            result = func(*args, **kwargs)

            with self.lock:
                self.failure_count = 0
                if self.state == self.State.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= 3:
                        self.state = self.State.CLOSED
                        logger.info("Circuit breaker closed")

            return result

        except Exception as e:
            with self.lock:
                self.failure_count += 1
                self.last_failure_time = time.time()

                if self.failure_count >= self.failure_threshold:
                    self.state = self.State.OPEN
                    logger.error(f"Circuit breaker opened after {self.failure_count} failures")

                if self.state == self.State.HALF_OPEN:
                    self.state = self.State.OPEN
                    logger.warning("Circuit breaker reopened")

            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True

        return (time.time() - self.last_failure_time) >= self.recovery_timeout

    def get_state(self) -> Dict[str, Any]:
        """Get circuit breaker state."""
        with self.lock:
            return {
                "state": self.state,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure_time": self.last_failure_time
            }


if __name__ == "__main__":
    import sys

    # Test rate limiter
    print("=== Rate Limiter Test ===")
    limiter = RateLimiter(rate=3, period=1, name="test")

    for i in range(5):
        if limiter.allow():
            print(f"Operation {i+1}: Allowed")
        else:
            print(f"Operation {i+1}: Blocked")

    # Test quota
    print("\n=== Operation Quota Test ===")
    quota = OperationQuota(operations_per_window=5, window_seconds=60)

    for i in range(7):
        operation_id = "create_memo"
        if quota.is_allowed(operation_id):
            quota.record_operation(operation_id)
            print(f"Operation {i+1}: Allowed (remaining: {quota.get_remaining(operation_id)})")
        else:
            print(f"Operation {i+1}: Blocked (remaining: {quota.get_remaining(operation_id)})")

    # Test adaptive throttler
    print("\n=== Adaptive Throttler Test ===")
    throttler = AdaptiveThrottler(initial_rate=5)

    for i in range(10):
        if i in [3, 4, 8]:  # Simulate some errors
            throttler.record_error()
            print(f"Operation {i+1}: Error")
        else:
            throttler.record_success()
            print(f"Operation {i+1}: Success (Rate: {throttler.current_rate})")

    print(f"\nThrottler Status: {throttler.get_status()}")

    # Test circuit breaker
    print("\n=== Circuit Breaker Test ===")
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=5)

    def failing_operation():
        raise ValueError("Test error")

    for i in range(5):
        try:
            breaker.call(failing_operation)
        except Exception as e:
            print(f"Operation {i+1}: {e}")
            print(f"State: {breaker.get_state()['state']}")

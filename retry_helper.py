#!/usr/bin/env python3
"""Retry helper for transient failures with exponential backoff."""

import time
import logging
from typing import Callable, TypeVar, Optional, Type, Tuple
from functools import wraps

T = TypeVar('T')

logger = logging.getLogger(__name__)


class RetryError(Exception):
    """Raised when all retry attempts have been exhausted."""
    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        super().__init__(message)
        self.last_exception = last_exception


def retry_with_backoff(
    max_attempts: int = 3,
    initial_delay: float = 0.1,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    Decorator to retry a function with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
        backoff_factor: Multiplier for delay after each retry
        exceptions: Tuple of exception types to retry on
        on_retry: Optional callback function called on each retry

    Example:
        @retry_with_backoff(max_attempts=3, initial_delay=0.5)
        def unstable_operation():
            # operation that might fail transiently
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise RetryError(
                            f"Operation failed after {max_attempts} attempts",
                            last_exception=e
                        )

                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    if on_retry:
                        try:
                            on_retry(e, attempt)
                        except Exception as callback_error:
                            logger.error(f"Retry callback failed: {callback_error}")

                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            raise RetryError(
                f"Operation failed after {max_attempts} attempts",
                last_exception=last_exception
            )

        return wrapper
    return decorator


def retry_on_condition(
    condition: Callable[[Exception], bool],
    max_attempts: int = 3,
    initial_delay: float = 0.1,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0
):
    """
    Decorator to retry a function based on a condition.

    Args:
        condition: Function that takes an exception and returns True if should retry
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
        backoff_factor: Multiplier for delay after each retry

    Example:
        def is_transient_error(e):
            return "timeout" in str(e).lower()

        @retry_on_condition(is_transient_error, max_attempts=3)
        def operation():
            pass
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if not condition(e):
                        raise

                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {e}"
                        )
                        raise RetryError(
                            f"Operation failed after {max_attempts} attempts",
                            last_exception=e
                        )

                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )

                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            raise RetryError(
                f"Operation failed after {max_attempts} attempts",
                last_exception=last_exception
            )

        return wrapper
    return decorator


class RetryContext:
    """Context manager for retry operations."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
        backoff_factor: float = 2.0,
        exceptions: Tuple[Type[Exception], ...] = (Exception,)
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.exceptions = exceptions
        self.attempt = 0
        self.delay = initial_delay

    def __enter__(self):
        self.attempt += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            return False

        if not issubclass(exc_type, self.exceptions):
            return False

        if self.attempt >= self.max_attempts:
            logger.error(f"Operation failed after {self.max_attempts} attempts: {exc_val}")
            return False

        logger.warning(
            f"Operation failed (attempt {self.attempt}/{self.max_attempts}): {exc_val}. "
            f"Retrying in {self.delay:.2f}s..."
        )

        time.sleep(self.delay)
        self.delay = min(self.delay * self.backoff_factor, self.max_delay)
        return True


def is_transient_error(error: Exception) -> bool:
    """Check if an error is likely transient and worth retrying."""
    error_str = str(error).lower()
    transient_indicators = [
        "timeout",
        "connection",
        "temporary",
        "unavailable",
        "busy",
        "locked",
        "network",
        "refused"
    ]
    return any(indicator in error_str for indicator in transient_indicators)


if __name__ == "__main__":
    import random

    @retry_with_backoff(max_attempts=5, initial_delay=0.1)
    def unstable_function():
        """Simulates an unstable function that fails randomly."""
        if random.random() < 0.7:
            raise ConnectionError("Simulated connection failure")
        return "Success"

    try:
        result = unstable_function()
        print(f"Result: {result}")
    except RetryError as e:
        print(f"Failed: {e}")
        print(f"Last exception: {e.last_exception}")

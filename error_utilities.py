#!/usr/bin/env python3
"""Error handling and exception management utilities."""

import logging
import sys
import traceback
from typing import Optional, Type, Callable, Any, Dict, List
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)


class MemoException(Exception):
    """Base exception for memo application."""

    def __init__(self, message: str, error_code: str = "MEMO_ERROR", details: Optional[Dict] = None):
        """
        Initialize exception.

        Args:
            message: Error message
            error_code: Error code identifier
            details: Additional error details
        """
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "timestamp": datetime.now().isoformat()
        }


class ValidationError(MemoException):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: Optional[str] = None, value: Optional[Any] = None):
        """
        Initialize validation error.

        Args:
            message: Error message
            field: Field that failed validation
            value: Invalid value
        """
        details = {}
        if field:
            details["field"] = field
        if value is not None:
            details["value"] = str(value)

        super().__init__(message, "VALIDATION_ERROR", details)


class StorageError(MemoException):
    """Raised when storage operations fail."""

    def __init__(self, message: str, operation: Optional[str] = None):
        """
        Initialize storage error.

        Args:
            message: Error message
            operation: Failed operation
        """
        details = {}
        if operation:
            details["operation"] = operation

        super().__init__(message, "STORAGE_ERROR", details)


class SyncError(MemoException):
    """Raised when sync operations fail."""

    def __init__(self, message: str, sync_target: Optional[str] = None):
        """
        Initialize sync error.

        Args:
            message: Error message
            sync_target: Sync target that failed
        """
        details = {}
        if sync_target:
            details["sync_target"] = sync_target

        super().__init__(message, "SYNC_ERROR", details)


class NotFoundError(MemoException):
    """Raised when resource is not found."""

    def __init__(self, resource_type: str, resource_id: str):
        """
        Initialize not found error.

        Args:
            resource_type: Type of resource
            resource_id: ID of resource
        """
        message = f"{resource_type} '{resource_id}' not found"
        details = {
            "resource_type": resource_type,
            "resource_id": resource_id
        }

        super().__init__(message, "NOT_FOUND", details)


class ErrorHandler:
    """Central error handling and recovery."""

    def __init__(self):
        """Initialize error handler."""
        self.error_history: List[Dict] = []
        self.error_counts: Dict[str, int] = {}
        self.recovery_strategies: Dict[Type[Exception], Callable] = {}

    def register_recovery(self, exception_type: Type[Exception], handler: Callable) -> None:
        """
        Register error recovery strategy.

        Args:
            exception_type: Exception type to handle
            handler: Recovery handler function
        """
        self.recovery_strategies[exception_type] = handler

    def handle(self, exc: Exception, action: str = "log") -> None:
        """
        Handle exception.

        Args:
            exc: Exception to handle
            action: Action to take (log, raise, recover, ignore)
        """
        # Record error
        error_info = {
            "timestamp": datetime.now().isoformat(),
            "type": type(exc).__name__,
            "message": str(exc),
            "action": action
        }
        self.error_history.append(error_info)

        # Update error counts
        error_type = type(exc).__name__
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

        # Execute action
        if action == "log":
            logger.error(f"{error_type}: {str(exc)}", exc_info=exc)

        elif action == "raise":
            raise exc

        elif action == "recover":
            # Try recovery strategy
            handler = self.recovery_strategies.get(type(exc))
            if handler:
                try:
                    handler(exc)
                    logger.info(f"Recovered from {error_type}")
                except Exception as recovery_error:
                    logger.error(f"Recovery failed: {recovery_error}", exc_info=recovery_error)
            else:
                logger.warning(f"No recovery strategy for {error_type}")

        elif action == "ignore":
            logger.debug(f"Ignoring {error_type}: {str(exc)}")

    def get_summary(self) -> Dict[str, Any]:
        """Get error summary."""
        return {
            "total_errors": len(self.error_history),
            "error_counts": self.error_counts,
            "recent_errors": self.error_history[-10:] if self.error_history else []
        }


class RetryStrategy:
    """Retry logic with exponential backoff."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.1,
        backoff_factor: float = 2.0,
        max_delay: float = 30.0,
        exceptions: tuple = (Exception,)
    ):
        """
        Initialize retry strategy.

        Args:
            max_attempts: Maximum retry attempts
            initial_delay: Initial delay in seconds
            backoff_factor: Backoff multiplier
            max_delay: Maximum delay in seconds
            exceptions: Exceptions to retry on
        """
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.exceptions = exceptions

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry.

        Args:
            func: Function to execute
            *args, **kwargs: Function arguments

        Returns:
            Function result

        Raises:
            Exception: If all retries fail
        """
        import time

        last_exception = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                return func(*args, **kwargs)

            except self.exceptions as e:
                last_exception = e

                if attempt >= self.max_attempts:
                    logger.error(f"All {self.max_attempts} attempts failed")
                    raise

                # Calculate delay
                delay = min(
                    self.initial_delay * (self.backoff_factor ** (attempt - 1)),
                    self.max_delay
                )

                logger.warning(
                    f"Attempt {attempt} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )

                time.sleep(delay)

        raise last_exception


def retry(max_attempts: int = 3, delay: float = 0.1, backoff: float = 2.0):
    """
    Decorator for retry logic.

    Args:
        max_attempts: Maximum attempts
        delay: Initial delay in seconds
        backoff: Backoff multiplier

    Returns:
        Decorator function
    """
    strategy = RetryStrategy(
        max_attempts=max_attempts,
        initial_delay=delay,
        backoff_factor=backoff
    )

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return strategy.execute(func, *args, **kwargs)

        return wrapper

    return decorator


def handle_errors(action: str = "log"):
    """
    Decorator for error handling.

    Args:
        action: Action to take (log, raise, recover, ignore)

    Returns:
        Decorator function
    """
    handler = ErrorHandler()

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                handler.handle(e, action=action)
                if action == "raise":
                    raise
                return None

        return wrapper

    return decorator


class ContextualException(Exception):
    """Exception with contextual information."""

    def __init__(self, message: str, context: Optional[Dict] = None):
        """
        Initialize contextual exception.

        Args:
            message: Error message
            context: Context dictionary
        """
        self.message = message
        self.context = context or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        """String representation."""
        result = self.message

        if self.context:
            result += "\n\nContext:"
            for key, value in self.context.items():
                result += f"\n  {key}: {value}"

        # Add traceback
        if sys.exc_info()[2]:
            result += "\n\nTraceback:"
            result += "".join(traceback.format_tb(sys.exc_info()[2]))

        return result


def safe_execute(
    func: Callable,
    *args,
    default: Any = None,
    log_errors: bool = True,
    **kwargs
) -> Any:
    """
    Safely execute function with error handling.

    Args:
        func: Function to execute
        *args: Function arguments
        default: Default value if execution fails
        log_errors: Whether to log errors
        **kwargs: Keyword arguments

    Returns:
        Function result or default
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_errors:
            logger.error(f"Safe execution failed: {e}", exc_info=e)
        return default


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    # Test custom exceptions
    print("=== Custom Exceptions ===")
    try:
        raise ValidationError("Invalid memo content", field="content", value="")
    except MemoException as e:
        print(f"Caught: {e.to_dict()}")

    try:
        raise NotFoundError("memo", "memo-001")
    except MemoException as e:
        print(f"Caught: {e.to_dict()}")

    # Test retry decorator
    print("\n=== Retry Decorator ===")
    attempt_count = 0

    @retry(max_attempts=3, delay=0.1)
    def failing_function():
        global attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise ValueError("Not yet")
        return "Success"

    result = failing_function()
    print(f"Result: {result}, Attempts: {attempt_count}")

    # Test error handler
    print("\n=== Error Handler ===")
    handler = ErrorHandler()

    try:
        raise ValueError("Test error")
    except Exception as e:
        handler.handle(e, action="log")

    print(f"Summary: {handler.get_summary()}")

    # Test safe execution
    print("\n=== Safe Execution ===")
    result = safe_execute(lambda: 1 / 0, default="Error handled")
    print(f"Result: {result}")

    # Test contextual exception
    print("\n=== Contextual Exception ===")
    try:
        raise ContextualException(
            "Database operation failed",
            context={
                "operation": "INSERT",
                "table": "memos",
                "timestamp": datetime.now().isoformat()
            }
        )
    except ContextualException as e:
        print(str(e))

#!/usr/bin/env python3
"""
Production Error Handling System
================================
Comprehensive error handling with user-friendly messages,
logging, and recovery strategies.
"""

import sys
import logging
import traceback
from typing import Optional, Dict, Any, Callable
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorCategory(Enum):
    """Error categories for better handling."""
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    DATABASE = "database"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    CONFIGURATION = "configuration"
    SYSTEM = "system"
    UNKNOWN = "unknown"


@dataclass
class ErrorContext:
    """Error context for detailed logging."""
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    user_message: str
    details: Optional[Dict[str, Any]] = None
    exception: Optional[Exception] = None
    traceback_str: Optional[str] = None
    recovery_hint: Optional[str] = None


class MemoError(Exception):
    """Base exception for memo system."""

    def __init__(
        self,
        message: str,
        user_message: Optional[str] = None,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Dict[str, Any]] = None,
        recovery_hint: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.user_message = user_message or message
        self.category = category
        self.severity = severity
        self.details = details or {}
        self.recovery_hint = recovery_hint


class ValidationError(MemoError):
    """Input validation error."""

    def __init__(self, message: str, field: Optional[str] = None, **kwargs):
        details = kwargs.pop('details', {})
        if field:
            details['field'] = field
        super().__init__(
            message,
            category=ErrorCategory.VALIDATION,
            severity=ErrorSeverity.WARNING,
            details=details,
            **kwargs
        )


class AuthenticationError(MemoError):
    """Authentication failure."""

    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(
            message,
            user_message="Invalid username or password",
            category=ErrorCategory.AUTHENTICATION,
            severity=ErrorSeverity.ERROR,
            recovery_hint="Please check your credentials and try again",
            **kwargs
        )


class AuthorizationError(MemoError):
    """Authorization failure."""

    def __init__(self, message: str = "Access denied", **kwargs):
        super().__init__(
            message,
            user_message="You don't have permission to perform this action",
            category=ErrorCategory.AUTHORIZATION,
            severity=ErrorSeverity.ERROR,
            recovery_hint="Contact your administrator for access",
            **kwargs
        )


class DatabaseError(MemoError):
    """Database operation error."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            user_message="A database error occurred. Please try again",
            category=ErrorCategory.DATABASE,
            severity=ErrorSeverity.ERROR,
            recovery_hint="If the problem persists, contact support",
            **kwargs
        )


class FileSystemError(MemoError):
    """Filesystem operation error."""

    def __init__(self, message: str, path: Optional[Path] = None, **kwargs):
        details = kwargs.pop('details', {})
        if path:
            details['path'] = str(path)
        super().__init__(
            message,
            user_message="A file system error occurred",
            category=ErrorCategory.FILESYSTEM,
            severity=ErrorSeverity.ERROR,
            details=details,
            **kwargs
        )


class ConfigurationError(MemoError):
    """Configuration error."""

    def __init__(self, message: str, **kwargs):
        super().__init__(
            message,
            user_message="System configuration error",
            category=ErrorCategory.CONFIGURATION,
            severity=ErrorSeverity.CRITICAL,
            recovery_hint="Check system configuration and environment variables",
            **kwargs
        )


class ErrorHandler:
    """Centralized error handling."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._error_callbacks: Dict[ErrorCategory, list[Callable]] = {}

    def handle_error(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> ErrorContext:
        """Handle an error and return error context."""
        # Convert to MemoError if needed
        if isinstance(error, MemoError):
            memo_error = error
        else:
            memo_error = MemoError(
                str(error),
                category=self._categorize_error(error),
                severity=ErrorSeverity.ERROR,
                details=context or {}
            )

        # Create error context
        error_ctx = ErrorContext(
            category=memo_error.category,
            severity=memo_error.severity,
            message=memo_error.message,
            user_message=memo_error.user_message,
            details=memo_error.details,
            exception=error,
            traceback_str=traceback.format_exc() if self.verbose else None,
            recovery_hint=memo_error.recovery_hint
        )

        # Log error
        self._log_error(error_ctx)

        # Call registered callbacks
        self._execute_callbacks(error_ctx)

        return error_ctx

    def _categorize_error(self, error: Exception) -> ErrorCategory:
        """Categorize unknown exception types."""
        error_type = type(error).__name__.lower()

        if 'validation' in error_type or 'value' in error_type:
            return ErrorCategory.VALIDATION
        elif 'permission' in error_type or 'access' in error_type:
            return ErrorCategory.AUTHORIZATION
        elif 'database' in error_type or 'sqlite' in error_type:
            return ErrorCategory.DATABASE
        elif 'file' in error_type or 'io' in error_type:
            return ErrorCategory.FILESYSTEM
        elif 'network' in error_type or 'connection' in error_type:
            return ErrorCategory.NETWORK
        elif 'config' in error_type:
            return ErrorCategory.CONFIGURATION
        else:
            return ErrorCategory.UNKNOWN

    def _log_error(self, error_ctx: ErrorContext) -> None:
        """Log error with appropriate level."""
        log_message = f"[{error_ctx.category.value}] {error_ctx.message}"

        if error_ctx.details:
            log_message += f" | Details: {error_ctx.details}"

        if error_ctx.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message, exc_info=error_ctx.exception)
        elif error_ctx.severity == ErrorSeverity.ERROR:
            logger.error(log_message, exc_info=error_ctx.exception if self.verbose else None)
        elif error_ctx.severity == ErrorSeverity.WARNING:
            logger.warning(log_message)
        else:
            logger.info(log_message)

    def register_callback(self, category: ErrorCategory, callback: Callable) -> None:
        """Register error callback for specific category."""
        if category not in self._error_callbacks:
            self._error_callbacks[category] = []
        self._error_callbacks[category].append(callback)

    def _execute_callbacks(self, error_ctx: ErrorContext) -> None:
        """Execute registered callbacks for error category."""
        if error_ctx.category in self._error_callbacks:
            for callback in self._error_callbacks[error_ctx.category]:
                try:
                    callback(error_ctx)
                except Exception as e:
                    logger.error(f"Error in callback: {e}")


class UserFeedback:
    """User-friendly error messages and feedback."""

    @staticmethod
    def format_error(error_ctx: ErrorContext, include_details: bool = False) -> str:
        """Format error for user display."""
        lines = []

        # Severity indicator
        if error_ctx.severity == ErrorSeverity.CRITICAL:
            lines.append("✗ CRITICAL ERROR")
        elif error_ctx.severity == ErrorSeverity.ERROR:
            lines.append("✗ Error")
        elif error_ctx.severity == ErrorSeverity.WARNING:
            lines.append("⚠ Warning")
        else:
            lines.append("ℹ Information")

        # User message
        lines.append(f"  {error_ctx.user_message}")

        # Recovery hint
        if error_ctx.recovery_hint:
            lines.append(f"\n  → {error_ctx.recovery_hint}")

        # Details (if requested and available)
        if include_details and error_ctx.details:
            lines.append("\n  Details:")
            for key, value in error_ctx.details.items():
                lines.append(f"    • {key}: {value}")

        return '\n'.join(lines)

    @staticmethod
    def format_success(message: str) -> str:
        """Format success message."""
        return f"✓ {message}"

    @staticmethod
    def format_info(message: str) -> str:
        """Format informational message."""
        return f"ℹ {message}"

    @staticmethod
    def format_warning(message: str) -> str:
        """Format warning message."""
        return f"⚠ {message}"

    @staticmethod
    def format_progress(message: str, current: int, total: int) -> str:
        """Format progress message."""
        percentage = (current / total * 100) if total > 0 else 0
        bar_length = 30
        filled = int(bar_length * current / total) if total > 0 else 0
        bar = '█' * filled + '░' * (bar_length - filled)
        return f"{message} [{bar}] {percentage:.1f}% ({current}/{total})"


class RetryStrategy:
    """Automatic retry for transient failures."""

    def __init__(
        self,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff_multiplier: float = 2.0
    ):
        self.max_attempts = max_attempts
        self.delay_seconds = delay_seconds
        self.backoff_multiplier = backoff_multiplier

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with retry logic."""
        import time

        last_exception = None
        delay = self.delay_seconds

        for attempt in range(1, self.max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                logger.warning(f"Attempt {attempt}/{self.max_attempts} failed: {e}")

                if attempt < self.max_attempts:
                    time.sleep(delay)
                    delay *= self.backoff_multiplier

        raise last_exception


# Global error handler
_global_error_handler: Optional[ErrorHandler] = None


def get_error_handler(verbose: bool = False) -> ErrorHandler:
    """Get global error handler instance."""
    global _global_error_handler

    if _global_error_handler is None:
        _global_error_handler = ErrorHandler(verbose=verbose)

    return _global_error_handler


def handle_cli_error(error: Exception, verbose: bool = False) -> int:
    """Handle CLI errors and return exit code."""
    handler = get_error_handler(verbose=verbose)
    error_ctx = handler.handle_error(error)

    # Print user-friendly error
    print(UserFeedback.format_error(error_ctx, include_details=verbose), file=sys.stderr)

    # Return appropriate exit code
    if error_ctx.severity == ErrorSeverity.CRITICAL:
        return 2
    elif error_ctx.severity == ErrorSeverity.ERROR:
        return 1
    else:
        return 0


__all__ = [
    'ErrorSeverity',
    'ErrorCategory',
    'ErrorContext',
    'MemoError',
    'ValidationError',
    'AuthenticationError',
    'AuthorizationError',
    'DatabaseError',
    'FileSystemError',
    'ConfigurationError',
    'ErrorHandler',
    'UserFeedback',
    'RetryStrategy',
    'get_error_handler',
    'handle_cli_error',
]

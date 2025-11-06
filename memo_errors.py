#!/usr/bin/env python3
"""Improved error handling and user experience for memo system."""

from typing import Optional
import sys


class MemoError(Exception):
    """Base exception for memo system errors."""

    def __init__(self, message: str, details: Optional[str] = None, suggestion: Optional[str] = None):
        self.message = message
        self.details = details
        self.suggestion = suggestion
        super().__init__(message)

    def format_user_message(self) -> str:
        """Format error message for end user."""
        msg = f"❌ Error: {self.message}"

        if self.details:
            msg += f"\n   Details: {self.details}"

        if self.suggestion:
            msg += f"\n   💡 Suggestion: {self.suggestion}"

        return msg


class ValidationError(MemoError):
    """Validation error with helpful context."""
    pass


class SecurityError(MemoError):
    """Security-related error."""
    pass


class StorageError(MemoError):
    """Storage/persistence error."""
    pass


class NotFoundError(MemoError):
    """Resource not found error."""
    pass


class DuplicateError(MemoError):
    """Duplicate resource error."""
    pass


class RateLimitError(MemoError):
    """Rate limit exceeded error."""
    pass


def format_validation_error(field: str, value: any, reason: str) -> ValidationError:
    """Create formatted validation error."""
    return ValidationError(
        f"Invalid {field}",
        details=f"Value '{value}' is invalid: {reason}",
        suggestion=f"Please provide a valid {field}"
    )


def format_not_found_error(resource_type: str, identifier: str) -> NotFoundError:
    """Create formatted not found error."""
    return NotFoundError(
        f"{resource_type.capitalize()} not found",
        details=f"No {resource_type} found with identifier '{identifier}'",
        suggestion=f"Use 'memo list' to see available {resource_type}s"
    )


def format_storage_error(operation: str, path: str, reason: str) -> StorageError:
    """Create formatted storage error."""
    return StorageError(
        f"Storage {operation} failed",
        details=f"Could not {operation} '{path}': {reason}",
        suggestion="Check file permissions and disk space"
    )


def format_security_error(check: str, reason: str) -> SecurityError:
    """Create formatted security error."""
    return SecurityError(
        f"Security check failed: {check}",
        details=reason,
        suggestion="Review input for potentially unsafe content"
    )


def print_error(error: Exception, verbose: bool = False) -> None:
    """Print error in user-friendly format."""
    if isinstance(error, MemoError):
        try:
            print(error.format_user_message(), file=sys.stderr)
        except UnicodeEncodeError:
            msg = error.format_user_message().replace("❌", "[ERROR]").replace("💡", "[TIP]")
            print(msg, file=sys.stderr)
    else:
        try:
            print(f"❌ Error: {str(error)}", file=sys.stderr)
        except UnicodeEncodeError:
            print(f"[ERROR] {str(error)}", file=sys.stderr)

    if verbose and hasattr(error, '__traceback__'):
        import traceback
        print("\nStack trace:", file=sys.stderr)
        traceback.print_exception(type(error), error, error.__traceback__)


def print_success(message: str, details: Optional[str] = None) -> None:
    """Print success message."""
    try:
        print(f"✅ {message}")
    except UnicodeEncodeError:
        print(f"[OK] {message}")
    if details:
        print(f"   {details}")


def print_warning(message: str, details: Optional[str] = None) -> None:
    """Print warning message."""
    try:
        print(f"⚠️  Warning: {message}", file=sys.stderr)
    except UnicodeEncodeError:
        print(f"[WARNING] {message}", file=sys.stderr)
    if details:
        print(f"   {details}", file=sys.stderr)


def print_info(message: str, details: Optional[str] = None) -> None:
    """Print info message."""
    print(f"ℹ️  {message}")
    if details:
        print(f"   {details}")


def confirm_action(prompt: str, default: bool = False) -> bool:
    """Ask user to confirm an action."""
    suffix = " [Y/n]: " if default else " [y/N]: "

    try:
        response = input(prompt + suffix).strip().lower()

        if not response:
            return default

        return response in ('y', 'yes')
    except (KeyboardInterrupt, EOFError):
        print()
        return False


def get_user_input(prompt: str, default: Optional[str] = None, required: bool = True) -> Optional[str]:
    """Get input from user with validation."""
    suffix = f" [{default}]: " if default else ": "

    try:
        value = input(prompt + suffix).strip()

        if not value and default:
            return default

        if required and not value:
            print_error(ValidationError("Input required"))
            return get_user_input(prompt, default, required)

        return value if value else None

    except (KeyboardInterrupt, EOFError):
        print()
        return None


def format_bytes(size: int) -> str:
    """Format bytes in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text

    return text[:max_length - len(suffix)] + suffix


def format_list(items: list, max_items: int = 10) -> str:
    """Format list for display."""
    if not items:
        return "(none)"

    if len(items) <= max_items:
        return ", ".join(str(item) for item in items)

    shown = items[:max_items]
    remaining = len(items) - max_items

    return ", ".join(str(item) for item in shown) + f" ... and {remaining} more"

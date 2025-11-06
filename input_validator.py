#!/usr/bin/env python3
"""
Input Validation and Sanitization
=================================
Production-grade input validation for all user-facing operations.
"""

import re
import html
from datetime import datetime
from typing import Any, Optional, Union
from pathlib import Path


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class InputValidator:
    """Comprehensive input validation."""

    # Regex patterns
    SAFE_ALPHANUMERIC = re.compile(r'^[a-zA-Z0-9_-]+$')
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    DATE_ISO_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    DATETIME_ISO_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')

    # Dangerous patterns
    SQL_INJECTION_PATTERNS = [
        re.compile(r"('\s*(or|and)\s*')", re.I),
        re.compile(r"('\s*=\s*')", re.I),
        re.compile(r"(;\s*drop\s+table)", re.I),
        re.compile(r"(;\s*delete\s+from)", re.I),
        re.compile(r"(union\s+select)", re.I),
        re.compile(r"(--\s*$)", re.I),
    ]

    XSS_PATTERNS = [
        re.compile(r'<script[^>]*>.*?</script>', re.I | re.S),
        re.compile(r'javascript:', re.I),
        re.compile(r'on\w+\s*=', re.I),
        re.compile(r'<iframe', re.I),
    ]

    PATH_TRAVERSAL_PATTERNS = [
        re.compile(r'\.\.[\\/]'),
        re.compile(r'[\\/]\.\.'),
        re.compile(r'^[\\/]'),
    ]

    @staticmethod
    def validate_string(
        value: Any,
        min_length: int = 0,
        max_length: int = 10000,
        allow_empty: bool = False,
        pattern: Optional[re.Pattern] = None,
        field_name: str = "Input"
    ) -> str:
        """Validate string input."""
        if value is None:
            if allow_empty:
                return ""
            raise ValidationError(f"{field_name} cannot be null")

        if not isinstance(value, str):
            raise ValidationError(f"{field_name} must be a string")

        if not allow_empty and not value.strip():
            raise ValidationError(f"{field_name} cannot be empty")

        if len(value) < min_length:
            raise ValidationError(f"{field_name} must be at least {min_length} characters")

        if len(value) > max_length:
            raise ValidationError(f"{field_name} must not exceed {max_length} characters")

        if pattern and not pattern.match(value):
            raise ValidationError(f"{field_name} format is invalid")

        return value

    @staticmethod
    def validate_integer(
        value: Any,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        field_name: str = "Input"
    ) -> int:
        """Validate integer input."""
        if value is None:
            raise ValidationError(f"{field_name} cannot be null")

        try:
            int_value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{field_name} must be an integer")

        if min_value is not None and int_value < min_value:
            raise ValidationError(f"{field_name} must be at least {min_value}")

        if max_value is not None and int_value > max_value:
            raise ValidationError(f"{field_name} must not exceed {max_value}")

        return int_value

    @staticmethod
    def validate_boolean(value: Any, field_name: str = "Input") -> bool:
        """Validate boolean input."""
        if isinstance(value, bool):
            return value

        if isinstance(value, str):
            lower = value.lower().strip()
            if lower in ('true', '1', 'yes', 'on'):
                return True
            if lower in ('false', '0', 'no', 'off'):
                return False

        if isinstance(value, int):
            if value == 1:
                return True
            if value == 0:
                return False

        raise ValidationError(f"{field_name} must be a boolean value")

    @staticmethod
    def validate_enum(
        value: Any,
        allowed_values: set,
        field_name: str = "Input"
    ) -> str:
        """Validate enum/choice input."""
        if value not in allowed_values:
            allowed = ', '.join(sorted(str(v) for v in allowed_values))
            raise ValidationError(f"{field_name} must be one of: {allowed}")

        return value

    @staticmethod
    def validate_email(email: str) -> str:
        """Validate email address."""
        email = email.strip().lower()

        if not InputValidator.EMAIL_PATTERN.match(email):
            raise ValidationError("Invalid email address format")

        if len(email) > 254:  # RFC 5321
            raise ValidationError("Email address is too long")

        return email

    @staticmethod
    def validate_uuid(uuid_str: str) -> str:
        """Validate UUID format."""
        uuid_str = uuid_str.strip().lower()

        if not InputValidator.UUID_PATTERN.match(uuid_str):
            raise ValidationError("Invalid UUID format")

        return uuid_str

    @staticmethod
    def validate_datetime(
        dt_str: str,
        allow_future: bool = True,
        field_name: str = "Date"
    ) -> datetime:
        """Validate and parse datetime string."""
        formats = [
            '%Y-%m-%d',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S%z',
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(dt_str, fmt)

                if not allow_future and dt > datetime.now():
                    raise ValidationError(f"{field_name} cannot be in the future")

                return dt
            except ValueError:
                continue

        raise ValidationError(f"{field_name} has invalid datetime format")

    @classmethod
    def detect_sql_injection(cls, text: str) -> bool:
        """Detect potential SQL injection attempts."""
        for pattern in cls.SQL_INJECTION_PATTERNS:
            if pattern.search(text):
                return True
        return False

    @classmethod
    def detect_xss(cls, text: str) -> bool:
        """Detect potential XSS attempts."""
        for pattern in cls.XSS_PATTERNS:
            if pattern.search(text):
                return True
        return False

    @classmethod
    def detect_path_traversal(cls, path_str: str) -> bool:
        """Detect path traversal attempts."""
        for pattern in cls.PATH_TRAVERSAL_PATTERNS:
            if pattern.search(path_str):
                return True
        return False

    @classmethod
    def sanitize_text(cls, text: str, max_length: Optional[int] = None) -> str:
        """Sanitize text input for safe storage and display."""
        # Remove null bytes
        text = text.replace('\x00', '')

        # Normalize line endings
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # Remove control characters except newline and tab
        text = ''.join(char for char in text if char in '\n\t' or ord(char) >= 32)

        # Truncate if needed
        if max_length and len(text) > max_length:
            text = text[:max_length]

        return text

    @classmethod
    def sanitize_html(cls, text: str) -> str:
        """Sanitize HTML to prevent XSS."""
        return html.escape(text)

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """Sanitize filename for safe filesystem operations."""
        # Remove path components
        filename = Path(filename).name

        # Remove dangerous characters
        filename = re.sub(r'[^\w\s.-]', '', filename)

        # Remove leading/trailing dots and spaces
        filename = filename.strip('. ')

        # Limit length
        if len(filename) > 255:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            filename = name[:255-len(ext)-1] + '.' + ext if ext else name[:255]

        if not filename:
            raise ValidationError("Invalid filename")

        return filename

    @classmethod
    def validate_memo_content(cls, content: str) -> str:
        """Validate memo content with security checks."""
        if cls.detect_sql_injection(content):
            raise ValidationError("Content contains potentially dangerous patterns")

        if cls.detect_xss(content):
            raise ValidationError("Content contains potentially dangerous HTML/JavaScript")

        content = cls.sanitize_text(content, max_length=1_048_576)  # 1MB limit

        return content

    @classmethod
    def validate_search_query(cls, query: str) -> str:
        """Validate search query input."""
        query = query.strip()

        if not query:
            raise ValidationError("Search query cannot be empty")

        if len(query) > 500:
            raise ValidationError("Search query is too long")

        if cls.detect_sql_injection(query):
            raise ValidationError("Search query contains invalid characters")

        return query

    @classmethod
    def validate_tag(cls, tag: str) -> str:
        """Validate tag format."""
        tag = tag.strip().lower()

        if not tag:
            raise ValidationError("Tag cannot be empty")

        if len(tag) > 50:
            raise ValidationError("Tag is too long (max 50 characters)")

        if not re.match(r'^[a-z0-9_-]+$', tag):
            raise ValidationError("Tag can only contain lowercase letters, numbers, hyphens, and underscores")

        return tag

    @classmethod
    def validate_category(cls, category: str) -> str:
        """Validate category format."""
        category = category.strip()

        if not category:
            raise ValidationError("Category cannot be empty")

        if len(category) > 100:
            raise ValidationError("Category is too long (max 100 characters)")

        if not re.match(r'^[a-zA-Z0-9_\s-]+$', category):
            raise ValidationError("Category contains invalid characters")

        return category

    @classmethod
    def validate_content_format(cls, content_format: str) -> str:
        """Validate content format."""
        content_format = content_format.strip().lower()

        allowed_formats = {'plain', 'markdown'}

        if content_format not in allowed_formats:
            allowed = ', '.join(sorted(allowed_formats))
            raise ValidationError(f"Content format must be one of: {allowed}")

        return content_format


class RateLimiter:
    """Simple in-memory rate limiter for API protection."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed under rate limit."""
        import time

        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        if identifier in self._requests:
            self._requests[identifier] = [
                req_time for req_time in self._requests[identifier]
                if req_time > window_start
            ]
        else:
            self._requests[identifier] = []

        # Check limit
        if len(self._requests[identifier]) >= self.max_requests:
            return False

        # Record request
        self._requests[identifier].append(now)
        return True

    def get_remaining(self, identifier: str) -> int:
        """Get remaining requests in current window."""
        import time

        now = time.time()
        window_start = now - self.window_seconds

        if identifier not in self._requests:
            return self.max_requests

        recent_requests = [
            req_time for req_time in self._requests[identifier]
            if req_time > window_start
        ]

        return max(0, self.max_requests - len(recent_requests))

    def reset(self, identifier: str) -> None:
        """Reset rate limit for an identifier."""
        if identifier in self._requests:
            del self._requests[identifier]


__all__ = [
    'ValidationError',
    'InputValidator',
    'RateLimiter',
]

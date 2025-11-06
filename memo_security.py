#!/usr/bin/env python3
"""Security enhancements for memo system."""

import re
import html
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timezone


class SecurityValidator:
    """Security validation for memo inputs."""

    # Maximum sizes
    MAX_TEXT_LENGTH = 1_000_000  # 1MB of text
    MAX_TAG_LENGTH = 128
    MAX_TAGS_PER_MEMO = 50
    MAX_CATEGORY_LENGTH = 256
    MAX_LINKS_PER_MEMO = 100

    # Patterns
    SAFE_TAG_PATTERN = re.compile(r'^[\w\-\_]+$')
    SAFE_CATEGORY_PATTERN = re.compile(r'^[\w\-\_\.]+$')
    PATH_TRAVERSAL_PATTERN = re.compile(r'\.\.[/\\]')
    CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]')

    @classmethod
    def validate_text(cls, text: str) -> tuple[bool, Optional[str]]:
        """Validate memo text content."""
        if not isinstance(text, str):
            return False, "Text must be a string"

        if not text.strip():
            return False, "Text cannot be empty"

        if len(text) > cls.MAX_TEXT_LENGTH:
            return False, f"Text exceeds maximum length of {cls.MAX_TEXT_LENGTH} characters"

        # Check for control characters (except newlines, tabs, carriage returns)
        if cls.CONTROL_CHAR_PATTERN.search(text):
            return False, "Text contains invalid control characters"

        return True, None

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        """Sanitize text by removing dangerous content."""
        if not isinstance(text, str):
            return ""

        # Remove null bytes and other control characters
        text = cls.CONTROL_CHAR_PATTERN.sub('', text)

        # Normalize whitespace
        text = text.strip()

        # Truncate if too long
        if len(text) > cls.MAX_TEXT_LENGTH:
            text = text[:cls.MAX_TEXT_LENGTH]

        return text

    @classmethod
    def validate_tag(cls, tag: str) -> tuple[bool, Optional[str]]:
        """Validate a single tag."""
        if not isinstance(tag, str):
            return False, "Tag must be a string"

        tag = tag.strip()

        if not tag:
            return False, "Tag cannot be empty"

        if len(tag) > cls.MAX_TAG_LENGTH:
            return False, f"Tag exceeds maximum length of {cls.MAX_TAG_LENGTH} characters"

        # Tags should only contain alphanumeric, hyphen, underscore
        if not cls.SAFE_TAG_PATTERN.match(tag):
            return False, "Tag contains invalid characters (use only letters, numbers, -, _)"

        return True, None

    @classmethod
    def sanitize_tag(cls, tag: str) -> Optional[str]:
        """Sanitize a tag, return None if invalid."""
        if not isinstance(tag, str):
            return None

        tag = tag.strip()

        if not tag:
            return None

        # Remove non-alphanumeric except hyphen and underscore
        tag = re.sub(r'[^\w\-]', '', tag)

        # Truncate if too long
        if len(tag) > cls.MAX_TAG_LENGTH:
            tag = tag[:cls.MAX_TAG_LENGTH]

        return tag if tag else None

    @classmethod
    def validate_tags(cls, tags: List[str]) -> tuple[bool, Optional[str]]:
        """Validate a list of tags."""
        if not isinstance(tags, list):
            return False, "Tags must be a list"

        if len(tags) > cls.MAX_TAGS_PER_MEMO:
            return False, f"Too many tags (maximum {cls.MAX_TAGS_PER_MEMO})"

        for tag in tags:
            valid, error = cls.validate_tag(tag)
            if not valid:
                return False, f"Invalid tag '{tag}': {error}"

        return True, None

    @classmethod
    def sanitize_tags(cls, tags: List[str]) -> List[str]:
        """Sanitize a list of tags."""
        if not isinstance(tags, list):
            return []

        sanitized = []
        seen = set()

        for tag in tags[:cls.MAX_TAGS_PER_MEMO]:  # Limit count
            clean_tag = cls.sanitize_tag(tag)
            if clean_tag and clean_tag not in seen:
                sanitized.append(clean_tag)
                seen.add(clean_tag)

        return sanitized

    @classmethod
    def validate_category(cls, category: str) -> tuple[bool, Optional[str]]:
        """Validate category name."""
        if not isinstance(category, str):
            return False, "Category must be a string"

        category = category.strip()

        if not category:
            return False, "Category cannot be empty"

        if len(category) > cls.MAX_CATEGORY_LENGTH:
            return False, f"Category exceeds maximum length of {cls.MAX_CATEGORY_LENGTH} characters"

        # Check for path traversal attempts
        if cls.PATH_TRAVERSAL_PATTERN.search(category):
            return False, "Category contains path traversal sequence"

        # Categories should be filesystem-safe
        if not cls.SAFE_CATEGORY_PATTERN.match(category):
            return False, "Category contains invalid characters"

        return True, None

    @classmethod
    def sanitize_category(cls, category: str) -> str:
        """Sanitize category name."""
        if not isinstance(category, str):
            return "default"

        category = category.strip()

        if not category:
            return "default"

        # Remove path traversal sequences
        category = category.replace("..", "")

        # Keep only safe characters
        category = re.sub(r'[^\w\-\.]', '_', category)

        # Truncate if too long
        if len(category) > cls.MAX_CATEGORY_LENGTH:
            category = category[:cls.MAX_CATEGORY_LENGTH]

        return category if category else "default"

    @classmethod
    def validate_status(cls, status: str) -> tuple[bool, Optional[str]]:
        """Validate status value."""
        valid_statuses = {"active", "completed", "archived"}

        if not isinstance(status, str):
            return False, "Status must be a string"

        if status not in valid_statuses:
            return False, f"Invalid status (must be one of: {', '.join(valid_statuses)})"

        return True, None

    @classmethod
    def validate_path(cls, path: Path) -> tuple[bool, Optional[str]]:
        """Validate that a path is safe and doesn't escape intended directory."""
        try:
            # Resolve to absolute path
            resolved = path.resolve()

            # Check for path traversal in string representation
            if ".." in str(path):
                return False, "Path contains parent directory references"

            # Check that path doesn't contain null bytes
            if '\x00' in str(path):
                return False, "Path contains null bytes"

            return True, None
        except (ValueError, OSError) as e:
            return False, f"Invalid path: {e}"

    @classmethod
    def validate_memo_id(cls, memo_id: str) -> tuple[bool, Optional[str]]:
        """Validate memo ID format."""
        if not isinstance(memo_id, str):
            return False, "Memo ID must be a string"

        if not memo_id:
            return False, "Memo ID cannot be empty"

        # Memo IDs should be timestamp-based: YYYYMMDDHHMMSSffffff
        if not re.match(r'^\d{20}$', memo_id):
            return False, "Invalid memo ID format"

        return True, None

    @classmethod
    def validate_timestamp(cls, timestamp: str) -> tuple[bool, Optional[str]]:
        """Validate ISO timestamp."""
        if not isinstance(timestamp, str):
            return False, "Timestamp must be a string"

        try:
            datetime.fromisoformat(timestamp)
            return True, None
        except (ValueError, TypeError) as e:
            return False, f"Invalid timestamp format: {e}"

    @classmethod
    def html_escape(cls, text: str) -> str:
        """Escape HTML special characters."""
        return html.escape(text, quote=True)

    @classmethod
    def validate_link_count(cls, links: List[str]) -> tuple[bool, Optional[str]]:
        """Validate number of links."""
        if not isinstance(links, list):
            return False, "Links must be a list"

        if len(links) > cls.MAX_LINKS_PER_MEMO:
            return False, f"Too many links (maximum {cls.MAX_LINKS_PER_MEMO})"

        return True, None


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self):
        self._operations = {}

    def check_rate_limit(
        self,
        operation: str,
        limit: int = 100,
        window_seconds: int = 60
    ) -> tuple[bool, Optional[str]]:
        """Check if operation is within rate limit."""
        now = datetime.now(timezone.utc)

        if operation not in self._operations:
            self._operations[operation] = []

        # Remove old entries outside window
        cutoff = now.timestamp() - window_seconds
        self._operations[operation] = [
            ts for ts in self._operations[operation]
            if ts > cutoff
        ]

        # Check limit
        if len(self._operations[operation]) >= limit:
            return False, f"Rate limit exceeded for {operation} (max {limit} per {window_seconds}s)"

        # Record this operation
        self._operations[operation].append(now.timestamp())

        return True, None

    def reset(self, operation: Optional[str] = None):
        """Reset rate limit counters."""
        if operation:
            self._operations.pop(operation, None)
        else:
            self._operations.clear()


# Global rate limiter instance
_rate_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter instance."""
    return _rate_limiter

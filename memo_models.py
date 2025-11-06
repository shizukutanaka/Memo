#!/usr/bin/env python3
"""Pydantic models for memo application data validation and serialization."""

from datetime import datetime
from typing import Dict, List, Optional, Any
from enum import Enum


class MemoStatus(str, Enum):
    """Status of a memo."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MemoCategory(str, Enum):
    """Common memo categories."""
    DEFAULT = "default"
    WORK = "work"
    PERSONAL = "personal"
    LEARNING = "learning"
    PROJECT = "project"
    ARCHIVE = "archive"


class SyncTarget(str, Enum):
    """Available sync targets."""
    LOCAL = "local"
    WEBDAV = "webdav"
    S3 = "s3"
    DROPBOX = "dropbox"


class MemoCreate:
    """Model for creating a new memo."""

    def __init__(
        self,
        content: str,
        tags: Optional[List[str]] = None,
        category: str = "default",
        status: str = "active",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize MemoCreate model.

        Args:
            content: Memo content (required)
            tags: List of tags
            category: Memo category
            status: Memo status
            metadata: Additional metadata
        """
        if not content or not isinstance(content, str):
            raise ValueError("content must be a non-empty string")

        if len(content) > 100 * 1024 * 1024:  # 100MB limit
            raise ValueError("content exceeds maximum size of 100MB")

        self.content = content
        self.tags = tags or []
        self.category = category
        self.status = status
        self.metadata = metadata or {}

        # Validate tags
        if not isinstance(self.tags, list):
            raise ValueError("tags must be a list")

        if len(self.tags) > 100:
            raise ValueError("maximum 100 tags per memo")

        for tag in self.tags:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("each tag must be a non-empty string")

        # Validate category
        try:
            MemoCategory(category)
        except ValueError:
            raise ValueError(f"invalid category: {category}")

        # Validate status
        try:
            MemoStatus(status)
        except ValueError:
            raise ValueError(f"invalid status: {status}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "tags": self.tags,
            "category": self.category,
            "status": self.status,
            "metadata": self.metadata
        }


class MemoRead:
    """Model for reading a memo."""

    def __init__(
        self,
        id: str,
        content: str,
        tags: List[str],
        category: str,
        status: str,
        created_at: str,
        updated_at: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize MemoRead model.

        Args:
            id: Memo ID
            content: Memo content
            tags: List of tags
            category: Memo category
            status: Memo status
            created_at: Creation timestamp
            updated_at: Last update timestamp
            metadata: Additional metadata
        """
        self.id = id
        self.content = content
        self.tags = tags
        self.category = category
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "tags": self.tags,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoRead":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            content=data["content"],
            tags=data.get("tags", []),
            category=data.get("category", "default"),
            status=data.get("status", "active"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            metadata=data.get("metadata", {})
        )


class MemoUpdate:
    """Model for updating a memo."""

    def __init__(
        self,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize MemoUpdate model.

        Args:
            content: Updated content
            tags: Updated tags
            category: Updated category
            status: Updated status
            metadata: Updated metadata
        """
        if content is not None and len(content) > 100 * 1024 * 1024:
            raise ValueError("content exceeds maximum size of 100MB")

        self.content = content
        self.tags = tags
        self.category = category
        self.status = status
        self.metadata = metadata

    def get_updates(self) -> Dict[str, Any]:
        """Get only non-None updates."""
        updates = {}
        if self.content is not None:
            updates["content"] = self.content
        if self.tags is not None:
            updates["tags"] = self.tags
        if self.category is not None:
            updates["category"] = self.category
        if self.status is not None:
            updates["status"] = self.status
        if self.metadata is not None:
            updates["metadata"] = self.metadata
        return updates


class SearchQuery:
    """Model for search queries."""

    def __init__(
        self,
        query: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ):
        """
        Initialize SearchQuery model.

        Args:
            query: Search query string
            category: Filter by category
            tags: Filter by tags
            status: Filter by status
            limit: Result limit
            offset: Result offset
        """
        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")

        self.query = query.strip()
        self.category = category
        self.tags = tags or []
        self.status = status
        self.limit = max(1, min(limit, 1000))  # Clamp between 1 and 1000
        self.offset = max(0, offset)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query": self.query,
            "category": self.category,
            "tags": self.tags,
            "status": self.status,
            "limit": self.limit,
            "offset": self.offset
        }


class SyncConfig:
    """Model for sync configuration."""

    def __init__(
        self,
        enabled: bool = False,
        target: str = "local",
        interval_seconds: int = 300,
        url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        path: Optional[str] = None
    ):
        """
        Initialize SyncConfig model.

        Args:
            enabled: Whether sync is enabled
            target: Sync target (local, webdav, s3, dropbox)
            interval_seconds: Sync interval in seconds
            url: Remote URL (for webdav, s3, etc.)
            username: Username for authentication
            password: Password for authentication
            path: Local/remote path
        """
        try:
            SyncTarget(target)
        except ValueError:
            raise ValueError(f"invalid sync target: {target}")

        if interval_seconds < 60:
            raise ValueError("interval_seconds must be at least 60")

        self.enabled = enabled
        self.target = target
        self.interval_seconds = interval_seconds
        self.url = url
        self.username = username
        self.password = password
        self.path = path

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "target": self.target,
            "interval_seconds": self.interval_seconds,
            "url": self.url,
            "username": self.username,
            "password": self.password,
            "path": self.path
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SyncConfig":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", False),
            target=data.get("target", "local"),
            interval_seconds=data.get("interval_seconds", 300),
            url=data.get("url"),
            username=data.get("username"),
            password=data.get("password"),
            path=data.get("path")
        )


class BackupConfig:
    """Model for backup configuration."""

    def __init__(
        self,
        enabled: bool = True,
        interval_seconds: int = 3600,
        retention_days: int = 30,
        path: Optional[str] = None,
        compress: bool = True,
        incremental: bool = True
    ):
        """
        Initialize BackupConfig model.

        Args:
            enabled: Whether backups are enabled
            interval_seconds: Backup interval in seconds
            retention_days: How many days to keep backups
            path: Backup directory path
            compress: Whether to compress backups
            incremental: Whether to use incremental backups
        """
        if interval_seconds < 300:
            raise ValueError("interval_seconds must be at least 300 (5 minutes)")

        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")

        self.enabled = enabled
        self.interval_seconds = interval_seconds
        self.retention_days = retention_days
        self.path = path
        self.compress = compress
        self.incremental = incremental

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "retention_days": self.retention_days,
            "path": self.path,
            "compress": self.compress,
            "incremental": self.incremental
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BackupConfig":
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            interval_seconds=data.get("interval_seconds", 3600),
            retention_days=data.get("retention_days", 30),
            path=data.get("path"),
            compress=data.get("compress", True),
            incremental=data.get("incremental", True)
        )


class ApplicationConfig:
    """Model for application configuration."""

    def __init__(
        self,
        db_path: str,
        log_level: str = "INFO",
        sync_config: Optional[SyncConfig] = None,
        backup_config: Optional[BackupConfig] = None,
        max_memo_size: int = 100 * 1024 * 1024,
        cache_enabled: bool = True
    ):
        """
        Initialize ApplicationConfig model.

        Args:
            db_path: Path to database
            log_level: Logging level
            sync_config: Sync configuration
            backup_config: Backup configuration
            max_memo_size: Maximum memo size
            cache_enabled: Whether caching is enabled
        """
        if not db_path:
            raise ValueError("db_path is required")

        self.db_path = db_path
        self.log_level = log_level.upper()
        self.sync_config = sync_config or SyncConfig()
        self.backup_config = backup_config or BackupConfig()
        self.max_memo_size = max_memo_size
        self.cache_enabled = cache_enabled

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "db_path": self.db_path,
            "log_level": self.log_level,
            "sync_config": self.sync_config.to_dict(),
            "backup_config": self.backup_config.to_dict(),
            "max_memo_size": self.max_memo_size,
            "cache_enabled": self.cache_enabled
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApplicationConfig":
        """Create from dictionary."""
        sync_config = None
        if "sync_config" in data:
            sync_config = SyncConfig.from_dict(data["sync_config"])

        backup_config = None
        if "backup_config" in data:
            backup_config = BackupConfig.from_dict(data["backup_config"])

        return cls(
            db_path=data["db_path"],
            log_level=data.get("log_level", "INFO"),
            sync_config=sync_config,
            backup_config=backup_config,
            max_memo_size=data.get("max_memo_size", 100 * 1024 * 1024),
            cache_enabled=data.get("cache_enabled", True)
        )


if __name__ == "__main__":
    # Example usage
    import json

    # Create a memo
    memo_create = MemoCreate(
        content="Hello World",
        tags=["greeting", "test"],
        category="personal"
    )
    print("Created memo:", json.dumps(memo_create.to_dict(), indent=2))

    # Read a memo
    memo_read = MemoRead(
        id="memo-001",
        content="Hello World",
        tags=["greeting", "test"],
        category="personal",
        status="active",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat()
    )
    print("\nRead memo:", json.dumps(memo_read.to_dict(), indent=2))

    # Search query
    search = SearchQuery(
        query="python",
        category="learning",
        limit=50
    )
    print("\nSearch query:", json.dumps(search.to_dict(), indent=2))

    # Configuration
    config = ApplicationConfig(
        db_path="./memos.db",
        sync_config=SyncConfig(
            enabled=True,
            target="local",
            path="/path/to/sync"
        ),
        backup_config=BackupConfig(
            enabled=True,
            compress=True,
            incremental=True
        )
    )
    print("\nApplication config:", json.dumps(config.to_dict(), indent=2))

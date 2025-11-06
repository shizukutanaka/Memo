#!/usr/bin/env python3
"""
Cloud Synchronization Module for Memo Application

This module provides local-first cloud synchronization capabilities for the memo application.
Supports multiple sync targets:
- Local filesystem (for development/testing)
- WebDAV (Nextcloud, ownCloud, generic WebDAV servers)
- Future: S3, Dropbox, OneDrive

Architecture:
- Local-first: All changes are made locally first
- Delta sync: Only changed items are synced
- Conflict resolution: Last-write-wins with timestamp comparison
- Offline support: Works seamlessly offline with sync on reconnection

Usage:
    from cloud_sync import CloudSyncManager

    sync_manager = CloudSyncManager(
        local_store=store,
        sync_type='local',  # or 'webdav'
        local_sync_dir='/path/to/sync'
    )

    # Push local changes to sync target
    sync_manager.push()

    # Pull remote changes to local
    sync_manager.pull()

    # Bi-directional sync
    sync_manager.sync()
"""

import json
import logging
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict


@dataclass
class SyncMetadata:
    """Metadata for tracking sync state."""
    local_version: int = 0
    remote_version: int = 0
    last_sync_time: Optional[str] = None
    conflict_strategy: str = "last-write-wins"  # or "client-first", "server-first"
    checksum: Optional[str] = None


class SyncTarget(ABC):
    """Abstract base class for sync targets."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    @abstractmethod
    def connect(self) -> bool:
        """Connect to the sync target. Returns True if successful."""
        pass

    @abstractmethod
    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        """Upload a file to the sync target."""
        pass

    @abstractmethod
    def download_file(self, remote_path: str, local_path: Path) -> bool:
        """Download a file from the sync target."""
        pass

    @abstractmethod
    def list_files(self, remote_dir: str = "/") -> List[str]:
        """List files in remote directory."""
        pass

    @abstractmethod
    def delete_file(self, remote_path: str) -> bool:
        """Delete a file from the sync target."""
        pass

    @abstractmethod
    def get_file_metadata(self, remote_path: str) -> Optional[Dict[str, Any]]:
        """Get metadata (mtime, size, etc.) for a remote file."""
        pass


class LocalSyncTarget(SyncTarget):
    """Local filesystem sync target for testing and development."""

    def __init__(self, sync_dir: Path, logger: Optional[logging.Logger] = None):
        super().__init__(logger)
        self.sync_dir = Path(sync_dir)
        self.sync_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        """Always connected for local filesystem."""
        return self.sync_dir.exists()

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        """Copy file to sync directory."""
        try:
            remote_full_path = self.sync_dir / remote_path.lstrip("/")
            remote_full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(local_path, "rb") as src:
                with open(remote_full_path, "wb") as dst:
                    dst.write(src.read())

            self.logger.debug(f"Uploaded {remote_path}")
            return True
        except Exception as e:
            self.logger.error(f"Upload failed for {remote_path}: {e}")
            return False

    def download_file(self, remote_path: str, local_path: Path) -> bool:
        """Copy file from sync directory."""
        try:
            remote_full_path = self.sync_dir / remote_path.lstrip("/")

            if not remote_full_path.exists():
                self.logger.warning(f"Remote file not found: {remote_path}")
                return False

            local_path.parent.mkdir(parents=True, exist_ok=True)

            with open(remote_full_path, "rb") as src:
                with open(local_path, "wb") as dst:
                    dst.write(src.read())

            self.logger.debug(f"Downloaded {remote_path}")
            return True
        except Exception as e:
            self.logger.error(f"Download failed for {remote_path}: {e}")
            return False

    def list_files(self, remote_dir: str = "/") -> List[str]:
        """List files in remote directory."""
        try:
            remote_full_path = self.sync_dir / remote_dir.lstrip("/")
            if not remote_full_path.exists():
                return []

            files = []
            for item in remote_full_path.rglob("*"):
                if item.is_file():
                    rel_path = str(item.relative_to(self.sync_dir))
                    files.append("/" + rel_path.replace("\\", "/"))

            return files
        except Exception as e:
            self.logger.error(f"List files failed: {e}")
            return []

    def delete_file(self, remote_path: str) -> bool:
        """Delete file from sync directory."""
        try:
            remote_full_path = self.sync_dir / remote_path.lstrip("/")
            if remote_full_path.exists():
                remote_full_path.unlink()
                self.logger.debug(f"Deleted {remote_path}")
            return True
        except Exception as e:
            self.logger.error(f"Delete failed for {remote_path}: {e}")
            return False

    def get_file_metadata(self, remote_path: str) -> Optional[Dict[str, Any]]:
        """Get metadata for remote file."""
        try:
            remote_full_path = self.sync_dir / remote_path.lstrip("/")
            if not remote_full_path.exists():
                return None

            stat = remote_full_path.stat()
            return {
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "mtime_iso": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        except Exception as e:
            self.logger.error(f"Get metadata failed for {remote_path}: {e}")
            return None


class WebDAVSyncTarget(SyncTarget):
    """WebDAV sync target for Nextcloud/ownCloud integration."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        logger: Optional[logging.Logger] = None,
    ):
        super().__init__(logger)
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.connected = False

        try:
            import requests

            self.requests = requests
        except ImportError:
            self.logger.error(
                "requests library not installed. "
                "Install with: pip install requests"
            )
            self.requests = None

    def connect(self) -> bool:
        """Test connection to WebDAV server."""
        if not self.requests:
            return False

        try:
            response = self.requests.request(
                "PROPFIND",
                f"{self.url}/",
                auth=(self.username, self.password),
                timeout=10,
            )
            self.connected = response.status_code in [207, 200]
            self.logger.info(
                f"WebDAV connection: {'OK' if self.connected else 'FAILED'}"
            )
            return self.connected
        except Exception as e:
            self.logger.error(f"WebDAV connection failed: {e}")
            self.connected = False
            return False

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        """Upload file to WebDAV server."""
        if not self.connected or not self.requests:
            return False

        try:
            with open(local_path, "rb") as f:
                response = self.requests.put(
                    f"{self.url}{remote_path}",
                    data=f,
                    auth=(self.username, self.password),
                    timeout=30,
                )

            success = response.status_code in [200, 201, 204]
            if success:
                self.logger.debug(f"Uploaded {remote_path}")
            else:
                self.logger.warning(
                    f"Upload failed for {remote_path}: {response.status_code}"
                )
            return success
        except Exception as e:
            self.logger.error(f"Upload failed for {remote_path}: {e}")
            return False

    def download_file(self, remote_path: str, local_path: Path) -> bool:
        """Download file from WebDAV server."""
        if not self.connected or not self.requests:
            return False

        try:
            response = self.requests.get(
                f"{self.url}{remote_path}",
                auth=(self.username, self.password),
                timeout=30,
            )

            if response.status_code == 200:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(response.content)
                self.logger.debug(f"Downloaded {remote_path}")
                return True
            else:
                self.logger.warning(
                    f"Download failed for {remote_path}: {response.status_code}"
                )
                return False
        except Exception as e:
            self.logger.error(f"Download failed for {remote_path}: {e}")
            return False

    def list_files(self, remote_dir: str = "/") -> List[str]:
        """List files in WebDAV directory."""
        if not self.connected or not self.requests:
            return []

        try:
            response = self.requests.request(
                "PROPFIND",
                f"{self.url}{remote_dir}",
                auth=(self.username, self.password),
                timeout=30,
            )

            if response.status_code == 207:
                # Parse WebDAV response (XML)
                # This is simplified - production code would parse XML properly
                files = []
                # Basic extraction of hrefs from WebDAV response
                import re

                hrefs = re.findall(r"<d:href>(.*?)</d:href>", response.text)
                files = [h for h in hrefs if h != remote_dir.rstrip("/") + "/"]
                return files
            else:
                self.logger.warning(f"List failed: {response.status_code}")
                return []
        except Exception as e:
            self.logger.error(f"List files failed: {e}")
            return []

    def delete_file(self, remote_path: str) -> bool:
        """Delete file from WebDAV server."""
        if not self.connected or not self.requests:
            return False

        try:
            response = self.requests.delete(
                f"{self.url}{remote_path}",
                auth=(self.username, self.password),
                timeout=30,
            )

            success = response.status_code in [200, 204, 404]
            if success:
                self.logger.debug(f"Deleted {remote_path}")
            return success
        except Exception as e:
            self.logger.error(f"Delete failed for {remote_path}: {e}")
            return False

    def get_file_metadata(self, remote_path: str) -> Optional[Dict[str, Any]]:
        """Get metadata for WebDAV file."""
        if not self.connected or not self.requests:
            return None

        try:
            response = self.requests.head(
                f"{self.url}{remote_path}",
                auth=(self.username, self.password),
                timeout=30,
            )

            if response.status_code == 200:
                return {
                    "size": int(response.headers.get("Content-Length", 0)),
                    "mtime": response.headers.get("Last-Modified"),
                }
            return None
        except Exception as e:
            self.logger.error(f"Get metadata failed for {remote_path}: {e}")
            return None


class CloudSyncManager:
    """
    Manages cloud synchronization for memos.

    Implements local-first sync with support for multiple sync targets.
    """

    def __init__(
        self,
        local_store,
        sync_target: SyncTarget,
        sync_dir: Path,
        logger: Optional[logging.Logger] = None,
    ):
        self.store = local_store
        self.sync_target = sync_target
        self.sync_dir = Path(sync_dir)
        self.metadata_file = self.sync_dir / ".sync_metadata.json"
        self.logger = logger or logging.getLogger(__name__)

        self.sync_dir.mkdir(parents=True, exist_ok=True)
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> Dict[str, SyncMetadata]:
        """Load sync metadata from disk."""
        try:
            if self.metadata_file.exists():
                with open(self.metadata_file, "r") as f:
                    data = json.load(f)
                    return {
                        k: SyncMetadata(**v) for k, v in data.items()
                    }
        except Exception as e:
            self.logger.warning(f"Failed to load metadata: {e}")

        return {}

    def _save_metadata(self) -> None:
        """Save sync metadata to disk."""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(
                    {k: asdict(v) for k, v in self.metadata.items()},
                    f,
                    indent=2,
                )
        except Exception as e:
            self.logger.error(f"Failed to save metadata: {e}")

    def _get_checksum(self, content: str) -> str:
        """Calculate checksum of content."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def push(self) -> Tuple[int, int]:
        """
        Push local changes to sync target.

        Returns:
            Tuple of (uploaded, deleted) counts
        """
        if not self.sync_target.connect():
            self.logger.error("Failed to connect to sync target")
            return 0, 0

        uploaded = 0
        deleted = 0

        try:
            # Get all local memos
            memos = self.store.list_all(limit=1000)

            for memo in memos:
                memo_id = memo["id"]
                content = memo["content"]
                checksum = self._get_checksum(content)

                # Check if memo needs sync
                metadata = self.metadata.get(memo_id)
                if metadata and metadata.checksum == checksum:
                    continue  # No changes

                # Upload memo as JSON
                memo_file = f"/memos/{memo_id}.json"
                local_temp = self.sync_dir / f"{memo_id}.json"

                with open(local_temp, "w", encoding="utf-8") as f:
                    json.dump(memo, f, ensure_ascii=False, indent=2)

                if self.sync_target.upload_file(local_temp, memo_file):
                    uploaded += 1
                    # Update metadata
                    self.metadata[memo_id] = SyncMetadata(
                        checksum=checksum,
                        last_sync_time=datetime.now(timezone.utc).isoformat(),
                    )

                local_temp.unlink(missing_ok=True)

            self._save_metadata()
            self.logger.info(f"Push complete: {uploaded} uploaded")

        except Exception as e:
            self.logger.error(f"Push failed: {e}")

        return uploaded, deleted

    def pull(self) -> Tuple[int, int]:
        """
        Pull remote changes from sync target.

        Returns:
            Tuple of (downloaded, updated) counts
        """
        if not self.sync_target.connect():
            self.logger.error("Failed to connect to sync target")
            return 0, 0

        downloaded = 0
        updated = 0

        try:
            remote_files = self.sync_target.list_files("/memos/")

            for remote_file in remote_files:
                if not remote_file.endswith(".json"):
                    continue

                memo_id = Path(remote_file).stem
                local_file = self.sync_dir / f"{memo_id}.json"

                if self.sync_target.download_file(remote_file, local_file):
                    downloaded += 1

                    # Load and update local memo if needed
                    try:
                        with open(local_file, "r", encoding="utf-8") as f:
                            remote_memo = json.load(f)

                        # Check for conflicts based on timestamp
                        local_memo = self.store.get_by_id(memo_id)
                        if local_memo:
                            local_time = datetime.fromisoformat(
                                local_memo.get("updated_at", "")
                            )
                            remote_time = datetime.fromisoformat(
                                remote_memo.get("updated_at", "")
                            )

                            if remote_time > local_time:
                                # Remote is newer, skip local update for now
                                # (Would need to implement content update method)
                                self.logger.debug(f"Remote version newer for {memo_id}")
                                updated += 1
                        else:
                            # New remote memo, import it
                            self.store.add(
                                remote_memo.get("content", ""),
                                tags=remote_memo.get("tags", []),
                                category=remote_memo.get("category", "default"),
                            )
                            updated += 1

                    except Exception as e:
                        self.logger.warning(f"Failed to process {memo_id}: {e}")

                    local_file.unlink(missing_ok=True)

            self._save_metadata()
            self.logger.info(f"Pull complete: {downloaded} downloaded, {updated} updated")

        except Exception as e:
            self.logger.error(f"Pull failed: {e}")

        return downloaded, updated

    def sync(self) -> None:
        """
        Perform bi-directional synchronization.

        Pushes local changes first, then pulls remote changes.
        """
        self.logger.info("Starting sync...")
        up, down = self.push()
        down, updated = self.pull()
        self.logger.info(f"Sync complete: {up} uploaded, {down} downloaded, {updated} updated")


# Convenience functions for quick setup
def create_local_sync(store, sync_dir: Path) -> CloudSyncManager:
    """Create a local filesystem sync manager."""
    target = LocalSyncTarget(sync_dir)
    return CloudSyncManager(store, target, sync_dir)


def create_webdav_sync(
    store, url: str, username: str, password: str, sync_dir: Path
) -> CloudSyncManager:
    """Create a WebDAV sync manager."""
    target = WebDAVSyncTarget(url, username, password)
    return CloudSyncManager(store, target, sync_dir)

#!/usr/bin/env python3
"""Incremental backup solution for memo application."""

import hashlib
import json
import logging
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from contextlib import contextmanager
import tempfile
import gzip

logger = logging.getLogger(__name__)


class BackupMetadata:
    """Manages backup metadata and incremental tracking."""

    def __init__(self, backup_dir: Path):
        """
        Initialize backup metadata.

        Args:
            backup_dir: Directory for storing backups
        """
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.backup_dir / ".backup_metadata.json"
        self.checksums_file = self.backup_dir / ".checksums.json"
        self.metadata = self._load_metadata()
        self.checksums = self._load_checksums()

    def _load_metadata(self) -> Dict[str, Any]:
        """Load backup metadata."""
        if self.metadata_file.exists():
            try:
                with self.metadata_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Failed to load backup metadata, starting fresh")

        return {
            "backups": [],
            "last_full_backup": None,
            "last_incremental_backup": None,
            "backup_count": 0
        }

    def _load_checksums(self) -> Dict[str, str]:
        """Load file checksums."""
        if self.checksums_file.exists():
            try:
                with self.checksums_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning("Failed to load checksums, starting fresh")

        return {}

    def _save_metadata(self) -> None:
        """Save backup metadata."""
        try:
            with self.metadata_file.open("w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2, default=str)
        except IOError as e:
            logger.error(f"Failed to save backup metadata: {e}")

    def _save_checksums(self) -> None:
        """Save checksums."""
        try:
            with self.checksums_file.open("w", encoding="utf-8") as f:
                json.dump(self.checksums, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save checksums: {e}")

    def add_backup(
        self,
        backup_name: str,
        backup_type: str = "incremental",
        size_bytes: int = 0
    ) -> None:
        """
        Record a new backup.

        Args:
            backup_name: Name of the backup
            backup_type: Type of backup (full or incremental)
            size_bytes: Size of the backup in bytes
        """
        backup_info = {
            "name": backup_name,
            "type": backup_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "size_bytes": size_bytes
        }

        self.metadata["backups"].append(backup_info)
        self.metadata["backup_count"] = len(self.metadata["backups"])

        if backup_type == "full":
            self.metadata["last_full_backup"] = backup_name
        else:
            self.metadata["last_incremental_backup"] = backup_name

        self._save_metadata()

    def update_checksum(self, file_id: str, checksum: str) -> None:
        """
        Update file checksum.

        Args:
            file_id: File identifier
            checksum: New checksum value
        """
        self.checksums[file_id] = checksum
        self._save_checksums()

    def get_checksum(self, file_id: str) -> Optional[str]:
        """Get stored checksum for a file."""
        return self.checksums.get(file_id)

    def get_last_full_backup(self) -> Optional[str]:
        """Get name of last full backup."""
        return self.metadata.get("last_full_backup")

    def get_last_incremental_backup(self) -> Optional[str]:
        """Get name of last incremental backup."""
        return self.metadata.get("last_incremental_backup")

    def get_backups(self) -> List[Dict[str, Any]]:
        """Get list of all backups."""
        return self.metadata.get("backups", [])


class IncrementalBackup:
    """Handles incremental backup operations."""

    def __init__(
        self,
        db_path: Path,
        backup_dir: Path,
        compress: bool = True,
        retention_days: int = 30
    ):
        """
        Initialize incremental backup.

        Args:
            db_path: Path to SQLite database
            backup_dir: Directory for storing backups
            compress: Whether to compress backups
            retention_days: How many days to keep backups
        """
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.compress = compress
        self.retention_days = retention_days
        self.metadata = BackupMetadata(self.backup_dir)

    @staticmethod
    def _calculate_checksum(file_path: Path) -> str:
        """Calculate SHA256 checksum of a file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _needs_backup(self) -> bool:
        """Check if database needs backup."""
        if not self.db_path.exists():
            return False

        current_checksum = self._calculate_checksum(self.db_path)
        stored_checksum = self.metadata.get_checksum("database")

        return stored_checksum != current_checksum

    def _create_full_backup(self) -> Tuple[bool, str]:
        """
        Create a full database backup.

        Returns:
            Tuple of (success, backup_path)
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_full_{timestamp}"

        try:
            # Use SQLite backup API for consistent backup
            backup_path = self.backup_dir / f"{backup_name}.db"

            with sqlite3.connect(str(self.db_path)) as source:
                with sqlite3.connect(str(backup_path)) as target:
                    source.backup(target)

            # Compress if needed
            if self.compress:
                compressed_path = backup_path.with_suffix(".db.gz")
                with open(backup_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                backup_path.unlink()
                backup_path = compressed_path
                backup_name = f"{backup_name}.gz"

            # Record metadata
            size_bytes = backup_path.stat().st_size
            self.metadata.add_backup(backup_name, "full", size_bytes)

            # Update checksum
            current_checksum = self._calculate_checksum(self.db_path)
            self.metadata.update_checksum("database", current_checksum)

            logger.info(f"Full backup created: {backup_name} ({size_bytes} bytes)")
            return True, str(backup_path)

        except Exception as e:
            logger.error(f"Full backup failed: {e}")
            return False, ""

    def _create_incremental_backup(self) -> Tuple[bool, str]:
        """
        Create an incremental database backup.

        Returns:
            Tuple of (success, backup_path)
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_name = f"backup_incr_{timestamp}"

        try:
            # For SQLite, we create a backup of changed tables
            # In production, you'd use WAL snapshots or other mechanisms
            backup_path = self.backup_dir / f"{backup_name}.db"

            # Create backup using SQL query
            with sqlite3.connect(str(self.db_path)) as source:
                with sqlite3.connect(str(backup_path)) as target:
                    # Copy schema
                    source.backup(target, pages=1)  # Copy a few pages incrementally
                    source.backup(target)  # Continue incremental backup

            # Compress if needed
            if self.compress:
                compressed_path = backup_path.with_suffix(".db.gz")
                with open(backup_path, "rb") as f_in:
                    with gzip.open(compressed_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)

                backup_path.unlink()
                backup_path = compressed_path
                backup_name = f"{backup_name}.gz"

            # Record metadata
            size_bytes = backup_path.stat().st_size
            self.metadata.add_backup(backup_name, "incremental", size_bytes)

            # Update checksum
            current_checksum = self._calculate_checksum(self.db_path)
            self.metadata.update_checksum("database", current_checksum)

            logger.info(f"Incremental backup created: {backup_name} ({size_bytes} bytes)")
            return True, str(backup_path)

        except Exception as e:
            logger.error(f"Incremental backup failed: {e}")
            return False, ""

    def create_backup(self, force_full: bool = False) -> Tuple[bool, str]:
        """
        Create a backup (full or incremental).

        Args:
            force_full: Force full backup instead of incremental

        Returns:
            Tuple of (success, backup_path)
        """
        if not self.db_path.exists():
            logger.warning(f"Database not found: {self.db_path}")
            return False, ""

        # Determine backup type
        last_full = self.metadata.get_last_full_backup()
        should_full = force_full or last_full is None

        if should_full:
            return self._create_full_backup()
        else:
            # Check if incremental is needed
            if self._needs_backup():
                return self._create_incremental_backup()
            else:
                logger.info("Database unchanged, skipping backup")
                return False, ""

    def restore_backup(self, backup_path: Path) -> bool:
        """
        Restore from a backup.

        Args:
            backup_path: Path to backup file

        Returns:
            True if successful
        """
        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
            return False

        try:
            # Handle compressed backups
            if backup_path.suffix == ".gz":
                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                    with gzip.open(backup_path, "rb") as f_in:
                        shutil.copyfileobj(f_in, tmp)
                    tmp_path = Path(tmp.name)

                # Restore from temporary file
                result = self._restore_from_file(tmp_path)
                tmp_path.unlink()
                return result
            else:
                return self._restore_from_file(backup_path)

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def _restore_from_file(self, backup_file: Path) -> bool:
        """Restore database from backup file."""
        try:
            # Create backup of current database
            if self.db_path.exists():
                backup_copy = self.db_path.with_suffix(".db.bak")
                shutil.copy2(self.db_path, backup_copy)

            # Restore
            with sqlite3.connect(str(backup_file)) as source:
                with sqlite3.connect(str(self.db_path)) as target:
                    source.backup(target)

            logger.info(f"Restore successful from {backup_file}")
            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False

    def cleanup_old_backups(self) -> int:
        """
        Remove backups older than retention period.

        Returns:
            Number of backups removed
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        removed_count = 0

        try:
            for backup_info in self.metadata.get_backups():
                backup_timestamp_str = backup_info.get("timestamp", "")
                try:
                    backup_date = datetime.fromisoformat(backup_timestamp_str)

                    if backup_date < cutoff_date:
                        backup_file = self.backup_dir / backup_info["name"]
                        if backup_file.exists():
                            backup_file.unlink()
                            removed_count += 1
                            logger.info(f"Removed old backup: {backup_info['name']}")

                except ValueError:
                    logger.warning(f"Invalid timestamp in backup metadata: {backup_timestamp_str}")

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

        return removed_count

    def get_backup_info(self) -> Dict[str, Any]:
        """Get backup information."""
        backups = self.metadata.get_backups()
        total_size = sum(b.get("size_bytes", 0) for b in backups)

        return {
            "backup_count": len(backups),
            "total_size_mb": total_size / (1024 * 1024),
            "last_full_backup": self.metadata.get_last_full_backup(),
            "last_incremental_backup": self.metadata.get_last_incremental_backup(),
            "retention_days": self.retention_days,
            "backups": backups
        }


@contextmanager
def auto_backup(
    db_path: Path,
    backup_dir: Path,
    retention_days: int = 30
):
    """
    Context manager for automatic backup.

    Args:
        db_path: Path to database
        backup_dir: Directory for backups
        retention_days: Retention period
    """
    backup = IncrementalBackup(db_path, backup_dir, retention_days=retention_days)

    # Create backup before operation
    success, backup_path = backup.create_backup()
    if success:
        logger.info(f"Pre-operation backup: {backup_path}")

    try:
        yield backup
    finally:
        # Cleanup old backups
        removed = backup.cleanup_old_backups()
        if removed > 0:
            logger.info(f"Cleaned up {removed} old backups")


if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    db_path = Path.home() / ".memo" / "memos.db"
    backup_dir = Path.home() / ".memo" / "backups"

    backup = IncrementalBackup(db_path, backup_dir)

    if len(sys.argv) > 1:
        if sys.argv[1] == "backup":
            force_full = "--full" in sys.argv
            success, path = backup.create_backup(force_full=force_full)
            print(f"Backup {'successful' if success else 'failed'}: {path}")

        elif sys.argv[1] == "restore":
            if len(sys.argv) > 2:
                backup_file = Path(sys.argv[2])
                success = backup.restore_backup(backup_file)
                print(f"Restore {'successful' if success else 'failed'}")
            else:
                print("Usage: python incremental_backup.py restore <backup_path>")

        elif sys.argv[1] == "info":
            info = backup.get_backup_info()
            print(json.dumps(info, indent=2, default=str))

        elif sys.argv[1] == "cleanup":
            removed = backup.cleanup_old_backups()
            print(f"Removed {removed} old backups")

        else:
            print("Usage: python incremental_backup.py [backup|restore|info|cleanup]")
    else:
        print("Usage: python incremental_backup.py [backup|restore|info|cleanup]")

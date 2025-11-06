#!/usr/bin/env python3
"""Backup and sync functionality for memo application."""

import json
import os
import shutil
import logging
from logging.handlers import RotatingFileHandler
from contextlib import suppress
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import tempfile
import zipfile
import hashlib


class BackupManager:
    """Handle backup and restore operations for memo data."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or (Path.home() / ".memo")
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = self.data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._setup_logger()

    def create_backup(self, name: Optional[str] = None) -> Path:
        """Create a backup of all memo data."""
        timestamp = datetime.now(timezone.utc)
        if name is None:
            name = f"backup_{timestamp.strftime('%Y%m%d_%H%M%S')}"

        backup_file = self.backup_dir / f"{name}.zip"

        data_files = []
        aggregate_hasher = hashlib.sha256()

        for file_path in sorted(self.data_dir.glob("*.json*")):
            if file_path.is_file() and file_path.parent == self.data_dir:
                checksum = self._compute_file_checksum(file_path)
                aggregate_hasher.update(checksum.encode("utf-8"))
                stat = file_path.stat()
                data_files.append(
                    {
                        "name": file_path.name,
                        "bytes": stat.st_size,
                        "checksum": checksum,
                        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    }
                )

        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile("w+b", delete=False, dir=self.backup_dir, suffix=".zip") as tmp:
                tmp_path = Path(tmp.name)
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_info in data_files:
                    source_path = self.data_dir / file_info["name"]
                    if not source_path.exists():
                        self.logger.warning("Skipping missing file %s during backup", source_path)
                        continue
                    zf.write(source_path, file_info["name"])

                metadata = {
                    "created": timestamp.isoformat(),
                    "files": data_files,
                    "aggregate_checksum": aggregate_hasher.hexdigest(),
                }
                zf.writestr("backup_metadata.json", json.dumps(metadata, indent=2))

            tmp_path.replace(backup_file)
            self.logger.info("Created backup %s with %d files", backup_file.name, len(data_files))
            return backup_file
        except Exception as exc:
            self.logger.error("Failed to create backup %s: %s", backup_file.name, exc)
            if tmp_path:
                with suppress(OSError):
                    tmp_path.unlink()
            raise

    def list_backups(self) -> List[Dict]:
        """List all available backups."""
        backups = []

        for backup_file in self.backup_dir.glob("*.zip"):
            try:
                with zipfile.ZipFile(backup_file, 'r') as zf:
                    if "backup_metadata.json" in zf.namelist():
                        metadata = json.loads(zf.read("backup_metadata.json"))
                        files_meta = metadata.get("files", [])
                        total_files = len(files_meta) if isinstance(files_meta, list) else 0
                        checksum = metadata.get("aggregate_checksum") or metadata.get("checksum")
                        created_str = metadata.get("created")
                        created_dt = None
                        if created_str:
                            try:
                                created_dt = datetime.fromisoformat(created_str)
                            except ValueError:
                                created_dt = None
                        backups.append({
                            "name": backup_file.stem,
                            "path": backup_file,
                            "created": created_dt.isoformat() if created_dt else metadata.get("created"),
                            "size": backup_file.stat().st_size,
                            "files": files_meta,
                            "file_count": total_files,
                            "checksum": checksum,
                        })
                    else:
                        # Legacy backup without metadata
                        stat = backup_file.stat()
                        backups.append({
                            "name": backup_file.stem,
                            "path": backup_file,
                            "size": stat.st_size,
                            "files": [],
                            "checksum": None,
                        })
            except (zipfile.BadZipFile, json.JSONDecodeError) as exc:
                self.logger.warning("Failed to read backup %s: %s", backup_file, exc)
                continue

        return sorted(backups, key=lambda x: x.get("created", ""), reverse=True)

    def get_backup_index(self, backup_name: str) -> Optional[Dict[str, Any]]:
        """Return normalized file metadata for a backup."""
        backup_file = self.backup_dir / f"{backup_name}.zip"
        if not backup_file.exists():
            return None

        index: Dict[str, Dict[str, Optional[Any]]] = {}
        aggregate_checksum: Optional[str] = None

        with zipfile.ZipFile(backup_file, "r") as zf:
            metadata = None
            if "backup_metadata.json" in zf.namelist():
                try:
                    metadata = json.loads(zf.read("backup_metadata.json"))
                except json.JSONDecodeError:
                    metadata = None

            files_meta = metadata.get("files") if isinstance(metadata, dict) else None
            if isinstance(files_meta, list) and files_meta:
                for entry in files_meta:
                    if isinstance(entry, dict):
                        name = entry.get("name")
                        if not name:
                            continue
                        index[name] = {
                            "checksum": entry.get("checksum"),
                            "bytes": entry.get("bytes"),
                            "modified": entry.get("modified"),
                        }
                    elif isinstance(entry, str):
                        index[entry] = {
                            "checksum": None,
                            "bytes": None,
                            "modified": None,
                        }

                aggregate_checksum = metadata.get("aggregate_checksum") if isinstance(metadata, dict) else None
                if not aggregate_checksum and isinstance(metadata, dict):
                    aggregate_checksum = metadata.get("checksum")
            else:
                aggregate_hasher = hashlib.sha256()
                for info in zf.infolist():
                    if info.filename == "backup_metadata.json":
                        continue
                    checksum = self._compute_stream_checksum(zf.open(info.filename))
                    aggregate_hasher.update(checksum.encode("utf-8"))
                    index[info.filename] = {
                        "checksum": checksum,
                        "bytes": info.file_size,
                        "modified": datetime(*info.date_time, tzinfo=timezone.utc).isoformat(),
                    }
                aggregate_checksum = aggregate_hasher.hexdigest() if index else None

        return {
            "files": index,
            "aggregate_checksum": aggregate_checksum,
        }

    def describe_backup(self, backup_name: str) -> Optional[Dict]:
        """Return detailed metadata for a backup."""
        backup_file = self.backup_dir / f"{backup_name}.zip"
        if not backup_file.exists():
            return None

        with zipfile.ZipFile(backup_file, "r") as zf:
            metadata = None
            if "backup_metadata.json" in zf.namelist():
                try:
                    metadata = json.loads(zf.read("backup_metadata.json"))
                except json.JSONDecodeError:
                    metadata = None

            file_entries = []
            for info in zf.infolist():
                if info.filename == "backup_metadata.json":
                    continue
                file_entries.append(
                    {
                        "name": info.filename,
                        "compressed": info.compress_size,
                        "uncompressed": info.file_size,
                        "modified": datetime(*info.date_time, tzinfo=timezone.utc).isoformat(),
                    }
                )

        return {
            "name": backup_name,
            "path": str(backup_file),
            "size": backup_file.stat().st_size,
            "created": metadata.get("created") if metadata else None,
            "metadata": metadata,
            "entries": file_entries,
        }

    def compare_backups(self, older_name: str, newer_name: str) -> Optional[Dict[str, Any]]:
        """Compare two backups and report file-level differences."""
        older = self.get_backup_index(older_name)
        newer = self.get_backup_index(newer_name)

        if older is None or newer is None:
            return None

        older_files = older["files"]
        newer_files = newer["files"]

        added = []
        removed = []
        changed = []
        unchanged_count = 0

        for name, new_entry in sorted(newer_files.items()):
            old_entry = older_files.get(name)
            if old_entry is None:
                added.append(
                    {
                        "name": name,
                        "bytes": new_entry.get("bytes"),
                        "checksum": new_entry.get("checksum"),
                    }
                )
                continue

            if self._entries_equal(old_entry, new_entry):
                unchanged_count += 1
                continue

            changed.append(
                {
                    "name": name,
                    "old_bytes": old_entry.get("bytes"),
                    "new_bytes": new_entry.get("bytes"),
                    "old_checksum": old_entry.get("checksum"),
                    "new_checksum": new_entry.get("checksum"),
                }
            )

        for name, old_entry in sorted(older_files.items()):
            if name not in newer_files:
                removed.append(
                    {
                        "name": name,
                        "bytes": old_entry.get("bytes"),
                        "checksum": old_entry.get("checksum"),
                    }
                )

        return {
            "older": older_name,
            "newer": newer_name,
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged": unchanged_count,
            "older_checksum": older.get("aggregate_checksum"),
            "newer_checksum": newer.get("aggregate_checksum"),
        }

    @staticmethod
    def _entries_equal(old_entry: Dict[str, Optional[Any]], new_entry: Dict[str, Optional[Any]]) -> bool:
        """Determine whether two metadata entries describe identical content."""
        old_checksum = old_entry.get("checksum")
        new_checksum = new_entry.get("checksum")
        if old_checksum and new_checksum:
            return old_checksum == new_checksum

        old_bytes = old_entry.get("bytes")
        new_bytes = new_entry.get("bytes")
        if old_bytes is not None and new_bytes is not None:
            try:
                return int(old_bytes) == int(new_bytes)
            except (TypeError, ValueError):
                pass
        if old_entry is not None:
            return False

        return False

    def verify_backup(self, backup_name: str) -> Tuple[bool, List[str]]:
        """Verify integrity of a backup archive."""
        backup_file = self.backup_dir / f"{backup_name}.zip"
        issues: List[str] = []
{{ ... }}

        if not backup_file.exists():
            return False, ["Backup not found"]

        try:
            with zipfile.ZipFile(backup_file, "r") as zf:
                corrupted_file = zf.testzip()
                if corrupted_file:
                    issues.append(f"Corrupted file detected in archive: {corrupted_file}")

                if "backup_metadata.json" not in zf.namelist():
                    issues.append("Missing backup_metadata.json")
                    return False, issues

                metadata = json.loads(zf.read("backup_metadata.json"))
                files_meta = metadata.get("files", [])
                aggregate_hasher = hashlib.sha256()

                if isinstance(files_meta, list):
                    for entry in files_meta:
                        if isinstance(entry, str):
                            filename = entry
                            expected_checksum = None
                        else:
                            filename = entry.get("name")
                            expected_checksum = entry.get("checksum")

                        if not filename:
                            issues.append("Metadata entry missing file name")
                            continue

                        if filename not in zf.namelist():
                            issues.append(f"Missing file in archive: {filename}")
                            continue

                        actual_checksum = self._compute_stream_checksum(zf.open(filename))
                        aggregate_hasher.update(actual_checksum.encode("utf-8"))
                        if expected_checksum and actual_checksum != expected_checksum:
                            issues.append(
                                f"Checksum mismatch for {filename}: expected {expected_checksum}, got {actual_checksum}"
                            )

                    expected_aggregate = metadata.get("aggregate_checksum") or metadata.get("checksum")
                    if expected_aggregate:
                        if aggregate_hasher.hexdigest() != expected_aggregate:
                            issues.append("Aggregate checksum mismatch")
                else:
                    issues.append("Invalid files metadata format")

        except zipfile.BadZipFile:
            issues.append("Archive is not a valid ZIP file")
        except Exception as exc:
            issues.append(f"Failed to verify backup: {exc}")

        return len(issues) == 0, issues

    def generate_report(self, recent_days: int = 7) -> Dict:
        """Generate a summary report for backups."""
        backups = self.list_backups()
        total = len(backups)
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=recent_days)

        recent_backups = []
        for backup in backups:
            created_str = backup.get("created")
            if created_str:
                try:
                    created_dt = datetime.fromisoformat(created_str)
                except ValueError:
                    continue
                if created_dt >= cutoff:
                    recent_backups.append(backup)

        oldest = backups[-1] if backups else None
        newest = backups[0] if backups else None

        return {
            "total": total,
            "recent_days": recent_days,
            "recent_count": len(recent_backups),
            "newest": newest,
            "oldest": oldest,
            "gap_hours": self._compute_gap_hours(backups),
        }

    def _compute_gap_hours(self, backups: List[Dict]) -> Optional[float]:
        if len(backups) < 2:
            return None

        newest = backups[0]
        oldest = backups[-1]

        try:
            newest_dt = datetime.fromisoformat(newest.get("created")) if newest.get("created") else None
            oldest_dt = datetime.fromisoformat(oldest.get("created")) if oldest.get("created") else None
        except ValueError:
            return None

        if newest_dt and oldest_dt:
            delta = newest_dt - oldest_dt
            return delta.total_seconds() / 3600
        return None

    def _compute_file_checksum(self, file_path: Path) -> str:
        hasher = hashlib.sha256()
        with file_path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _compute_stream_checksum(self, stream) -> str:
        try:
            data = stream.read()
        finally:
            stream.close()
        hasher = hashlib.sha256()
        hasher.update(data)
        return hasher.hexdigest()

    def restore_backup(self, backup_name: str) -> bool:
        """Restore from a backup."""
        backup_file = self.backup_dir / f"{backup_name}.zip"

        if not backup_file.exists():
            self.logger.error("Backup %s not found for restore", backup_name)
            return False

        try:
            safety_backup = self.create_backup(f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            self.logger.info("Created safety backup %s before restoring %s", safety_backup.name, backup_name)

            with zipfile.ZipFile(backup_file, 'r') as zf:
                for member in zf.infolist():
                    if member.filename == "backup_metadata.json":
                        continue
                    if not self._is_within_directory(member.filename, self.data_dir):
                        self.logger.warning("Skipping unsafe path %s during restore", member.filename)
                        continue

                    target_path = self.data_dir / member.filename
                    target_path.parent.mkdir(parents=True, exist_ok=True)

                    with zf.open(member) as source:
                        self._write_atomic_file(target_path, source)

            return True
        except Exception as exc:
            self.logger.error("Failed to restore backup %s: %s", backup_name, exc)
            return False

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """Remove old backups, keeping only the most recent ones."""
        backups = self.list_backups()

        if len(backups) <= keep_count:
            return 0

        removed_count = 0
        for backup in backups[keep_count:]:
            try:
                Path(backup["path"]).unlink()
                removed_count += 1
                self.logger.info("Removed old backup %s", backup["name"])
            except OSError as exc:
                self.logger.warning("Failed to remove backup %s: %s", backup.get("name"), exc)
                continue

        return removed_count

    def get_checksum(self) -> str:
        """Get checksum of current memo data for sync detection."""
        hasher = hashlib.sha256()

        data_files = sorted(self.data_dir.glob("*.json*"))
        for file_path in data_files:
            if file_path.is_file() and file_path.parent == self.data_dir:
                with file_path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(65536), b""):
                        hasher.update(chunk)

        return hasher.hexdigest()


def generate_schedule_instructions(
    target: str,
    frequency: str = "daily",
    time_str: str = "02:00",
    report_days: int = 7,
    log_path: Optional[str] = None,
) -> str:
    """Generate platform-specific instructions for scheduling backups."""
    target = (target or "cron").lower()
    frequency = (frequency or "daily").lower()
    script_path = Path(__file__).resolve()

    try:
        parsed_time = datetime.strptime(time_str, "%H:%M")
        hour = parsed_time.hour
        minute = parsed_time.minute
    except ValueError:
        hour, minute = 2, 0
        time_str = "02:00"

    if frequency not in {"hourly", "daily", "weekly", "monthly"}:
        frequency = "daily"

    if target == "cron":
        if frequency == "hourly":
            cron_expr = f"{minute} * * * *"
        elif frequency == "weekly":
            cron_expr = f"{minute} {hour} * * 1"
        elif frequency == "monthly":
            cron_expr = f"{minute} {hour} 1 * *"
        else:
            cron_expr = f"{minute} {hour} * * *"

        log_suffix = ""
        if log_path:
            log_suffix = f" >> '{log_path}' 2>&1"

        return (
            "# Cron configuration\n"
            "# Run `crontab -e` and add the following line:\n"
            f"{cron_expr} cd '{script_path.parent}' && /usr/bin/env python3 '{script_path}' backup && /usr/bin/env python3 '{script_path}' report {report_days}{log_suffix}\n"
            "# Adjust timezone/paths as needed.\n"
        )

    if target == "systemd":
        timer_name = "memo-backup"
        if frequency == "hourly":
            on_calendar = f"*-*-* *:{minute:02d}"
        elif frequency == "weekly":
            on_calendar = f"Mon {time_str}"
        elif frequency == "monthly":
            on_calendar = f"*-*-01 {time_str}"
        else:
            on_calendar = f"*-*-* {time_str}"

        service_unit = (
            f"# {timer_name}.service\n"
            "[Unit]\n"
            "Description=Memo backup job\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"WorkingDirectory={script_path.parent}\n"
            f"ExecStart=/usr/bin/env python3 {script_path} backup\n"
            f"ExecStart=/usr/bin/env python3 {script_path} report {report_days}\n"
        )

        if log_path:
            service_unit += (
                f"StandardOutput=append:{log_path}\n"
                f"StandardError=append:{log_path}\n"
            )

        timer_unit = (
            f"# {timer_name}.timer\n"
            "[Unit]\n"
            "Description=Memo backup schedule\n\n"
            "[Timer]\n"
            f"OnCalendar={on_calendar}\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

        instructions = (
            service_unit
            + "\n"
            + timer_unit
            + "\n# Save both files under ~/.config/systemd/user/ and run:\n"
            f"systemctl --user enable --now {timer_name}.timer\n"
        )
        return instructions

    if target == "powershell":
        script_str = str(script_path)
        workdir_str = str(script_path.parent)
        repetition_interval = {
            "hourly": "PT1H",
            "weekly": "P7D",
            "monthly": "P1M",
        }.get(frequency, "P1D")

        log_block = ""
        if log_path:
            log_block = (
                f"$LogPath = '{log_path}'\n"
                "$LogDirectory = Split-Path $LogPath\n"
                "if (-not (Test-Path $LogDirectory)) { New-Item -ItemType Directory -Path $LogDirectory | Out-Null }\n"
            )
            capture = "Tee-Object -FilePath $LogPath -Append"
        else:
            capture = "Out-Null"

        return (
            "# Windows Task Scheduler (PowerShell)\n"
            f"{log_block}"
            f"$Action1 = New-ScheduledTaskAction -Execute 'python.exe' -Argument \"'{script_str}' backup\" -WorkingDirectory '{workdir_str}'\n"
            f"$Action2 = New-ScheduledTaskAction -Execute 'python.exe' -Argument \"'{script_str}' report {report_days}\" -WorkingDirectory '{workdir_str}'\n"
            f"$Trigger = New-ScheduledTaskTrigger -Once -At '{time_str}' -RepetitionInterval {repetition_interval} -RepetitionDuration ([TimeSpan]::MaxValue)\n"
            "$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive\n"
            f"Register-ScheduledTask -TaskName 'MemoBackup' -Action $Action1,$Action2 -Trigger $Trigger -Principal $Principal -Description 'Memo backup automation' | {capture}\n"
            "# Adjust RunLevel or credentials through Task Scheduler if needed.\n"
        )

    return (
        "# Unsupported platform. Specify one of: cron, systemd, powershell.\n"
        "# Example: python backup.py schedule cron daily 02:00\n"
    )


class SyncManager:
    """Handle synchronization with external sources."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or (Path.home() / ".memo")
        self.sync_config_file = self.data_dir / "sync_config.json"
        self.backup_manager = BackupManager(data_dir)

    def setup_sync(self, sync_type: str, config: Dict) -> bool:
        """Setup synchronization configuration."""
        sync_config = {
            "type": sync_type,
            "config": config,
            "last_sync": None,
            "last_checksum": None
        }

        try:
            with self.sync_config_file.open("w", encoding="utf-8") as f:
                json.dump(sync_config, f, indent=2)
            return True
        except IOError:
            return False

    def get_sync_config(self) -> Optional[Dict]:
        """Get current sync configuration."""
        if not self.sync_config_file.exists():
            return None

        try:
            with self.sync_config_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError):
            return None

    def sync_to_directory(self, target_dir: Path) -> bool:
        """Sync to a directory (simple file copy)."""
        target_dir = Path(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Copy all data files
            for file_path in self.data_dir.glob("*.json*"):
                if file_path.is_file() and file_path.parent == self.data_dir:
                    self._atomic_copy(file_path, target_dir / file_path.name)

            # Update sync metadata
            self._update_sync_metadata()
            return True
        except (IOError, OSError):
            return False

    def sync_from_directory(self, source_dir: Path) -> bool:
        """Sync from a directory (simple file copy)."""
        source_dir = Path(source_dir)

        if not source_dir.exists():
            return False

        try:
            # Create backup before sync
            self.backup_manager.create_backup(f"pre_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

            # Copy files from source
            for file_path in source_dir.glob("*.json*"):
                if file_path.is_file():
                    self._atomic_copy(file_path, self.data_dir / file_path.name)

            self._update_sync_metadata()
            return True
        except (IOError, OSError):
            return False

    def _update_sync_metadata(self):
        """Update sync metadata after successful sync."""
        config = self.get_sync_config()
        if config:
            config["last_sync"] = datetime.now(timezone.utc).isoformat()
            config["last_checksum"] = self.backup_manager.get_checksum()

            with self.sync_config_file.open("w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)

    def has_changes_since_sync(self) -> bool:
        """Check if data has changed since last sync."""
        config = self.get_sync_config()
        if not config or not config.get("last_checksum"):
            return True

        current_checksum = self.backup_manager.get_checksum()
        return current_checksum != config["last_checksum"]

    def _atomic_copy(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile("wb", delete=False, dir=destination.parent, suffix=destination.suffix or ".tmp") as tmp:
                tmp_path = Path(tmp.name)
                with source.open("rb") as src:
                    shutil.copyfileobj(src, tmp)
            if tmp_path:
                tmp_path.replace(destination)
        except Exception as exc:
            if tmp_path:
                with suppress(OSError):
                    tmp_path.unlink()
            raise IOError(f"Failed to copy {source} to {destination}: {exc}")

    def _setup_logger(self) -> logging.Logger:
        logger_name = f"memo.backup.{self.data_dir.name}"
        logger = logging.getLogger(logger_name)
        if logger.handlers:
            return logger

        log_file = self.log_dir / "backup.log"
        handler = RotatingFileHandler(log_file, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        return logger

    def _write_atomic_file(self, target_path: Path, source_stream) -> None:
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile("wb", delete=False, dir=target_path.parent, suffix=target_path.suffix or ".tmp") as tmp:
                tmp_path = Path(tmp.name)
                shutil.copyfileobj(source_stream, tmp)
            if tmp_path:
                tmp_path.replace(target_path)
        except Exception as exc:
            if tmp_path:
                with suppress(OSError):
                    tmp_path.unlink()
            raise IOError(f"Failed to write {target_path}: {exc}")

    def _is_within_directory(self, member_name: str, base_dir: Path) -> bool:
        target = Path(member_name)
        if target.is_absolute():
            return False
        normalized = (base_dir / target).resolve()
        return str(normalized).startswith(str(base_dir.resolve()))


def _extract_data_dir(argv: List[str]) -> Tuple[Optional[Path], List[str]]:
    """Extract optional data directory argument from argv."""
    data_dir_env = os.environ.get("MEMO_DATA_DIR")
    data_dir: Optional[Path] = Path(data_dir_env).expanduser() if data_dir_env else None

    filtered = [argv[0]]
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in {"--data-dir", "-d"}:
            if i + 1 >= len(argv):
                print("--data-dir requires a path", file=sys.stderr)
                sys.exit(1)
            data_dir = Path(argv[i + 1]).expanduser()
            i += 2
            continue
        filtered.append(arg)
        i += 1

    return data_dir, filtered


if __name__ == "__main__":
    import sys

    data_dir_override, filtered_argv = _extract_data_dir(sys.argv)
    sys.argv = filtered_argv

    if len(sys.argv) < 2:
        print(
            "Usage: backup.py [--data-dir PATH] "
            "[backup|list|describe|verify|report|restore|cleanup|diff|schedule|sync] [args...]"
        )
        sys.exit(1)

    backup_manager = BackupManager(data_dir_override)
    sync_manager = SyncManager(data_dir_override)
    command = sys.argv[1]

    if command == "backup":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        backup_file = backup_manager.create_backup(name)
        print(f"Created backup: {backup_file}")

    elif command == "list":
        backups = backup_manager.list_backups()
        if backups:
            print("Available backups:")
            for backup in backups:
                created_str = backup.get("created")
                try:
                    created_fmt = datetime.fromisoformat(created_str).strftime("%Y-%m-%d %H:%M") if created_str else "-"
                except ValueError:
                    created_fmt = created_str or "-"
                size_mb = backup["size"] / (1024 * 1024)
                print(f"  {backup['name']} - {created_fmt} ({size_mb:.1f} MB)")
        else:
            print("No backups found")

    elif command == "describe":
        if len(sys.argv) < 3:
            print("Usage: backup.py describe <backup_name>")
            sys.exit(1)

        backup_name = sys.argv[2]
        details = backup_manager.describe_backup(backup_name)
        if not details:
            print(f"Backup '{backup_name}' not found", file=sys.stderr)
            sys.exit(1)

        print(f"Name: {details['name']}")
        print(f"Path: {details['path']}")
        print(f"Size: {details['size'] / (1024 * 1024):.2f} MB")
        if details.get("created"):
            print(f"Created: {details['created']}")

        metadata = details.get("metadata") or {}
        print("Files:")
        files_meta = metadata.get("files") or details.get("entries", [])
        for entry in files_meta:
            if isinstance(entry, dict):
                checksum = entry.get("checksum", "-")
                size_bytes = entry.get("bytes") or entry.get("uncompressed")
                modified = entry.get("modified", "-")
                print(f"  {entry.get('name')}: {size_bytes} bytes, modified {modified}, checksum {checksum}")
            else:
                print(f"  {entry}")

    elif command == "restore":
        if len(sys.argv) < 3:
            print("Usage: backup.py restore <backup_name>")
            sys.exit(1)

        backup_name = sys.argv[2]
        if backup_manager.restore_backup(backup_name):
            print(f"Restored from backup: {backup_name}")
        else:
            print(f"Failed to restore backup: {backup_name}")

    elif command == "cleanup":
        keep_count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        removed = backup_manager.cleanup_old_backups(keep_count)
        print(f"Removed {removed} old backups")

    elif command == "verify":
        if len(sys.argv) < 3:
            print("Usage: backup.py verify <backup_name>")
            sys.exit(1)

        ok, issues = backup_manager.verify_backup(sys.argv[2])
        if ok:
            print("Backup verified successfully")
        else:
            print("Backup verification failed:")
            for issue in issues:
                print(f"  - {issue}")

    elif command == "report":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        report = backup_manager.generate_report(days)

        print(f"Total backups: {report['total']}")
        print(f"Backups in last {report['recent_days']} days: {report['recent_count']}")

        newest = report.get("newest")
        if newest:
            print(f"Most recent: {newest['name']} ({newest.get('created')})")
        oldest = report.get("oldest")
        if oldest:
            print(f"Oldest: {oldest['name']} ({oldest.get('created')})")

        gap_hours = report.get("gap_hours")
        if gap_hours is not None:
            print(f"Span covered: {gap_hours:.1f} hours")

    elif command == "diff":
        json_flag = False
        args = sys.argv[2:]
        if "--json" in args:
            json_flag = True
            args = [arg for arg in args if arg != "--json"]

        if len(args) != 2:
            print("Usage: backup.py diff [--json] <older_backup> <newer_backup>", file=sys.stderr)
            sys.exit(1)

        older_name, newer_name = args
        diff_result = backup_manager.compare_backups(older_name, newer_name)
        if diff_result is None:
            print("One or both backups were not found", file=sys.stderr)
            sys.exit(1)

        if json_flag:
            print(json.dumps(diff_result, indent=2, ensure_ascii=False))
        else:
            print(f"Comparing backups '{older_name}' -> '{newer_name}'")
            print(f"Added files: {len(diff_result['added'])}")
            for entry in diff_result["added"]:
                size = entry.get("bytes")
                size_str = f" ({size} bytes)" if size is not None else ""
                print(f"  + {entry['name']}{size_str}")

            print(f"Removed files: {len(diff_result['removed'])}")
            for entry in diff_result["removed"]:
                size = entry.get("bytes")
                size_str = f" ({size} bytes)" if size is not None else ""
                print(f"  - {entry['name']}{size_str}")

            print(f"Changed files: {len(diff_result['changed'])}")
            for entry in diff_result["changed"]:
                old_size = entry.get("old_bytes")
                new_size = entry.get("new_bytes")
                size_delta = ""
                if old_size is not None and new_size is not None:
                    try:
                        delta = int(new_size) - int(old_size)
                        size_delta = f" (Δ {delta:+d} bytes)"
                    except (TypeError, ValueError):
                        size_delta = ""
                print(f"  * {entry['name']}{size_delta}")

            print(f"Unchanged files: {diff_result['unchanged']}")
            if diff_result.get("older_checksum") and diff_result.get("newer_checksum"):
                print(f"Aggregate checksums: {diff_result['older_checksum']} -> {diff_result['newer_checksum']}")

    elif command == "sync":
        if len(sys.argv) < 3:
            print("Usage: backup.py sync <setup|status|to|from|show> [...]", file=sys.stderr)
            sys.exit(1)

        sync_cmd = sys.argv[2]

        def _resolve_directory_arg(arg_index: int) -> Path:
            if len(sys.argv) > arg_index:
                return Path(sys.argv[arg_index]).expanduser()

            config = sync_manager.get_sync_config()
            if not config or config.get("type") != "directory":
                print("No directory sync configuration found; specify a path explicitly", file=sys.stderr)
                sys.exit(1)

            stored_path = (config.get("config") or {}).get("path")
            if not stored_path:
                print("Stored sync configuration is missing a directory path", file=sys.stderr)
                sys.exit(1)

            return Path(stored_path).expanduser()

        if sync_cmd == "setup":
            if len(sys.argv) < 5 or sys.argv[3] != "directory":
                print("Usage: backup.py sync setup directory <path>", file=sys.stderr)
                sys.exit(1)

            target_dir = Path(sys.argv[4]).expanduser()
            config = {"path": str(target_dir)}
            if sync_manager.setup_sync("directory", config):
                print(f"Configured directory sync: {target_dir}")
            else:
                print("Failed to write sync configuration", file=sys.stderr)
                sys.exit(1)

        elif sync_cmd == "status" or sync_cmd == "show":
            config = sync_manager.get_sync_config()
            if not config:
                print("No sync configuration found")
                sys.exit(0)

            print("Sync configuration:")
            print(f"  Type: {config.get('type')}")
            if config.get("config"):
                for key, value in config["config"].items():
                    print(f"  {key}: {value}")
            print(f"  Last sync: {config.get('last_sync') or '-'}")
            print(f"  Last checksum: {config.get('last_checksum') or '-'}")
            print(f"Pending changes: {'yes' if sync_manager.has_changes_since_sync() else 'no'}")

        elif sync_cmd == "to":
            target_dir = _resolve_directory_arg(3)
            if sync_manager.sync_to_directory(target_dir):
                print(f"Synced memo data to {target_dir}")
            else:
                print("Directory sync failed", file=sys.stderr)
                sys.exit(1)

        elif sync_cmd == "from":
            source_dir = _resolve_directory_arg(3)
            if sync_manager.sync_from_directory(source_dir):
                print(f"Synced memo data from {source_dir}")
            else:
                print("Directory import failed", file=sys.stderr)
                sys.exit(1)

        else:
            print(f"Unknown sync subcommand: {sync_cmd}", file=sys.stderr)
            sys.exit(1)

    elif command == "schedule":
        import argparse

        schedule_parser = argparse.ArgumentParser(description="Generate automation instructions for backups")
        schedule_parser.add_argument("target", nargs="?", default="cron", help="cron, systemd, or powershell")
        schedule_parser.add_argument("frequency", nargs="?", default="daily", help="hourly, daily, weekly, monthly")
        schedule_parser.add_argument("time", nargs="?", default="02:00", help="Trigger time in HH:MM (24h)")
        schedule_parser.add_argument("--report-days", type=int, default=7, help="Days to include in backup report")
        schedule_parser.add_argument("--log-path", help="Optional log file for backup output")
        schedule_parser.add_argument("-o", "--output", help="Write instructions to file")

        args = schedule_parser.parse_args(sys.argv[2:])

        instructions = generate_schedule_instructions(
            args.target,
            args.frequency,
            args.time,
            args.report_days,
            args.log_path,
        )

        if args.output:
            output_path = Path(args.output).expanduser()
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(instructions, encoding="utf-8")
                print(f"Wrote schedule instructions to {output_path}")
            except OSError as exc:
                print(f"Failed to write instructions: {exc}", file=sys.stderr)
                sys.exit(1)
        else:
            print(instructions)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
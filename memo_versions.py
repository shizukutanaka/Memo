#!/usr/bin/env python3
"""Version control and edit history for memos."""

import json
import difflib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import logging


class MemoVersion:
    """Represents a single version of a memo."""

    def __init__(self, version_number: int, memo_data: Dict, edited_by: str = "system"):
        self.version_number = version_number
        self.memo_data = memo_data.copy()
        self.timestamp = datetime.now(timezone.utc)
        self.edited_by = edited_by

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'version_number': self.version_number,
            'memo_data': self.memo_data,
            'timestamp': self.timestamp.isoformat(),
            'edited_by': self.edited_by,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoVersion':
        """Create from dictionary."""
        version = cls(
            version_number=data['version_number'],
            memo_data=data['memo_data'],
            edited_by=data.get('edited_by', 'system')
        )
        version.timestamp = datetime.fromisoformat(data['timestamp'])
        return version


class VersionHistory:
    """Manages version history for a single memo."""

    def __init__(self, memo_id: str):
        self.memo_id = memo_id
        self.versions: List[MemoVersion] = []

    def add_version(self, memo_data: Dict, edited_by: str = "system") -> MemoVersion:
        """Add a new version."""
        version_number = len(self.versions) + 1
        version = MemoVersion(version_number, memo_data, edited_by)
        self.versions.append(version)
        return version

    def get_version(self, version_number: int) -> Optional[MemoVersion]:
        """Get specific version."""
        for version in self.versions:
            if version.version_number == version_number:
                return version
        return None

    def get_latest_version(self) -> Optional[MemoVersion]:
        """Get latest version."""
        return self.versions[-1] if self.versions else None

    def get_diff(self, old_version: int, new_version: int) -> str:
        """Get diff between two versions."""
        old = self.get_version(old_version)
        new = self.get_version(new_version)

        if not old or not new:
            return "Version not found"

        old_text = json.dumps(old.memo_data, indent=2, ensure_ascii=False)
        new_text = json.dumps(new.memo_data, indent=2, ensure_ascii=False)

        diff = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f'version_{old_version}',
            tofile=f'version_{new_version}',
            lineterm=''
        )

        return ''.join(diff)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'memo_id': self.memo_id,
            'versions': [v.to_dict() for v in self.versions]
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'VersionHistory':
        """Create from dictionary."""
        history = cls(data['memo_id'])
        history.versions = [MemoVersion.from_dict(v) for v in data['versions']]
        return history


class VersionManager:
    """Manages version histories for all memos."""

    def __init__(self, data_dir: Path, logger: Optional[logging.Logger] = None):
        self.data_dir = data_dir
        self.versions_dir = data_dir / "versions"
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger or logging.getLogger(__name__)
        self.histories: Dict[str, VersionHistory] = {}
        self._load_histories()

    def _get_history_file(self, memo_id: str) -> Path:
        """Get file path for memo history."""
        return self.versions_dir / f"{memo_id}.json"

    def _load_histories(self):
        """Load all version histories."""
        if not self.versions_dir.exists():
            return

        for history_file in self.versions_dir.glob("*.json"):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    history = VersionHistory.from_dict(data)
                    self.histories[history.memo_id] = history
            except Exception as e:
                self.logger.error(f"Failed to load history {history_file}: {e}")

    def _save_history(self, memo_id: str):
        """Save version history for a memo."""
        if memo_id not in self.histories:
            return

        history_file = self._get_history_file(memo_id)
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(self.histories[memo_id].to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save history for {memo_id}: {e}")

    def track_change(self, memo_id: str, memo_data: Dict, edited_by: str = "system"):
        """Track a change to a memo."""
        if memo_id not in self.histories:
            self.histories[memo_id] = VersionHistory(memo_id)

        self.histories[memo_id].add_version(memo_data, edited_by)
        self._save_history(memo_id)

    def get_history(self, memo_id: str) -> Optional[VersionHistory]:
        """Get version history for a memo."""
        return self.histories.get(memo_id)

    def get_version(self, memo_id: str, version_number: int) -> Optional[Dict]:
        """Get specific version of a memo."""
        history = self.get_history(memo_id)
        if not history:
            return None

        version = history.get_version(version_number)
        return version.memo_data if version else None

    def rollback(self, memo_id: str, version_number: int) -> Optional[Dict]:
        """Rollback to a specific version."""
        version_data = self.get_version(memo_id, version_number)
        if version_data:
            # Track the rollback as a new version
            self.track_change(memo_id, version_data, "system:rollback")
        return version_data

    def show_history(self, memo_id: str) -> str:
        """Format version history for display."""
        history = self.get_history(memo_id)
        if not history or not history.versions:
            return f"No version history for memo {memo_id}"

        lines = [f"Version History for Memo {memo_id}:", ""]
        for version in history.versions:
            lines.append(f"Version {version.version_number}")
            lines.append(f"  Timestamp: {version.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append(f"  Edited by: {version.edited_by}")
            lines.append(f"  Text: {version.memo_data.get('text', '')[:50]}...")
            lines.append("")

        return "\n".join(lines)

    def show_diff(self, memo_id: str, old_version: int, new_version: int) -> str:
        """Show diff between two versions."""
        history = self.get_history(memo_id)
        if not history:
            return f"No version history for memo {memo_id}"

        return history.get_diff(old_version, new_version)

    def cleanup_old_versions(self, memo_id: str, keep_count: int = 10):
        """Keep only the N most recent versions."""
        history = self.get_history(memo_id)
        if not history:
            return

        if len(history.versions) > keep_count:
            history.versions = history.versions[-keep_count:]
            self._save_history(memo_id)

    def get_statistics(self) -> Dict:
        """Get version control statistics."""
        total_memos = len(self.histories)
        total_versions = sum(len(h.versions) for h in self.histories.values())
        avg_versions = total_versions / total_memos if total_memos > 0 else 0

        most_edited = None
        max_versions = 0
        for memo_id, history in self.histories.items():
            if len(history.versions) > max_versions:
                max_versions = len(history.versions)
                most_edited = memo_id

        return {
            'total_memos_tracked': total_memos,
            'total_versions': total_versions,
            'average_versions_per_memo': round(avg_versions, 2),
            'most_edited_memo': most_edited,
            'most_edited_versions': max_versions,
        }

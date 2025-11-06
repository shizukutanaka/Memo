#!/usr/bin/env python3
"""Attachment management for memos."""

import hashlib
import shutil
from pathlib import Path
from typing import Dict, List, Optional
import logging
import json
from datetime import datetime


class Attachment:
    """Represents a file attachment."""

    def __init__(self, file_path: Path, memo_id: str):
        self.file_path = Path(file_path)
        self.memo_id = memo_id
        self.filename = self.file_path.name
        self.size = self.file_path.stat().st_size if self.file_path.exists() else 0
        self.mime_type = self._guess_mime_type()
        self.created_at = datetime.now()
        self.checksum = self._calculate_checksum()

    def _guess_mime_type(self) -> str:
        """Guess MIME type from extension."""
        ext_map = {
            '.txt': 'text/plain',
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.zip': 'application/zip',
            '.md': 'text/markdown',
            '.json': 'application/json',
        }
        return ext_map.get(self.file_path.suffix.lower(), 'application/octet-stream')

    def _calculate_checksum(self) -> str:
        """Calculate SHA256 checksum of file."""
        if not self.file_path.exists():
            return ""

        sha256_hash = hashlib.sha256()
        with open(self.file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'filename': self.filename,
            'memo_id': self.memo_id,
            'size': self.size,
            'mime_type': self.mime_type,
            'created_at': self.created_at.isoformat(),
            'checksum': self.checksum,
        }

    @classmethod
    def from_dict(cls, data: Dict, file_path: Path) -> 'Attachment':
        """Create from dictionary."""
        attachment = cls(file_path, data['memo_id'])
        attachment.created_at = datetime.fromisoformat(data['created_at'])
        return attachment


class AttachmentManager:
    """Manages file attachments for memos."""

    def __init__(self, data_dir: Path, logger: Optional[logging.Logger] = None):
        self.data_dir = data_dir
        self.attachments_dir = data_dir / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.attachments_dir / "index.json"
        self.logger = logger or logging.getLogger(__name__)
        self.index: Dict[str, List[Dict]] = {}  # memo_id -> list of attachments
        self._load_index()

        # Maximum file size (10MB by default)
        self.max_file_size = 10 * 1024 * 1024

    def _load_index(self):
        """Load attachment index."""
        if not self.index_file.exists():
            return

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                self.index = json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load attachment index: {e}")

    def _save_index(self):
        """Save attachment index."""
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(self.index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save attachment index: {e}")

    def _get_attachment_path(self, memo_id: str, filename: str) -> Path:
        """Get storage path for attachment."""
        # Create subdirectory for memo
        memo_dir = self.attachments_dir / memo_id
        memo_dir.mkdir(parents=True, exist_ok=True)
        return memo_dir / filename

    def attach_file(self, memo_id: str, file_path: Path) -> Optional[Attachment]:
        """Attach a file to a memo."""
        if not file_path.exists():
            self.logger.error(f"File not found: {file_path}")
            return None

        # Check file size
        file_size = file_path.stat().st_size
        if file_size > self.max_file_size:
            self.logger.error(f"File too large: {file_size} bytes (max: {self.max_file_size})")
            return None

        # Copy file to attachments directory
        dest_path = self._get_attachment_path(memo_id, file_path.name)

        # Handle duplicate filenames
        if dest_path.exists():
            base = dest_path.stem
            ext = dest_path.suffix
            counter = 1
            while dest_path.exists():
                dest_path = dest_path.parent / f"{base}_{counter}{ext}"
                counter += 1

        try:
            shutil.copy2(file_path, dest_path)
        except Exception as e:
            self.logger.error(f"Failed to copy file: {e}")
            return None

        # Create attachment record
        attachment = Attachment(dest_path, memo_id)

        # Update index
        if memo_id not in self.index:
            self.index[memo_id] = []
        self.index[memo_id].append(attachment.to_dict())
        self._save_index()

        return attachment

    def remove_attachment(self, memo_id: str, filename: str) -> bool:
        """Remove an attachment."""
        if memo_id not in self.index:
            return False

        # Find and remove from index
        attachments = self.index[memo_id]
        found = False
        for i, att in enumerate(attachments):
            if att['filename'] == filename:
                attachments.pop(i)
                found = True
                break

        if not found:
            return False

        # Remove file
        file_path = self._get_attachment_path(memo_id, filename)
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            self.logger.error(f"Failed to remove file: {e}")

        # Clean up empty memo directory
        memo_dir = self.attachments_dir / memo_id
        if memo_dir.exists() and not any(memo_dir.iterdir()):
            memo_dir.rmdir()

        self._save_index()
        return True

    def get_attachments(self, memo_id: str) -> List[Dict]:
        """Get all attachments for a memo."""
        return self.index.get(memo_id, [])

    def remove_all_attachments(self, memo_id: str) -> int:
        """Remove all attachments for a memo."""
        if memo_id not in self.index:
            return 0

        count = len(self.index[memo_id])

        # Remove all files
        memo_dir = self.attachments_dir / memo_id
        if memo_dir.exists():
            shutil.rmtree(memo_dir)

        # Remove from index
        del self.index[memo_id]
        self._save_index()

        return count

    def verify_attachment(self, memo_id: str, filename: str) -> bool:
        """Verify attachment integrity using checksum."""
        attachments = self.get_attachments(memo_id)
        for att_data in attachments:
            if att_data['filename'] == filename:
                file_path = self._get_attachment_path(memo_id, filename)
                if not file_path.exists():
                    return False

                # Recalculate checksum
                temp_att = Attachment(file_path, memo_id)
                return temp_att.checksum == att_data['checksum']

        return False

    def get_statistics(self) -> Dict:
        """Get attachment statistics."""
        total_memos = len(self.index)
        total_attachments = sum(len(atts) for atts in self.index.values())
        total_size = 0

        for memo_id, attachments in self.index.items():
            for att in attachments:
                total_size += att['size']

        return {
            'total_memos_with_attachments': total_memos,
            'total_attachments': total_attachments,
            'total_size_bytes': total_size,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
        }

    def list_all_attachments(self) -> str:
        """Format all attachments for display."""
        if not self.index:
            return "No attachments"

        lines = ["📎 Attachments:", ""]
        for memo_id, attachments in self.index.items():
            lines.append(f"Memo {memo_id}:")
            for att in attachments:
                size_kb = round(att['size'] / 1024, 2)
                lines.append(f"  - {att['filename']} ({size_kb} KB)")
                lines.append(f"    Type: {att['mime_type']}")
            lines.append("")

        return "\n".join(lines)

    def search_by_type(self, mime_type: str) -> List[Dict]:
        """Search attachments by MIME type."""
        results = []
        for memo_id, attachments in self.index.items():
            for att in attachments:
                if att['mime_type'] == mime_type:
                    results.append({
                        'memo_id': memo_id,
                        **att
                    })
        return results

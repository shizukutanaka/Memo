#!/usr/bin/env python3
"""Data integrity and validation for memo system."""

import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timezone
import logging
import hashlib


class IntegrityChecker:
    """Check and maintain data integrity."""

    def __init__(self, data_file: Path, logger: Optional[logging.Logger] = None):
        self.data_file = data_file
        self.logger = logger or logging.getLogger(__name__)
        self.issues: List[Dict] = []

    def check_file_integrity(self) -> Tuple[bool, List[Dict]]:
        """Check file integrity and return status and issues."""
        self.issues.clear()

        if not self.data_file.exists():
            return True, []  # Empty file is valid

        # Check file is readable
        try:
            with self.data_file.open("r", encoding="utf-8") as f:
                pass
        except (OSError, PermissionError) as e:
            self.issues.append({
                'type': 'file_error',
                'severity': 'critical',
                'message': f"Cannot read file: {e}"
            })
            return False, self.issues

        # Check JSON structure
        line_num = 0
        memo_ids = set()
        duplicate_ids = []

        try:
            with self.data_file.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    # Check JSON parsing
                    try:
                        memo = json.loads(line)
                    except json.JSONDecodeError as e:
                        self.issues.append({
                            'type': 'json_error',
                            'severity': 'error',
                            'line': line_num,
                            'message': f"Invalid JSON: {e}"
                        })
                        continue

                    # Check required fields
                    required_fields = ['id', 'timestamp', 'text']
                    for field in required_fields:
                        if field not in memo:
                            self.issues.append({
                                'type': 'missing_field',
                                'severity': 'error',
                                'line': line_num,
                                'memo_id': memo.get('id', 'unknown'),
                                'field': field,
                                'message': f"Missing required field: {field}"
                            })

                    # Check for duplicate IDs
                    memo_id = memo.get('id')
                    if memo_id:
                        if memo_id in memo_ids:
                            duplicate_ids.append(memo_id)
                            self.issues.append({
                                'type': 'duplicate_id',
                                'severity': 'warning',
                                'line': line_num,
                                'memo_id': memo_id,
                                'message': f"Duplicate memo ID: {memo_id}"
                            })
                        else:
                            memo_ids.add(memo_id)

                    # Check timestamp validity
                    timestamp = memo.get('timestamp')
                    if timestamp:
                        try:
                            datetime.fromisoformat(timestamp)
                        except (ValueError, TypeError) as e:
                            self.issues.append({
                                'type': 'invalid_timestamp',
                                'severity': 'warning',
                                'line': line_num,
                                'memo_id': memo.get('id', 'unknown'),
                                'message': f"Invalid timestamp: {e}"
                            })

                    # Check status validity
                    status = memo.get('status', 'active')
                    valid_statuses = {'active', 'completed', 'archived'}
                    if status not in valid_statuses:
                        self.issues.append({
                            'type': 'invalid_status',
                            'severity': 'warning',
                            'line': line_num,
                            'memo_id': memo.get('id', 'unknown'),
                            'message': f"Invalid status: {status}"
                        })

        except Exception as e:
            self.issues.append({
                'type': 'unexpected_error',
                'severity': 'critical',
                'message': f"Unexpected error at line {line_num}: {e}"
            })
            return False, self.issues

        # Determine overall status
        critical_issues = [i for i in self.issues if i['severity'] == 'critical']
        has_critical = len(critical_issues) > 0

        return not has_critical, self.issues

    def calculate_checksum(self) -> Optional[str]:
        """Calculate MD5 checksum of data file."""
        if not self.data_file.exists():
            return None

        try:
            hasher = hashlib.md5()
            with self.data_file.open("rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except (OSError, PermissionError) as e:
            self.logger.error(f"Failed to calculate checksum: {e}")
            return None

    def verify_checksum(self, expected_checksum: str) -> bool:
        """Verify file checksum matches expected value."""
        current = self.calculate_checksum()
        if current is None:
            return False
        return current == expected_checksum

    def get_file_stats(self) -> Dict:
        """Get file statistics."""
        if not self.data_file.exists():
            return {
                'exists': False,
                'size_bytes': 0,
                'line_count': 0,
                'memo_count': 0
            }

        try:
            stat = self.data_file.stat()
            line_count = 0
            memo_count = 0

            with self.data_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line_count += 1
                    if line.strip():
                        memo_count += 1

            return {
                'exists': True,
                'size_bytes': stat.st_size,
                'line_count': line_count,
                'memo_count': memo_count,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'checksum': self.calculate_checksum()
            }
        except Exception as e:
            self.logger.error(f"Failed to get file stats: {e}")
            return {'error': str(e)}

    def repair_issues(self, backup_path: Optional[Path] = None) -> Tuple[bool, str]:
        """Attempt to repair integrity issues."""
        if not self.issues:
            return True, "No issues to repair"

        if backup_path:
            # Create backup before repair
            try:
                import shutil
                shutil.copy2(self.data_file, backup_path)
                self.logger.info(f"Created backup at {backup_path}")
            except Exception as e:
                return False, f"Failed to create backup: {e}"

        repaired = []
        failed = []

        # Attempt to fix each issue
        for issue in self.issues:
            issue_type = issue['type']

            if issue_type == 'duplicate_id':
                # Could regenerate IDs, but risky
                failed.append(f"Cannot auto-fix duplicate ID: {issue['memo_id']}")

            elif issue_type == 'invalid_status':
                # Could set to 'active', but requires rewrite
                failed.append(f"Cannot auto-fix invalid status at line {issue['line']}")

            elif issue_type == 'json_error':
                # Cannot automatically fix JSON errors
                failed.append(f"Cannot auto-fix JSON error at line {issue['line']}")

            else:
                failed.append(f"Unknown issue type: {issue_type}")

        if repaired:
            message = f"Repaired {len(repaired)} issues. Failed: {len(failed)}"
            return True, message
        else:
            return False, f"Could not repair issues automatically. Manual intervention required."


class AutoBackup:
    """Automatic backup before destructive operations."""

    def __init__(self, data_file: Path, backup_dir: Path, logger: Optional[logging.Logger] = None):
        self.data_file = data_file
        self.backup_dir = backup_dir
        self.logger = logger or logging.getLogger(__name__)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_pre_operation_backup(self, operation_name: str) -> Optional[Path]:
        """Create backup before destructive operation."""
        if not self.data_file.exists():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"pre_{operation_name}_{timestamp}.jsonl"
        backup_path = self.backup_dir / backup_name

        try:
            import shutil
            shutil.copy2(self.data_file, backup_path)
            self.logger.info(f"Created pre-operation backup: {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            return None

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """Clean up old backups, keeping only most recent."""
        if not self.backup_dir.exists():
            return 0

        # Get all pre-operation backups
        backups = sorted(
            [f for f in self.backup_dir.glob("pre_*.jsonl")],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if len(backups) <= keep_count:
            return 0

        # Delete old backups
        deleted = 0
        for backup in backups[keep_count:]:
            try:
                backup.unlink()
                deleted += 1
                self.logger.info(f"Deleted old backup: {backup}")
            except Exception as e:
                self.logger.error(f"Failed to delete backup {backup}: {e}")

        return deleted


def run_integrity_check(data_file: Path) -> bool:
    """Run integrity check and print results."""
    checker = IntegrityChecker(data_file)
    is_valid, issues = checker.check_file_integrity()

    if is_valid and not issues:
        print("✅ Data integrity check passed")
        return True

    print(f"⚠️  Found {len(issues)} integrity issues:")
    for issue in issues:
        severity_icon = {
            'critical': '❌',
            'error': '⚠️',
            'warning': '💡'
        }.get(issue['severity'], '•')

        print(f"{severity_icon} {issue['type']}: {issue['message']}")
        if 'line' in issue:
            print(f"   Line: {issue['line']}")
        if 'memo_id' in issue:
            print(f"   Memo ID: {issue['memo_id']}")

    return is_valid


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) > 1:
        data_file = Path(sys.argv[1])
    else:
        data_file = Path.home() / ".memo" / "memos.jsonl"

    success = run_integrity_check(data_file)
    sys.exit(0 if success else 1)

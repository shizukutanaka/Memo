"""Core functionality tests for the memo system.

These tests run against the real storage API in ``memo.py``
(:class:`MemoStore`). An earlier version of this file was written against
a ``MemoSystem`` class that never existed in ``memo.py``; the resulting
ImportError was swallowed by a module-level ``pytest.skip``, so the suite
collected zero tests and reported success without verifying anything.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from memo import MemoStore, ValidationError, export_memos, generate_stats_report


@pytest.fixture
def store(test_db_path, mock_home):
    """A MemoStore backed by a temporary database and home directory."""
    return MemoStore(data_file=test_db_path)


def add_memo(store, data):
    """Add a memo described by a fixture dict through the real API."""
    return store.add(
        data["content"],
        tags=data.get("tags"),
        category=data.get("category"),
        status=data.get("status"),
    )


class TestMemoStore:
    """Test suite for core MemoStore functionality."""

    def test_add_memo_success(self, store, sample_memo_data):
        """Test adding a memo successfully."""
        memo = add_memo(store, sample_memo_data)

        assert isinstance(memo, dict)
        assert isinstance(memo["id"], str)
        assert memo["id"]
        assert memo["content"] == sample_memo_data["content"]

    def test_add_memo_minimal(self, store):
        """Test adding a memo with minimal information."""
        memo = store.add("Simple memo")

        assert isinstance(memo, dict)
        assert memo["id"]
        assert memo["content"] == "Simple memo"

    def test_add_memo_empty_content_raises_error(self, store):
        """Test that empty content raises a validation error."""
        with pytest.raises(ValidationError):
            store.add("")

        with pytest.raises(ValidationError):
            store.add("   ")

    def test_list_memos(self, store, multiple_memos):
        """Test listing memos."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        memos = store.list_all(limit=10)

        assert len(memos) == len(multiple_memos)
        assert all(isinstance(m, dict) for m in memos)
        assert all("content" in m for m in memos)

    def test_search_memos(self, store, multiple_memos):
        """Test searching memos by keyword."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        results = store.search("testing")

        assert len(results) > 0
        assert any("testing" in m["content"].lower() for m in results)

    @pytest.mark.parametrize("query", ["議", "整理", "AI", "%", "_"])
    def test_short_search_matches_literal_content(self, store, query):
        match = store.add("議事録を整理する; ai 10% foo_bar")
        store.add("Unrelated notes")

        assert [memo["id"] for memo in store.search(query)] == [match["id"]]

    def test_short_search_respects_filters(self, store):
        match = store.add("整理 current", tags=["work"])
        store.add("整理 completed", tags=["work"], status="completed")
        store.add("整理 personal", tags=["personal"])

        results = store.search("整理", statuses=["active"], tags=["work"])

        assert [memo["id"] for memo in results] == [match["id"]]
        assert results[0]["text"] == "整理 current"
        assert not store.search("整理", from_date=datetime.max.replace(tzinfo=timezone.utc))

    def test_get_memo_by_id(self, store, sample_memo_data):
        """Test retrieving a specific memo by ID."""
        added = add_memo(store, sample_memo_data)
        memo = store.get_by_id(added["id"])

        assert memo is not None
        assert memo["id"] == added["id"]
        assert memo["content"] == sample_memo_data["content"]

    def test_update_memo(self, store, sample_memo_data):
        """Test updating memo content."""
        added = add_memo(store, sample_memo_data)
        new_content = "Updated content"

        updated = store.edit(added["id"], new_content)
        assert updated is not None
        assert updated["content"] == new_content

        fetched = store.get_by_id(added["id"])
        assert fetched["content"] == new_content

    def test_delete_memo(self, store, sample_memo_data):
        """Test deleting a memo.

        MemoStore.delete() is a hard delete: the memo row is removed, so a
        subsequent lookup finds nothing. (There is no soft-delete /
        ``deleted_at`` mechanism in this API.)
        """
        added = add_memo(store, sample_memo_data)

        assert store.delete(added["id"]) is True
        assert store.get_by_id(added["id"]) is None
        # Deleting the same memo again reports that nothing was deleted
        assert store.delete(added["id"]) is False

    def test_get_statistics(self, store, multiple_memos):
        """Test retrieving system statistics."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        stats = generate_stats_report(store, days=30)

        assert isinstance(stats, dict)
        assert "total_memos" in stats
        assert stats["total_memos"] == len(multiple_memos)

    def test_category_filtering(self, store, multiple_memos):
        """Test filtering memos by category."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        work_memos = store.list_all(limit=10, category="work")

        assert len(work_memos) == 1
        assert all(m["category"] == "work" for m in work_memos)

    def test_tag_search(self, store, multiple_memos):
        """Test searching memos by tag."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        urgent_memos = store.search_by_tag("urgent")

        assert len(urgent_memos) == 1
        assert "urgent" in urgent_memos[0]["tags"]


class TestMemoValidation:
    """Test suite for input validation."""

    def test_validate_content_length(self, store):
        """Test that long content within the limit is accepted.

        The enforced maximum is SecurityValidator.MAX_TEXT_LENGTH
        (1,000,000 characters); 100,000 characters is well within it.
        """
        very_long_content = "x" * 100000
        memo = store.add(very_long_content)

        assert memo["id"]
        assert memo["content"] == very_long_content

    def test_new_memo_priority_is_zero(self, store):
        """Test the priority of a newly added memo.

        MemoStore.add() has no priority parameter: priorities are only
        carried through import/migration paths, and new memos always
        start with priority 0.
        """
        memo = store.add("Priority check")

        assert memo["priority"] == 0
        assert store.get_by_id(memo["id"])["priority"] == 0

    def test_validate_status_values(self, store):
        """Test that the valid status values are accepted and stored."""
        valid_statuses = ["active", "completed", "archived"]

        for status in valid_statuses:
            memo = store.add(f"Status {status}", status=status)
            assert memo["id"]
            assert store.get_by_id(memo["id"])["status"] == status


class TestMemoDatabase:
    """Test suite for database operations."""

    def test_database_creation(self, store, test_db_path):
        """Test that database is created properly."""
        assert test_db_path.exists()

        # Verify database schema
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()

        # Check if memos table exists
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memos'"
        )
        result = cursor.fetchone()

        conn.close()

        assert result is not None

    def test_database_integrity(self, store, multiple_memos):
        """Test database integrity after multiple operations."""
        memo_ids = []
        for memo_data in multiple_memos:
            memo = add_memo(store, memo_data)
            memo_ids.append(memo["id"])

        # Update some memos
        store.edit(memo_ids[0], "Updated content")

        # Delete some memos
        store.delete(memo_ids[1])

        # Verify database integrity
        conn = sqlite3.connect(store.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()

        assert result[0] == "ok"


class TestStartupIntegrityCheck:
    """The startup integrity check must verify the real (SQLite) store.

    Regression coverage: ``MemoStore._run_startup_integrity_check`` used
    to call ``IntegrityChecker.check_integrity()`` / ``repair_file()``,
    which never existed (the memo_integrity checker validates the old
    JSONL data file), so every startup logged an ERROR and no check
    ever ran. The check now uses SQLite's own PRAGMA integrity_check.
    """

    @staticmethod
    def _capture_errors(store):
        """Attach a handler collecting ERROR records from the store logger."""
        import logging

        records = []

        class _Collector(logging.Handler):
            def emit(self, record):
                if record.levelno >= logging.ERROR:
                    records.append(record.getMessage())

        handler = _Collector()
        store.logger.addHandler(handler)
        return records, handler

    def test_healthy_database_logs_no_error(self, store):
        records, handler = self._capture_errors(store)
        try:
            store._run_startup_integrity_check()
        finally:
            store.logger.removeHandler(handler)

        assert records == []

    def test_corrupt_database_is_reported(self, store, tmp_path):
        corrupt = tmp_path / "corrupt.db"
        corrupt.write_bytes(b"this is not a sqlite database" * 64)

        original_path = store.db_path
        store.db_path = corrupt
        records, handler = self._capture_errors(store)
        try:
            store._run_startup_integrity_check()
        finally:
            store.logger.removeHandler(handler)
            store.db_path = original_path

        assert records, "a corrupt database must be reported at ERROR level"
        # The report must come from the real check, not from calling a
        # method that does not exist (the old dead code path).
        assert all("has no attribute" not in message for message in records)

    def test_check_disabled_by_config(self, store, monkeypatch):
        real_get = store.config.get

        def fake_get(key, default=None):
            if key == "integrity.check_on_startup":
                return False
            return real_get(key, default)

        monkeypatch.setattr(store.config, "get", fake_get)

        records, handler = self._capture_errors(store)
        try:
            store._run_startup_integrity_check()
        finally:
            store.logger.removeHandler(handler)

        assert records == []


class TestMemoExport:
    """Test suite for export functionality."""

    def test_export_json(self, store, multiple_memos):
        """Test exporting memos to JSON."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        exported = export_memos(store.list_all(limit=0), "json")
        parsed = json.loads(exported)

        assert len(parsed) == len(multiple_memos)
        assert all("content" in m for m in parsed)

    def test_export_csv(self, store, multiple_memos):
        """Test exporting memos to CSV."""
        for memo_data in multiple_memos:
            add_memo(store, memo_data)

        exported = export_memos(store.list_all(limit=0), "csv")
        lines = [line for line in exported.splitlines() if line.strip()]

        # Header row plus one row per memo
        assert lines[0].startswith("id,timestamp,text,tags,category,status")
        assert len(lines) == 1 + len(multiple_memos)


class TestBackupConsistency:
    """Backups must preserve committed data from the WAL-mode database."""

    def test_backup_includes_commit_visible_only_in_wal(self, store):
        reader = sqlite3.connect(str(store.db_path))
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM memos").fetchone()

        try:
            added = store.add("committed while a concurrent reader is open")
            backup_path = store.create_backup("concurrent_reader")

            backup_conn = sqlite3.connect(str(backup_path))
            try:
                rows = backup_conn.execute(
                    "SELECT id, content FROM memos WHERE id = ?", (added["id"],)
                ).fetchall()
            finally:
                backup_conn.close()
        finally:
            reader.close()

        assert rows == [(added["id"], "committed while a concurrent reader is open")]

    def test_restore_replaces_commit_visible_only_in_wal(self, store):
        empty_backup = store.create_backup("empty")

        reader = sqlite3.connect(str(store.db_path))
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM memos").fetchone()

        try:
            store.add("post-backup memo")
            assert store.restore_backup(empty_backup) is True

            verification_conn = sqlite3.connect(str(store.db_path))
            try:
                count = verification_conn.execute("SELECT count(*) FROM memos").fetchone()[0]
            finally:
                verification_conn.close()
        finally:
            reader.close()

        assert count == 0


class TestQuarantine:
    """Invalid lines are quarantined for manual inspection.

    Regression: ``MemoStore.corrupted_file`` was never assigned, so
    ``_quarantine_line`` raised AttributeError (not the OSError it
    catches) and crashed the caller instead of recording the line.
    """

    def test_quarantine_line_is_recorded(self, store):
        store._quarantine_line('{"broken": ')
        store._quarantine_line('{"also broken": ')

        content = store.corrupted_file.read_text(encoding="utf-8")
        assert content.splitlines() == ['{"broken": ', '{"also broken": ']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

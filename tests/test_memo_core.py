"""Core functionality tests for the memo system."""

import pytest
import sqlite3
from pathlib import Path
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from memo import MemoSystem, MemoValidationError
except ImportError:
    pytest.skip("memo module not available", allow_module_level=True)


class TestMemoSystem:
    """Test suite for core MemoSystem functionality."""

    def test_add_memo_success(self, test_db_path, sample_memo_data):
        """Test adding a memo successfully."""
        system = MemoSystem(db_path=test_db_path)
        memo_id = system.add_memo(**sample_memo_data)

        assert isinstance(memo_id, int)
        assert memo_id > 0

    def test_add_memo_minimal(self, test_db_path):
        """Test adding a memo with minimal information."""
        system = MemoSystem(db_path=test_db_path)
        memo_id = system.add_memo(content="Simple memo")

        assert isinstance(memo_id, int)
        assert memo_id > 0

    def test_add_memo_empty_content_raises_error(self, test_db_path):
        """Test that empty content raises ValidationError."""
        system = MemoSystem(db_path=test_db_path)

        with pytest.raises((MemoValidationError, ValueError)):
            system.add_memo(content="")

    def test_list_memos(self, test_db_path, multiple_memos):
        """Test listing memos."""
        system = MemoSystem(db_path=test_db_path)

        # Add multiple memos
        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        # List all memos
        memos = system.list_memos(limit=10)

        assert len(memos) == len(multiple_memos)
        assert all(isinstance(m, dict) for m in memos)
        assert all("content" in m for m in memos)

    def test_search_memos(self, test_db_path, multiple_memos):
        """Test searching memos by keyword."""
        system = MemoSystem(db_path=test_db_path)

        # Add test data
        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        # Search for specific keyword
        results = system.search_memos(query="testing")

        assert len(results) > 0
        assert any("testing" in m["content"].lower() for m in results)

    def test_get_memo_by_id(self, test_db_path, sample_memo_data):
        """Test retrieving a specific memo by ID."""
        system = MemoSystem(db_path=test_db_path)

        memo_id = system.add_memo(**sample_memo_data)
        memo = system.get_memo(memo_id)

        assert memo is not None
        assert memo["id"] == memo_id
        assert memo["content"] == sample_memo_data["content"]

    def test_update_memo(self, test_db_path, sample_memo_data):
        """Test updating memo content."""
        system = MemoSystem(db_path=test_db_path)

        memo_id = system.add_memo(**sample_memo_data)
        new_content = "Updated content"

        system.update_memo(memo_id, content=new_content)
        updated_memo = system.get_memo(memo_id)

        assert updated_memo["content"] == new_content

    def test_delete_memo(self, test_db_path, sample_memo_data):
        """Test deleting a memo (soft delete)."""
        system = MemoSystem(db_path=test_db_path)

        memo_id = system.add_memo(**sample_memo_data)
        system.delete_memo(memo_id)

        # Verify memo is marked as deleted
        memo = system.get_memo(memo_id, include_deleted=True)
        assert memo["deleted_at"] is not None

    def test_get_statistics(self, test_db_path, multiple_memos):
        """Test retrieving system statistics."""
        system = MemoSystem(db_path=test_db_path)

        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        stats = system.get_statistics()

        assert isinstance(stats, dict)
        assert "total_memos" in stats
        assert stats["total_memos"] == len(multiple_memos)

    def test_category_filtering(self, test_db_path, multiple_memos):
        """Test filtering memos by category."""
        system = MemoSystem(db_path=test_db_path)

        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        work_memos = system.list_memos(category="work")

        assert len(work_memos) > 0
        assert all(m["category"] == "work" for m in work_memos)

    def test_tag_search(self, test_db_path, multiple_memos):
        """Test searching memos by tag."""
        system = MemoSystem(db_path=test_db_path)

        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        urgent_memos = system.search_by_tag("urgent")

        assert len(urgent_memos) > 0


class TestMemoValidation:
    """Test suite for input validation."""

    def test_validate_content_length(self, test_db_path):
        """Test content length validation."""
        system = MemoSystem(db_path=test_db_path)

        # Test maximum length (if applicable)
        very_long_content = "x" * 100000
        memo_id = system.add_memo(content=very_long_content)

        assert memo_id > 0

    def test_validate_priority_range(self, test_db_path):
        """Test priority value validation."""
        system = MemoSystem(db_path=test_db_path)

        # Valid priorities
        for priority in [0, 1, 2, 3]:
            memo_id = system.add_memo(
                content=f"Priority {priority}",
                priority=priority
            )
            assert memo_id > 0

    def test_validate_status_values(self, test_db_path):
        """Test status value validation."""
        system = MemoSystem(db_path=test_db_path)

        valid_statuses = ["active", "completed", "archived"]

        for status in valid_statuses:
            memo_id = system.add_memo(
                content=f"Status {status}",
                status=status
            )
            assert memo_id > 0


class TestMemoDatabase:
    """Test suite for database operations."""

    def test_database_creation(self, test_db_path):
        """Test that database is created properly."""
        system = MemoSystem(db_path=test_db_path)

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

    def test_database_integrity(self, test_db_path, multiple_memos):
        """Test database integrity after multiple operations."""
        system = MemoSystem(db_path=test_db_path)

        # Add memos
        memo_ids = []
        for memo_data in multiple_memos:
            memo_id = system.add_memo(**memo_data)
            memo_ids.append(memo_id)

        # Update some memos
        system.update_memo(memo_ids[0], content="Updated content")

        # Delete some memos
        system.delete_memo(memo_ids[1])

        # Verify database integrity
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        conn.close()

        assert result[0] == "ok"


class TestMemoExport:
    """Test suite for export functionality."""

    def test_export_json(self, test_db_path, temp_dir, multiple_memos):
        """Test exporting memos to JSON."""
        system = MemoSystem(db_path=test_db_path)

        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        export_path = temp_dir / "export.json"
        system.export_memos(str(export_path), format="json")

        assert export_path.exists()
        assert export_path.stat().st_size > 0

    def test_export_csv(self, test_db_path, temp_dir, multiple_memos):
        """Test exporting memos to CSV."""
        system = MemoSystem(db_path=test_db_path)

        for memo_data in multiple_memos:
            system.add_memo(**memo_data)

        export_path = temp_dir / "export.csv"
        system.export_memos(str(export_path), format="csv")

        assert export_path.exists()
        assert export_path.stat().st_size > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

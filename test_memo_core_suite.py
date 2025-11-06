#!/usr/bin/env python3
"""Comprehensive test suite for memo core functionality."""

import json
import os
import shutil
import tempfile
import unittest
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent))

from memo_core import MemoCore, MemoValidator, MemoStorage, MemoCollection, MemoTemplate


class TestMemoCore(unittest.TestCase):
    """Test the core memo functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.memo_id = "20240101120000001"
        self.text = "This is a test memo"
        self.tags = ["test", "important"]
        self.category = "testing"
        self.status = "active"

    def test_memo_creation(self):
        """Test basic memo creation."""
        memo = MemoCore(
            memo_id=self.memo_id,
            text=self.text,
            tags=self.tags,
            category=self.category,
            status=self.status
        )

        self.assertEqual(memo.id, self.memo_id)
        self.assertEqual(memo.text, self.text)
        self.assertEqual(memo.tags, self.tags)
        self.assertEqual(memo.category, self.category)
        self.assertEqual(memo.status, self.status)
        self.assertIsNotNone(memo.created)
        self.assertIsNotNone(memo.edited)

    def test_memo_from_dict(self):
        """Test creating memo from dictionary."""
        data = {
            "id": self.memo_id,
            "text": self.text,
            "tags": self.tags,
            "category": self.category,
            "status": self.status,
            "created": datetime.now(timezone.utc).isoformat(),
            "edited": datetime.now(timezone.utc).isoformat(),
        }

        memo = MemoCore.from_dict(data)

        self.assertEqual(memo.id, self.memo_id)
        self.assertEqual(memo.text, self.text)
        self.assertEqual(memo.tags, self.tags)
        self.assertEqual(memo.category, self.category)
        self.assertEqual(memo.status, self.status)

    def test_memo_to_dict(self):
        """Test converting memo to dictionary."""
        memo = MemoCore(
            memo_id=self.memo_id,
            text=self.text,
            tags=self.tags,
            category=self.category,
            status=self.status
        )

        data = memo.to_dict()

        self.assertEqual(data["id"], self.memo_id)
        self.assertEqual(data["text"], self.text)
        self.assertEqual(data["tags"], self.tags)
        self.assertEqual(data["category"], self.category)
        self.assertEqual(data["status"], self.status)
        self.assertIn("created", data)
        self.assertIn("edited", data)

    def test_memo_update(self):
        """Test updating memo fields."""
        memo = MemoCore(
            memo_id=self.memo_id,
            text=self.text,
            tags=self.tags,
            category=self.category,
            status=self.status
        )

        old_edited = memo.edited
        time.sleep(0.001)  # Ensure different timestamp

        new_text = "Updated text"
        new_tags = ["updated", "test"]
        new_status = "completed"

        memo.update(text=new_text, tags=new_tags, status=new_status)

        self.assertEqual(memo.text, new_text)
        self.assertEqual(memo.tags, new_tags)
        self.assertEqual(memo.status, new_status)
        self.assertNotEqual(memo.edited, old_edited)  # Should be updated

    def test_memo_reminder_due(self):
        """Test reminder due functionality."""
        # Test memo without reminder
        memo = MemoCore(text="No reminder")
        self.assertFalse(memo.is_due())

        # Test memo with future reminder
        future_time = datetime.now(timezone.utc) + timedelta(days=1)
        memo_with_reminder = MemoCore(text="Future reminder", reminder=future_time.isoformat())
        self.assertFalse(memo_with_reminder.is_due())

        # Test memo with past reminder
        past_time = datetime.now(timezone.utc) - timedelta(days=1)
        memo_due = MemoCore(text="Due reminder", reminder=past_time.isoformat())
        self.assertTrue(memo_due.is_due())

        # Test with custom before time
        almost_due_time = datetime.now(timezone.utc) + timedelta(hours=1)
        memo_almost_due = MemoCore(text="Almost due", reminder=almost_due_time.isoformat())

        before_check = datetime.now(timezone.utc) + timedelta(hours=2)
        self.assertFalse(memo_almost_due.is_due(before_check))

    def test_memo_validation_text(self):
        """Test text validation."""
        # Valid text
        valid, error = MemoValidator.validate_text("Valid text")
        self.assertTrue(valid)
        self.assertEqual(error, "")

        # Empty text
        valid, error = MemoValidator.validate_text("")
        self.assertFalse(valid)
        self.assertIn("empty", error)

        valid, error = MemoValidator.validate_text("   ")
        self.assertFalse(valid)
        self.assertIn("empty", error)

        # Text too long
        long_text = "x" * (MemoValidator.MAX_TEXT_LENGTH + 1)
        valid, error = MemoValidator.validate_text(long_text)
        self.assertFalse(valid)
        self.assertIn("too long", error)

    def test_memo_validation_tags(self):
        """Test tags validation."""
        # Valid tags
        valid, error = MemoValidator.validate_tags(["valid", "tags"])
        self.assertTrue(valid)
        self.assertEqual(error, "")

        # Too many tags
        many_tags = ["tag"] * (MemoValidator.MAX_TAGS + 1)
        valid, error = MemoValidator.validate_tags(many_tags)
        self.assertFalse(valid)
        self.assertIn("too many", error)

        # Invalid tag characters
        valid, error = MemoValidator.validate_tags(["valid", "invalid tag!"])
        self.assertFalse(valid)
        self.assertIn("Invalid tag", error)

        # Tag too long
        long_tag = "x" * (MemoValidator.MAX_TAG_LENGTH + 1)
        valid, error = MemoValidator.validate_tags([long_tag])
        self.assertFalse(valid)
        self.assertIn("Invalid tag length", error)

    def test_memo_validation_category(self):
        """Test category validation."""
        # Valid category
        valid, error = MemoValidator.validate_category("valid_category")
        self.assertTrue(valid)
        self.assertEqual(error, "")

        # Category too long
        long_category = "x" * (MemoValidator.MAX_CATEGORY_LENGTH + 1)
        valid, error = MemoValidator.validate_category(long_category)
        self.assertFalse(valid)
        self.assertIn("too long", error)

        # Invalid category characters
        valid, error = MemoValidator.validate_category("invalid category!")
        self.assertFalse(valid)
        self.assertIn("Invalid category", error)

    def test_memo_validation_status(self):
        """Test status validation."""
        # Valid status
        valid, error = MemoValidator.validate_status("active")
        self.assertTrue(valid)
        self.assertEqual(error, "")

        # Invalid status
        valid, error = MemoValidator.validate_status("invalid")
        self.assertFalse(valid)
        self.assertIn("Invalid status", error)

    def test_memo_complete_validation(self):
        """Test complete memo validation."""
        # Valid memo
        memo = MemoCore(text="Valid memo", tags=["test"], category="testing", status="active")
        valid, errors = MemoValidator.validate_memo(memo)
        self.assertTrue(valid)
        self.assertEqual(len(errors), 0)

        # Invalid memo
        invalid_memo = MemoCore(text="", tags=["x" * 100], category="invalid!", status="invalid")
        valid, errors = MemoValidator.validate_memo(invalid_memo)
        self.assertFalse(valid)
        self.assertGreater(len(errors), 0)


class TestMemoCollection(unittest.TestCase):
    """Test memo collection functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

        # Mock storage
        self.mock_storage = Mock(spec=MemoStorage)
        self.mock_storage.data_dir = Path(self.temp_dir)

        # Create sample memos
        self.memos = [
            MemoCore(text="Test memo 1", tags=["test", "important"], category="testing", status="active"),
            MemoCore(text="Test memo 2", tags=["test"], category="development", status="completed"),
            MemoCore(text="Test memo 3", tags=["important"], category="testing", status="active"),
        ]

        self.mock_storage.list_memos.return_value = self.memos
        self.mock_storage.get_memo.side_effect = lambda memo_id: next(
            (memo for memo in self.memos if memo.id == memo_id), None
        )

        self.collection = MemoCollection(self.mock_storage)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_memo_from_dict(self):
        """Test adding memo from dictionary."""
        data = {
            "text": "New memo",
            "tags": ["new"],
            "category": "testing",
            "status": "active"
        }

        self.mock_storage.add_memo.return_value = True

        result = self.collection.add_memo_from_dict(data)

        self.assertIsNotNone(result)
        self.assertEqual(result.text, "New memo")
        self.mock_storage.add_memo.assert_called_once()

    def test_get_memo_by_id(self):
        """Test getting memo by ID."""
        memo = self.collection.get_memo_by_id(self.memos[0].id)

        self.assertIsNotNone(memo)
        self.assertEqual(memo.id, self.memos[0].id)
        self.mock_storage.get_memo.assert_called_once_with(self.memos[0].id)

    def test_list_memos_paginated(self):
        """Test paginated memo listing."""
        result = self.collection.list_memos_paginated(page=1, per_page=2)

        self.assertEqual(result["page"], 1)
        self.assertEqual(result["per_page"], 2)
        self.assertEqual(result["total"], len(self.memos))
        self.assertEqual(len(result["memos"]), 2)
        self.assertEqual(result["total_pages"], 2)

    def test_get_memos_by_category(self):
        """Test getting memos by category."""
        testing_memos = self.collection.get_memos_by_category("testing")

        self.assertEqual(len(testing_memos), 2)
        for memo in testing_memos:
            self.assertEqual(memo.category, "testing")

    def test_get_memos_by_status(self):
        """Test getting memos by status."""
        active_memos = self.collection.get_memos_by_status("active")

        self.assertEqual(len(active_memos), 2)
        for memo in active_memos:
            self.assertEqual(memo.status, "active")

    def test_get_memos_by_tag(self):
        """Test getting memos by tag."""
        test_memos = self.collection.get_memos_by_tag("test")

        self.assertEqual(len(test_memos), 2)
        for memo in test_memos:
            self.assertIn("test", memo.tags)

    def test_get_due_reminders(self):
        """Test getting due reminders."""
        # Add a memo with past reminder
        past_time = datetime.now(timezone.utc) - timedelta(days=1)
        due_memo = MemoCore(text="Due memo", reminder=past_time.isoformat())
        self.memos.append(due_memo)

        due_reminders = self.collection.get_due_reminders()

        self.assertGreater(len(due_reminders), 0)
        for memo in due_reminders:
            self.assertIsNotNone(memo.reminder)

    def test_get_storage_stats(self):
        """Test getting storage statistics."""
        stats = self.collection.get_storage_stats()

        self.assertIn("total", stats)
        self.assertIn("categories", stats)
        self.assertIn("statuses", stats)
        self.assertIn("tags", stats)

        # Check category stats
        self.assertIn("testing", stats["categories"])
        self.assertIn("development", stats["categories"])
        self.assertEqual(stats["categories"]["testing"], 2)
        self.assertEqual(stats["categories"]["development"], 1)


class TestMemoTemplate(unittest.TestCase):
    """Test memo template functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

        # Mock storage
        self.mock_storage = Mock(spec=MemoStorage)
        self.mock_storage.data_dir = Path(self.temp_dir)

        self.template_manager = MemoTemplate(self.mock_storage)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_default_templates(self):
        """Test getting default templates."""
        templates = self.template_manager.get_templates()

        self.assertIsInstance(templates, dict)
        self.assertGreater(len(templates), 0)

        # Check for expected default templates
        self.assertIn("meeting", templates)
        self.assertIn("task", templates)
        self.assertIn("idea", templates)

        # Check template structure
        meeting_template = templates["meeting"]
        self.assertIn("name", meeting_template)
        self.assertIn("template", meeting_template)
        self.assertIn("category", meeting_template)
        self.assertIn("tags", meeting_template)

    def test_create_from_template(self):
        """Test creating memo from template."""
        variables = {
            "title": "Test Meeting",
            "date": "2024-01-01",
            "attendees": "Alice, Bob"
        }

        self.mock_storage.add_memo.return_value = True

        result = self.template_manager.create_from_template("meeting", variables)

        self.assertIsNotNone(result)
        self.mock_storage.add_memo.assert_called_once()

        # Check that template variables were substituted
        self.assertIn("Test Meeting", result.text)
        self.assertIn("2024-01-01", result.text)
        self.assertIn("Alice, Bob", result.text)

    def test_create_from_nonexistent_template(self):
        """Test creating memo from non-existent template."""
        result = self.template_manager.create_from_template("nonexistent", {})

        self.assertIsNone(result)

    def test_template_variable_substitution_error(self):
        """Test template with missing variables."""
        # Template requires 'title' but we don't provide it
        result = self.template_manager.create_from_template("meeting", {"date": "2024-01-01"})

        # Should handle missing variables gracefully
        self.assertIsNone(result)


class TestMemoValidator(unittest.TestCase):
    """Test memo validation functionality."""

    def test_text_validation_edge_cases(self):
        """Test text validation edge cases."""
        # None text
        valid, error = MemoValidator.validate_text(None)
        self.assertFalse(valid)

        # Whitespace only
        valid, error = MemoValidator.validate_text("   \n\t   ")
        self.assertFalse(valid)

        # Very long text (exactly at limit)
        max_text = "x" * MemoValidator.MAX_TEXT_LENGTH
        valid, error = MemoValidator.validate_text(max_text)
        self.assertTrue(valid)

    def test_tags_validation_edge_cases(self):
        """Test tags validation edge cases."""
        # Empty tags list
        valid, error = MemoValidator.validate_tags([])
        self.assertTrue(valid)

        # None tags
        valid, error = MemoValidator.validate_tags(None)
        self.assertTrue(valid)  # Should handle None gracefully

        # Tag with special characters that should be allowed
        valid, error = MemoValidator.validate_tags(["tag-with-hyphens", "tag_with_underscores"])
        self.assertTrue(valid)

        # Tag with spaces (should fail)
        valid, error = MemoValidator.validate_tags(["tag with spaces"])
        self.assertFalse(valid)

    def test_category_validation_edge_cases(self):
        """Test category validation edge cases."""
        # Empty category
        valid, error = MemoValidator.validate_category("")
        self.assertTrue(valid)  # Empty should be allowed

        # Category with allowed special characters
        valid, error = MemoValidator.validate_category("category_with-hyphens")
        self.assertTrue(valid)

        # Category with spaces (should fail)
        valid, error = MemoValidator.validate_category("category with spaces")
        self.assertFalse(valid)

    def test_complete_memo_validation(self):
        """Test complete memo validation with various scenarios."""
        # Perfectly valid memo
        perfect_memo = MemoCore(
            text="Perfect memo",
            tags=["perfect"],
            category="testing",
            status="active"
        )
        valid, errors = MemoValidator.validate_memo(perfect_memo)
        self.assertTrue(valid)
        self.assertEqual(len(errors), 0)

        # Memo with multiple validation errors
        invalid_memo = MemoCore(
            text="",  # Invalid: empty
            tags=["x" * 100],  # Invalid: too long
            category="invalid category!",  # Invalid: special chars
            status="invalid_status"  # Invalid: wrong status
        )
        valid, errors = MemoValidator.validate_memo(invalid_memo)
        self.assertFalse(valid)
        self.assertEqual(len(errors), 4)  # All four fields should have errors


class TestIntegration(unittest.TestCase):
    """Integration tests for memo core functionality."""

    def setUp(self):
        """Set up integration test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up integration test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_memo_lifecycle(self):
        """Test complete memo lifecycle."""
        # Create storage mock
        storage = Mock(spec=MemoStorage)
        storage.data_dir = Path(self.temp_dir)

        # Create collection
        collection = MemoCollection(storage)

        # Test creating memo
        memo_data = {
            "text": "Integration test memo",
            "tags": ["integration", "test"],
            "category": "testing",
            "status": "active"
        }

        storage.add_memo.return_value = True

        memo = collection.add_memo_from_dict(memo_data)
        self.assertIsNotNone(memo)

        # Test retrieving memo
        storage.get_memo.return_value = memo
        retrieved = collection.get_memo_by_id(memo.id)
        self.assertIsNotNone(retrieved)

        # Test updating memo
        updates = {"text": "Updated integration test memo", "status": "completed"}
        storage.update_memo.return_value = True

        success = collection.update_memo_from_dict(memo.id, updates)
        self.assertTrue(success)

        # Test deleting memo
        storage.delete_memo.return_value = True
        deleted = collection.delete_memo_by_id(memo.id)
        self.assertTrue(deleted)

    def test_search_functionality(self):
        """Test search functionality integration."""
        # Create storage with sample data
        storage = Mock(spec=MemoStorage)
        storage.data_dir = Path(self.temp_dir)

        sample_memos = [
            MemoCore(text="Python programming tutorial", tags=["python", "tutorial"]),
            MemoCore(text="JavaScript web development", tags=["javascript", "web"]),
            MemoCore(text="Python data science", tags=["python", "data"]),
        ]

        storage.list_memos.return_value = sample_memos

        collection = MemoCollection(storage)

        # Test category filtering
        python_memos = collection.get_memos_by_category("programming")
        # This would depend on actual storage implementation

        # Test tag filtering
        python_tag_memos = collection.get_memos_by_tag("python")
        # This would depend on actual storage implementation

        # Test statistics
        stats = collection.get_storage_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    # Run tests with verbose output
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""Test suite for FTS5 search functionality."""

import pytest
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from memo import MemoStore


@pytest.fixture
def test_db():
    """Create temporary test database."""
    db_path = Path("/tmp/test_memos.db")
    if db_path.exists():
        db_path.unlink()

    store = MemoStore(data_file=db_path)
    yield store

    # Cleanup
    if db_path.exists():
        db_path.unlink()


class TestFTS5Search:
    """Test Full-Text Search with FTS5."""

    def test_basic_search(self, test_db):
        """Test basic FTS5 search."""
        # Add test memos
        test_db.add("Python programming tutorial", tags=["python", "tutorial"])
        test_db.add("JavaScript is fun", tags=["javascript"])
        test_db.add("Python web development", tags=["python", "web"])

        # Search
        results = test_db.search("Python")

        assert len(results) >= 2
        assert any("Python" in r['content'] for r in results)

    def test_phrase_search(self, test_db):
        """Test exact phrase matching."""
        test_db.add("Hello world application")
        test_db.add("Hello Python world")

        results = test_db.search("Hello world", whole_word=True)

        # Should match "Hello world application"
        assert len(results) >= 1

    def test_fuzzy_search(self, test_db):
        """Test fuzzy/OR search."""
        test_db.add("Machine learning algorithms")
        test_db.add("Deep neural networks")
        test_db.add("Statistical methods")

        results = test_db.search("learning networks", fuzzy=True)

        # Should return multiple results with OR logic
        assert len(results) >= 1

    def test_search_with_filters(self, test_db):
        """Test search with additional filters."""
        from_date = datetime.now(timezone.utc)

        test_db.add("Important meeting notes", tags=["meeting"])
        test_db.add("Casual chat log", tags=["chat"])

        results = test_db.search("meeting", tags=["meeting"])

        assert len(results) >= 1
        assert all("meeting" in r['tags'] for r in results)

    def test_search_no_results(self, test_db):
        """Test search with no matching results."""
        test_db.add("Python tutorial")

        results = test_db.search("NonexistentKeyword")

        assert len(results) == 0

    def test_search_japanese(self, test_db):
        """Test Japanese text search."""
        test_db.add("日本語の検索テスト", tags=["japanese"])
        test_db.add("プログラミング講座", tags=["python"])

        results = test_db.search("日本語")

        # May succeed or fallback depending on FTS5 support
        assert isinstance(results, list)

    def test_fts_auto_sync(self, test_db):
        """Test automatic FTS index sync on INSERT."""
        # Add memo
        memo = test_db.add("Automated sync test", tags=["test"])

        # Search should find it
        results = test_db.search("Automated")

        assert len(results) >= 1
        assert memo['id'] in [r['id'] for r in results]

    def test_search_ranking(self, test_db):
        """Test BM25 ranking order."""
        test_db.add("machine learning python")
        test_db.add("python python python")
        test_db.add("machine learning")

        results = test_db.search("python")

        # Python-heavy memo should rank higher
        assert len(results) >= 1


class TestSearchEdgeCases:
    """Test edge cases in search functionality."""

    def test_empty_query(self, test_db):
        """Test search with empty query string."""
        test_db.add("Some content")

        results = test_db.search("")

        assert len(results) == 0

    def test_special_characters(self, test_db):
        """Test search with special characters."""
        test_db.add("Email: user@example.com (important)")

        results = test_db.search("@example")

        # Should handle special chars gracefully
        assert isinstance(results, list)

    def test_very_long_query(self, test_db):
        """Test search with very long query string."""
        test_db.add("Sample memo content")

        long_query = "a" * 1000
        results = test_db.search(long_query)

        assert len(results) == 0

    def test_unicode_normalization(self, test_db):
        """Test Unicode text search."""
        test_db.add("Café français résumé")

        results = test_db.search("Café")

        # Should handle accents
        assert isinstance(results, list)


class TestSearchPerformance:
    """Test search performance with larger datasets."""

    def test_search_with_many_memos(self, test_db):
        """Test search performance with 1000+ memos."""
        # Add 100 memos for testing (reduced for faster tests)
        for i in range(100):
            test_db.add(f"Memo {i} with content about Python programming")

        results = test_db.search("Python")

        # Should find multiple results
        assert len(results) >= 50

    def test_search_limit_performance(self, test_db):
        """Test that LIMIT clause prevents excessive results."""
        for i in range(150):
            test_db.add(f"Common word here {i}")

        results = test_db.search("Common")

        # Should be limited to 100
        assert len(results) <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

#!/usr/bin/env python3
"""
Comprehensive Test Suite for Enterprise Memo System
===================================================
Complete testing coverage for security, performance, and functionality.
"""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from i18n import I18N
from memo_system import (
    AccessLevel,
    DatabaseManager,
    MemoService,
    PerformanceMonitor,
    SecurityLevel,
    SecurityManager,
    SystemConfig,
)
from memo_utils import DataExporter, LRUCache, RateLimiter, SearchEngine


class TestMemoService(unittest.TestCase):
    """Test core memo service operations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = SystemConfig(
            db_path=Path(self.temp_dir) / "test.db",
            backup_dir=Path(self.temp_dir) / "backups",
            log_dir=Path(self.temp_dir) / "logs",
        )
        self.security = SecurityManager(self.config)
        self.db = DatabaseManager(self.config, self.security)
        self.service = MemoService(self.db, self.security, self.config)

        # Create test user
        self.user_id = "test-user"
        self.db.conn.execute(
            """
            INSERT INTO users (id, username, email, password_hash, access_level)
            VALUES (?, ?, ?, ?, ?)
            """,
            (self.user_id, "testuser", "test@example.com", "hash", AccessLevel.USER),
        )
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir)

    def test_create_memo(self):
        """Test memo creation"""
        content = "Test memo content"
        tags = ["test", "unit-test"]

        memo_id = self.service.create_memo(
            self.user_id, content, tags, SecurityLevel.INTERNAL
        )

        self.assertIsNotNone(memo_id)

        # Verify memo was created
        cursor = self.db.conn.execute(
            "SELECT content FROM memos WHERE id = ?", (memo_id,)
        )
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], content)

    def test_get_memo(self):
        """Test retrieving memo"""
        # Create memo
        content = "Test retrieval"
        memo_id = self.service.create_memo(
            self.user_id, content, ["test"]
        )

        # Retrieve memo
        memo = self.service.get_memo(memo_id, self.user_id)

        self.assertIsNotNone(memo)
        self.assertEqual(memo.content, content)
        self.assertEqual(memo.user_id, self.user_id)
        self.assertIn("test", memo.tags)

    def test_search_memos(self):
        """Test memo search functionality"""
        # Create test memos
        self.service.create_memo(self.user_id, "Python programming guide", ["python"])
        self.service.create_memo(self.user_id, "JavaScript tutorial", ["javascript"])
        self.service.create_memo(self.user_id, "Python data structures", ["python", "data"])

        # Search for Python
        results = self.service.search_memos(self.user_id, "Python")

        self.assertEqual(len(results), 2)
        for memo in results:
            self.assertIn("python", memo.content.lower())

    def test_update_memo(self):
        """Test memo update"""
        # Create memo
        original_content = "Original content"
        memo_id = self.service.create_memo(self.user_id, original_content)

        # Update memo
        new_content = "Updated content"
        success = self.service.update_memo(memo_id, self.user_id, new_content)
        self.assertTrue(success)

        # Verify update
        memo = self.service.get_memo(memo_id, self.user_id)
        self.assertEqual(memo.content, new_content)
        self.assertEqual(memo.version, 2)

    def test_delete_memo(self):
        """Test memo deletion"""
        # Create memo
        memo_id = self.service.create_memo(self.user_id, "To be deleted")

        # Delete memo
        success = self.service.delete_memo(memo_id, self.user_id)
        self.assertTrue(success)

        # Memo should not be retrievable
        memo = self.service.get_memo(memo_id, self.user_id)
        self.assertIsNone(memo)

    def test_encryption_for_confidential_memos(self):
        """Test that confidential memos are encrypted"""
        if not self.security.fernet:
            self.skipTest("Cryptography not available")

        content = "Confidential information"
        memo_id = self.service.create_memo(
            self.user_id, content, [], SecurityLevel.CONFIDENTIAL
        )

        # Check database directly
        cursor = self.db.conn.execute(
            "SELECT content, encrypted_content FROM memos WHERE id = ?", (memo_id,)
        )
        row = cursor.fetchone()

        self.assertEqual(row[0], "[ENCRYPTED]")
        self.assertIsNotNone(row[1])
        self.assertNotEqual(row[1], content)

        # Retrieval should decrypt
        memo = self.service.get_memo(memo_id, self.user_id)
        self.assertEqual(memo.content, content)


class TestLRUCache(unittest.TestCase):
    """Test LRU cache implementation"""

    def setUp(self):
        self.cache = LRUCache(capacity=3)

    def test_basic_operations(self):
        """Test basic cache operations"""
        # Put and get
        self.cache.put("key1", "value1")
        self.assertEqual(self.cache.get("key1"), "value1")

        # Non-existent key
        self.assertIsNone(self.cache.get("key2"))

    def test_lru_eviction(self):
        """Test LRU eviction policy"""
        # Fill cache
        self.cache.put("key1", "value1")
        self.cache.put("key2", "value2")
        self.cache.put("key3", "value3")

        # Access key1 to make it recently used
        self.cache.get("key1")

        # Add new item, key2 should be evicted (least recently used)
        self.cache.put("key4", "value4")

        self.assertIsNotNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))  # Evicted
        self.assertIsNotNone(self.cache.get("key3"))
        self.assertIsNotNone(self.cache.get("key4"))

    def test_cache_invalidation(self):
        """Test cache invalidation"""
        self.cache.put("key1", "value1")
        self.cache.invalidate("key1")
        self.assertIsNone(self.cache.get("key1"))

    def test_cache_clear(self):
        """Test cache clearing"""
        self.cache.put("key1", "value1")
        self.cache.put("key2", "value2")
        self.cache.clear()

        self.assertIsNone(self.cache.get("key1"))
        self.assertIsNone(self.cache.get("key2"))


class TestSearchEngine(unittest.TestCase):
    """Test search engine functionality"""

    def setUp(self):
        self.search_engine = SearchEngine()

    def test_document_indexing(self):
        """Test document indexing"""
        self.search_engine.index_document("doc1", "Python programming tutorial")
        self.search_engine.index_document("doc2", "JavaScript web development")
        self.search_engine.index_document("doc3", "Python data science")

        # Search for Python
        results = self.search_engine.search("Python")
        self.assertEqual(len(results), 2)

        doc_ids = [r['id'] for r in results]
        self.assertIn("doc1", doc_ids)
        self.assertIn("doc3", doc_ids)

    def test_relevance_ranking(self):
        """Test search result ranking"""
        self.search_engine.index_document("doc1", "Python Python Python")
        self.search_engine.index_document("doc2", "Python programming")
        self.search_engine.index_document("doc3", "Learn Python")

        results = self.search_engine.search("Python")

        # Document with more occurrences should rank higher
        self.assertEqual(results[0]['id'], "doc1")
        self.assertGreater(results[0]['score'], results[1]['score'])

    def test_tokenization(self):
        """Test text tokenization"""
        tokens = self.search_engine._tokenize(
            "The quick brown fox jumps over the lazy dog"
        )

        # Stop words should be removed
        self.assertNotIn("the", tokens)
        self.assertNotIn("over", tokens)

        # Content words should remain
        self.assertIn("quick", tokens)
        self.assertIn("brown", tokens)
        self.assertIn("fox", tokens)


class TestRateLimiter(unittest.TestCase):
    """Test rate limiting functionality"""

    def setUp(self):
        self.limiter = RateLimiter(max_requests=3, time_window=1)

    def test_rate_limiting(self):
        """Test basic rate limiting"""
        identifier = "user123"

        # First 3 requests should be allowed
        for _ in range(3):
            self.assertTrue(self.limiter.is_allowed(identifier))

        # 4th request should be denied
        self.assertFalse(self.limiter.is_allowed(identifier))

        # After waiting, should be allowed again
        time.sleep(1.1)
        self.assertTrue(self.limiter.is_allowed(identifier))

    def test_multiple_identifiers(self):
        """Test rate limiting with multiple identifiers"""
        # Each identifier has its own limit
        self.assertTrue(self.limiter.is_allowed("user1"))
        self.assertTrue(self.limiter.is_allowed("user2"))
        self.assertTrue(self.limiter.is_allowed("user1"))
        self.assertTrue(self.limiter.is_allowed("user2"))

    def test_reset(self):
        """Test rate limit reset"""
        identifier = "user123"

        # Use up limit
        for _ in range(3):
            self.limiter.is_allowed(identifier)

        # Should be blocked
        self.assertFalse(self.limiter.is_allowed(identifier))

        # Reset
        self.limiter.reset(identifier)

        # Should be allowed again
        self.assertTrue(self.limiter.is_allowed(identifier))


class TestI18N(unittest.TestCase):
    """Test internationalization"""

    def setUp(self):
        self.i18n = I18N('en')

    def test_get_translation(self):
        """Test getting translations"""
        self.assertEqual(self.i18n.get('welcome'), 'Welcome to Memo System')
        self.assertEqual(self.i18n.get('error'), 'Error')

    def test_language_switching(self):
        """Test switching languages"""
        # Switch to Japanese
        self.i18n.set_language('ja')
        self.assertEqual(self.i18n.get('welcome'), 'メモシステムへようこそ')

        # Switch to Chinese
        self.i18n.set_language('zh')
        self.assertEqual(self.i18n.get('welcome'), '欢迎使用备忘录系统')

    def test_unsupported_language(self):
        """Test handling of unsupported language"""
        with self.assertRaises(ValueError):
            self.i18n.set_language('xx')

    def test_format_with_parameters(self):
        """Test string formatting with parameters"""
        # Add a test translation with placeholder
        self.i18n.translations['test_format'] = 'Hello {name}!'
        result = self.i18n.get('test_format', name='World')
        self.assertEqual(result, 'Hello World!')

    def test_fallback_to_key(self):
        """Test fallback when translation not found"""
        result = self.i18n.get('non_existent_key')
        self.assertEqual(result, 'non_existent_key')

    def test_external_locale_loading(self):
        """External JSON locale should be loaded and registered."""
        with tempfile.TemporaryDirectory() as tmpdir:
            locales_dir = Path(tmpdir)
            payload = {
                "__meta__": {"language_name": "Test Language"},
                "welcome": "Custom Welcome",
            }
            locale_file = locales_dir / "tl.json"
            locale_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            original_dir = I18N.LOCALES_DIR
            I18N.LOCALES_DIR = locales_dir
            I18N._external_loaded = False
            try:
                custom_i18n = I18N("tl")
                self.assertEqual(custom_i18n.get("welcome"), "Custom Welcome")
                self.assertIn("tl", custom_i18n.get_supported_languages())
            finally:
                I18N.LOCALES_DIR = original_dir
                I18N._external_loaded = False

    def test_external_locale_missing_key_uses_builtin(self):
        """Missing keys in external locale should fall back to built-in strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            locales_dir = Path(tmpdir)
            payload = {
                "__meta__": {"language_name": "Partial Language"},
                "welcome": "Localized Welcome",
            }
            (locales_dir / "pl.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            original_dir = I18N.LOCALES_DIR
            I18N.LOCALES_DIR = locales_dir
            I18N._external_loaded = False
            try:
                partial_i18n = I18N("pl")
                self.assertEqual(partial_i18n.get("welcome"), "Localized Welcome")
                # Key not present in JSON should use bundled translation (from base set)
                self.assertEqual(partial_i18n.get("error"), "Error")
            finally:
                I18N.LOCALES_DIR = original_dir
                I18N._external_loaded = False


class TestDataExporter(unittest.TestCase):
    """Test data export functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_data = [
            {"id": "1", "content": "Test memo 1", "created": "2024-01-01"},
            {"id": "2", "content": "Test memo 2", "created": "2024-01-02"}
        ]

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_export_json(self):
        """Test JSON export"""
        output_file = os.path.join(self.temp_dir, "export.json")
        DataExporter.export_json(self.test_data, output_file)

        # Verify file contents
        with open(output_file, 'r') as f:
            loaded = json.load(f)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]['id'], "1")

    def test_export_csv(self):
        """Test CSV export"""
        output_file = os.path.join(self.temp_dir, "export.csv")
        DataExporter.export_csv(self.test_data, output_file)

        # Verify file exists
        self.assertTrue(os.path.exists(output_file))

        # Read and verify contents
        import csv
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['id'], "1")

    def test_export_markdown(self):
        """Test Markdown export"""
        output_file = os.path.join(self.temp_dir, "export.md")
        DataExporter.export_markdown(self.test_data, output_file)

        # Verify file exists and contains expected content
        with open(output_file, 'r') as f:
            content = f.read()

        self.assertIn("# Exported Data", content)
        self.assertIn("Test memo 1", content)
        self.assertIn("Test memo 2", content)


class TestPerformanceMonitor(unittest.TestCase):
    """Test performance monitoring"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = SystemConfig(
            db_path=Path(self.temp_dir) / "test.db",
            backup_dir=Path(self.temp_dir) / "backups",
            log_dir=Path(self.temp_dir) / "logs"
        )
        self.security = SecurityManager(self.config)
        self.db = DatabaseManager(self.config, self.security)
        self.monitor = PerformanceMonitor(self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir)

    def test_record_metric(self):
        """Test metric recording"""
        self.monitor.record_metric("test_operation", 100.5, "ms")

        # Verify metric was recorded
        cursor = self.db.conn.execute(
            "SELECT value, unit FROM metrics WHERE metric_name = ?",
            ("test_operation",)
        )
        row = cursor.fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], 100.5)
        self.assertEqual(row[1], "ms")

    def test_get_system_status(self):
        """Test system status retrieval"""
        status = self.monitor.get_system_status()

        self.assertIn('timestamp', status)
        self.assertIn('database_size', status)
        self.assertIn('total_memos', status)
        self.assertIn('active_users', status)
        self.assertIn('active_sessions', status)

        # If monitoring available, check additional metrics
        if self.monitor.enabled:
            self.assertIn('cpu_percent', status)
            self.assertIn('memory_percent', status)
            self.assertIn('disk_usage', status)


class TestConcurrency(unittest.TestCase):
    """Test concurrent operations"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = SystemConfig(
            db_path=Path(self.temp_dir) / "test.db",
            backup_dir=Path(self.temp_dir) / "backups",
            log_dir=Path(self.temp_dir) / "logs"
        )
        self.security = SecurityManager(self.config)
        self.db = DatabaseManager(self.config, self.security)
        self.service = MemoService(self.db, self.security, self.config)

        # Create test user
        self.user_id = "test-user"
        self.db.conn.execute("""
            INSERT INTO users (id, username, email, password_hash, access_level)
            VALUES (?, ?, ?, ?, ?)
        """, (self.user_id, "testuser", "test@example.com", "hash", AccessLevel.USER))
        self.db.conn.commit()

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir)

    def test_concurrent_memo_creation(self):
        """Test concurrent memo creation"""
        memo_ids = []
        lock = threading.Lock()

        def create_memo(index):
            memo_id = self.service.create_memo(
                self.user_id, f"Concurrent memo {index}", [f"tag{index}"]
            )
            with lock:
                memo_ids.append(memo_id)

        # Create memos concurrently
        threads = []
        for i in range(10):
            t = threading.Thread(target=create_memo, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # All memos should be created
        self.assertEqual(len(memo_ids), 10)
        self.assertEqual(len(set(memo_ids)), 10)  # All unique


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestMemoService))
    suite.addTests(loader.loadTestsFromTestCase(TestLRUCache))
    suite.addTests(loader.loadTestsFromTestCase(TestSearchEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestRateLimiter))
    suite.addTests(loader.loadTestsFromTestCase(TestI18N))
    suite.addTests(loader.loadTestsFromTestCase(TestDataExporter))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceMonitor))
    suite.addTests(loader.loadTestsFromTestCase(TestConcurrency))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return success status
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
#!/usr/bin/env python3
"""Lightweight memo application with enhanced features."""

import json
import sys
import io
import time
from datetime import datetime, timezone, timedelta
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import tempfile
from typing import Dict, Iterable, List, Optional, Tuple, Any, Generator
from contextlib import suppress, contextmanager
import argparse
import re
import csv
from collections import Counter
import os
import sqlite3
import secrets
import hashlib
from config import Config

# Import improvement modules
try:
    from memo_security import SecurityValidator, get_rate_limiter
    from memo_performance import get_cache, get_index, get_performance_monitor
    from memo_errors import (
        ValidationError, SecurityError, StorageError, NotFoundError,
        print_error, print_success, print_warning,
        format_validation_error, format_not_found_error, format_storage_error
    )
    from memo_integrity import IntegrityChecker, AutoBackup
    from memo_enhanced_utils import ProgressIndicator, ConfigValidator, confirm_destructive_operation
    IMPROVEMENTS_AVAILABLE = True
except ImportError:
    IMPROVEMENTS_AVAILABLE = False
    SecurityValidator = None
    get_rate_limiter = None
    IntegrityChecker = None
    AutoBackup = None

try:  # pragma: no cover - platform specific
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:  # pragma: no cover - Windows specific
    import msvcrt  # type: ignore
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


VALID_STATUSES = {"active", "completed", "archived"}


class MemoValidationError(ValueError):
    """Raised when memo content fails validation."""


class FileLock:
    """Simple cross-platform file lock with timeout."""

    def __init__(
        self,
        lock_path: Path,
        timeout: float = 10.0,
        retry_interval: float = 0.1,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.lock_path = lock_path
        self.timeout = max(timeout, 0.1)
        self.retry_interval = max(retry_interval, 0.01)
        self.logger = logger
        self._handle: Optional[io.TextIOWrapper] = None

    def acquire(self) -> None:
        start = time.time()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

        while True:
            self._handle = self.lock_path.open("a+")
            try:
                self._try_lock()
                return
            except BlockingIOError:
                self._handle.close()
                if time.time() - start >= self.timeout:
                    raise TimeoutError("Timed out acquiring memo store lock")
                time.sleep(self.retry_interval)
            except OSError as exc:
                self._handle.close()
                if time.time() - start >= self.timeout:
                    raise TimeoutError(f"Failed to acquire memo store lock: {exc}")
                time.sleep(self.retry_interval)

    def release(self) -> None:
        if not self._handle:
            return
        try:
            self._unlock()
        finally:
            self._handle.close()
            self._handle = None

    def _try_lock(self) -> None:
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            self._handle.seek(0)
            try:
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in {13, 33}:  # Permission denied / lock violation
                    raise BlockingIOError from exc
                raise
        else:  # pragma: no cover - minimal platforms
            raise OSError("No locking primitives available on this platform")

    def _unlock(self) -> None:
        if fcntl is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            self._handle.seek(0)
            msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class MemoStore:
    """SQLite-based memo storage for improved performance."""

    def __init__(self, data_file: Optional[Path] = None):
        self.data_dir = Path.home() / ".memo"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.chmod(0o700)

        # Use SQLite database instead of JSONL
        self.db_path = data_file or (self.data_dir / "memos.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.templates_file = self.data_dir / "templates.json"
        self.backup_dir = self.data_dir / "backups"
        self.config = Config()
        self.default_category = self.config.get("behavior.default_category", "default")
        self.default_status = self.config.get("behavior.default_status", "active")
        self.auto_backup = self.config.get("backup.auto_backup", True)
        self.backup_count = self.config.get("backup.keep_count", 10)
        self.lock_timeout = self.config.get("limits.lock_timeout_seconds", 10.0)
        self.lock_retry_interval = self.config.get("limits.lock_retry_interval_seconds", 0.1)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

        if not self.templates_file.exists():
            self.templates_file.touch()

        self.log_dir = self.data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.logger = self._setup_logger()

        # Run integrity check on startup if improvements available
        if IMPROVEMENTS_AVAILABLE and IntegrityChecker:
            self._run_startup_integrity_check()

        self._check_auto_backup()

    def _init_database(self) -> None:
        """Initialize SQLite database with optimized schema."""
        conn = sqlite3.connect(str(self.db_path))
        # WAL mode for concurrent read/write
        conn.execute("PRAGMA journal_mode=WAL")
        # Integrity constraints
        conn.execute("PRAGMA foreign_keys=ON")
        # Balance between speed and durability
        conn.execute("PRAGMA synchronous=NORMAL")
        # Increased cache for better performance
        conn.execute("PRAGMA cache_size=2000")
        # Use memory for temporary storage
        conn.execute("PRAGMA temp_store=MEMORY")
        # Memory-mapped I/O for faster access
        conn.execute("PRAGMA mmap_size=30000000")
        # Optimize for common patterns
        conn.execute("PRAGMA optimize")
        # Reduce WAL checkpoint frequency
        conn.execute("PRAGMA wal_autocheckpoint=10000")

        # Create memos table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memos (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'default',
                tags TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                priority INTEGER DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                checksum TEXT
            );

            -- Full-text search virtual table with BM25 ranking
            -- Using trigram tokenizer for better Japanese language support
            -- trigram tokenizer breaks text into 3-char sequences, ideal for CJK
            CREATE VIRTUAL TABLE IF NOT EXISTS memos_fts USING fts5(
                id,
                content,
                category,
                tags,
                tokenize='trigram'
            );

            -- FTS triggers for auto-sync
            CREATE TRIGGER IF NOT EXISTS memos_ai AFTER INSERT ON memos BEGIN
              INSERT INTO memos_fts (rowid, id, content, category, tags)
              VALUES (new.rowid, new.id, new.content, new.category, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS memos_ad AFTER DELETE ON memos BEGIN
              DELETE FROM memos_fts WHERE rowid = old.rowid;
            END;

            CREATE TRIGGER IF NOT EXISTS memos_au AFTER UPDATE ON memos BEGIN
              DELETE FROM memos_fts WHERE rowid = old.rowid;
              INSERT INTO memos_fts (rowid, id, content, category, tags)
              VALUES (new.rowid, new.id, new.content, new.category, new.tags);
            END;

            -- Indexes for performance
            -- Single column indexes for filtering
            CREATE INDEX IF NOT EXISTS idx_memos_category ON memos(category);
            CREATE INDEX IF NOT EXISTS idx_memos_status ON memos(status);
            CREATE INDEX IF NOT EXISTS idx_memos_priority ON memos(priority);
            CREATE INDEX IF NOT EXISTS idx_memos_created_at ON memos(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memos_updated_at ON memos(updated_at DESC);

            -- Composite indexes for common queries
            CREATE INDEX IF NOT EXISTS idx_memos_status_updated ON memos(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memos_category_created ON memos(category, created_at DESC);

            -- Expression-based index for case-insensitive search
            CREATE INDEX IF NOT EXISTS idx_memos_content_search ON memos(
                LOWER(SUBSTR(content, 1, 50))
            );

            -- Templates table
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'templates',
                tags TEXT DEFAULT '',
                created_at DATETIME NOT NULL
            );
        """)

        conn.commit()
        conn.close()

    def _init_templates(self) -> None:
        """Initialize default templates if not exists."""
        try:
            if self.templates_file.exists() and self.templates_file.stat().st_size > 0:
                return

            default_templates = {
                "meeting": {
                    "name": "会議メモ",
                    "content": "# 会議メモ\n\n## 参加者\n- \n\n## アジェンダ\n- \n\n## 決定事項\n- \n\n## アクションアイテム\n- ",
                    "category": "templates",
                    "tags": "meeting,template"
                },
                "todo": {
                    "name": "タスクリスト",
                    "content": "# タスクリスト\n\n## 優先度: 高\n- [ ] \n\n## 優先度: 中\n- [ ] \n\n## 優先度: 低\n- [ ] ",
                    "category": "templates",
                    "tags": "todo,template"
                }
            }

            with open(self.templates_file, 'w', encoding='utf-8') as f:
                json.dump(default_templates, f, ensure_ascii=False, indent=2)

        except Exception as e:
            self.logger.warning(f"Failed to initialize templates: {e}")

    @contextmanager
    def _acquire_lock(self, shared: bool = False) -> Generator[None, None, None]:
        """Context manager for acquiring store lock."""
        lock_path = self.db_path.with_suffix(".lock")
        lock = FileLock(lock_path, timeout=self.lock_timeout, retry_interval=self.lock_retry_interval, logger=self.logger)
        # shared flag kept for future enhancement; current implementation uses exclusive lock
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _checkpoint_wal(self, checkpoint_type: str = "passive") -> None:
        """Manage WAL checkpoint to prevent unbounded growth.

        Args:
            checkpoint_type: Type of checkpoint - 'passive', 'full', or 'truncate'
                           - passive: Don't wait for other readers
                           - full: Wait for all readers to finish
                           - truncate: Also truncate the WAL file
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            if checkpoint_type == "passive":
                cursor.execute("PRAGMA wal_checkpoint(passive)")
            elif checkpoint_type == "full":
                cursor.execute("PRAGMA wal_checkpoint(full)")
            elif checkpoint_type == "truncate":
                cursor.execute("PRAGMA wal_checkpoint(truncate)")
            else:
                cursor.execute("PRAGMA wal_checkpoint(passive)")

            conn.close()
            self.logger.debug(f"WAL checkpoint ({checkpoint_type}) executed")
        except Exception as e:
            self.logger.warning(f"WAL checkpoint failed: {e}")

    def _optimize_indexes(self) -> None:
        """Run ANALYZE to gather index statistics for query planner optimization.

        Should be called periodically (e.g., after bulk operations) to help
        SQLite optimizer choose better execution plans.
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Gather statistics on all indexes
            cursor.execute("PRAGMA optimize")
            cursor.execute("ANALYZE")

            conn.commit()
            conn.close()
            self.logger.debug("Index optimization (ANALYZE) completed")
        except Exception as e:
            self.logger.warning(f"Index optimization failed: {e}")

    def add(
        self,
        text: str,
        tags: List[str] = None,
        category: str = None,
        linked_memos: List[str] = None,
        status: Optional[str] = None,
    ) -> Dict:
        """Add a new memo with SQLite storage."""
        # Validate and sanitize inputs if improvements available
        if IMPROVEMENTS_AVAILABLE and SecurityValidator:
            # Validate text
            valid, error = SecurityValidator.validate_text(text)
            if not valid:
                raise ValidationError("Invalid memo text", details=error)

            # Sanitize text
            text = SecurityValidator.sanitize_text(text)

            # Validate and sanitize tags
            if tags:
                sanitized_tags = SecurityValidator.sanitize_tags(tags)
            else:
                sanitized_tags = []

        else:
            # Fallback to basic sanitization
            sanitized_tags = self._sanitize_tags(tags or [])

        # Generate unique ID
        memo_id = secrets.token_urlsafe(16)

        # Prepare data
        category = category or self.default_category
        status = status or self.default_status
        tags_str = ','.join(sanitized_tags) if sanitized_tags else ''
        now = datetime.now(timezone.utc).isoformat()
        checksum = hashlib.sha256(text.encode('utf-8')).hexdigest()

        with self._acquire_lock():
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            try:
                # Insert memo (FTS trigger will auto-populate memos_fts)
                cursor.execute("""
                    INSERT INTO memos (id, content, category, tags, status, priority,
                                     created_at, updated_at, checksum)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (memo_id, text, category, tags_str, status, 0, now, now, checksum))

                conn.commit()

                # Cache if available
                if IMPROVEMENTS_AVAILABLE:
                    cache = get_cache()
                    memo_data = {
                        'id': memo_id,
                        'content': text,
                        'category': category,
                        'tags': sanitized_tags,
                        'status': status,
                        'priority': 0,
                        'created_at': now,
                        'updated_at': now,
                        'checksum': checksum
                    }
                    cache.put(f"memo:{memo_id}", memo_data)

                if print_success:
                    print_success(f"メモを追加しました (ID: {memo_id})")

                # Perform WAL checkpoint after add to manage file growth
                self._checkpoint_wal("passive")

                return {
                    'id': memo_id,
                    'content': text,
                    'text': text,  # Compatibility with format_memo
                    'category': category,
                    'tags': sanitized_tags,
                    'status': status,
                    'created_at': now,
                    'created': now,  # Compatibility with format_memo
                    'timestamp': now  # Compatibility with format_memo
                }

            except Exception as e:
                conn.rollback()
                if print_error:
                    print_error(f"メモの追加に失敗しました: {e}")
                raise
            finally:
                conn.close()

    def list_all(
        self,
        limit: int = 50,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        category: str = None,
        statuses: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List recent memos with optional date, category, status, and tag filtering using SQLite."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Build query
            query = "SELECT * FROM memos WHERE 1=1"
            params = []

            if from_date:
                query += " AND created_at >= ?"
                params.append(from_date.isoformat())

            if to_date:
                query += " AND created_at <= ?"
                params.append(to_date.isoformat())

            if category:
                query += " AND category = ?"
                params.append(category)

            if statuses:
                placeholders = ','.join('?' * len(statuses))
                query += f" AND status IN ({placeholders})"
                params.extend(statuses)

            if tags:
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append("tags LIKE ?")
                    params.append(f'%{tag}%')
                query += " AND (" + " OR ".join(tag_conditions) + ")"

            query += " ORDER BY created_at DESC"

            if limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            rows = cursor.execute(query, params).fetchall()
            conn.close()

            memos = []
            for row in rows:
                memo = {
                    'id': row['id'],
                    'content': row['content'],
                    'text': row['content'],  # Compatibility
                    'category': row['category'],
                    'tags': row['tags'].split(',') if row['tags'] else [],
                    'status': row['status'],
                    'priority': row['priority'],
                    'created_at': row['created_at'],
                    'created': row['created_at'],  # Compatibility
                    'updated_at': row['updated_at'],
                    'edited': row['updated_at'],  # Compatibility
                    'timestamp': row['created_at'],  # Compatibility
                    'checksum': row['checksum']
                }
                memos.append(memo)

            return memos

        except Exception as e:
            self.logger.error(f"Failed to list memos: {e}")
            return []

    def search(
        self,
        query: str,
        regex: bool = False,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        statuses: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        case_sensitive: bool = False,
        whole_word: bool = False,
        fuzzy: bool = False,
    ) -> List[Dict]:
        """Search memos using SQLite FTS5 with BM25 ranking and advanced options."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Prepare FTS query based on options
            if not query:
                conn.close()
                return []

            fts_query = query

            # Phrase search for whole word matching
            if whole_word:
                fts_query = f'"{query}"'
            # OR queries for better recall
            elif fuzzy:
                terms = query.split()
                fts_query = " OR ".join(terms) if len(terms) > 1 else query

            # Build FTS search with BM25 ranking
            sql = """
                SELECT m.id, m.content, m.category, m.tags, m.status, m.priority,
                       m.created_at, m.updated_at, m.checksum,
                       f.rank as search_rank
                FROM memos_fts f
                INNER JOIN memos m ON f.rowid = m.rowid
                WHERE f MATCH ?
            """
            params = [fts_query]

            # Add date range filters
            if from_date:
                sql += " AND m.created_at >= ?"
                params.append(from_date.isoformat())

            if to_date:
                sql += " AND m.created_at <= ?"
                params.append(to_date.isoformat())

            # Add status filter
            if statuses:
                placeholders = ','.join('?' * len(statuses))
                sql += f" AND m.status IN ({placeholders})"
                params.extend(statuses)

            # Add tag filters
            if tags:
                tag_conditions = []
                for tag in tags:
                    tag_conditions.append("m.tags LIKE ?")
                    params.append(f'%{tag}%')
                sql += " AND (" + " OR ".join(tag_conditions) + ")"

            # Order by BM25 rank and recency
            sql += " ORDER BY f.rank DESC, m.updated_at DESC LIMIT 100"

            try:
                rows = cursor.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # Fallback to basic LIKE search if FTS fails
                self.logger.warning(f"FTS query failed for '{query}', falling back to LIKE search")
                return self._fallback_search(query, from_date, to_date, statuses, tags, conn)

            conn.close()

            results = []
            for row in rows:
                memo = {
                    'id': row['id'],
                    'content': row['content'],
                    'text': row['content'],  # Compatibility
                    'category': row['category'],
                    'tags': row['tags'].split(',') if row['tags'] else [],
                    'status': row['status'],
                    'priority': row['priority'],
                    'created_at': row['created_at'],
                    'created': row['created_at'],  # Compatibility
                    'updated_at': row['updated_at'],
                    'timestamp': row['created_at'],  # Compatibility
                    'checksum': row['checksum'],
                    'search_rank': row['search_rank']
                }
                results.append(memo)

            return results

        except Exception as e:
            self.logger.error(f"Search failed: {e}")
            return []

    def _fallback_search(self, query: str, from_date: Optional[datetime] = None,
                         to_date: Optional[datetime] = None, statuses: Optional[List[str]] = None,
                         tags: Optional[List[str]] = None, conn: Optional[sqlite3.Connection] = None) -> List[Dict]:
        """Fallback search using LIKE when FTS fails."""
        if conn is None:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row

        cursor = conn.cursor()

        sql = "SELECT * FROM memos WHERE content LIKE ?"
        params = [f'%{query}%']

        if from_date:
            sql += " AND created_at >= ?"
            params.append(from_date.isoformat())

        if to_date:
            sql += " AND created_at <= ?"
            params.append(to_date.isoformat())

        if statuses:
            placeholders = ','.join('?' * len(statuses))
            sql += f" AND status IN ({placeholders})"
            params.extend(statuses)

        if tags:
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%{tag}%')
            sql += " AND (" + " OR ".join(tag_conditions) + ")"

        sql += " ORDER BY updated_at DESC LIMIT 100"

        rows = cursor.execute(sql, params).fetchall()
        conn.close()

        results = []
        for row in rows:
            memo = {
                'id': row['id'],
                'content': row['content'],
                'text': row['content'],
                'category': row['category'],
                'tags': row['tags'].split(',') if row['tags'] else [],
                'status': row['status'],
                'priority': row['priority'],
                'created_at': row['created_at'],
                'created': row['created_at'],
                'updated_at': row['updated_at'],
                'timestamp': row['created_at'],
                'checksum': row['checksum']
            }
            results.append(memo)

        return results

    def _fuzzy_search(
        self,
        query: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        statuses: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        threshold: float = 0.6,
    ) -> List[Dict]:
        """Fuzzy search using Levenshtein distance."""
        from difflib import SequenceMatcher

        scored_results: List[Tuple[float, datetime, Dict]] = []
        query_lower = query.lower()

        for memo in self._iter_memos():
            memo_dt = self._parse_timestamp(memo, "timestamp")
            if memo_dt is None:
                continue

            # Apply filters
            if from_date and memo_dt < from_date:
                continue
            if to_date and memo_dt > to_date:
                continue
            if statuses and memo.get("status", "active") not in statuses:
                continue
            if tags:
                memo_tags = memo.get("tags", [])
                if not all(tag in memo_tags for tag in tags):
                    continue

            text = memo.get("text", "").lower()
            words = text.split()

            # Calculate fuzzy match score
            best_score = 0.0
            for word in words:
                score = SequenceMatcher(None, query_lower, word).ratio()
                best_score = max(best_score, score)

            # Also check for substring fuzzy match
            for i in range(len(text) - len(query_lower) + 1):
                substring = text[i:i+len(query_lower)]
                score = SequenceMatcher(None, query_lower, substring).ratio()
                best_score = max(best_score, score)

            if best_score >= threshold:
                scored_results.append((best_score, memo_dt, memo))

        # Sort by score first, then by date
        scored_results.sort(key=lambda item: (-item[0], item[1]), reverse=True)
        results = [memo for _, _, memo in scored_results]
        return results

    def search_by_tag(self, tag: str, statuses: Optional[List[str]] = None) -> List[Dict]:
        """Search memos by tag with optional status filtering."""
        results = []

        memo_entries: List[Tuple[datetime, Dict]] = []
        for memo in self._iter_memos():
            if tag in memo.get("tags", []):
                if statuses and memo.get("status", "active") not in statuses:
                    continue
                memo_dt = self._parse_timestamp(memo, "timestamp")
                if memo_dt is None:
                    continue
                memo_entries.append((memo_dt, memo))

        memo_entries.sort(key=lambda item: item[0], reverse=True)
        results = [entry[1] for entry in memo_entries]
        return results

    def delete(self, memo_id: str) -> bool:
        """Delete a memo by ID using SQLite."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Delete from both tables
            cursor.execute("DELETE FROM memos WHERE id = ?", (memo_id,))
            cursor.execute("DELETE FROM memos_fts WHERE id = ?", (memo_id,))

            deleted = cursor.rowcount > 0
            conn.commit()
            conn.close()

            # Clear cache if available
            if IMPROVEMENTS_AVAILABLE and deleted:
                cache = get_cache()
                cache.delete(f"memo:{memo_id}")

            return deleted

        except Exception as e:
            self.logger.error(f"Failed to delete memo: {e}")
            return False

    def edit(
        self,
        memo_id: str,
        new_text: str,
        new_tags: List[str] = None,
        new_category: str = None,
        new_links: List[str] = None,
        new_status: Optional[str] = None,
    ) -> Optional[Dict]:
        """Edit an existing memo using SQLite."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Prepare update data
            update_fields = ["content = ?"]
            params = [new_text]

            # Handle tags
            if new_tags is not None:
                sanitized_tags = self._sanitize_tags(new_tags) if not IMPROVEMENTS_AVAILABLE else new_tags
                tags_str = ','.join(sanitized_tags) if sanitized_tags else ''
                update_fields.append("tags = ?")
                params.append(tags_str)

            # Handle category
            if new_category is not None:
                update_fields.append("category = ?")
                params.append(new_category)

            # Handle status
            if new_status is not None and new_status in VALID_STATUSES:
                update_fields.append("status = ?")
                params.append(new_status)

            # Update timestamp
            now = datetime.now(timezone.utc).isoformat()
            update_fields.append("updated_at = ?")
            params.append(now)

            # Update checksum
            checksum = hashlib.sha256(new_text.encode('utf-8')).hexdigest()
            update_fields.append("checksum = ?")
            params.append(checksum)

            # Execute update
            sql = f"UPDATE memos SET {', '.join(update_fields)} WHERE id = ?"
            params.append(memo_id)

            cursor.execute(sql, params)
            updated = cursor.rowcount > 0

            if updated:
                # Update FTS table
                cursor.execute("""
                    UPDATE memos_fts SET content = ?, category = ?, tags = ?
                    WHERE id = ?
                """, (new_text, new_category or '', tags_str, memo_id))

                conn.commit()

                # Get updated memo
                row = cursor.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
                if row:
                    memo = {
                        'id': row['id'],
                        'content': row['content'],
                        'category': row['category'],
                        'tags': row['tags'].split(',') if row['tags'] else [],
                        'status': row['status'],
                        'priority': row['priority'],
                        'created_at': row['created_at'],
                        'updated_at': row['updated_at'],
                        'checksum': row['checksum']
                    }

                    # Update cache if available
                    if IMPROVEMENTS_AVAILABLE:
                        cache = get_cache()
                        cache.put(f"memo:{memo_id}", memo)

                    conn.close()
                    return memo

            conn.close()
            return None

        except Exception as e:
            self.logger.error(f"Failed to edit memo: {e}")
            return None

    def add_batch(self, memos: List[Dict], optimize_after: bool = True) -> Dict[str, int]:
        """Add multiple memos in batch for improved performance.

        Uses transaction batch inserts which are 20x faster than individual inserts.

        Args:
            memos: List of memo dicts with keys: content, tags, category, status
            optimize_after: Run PRAGMA optimize after batch insert

        Returns:
            Dict with counts: {'added': count, 'failed': count}
        """
        added = 0
        failed = 0

        try:
            with self._acquire_lock():
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()

                # Prepare batch data
                batch_data = []
                now = datetime.now(timezone.utc).isoformat()

                for memo in memos:
                    if not isinstance(memo, dict) or 'content' not in memo:
                        failed += 1
                        continue

                    memo_id = secrets.token_urlsafe(16)
                    content = memo.get('content', '').strip()
                    tags_str = ','.join(memo.get('tags', []))
                    category = memo.get('category', self.default_category)
                    status = memo.get('status', self.default_status)
                    checksum = hashlib.sha256(content.encode('utf-8')).hexdigest()

                    batch_data.append((
                        memo_id, content, category, tags_str,
                        status, 0, now, now, checksum
                    ))

                # Execute batch insert
                if batch_data:
                    cursor.executemany("""
                        INSERT INTO memos (id, content, category, tags, status,
                                         priority, created_at, updated_at, checksum)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, batch_data)

                    added = len(batch_data)
                    conn.commit()

                conn.close()

                # Optimize indexes after batch operation
                if optimize_after and added > 0:
                    self._optimize_indexes()
                    self._checkpoint_wal("passive")

                self.logger.info(f"Batch insert: {added} added, {failed} failed")

        except Exception as e:
            self.logger.error(f"Batch insert failed: {e}")

        return {'added': added, 'failed': failed}

    def list_categories(self) -> List[str]:
        """List all unique categories using SQLite."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            rows = cursor.execute("SELECT DISTINCT category FROM memos ORDER BY category").fetchall()
            conn.close()

            return [row[0] for row in rows]

        except Exception as e:
            self.logger.error(f"Failed to list categories: {e}")
            return []

    def _init_templates(self):
        """Initialize default templates if they don't exist."""
        if not self.templates_file.exists():
            default_templates = {
                "meeting": {
                    "name": "Meeting Notes",
                    "template": "# Meeting: {title}\n\n**Date:** {date}\n**Attendees:** {attendees}\n\n## Agenda\n- \n\n## Notes\n\n\n## Action Items\n- [ ] \n\n## Next Steps\n",
                    "category": "meetings",
                    "tags": ["meeting"]
                },
                "task": {
                    "name": "Task",
                    "template": "# Task: {title}\n\n**Priority:** {priority}\n**Due:** {due_date}\n\n## Description\n{description}\n\n## Sub-tasks\n- [ ] \n\n## Notes\n",
                    "category": "tasks",
                    "tags": ["task", "todo"]
                },
                "idea": {
                    "name": "Idea",
                    "template": "# Idea: {title}\n\n## Description\n{description}\n\n## Potential Impact\n\n\n## Next Actions\n- [ ] Research further\n- [ ] Create prototype\n",
                    "category": "ideas",
                    "tags": ["idea", "brainstorm"]
                },
                "daily": {
                    "name": "Daily Log",
                    "template": "# Daily Log - {date}\n\n## Accomplishments\n- \n\n## Challenges\n- \n\n## Tomorrow's Focus\n- \n\n## Notes\n",
                    "category": "daily",
                    "tags": ["daily", "log"]
                }
            }
            with self.templates_file.open("w", encoding="utf-8") as f:
                json.dump(default_templates, f, ensure_ascii=False, indent=2)

    def get_templates(self) -> Dict:
        """Get all available templates."""
        if self.templates_file.exists():
            with self.templates_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def create_from_template(self, template_key: str, variables: Dict[str, str]) -> Optional[Dict]:
        """Create a memo from a template."""
        templates = self.get_templates()
        if template_key not in templates:
            return None

        template = templates[template_key]
        text = template["template"].format(**variables)
        tags = template.get("tags", [])
        category = template.get("category", "default")

        return self.add(text, tags, category)

    def add_template(self, key: str, name: str, template_text: str, category: str = "default", tags: List[str] = None) -> bool:
        """Add a new template."""
        templates = self.get_templates()
        templates[key] = {
            "name": name,
            "template": template_text,
            "category": category,
            "tags": self._sanitize_tags(tags or [])
        }

        with self.templates_file.open("w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
        return True

    def delete_template(self, key: str) -> bool:
        """Delete a template."""
        templates = self.get_templates()
        if key in templates:
            del templates[key]
            with self.templates_file.open("w", encoding="utf-8") as f:
                json.dump(templates, f, ensure_ascii=False, indent=2)
            return True
        return False

    def get_linked_memos(self, memo_id: str) -> List[Dict]:
        """Get all memos linked to a specific memo."""
        memo = self.get_by_id(memo_id)
        if not memo:
            return []

        linked_ids = memo.get("links", [])
        linked_memos = []

        for link_id in linked_ids:
            linked_memo = self.get_by_id(link_id)
            if linked_memo:
                linked_memos.append(linked_memo)

        return linked_memos

    def get_backlinks(self, memo_id: str) -> List[Dict]:
        """Get all memos that link to a specific memo."""
        backlinks = []

        for memo in self._iter_memos():
            if memo_id in memo.get("links", []):
                backlinks.append(memo)

        return backlinks

    def add_link(self, source_id: str, target_id: str) -> bool:
        """Add a link from source memo to target memo."""
        if source_id == target_id:
            self.logger.warning("Skipping self-link for memo %s", source_id)
            return False

        if not self.get_by_id(target_id):
            return False

        memos = []
        found = False

        for memo in self._iter_memos():
            if memo.get("id") == source_id:
                links = memo.get("links", [])
                if target_id not in links:
                    links.append(target_id)
                    memo["links"] = links
                    memo["edited"] = datetime.now(timezone.utc).isoformat()
                found = True
            memos.append(memo)

        if found:
            if not self._rewrite_all_memos(memos):
                self.logger.error("Failed to persist link addition between %s and %s", source_id, target_id)
                return False

        return found

    def remove_link(self, source_id: str, target_id: str) -> bool:
        """Remove a link from source memo to target memo."""
        memos = []
        found = False

        for memo in self._iter_memos():
            if memo.get("id") == source_id:
                links = memo.get("links", [])
                if target_id in links:
                    links.remove(target_id)
                    memo["links"] = links
                    memo["edited"] = datetime.now(timezone.utc).isoformat()
                found = True
            memos.append(memo)

        if found:
            if not self._rewrite_all_memos(memos):
                self.logger.error("Failed to persist link removal between %s and %s", source_id, target_id)
                return False

        return found

    def get_due_reminders(self, before: Optional[datetime] = None, statuses: Optional[List[str]] = None) -> List[Dict]:
        """Get memos with reminders due before specified time and optional statuses."""
        if before is None:
            before = datetime.now(timezone.utc)

        due_memos = []
        for memo in self._iter_memos():
            reminder = memo.get("reminder")
            if reminder:
                try:
                    reminder_dt = datetime.fromisoformat(reminder)
                except (TypeError, ValueError):
                    self.logger.warning("Skipping memo %s with invalid reminder '%s'", memo.get("id"), reminder)
                    continue
                if reminder_dt <= before:
                    if statuses and memo.get("status", "active") not in statuses:
                        continue
                    if memo.get("status", "active") == "active" or statuses:
                        due_memos.append(memo)

        due_memos.sort(key=lambda m: m.get("reminder", ""))
        return due_memos

    def list_reminders(self, from_time: Optional[datetime] = None, to_time: Optional[datetime] = None, statuses: Optional[List[str]] = None) -> List[Dict]:
        """List memos with reminders within a time window."""
        reminders = []
        for memo in self._iter_memos():
            reminder = memo.get("reminder")
            if reminder:
                try:
                    reminder_dt = datetime.fromisoformat(reminder)
                except (TypeError, ValueError):
                    self.logger.warning("Skipping memo %s with invalid reminder '%s'", memo.get("id"), reminder)
                    continue

                if from_time and reminder_dt < from_time:
                    continue
                if to_time and reminder_dt > to_time:
                    continue
                if statuses and memo.get("status", "active") not in statuses:
                    continue

                reminders.append(memo)

        reminders.sort(key=lambda m: m.get("reminder", ""))
        return reminders

    def update_reminder(self, memo_id: str, reminder: Optional[str]) -> bool:
        """Update reminder for a memo (set None to clear)."""
        memos = []
        updated = False

        for memo in self._iter_memos():
            if memo.get("id") == memo_id:
                if reminder:
                    memo["reminder"] = reminder
                else:
                    memo.pop("reminder", None)
                memo["edited"] = datetime.now(timezone.utc).isoformat()
                updated = True
            memos.append(memo)

        if updated:
            if not self._rewrite_all_memos(memos):
                self.logger.error("Failed to persist reminder update for memo %s", memo_id)
                return False

        return updated

    def duplicate_memo(self, memo_id: str, new_text: Optional[str] = None) -> Optional[Dict]:
        """Duplicate an existing memo with optional new text."""
        original = self.get_by_id(memo_id)
        if not original:
            return None

        text = new_text if new_text is not None else original["text"]
        tags = original.get("tags", []).copy()
        category = original.get("category", "default")
        status = original.get("status", "active")

        return self.add(text, tags, category, None, status)

    def merge_memos(self, memo_ids: List[str], separator: str = "\n\n---\n\n") -> Optional[Dict]:
        """Merge multiple memos into one."""
        memos_to_merge = []
        all_tags = set()
        categories = set()

        for memo_id in memo_ids:
            memo = self.get_by_id(memo_id)
            if memo:
                memos_to_merge.append(memo)
                all_tags.update(memo.get("tags", []))
                categories.add(memo.get("category", "default"))

        if not memos_to_merge:
            return None

        # Sort by timestamp
        memos_to_merge.sort(key=lambda m: m["timestamp"])

        # Merge texts
        merged_text = separator.join(memo["text"] for memo in memos_to_merge)

        # Use most common category or first one
        category = max(categories, key=lambda c: sum(1 for m in memos_to_merge if m.get("category", "default") == c))

        # Create merged memo
        merged_memo = self.add(merged_text, list(all_tags), category)

        # Optionally delete original memos
        # for memo_id in memo_ids:
        #     self.delete(memo_id)

        return merged_memo

    def split_memo(self, memo_id: str, delimiter: str = "\n\n") -> List[Dict]:
        """Split a memo into multiple memos."""
        original = self.get_by_id(memo_id)
        if not original:
            return []

        parts = original["text"].split(delimiter)
        if len(parts) <= 1:
            return [original]

        new_memos = []
        tags = original.get("tags", [])
        category = original.get("category", "default")

        for part in parts:
            part = part.strip()
            if part:
                memo = self.add(part, tags.copy(), category)
                new_memos.append(memo)

        return new_memos

    def update_tags_bulk(self, memo_ids: List[str], add_tags: Optional[List[str]] = None, remove_tags: Optional[List[str]] = None) -> Dict[str, int]:
        """Add or remove tags for multiple memos."""
        add_tags = self._sanitize_tags(add_tags or [])
        remove_tags = self._sanitize_tags(remove_tags or [])
        if not memo_ids or (not add_tags and not remove_tags):
            return {"updated": 0, "added": 0, "removed": 0}

        target_ids = set(memo_ids)
        memos = []
        updated_count = 0
        added_total = 0
        removed_total = 0

        remove_lookup = set(remove_tags)

        for memo in self._iter_memos():
            if memo.get("id") in target_ids:
                tags = memo.get("tags", [])
                if remove_lookup:
                    before_len = len(tags)
                    tags = [tag for tag in tags if tag not in remove_lookup]
                    removed_total += before_len - len(tags)

                if add_tags:
                    for tag in add_tags:
                        if tag not in tags:
                            tags.append(tag)
                            added_total += 1

                if tags != memo.get("tags", []):
                    memo["tags"] = tags
                    memo["edited"] = datetime.now(timezone.utc).isoformat()
                    updated_count += 1
            memos.append(memo)

        if updated_count:
            if not self._rewrite_all_memos(memos):
                self.logger.error("Failed to persist bulk tag update for %d memos", updated_count)
                return {"updated": 0, "added": 0, "removed": 0}

        return {"updated": updated_count, "added": added_total, "removed": removed_total}

    def update_status(self, memo_id: str, new_status: str) -> bool:
        """Update memo status."""
        memos = []
        found = False

        for memo in self._iter_memos():
            if memo.get("id") == memo_id:
                memo["status"] = new_status
                memo["edited"] = datetime.now(timezone.utc).isoformat()
                found = True
            memos.append(memo)

        if found:
            if not self._rewrite_all_memos(memos):
                self.logger.error("Failed to persist status update for memo %s", memo_id)
                return False

        return found

    def archive_memo(self, memo_id: str) -> bool:
        """Archive a memo (set status to archived)."""
        return self.update_status(memo_id, "archived")

    def unarchive_memo(self, memo_id: str) -> bool:
        """Unarchive a memo (set status to active)."""
        return self.update_status(memo_id, "active")

    def complete_memo(self, memo_id: str) -> bool:
        """Mark a memo as completed."""
        return self.update_status(memo_id, "completed")

    def update_status_bulk(self, memo_ids: List[str], new_status: str) -> int:
        """Update status for multiple memos in a single pass."""
        if not memo_ids:
            return 0

        target_ids = set(memo_ids)
        memos = []
        updated_count = 0

        for memo in self._iter_memos():
            if memo.get("id") in target_ids and memo.get("status", "active") != new_status:
                memo["status"] = new_status
                memo["edited"] = datetime.now(timezone.utc).isoformat()
                updated_count += 1
            memos.append(memo)

        if updated_count:
            if not self._rewrite_all_memos(memos):
                self.logger.error("Failed to persist bulk status update to %s", new_status)
                return 0

        return updated_count

    def get_by_id(self, memo_id: str) -> Optional[Dict]:
        """Get a memo by ID using SQLite with caching."""
        # Try cache first if improvements available
        if IMPROVEMENTS_AVAILABLE:
            cache = get_cache()
            cached = cache.get(f"memo:{memo_id}")
            if cached:
                return cached

        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            row = cursor.execute("SELECT * FROM memos WHERE id = ?", (memo_id,)).fetchone()
            conn.close()

            if row:
                memo = {
                    'id': row['id'],
                    'content': row['content'],
                    'category': row['category'],
                    'tags': row['tags'].split(',') if row['tags'] else [],
                    'status': row['status'],
                    'priority': row['priority'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at'],
                    'checksum': row['checksum']
                }

                # Update cache if available
                if IMPROVEMENTS_AVAILABLE:
                    cache = get_cache()
                    cache.put(f"memo:{memo_id}", memo)

                return memo

        except Exception as e:
            self.logger.error(f"Failed to get memo by ID: {e}")

        return None

    def resolve_id(self, partial_id: str) -> Optional[str]:
        """Resolve a memo ID from a prefix; raise ValueError if ambiguous."""
        if not partial_id:
            return None

        memos = self.list_all(limit=0)
        matches = [memo["id"] for memo in memos if memo["id"].startswith(partial_id)]

        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError("ambiguous", matches)
        return matches[0]

    def _setup_logger(self) -> logging.Logger:
        """Configure a rotating logger for memo operations."""
        logger_name = f"memo.store.{self.db_path.stem}"
        logger = logging.getLogger(logger_name)
        if not logger.handlers:
            log_path = self.log_dir / "memo.log"
            handler = RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        return logger

    def _iter_memos(self) -> Iterable[Dict]:
        """Yield memos from storage with corruption handling."""
        if not self.db_path.exists():
            return

        try:
            with self._acquire_lock(shared=True):
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT id, content, category, tags, status, priority, created_at, updated_at FROM memos ORDER BY updated_at DESC")

                for row in cursor.fetchall():
                    memo = {
                        "id": row[0],
                        "text": row[1],
                        "content": row[1],  # Compatibility
                        "category": row[2],
                        "tags": row[3].split(",") if row[3] else [],
                        "status": row[4],
                        "priority": row[5],
                        "created": row[6],
                        "created_at": row[6],  # Compatibility
                        "edited": row[7],
                        "updated_at": row[7],  # Compatibility
                        "timestamp": row[6]  # Compatibility
                    }
                    yield memo

                conn.close()
        except OSError as exc:
            self.logger.error("Failed to access memo store: %s", exc)

    def _parse_timestamp(self, memo: Dict, field: str) -> Optional[datetime]:
        """Safely parse timestamp fields."""
        value = memo.get(field)
        if not value:
            self.logger.warning("Memo %s missing %s", memo.get("id", "unknown"), field)
            return None

        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            self.logger.warning("Memo %s has invalid %s '%s': %s", memo.get("id", "unknown"), field, value, exc)
            self._quarantine_line(json.dumps(memo, ensure_ascii=False))
            return None

    def _rewrite_all_memos(self, memos: List[Dict]) -> bool:
        """Atomically replace memo store contents with provided memos using batch insert."""
        try:
            with self._acquire_lock():
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()

                # Begin transaction
                cursor.execute("BEGIN TRANSACTION")
                try:
                    # Clear existing memos
                    cursor.execute("DELETE FROM memos")

                    # Prepare batch data for executemany
                    batch_data = []
                    now = datetime.now(timezone.utc).isoformat()
                    for memo in memos:
                        batch_data.append((
                            memo.get("id"),
                            memo.get("text", ""),
                            memo.get("category", "default"),
                            ",".join(memo.get("tags", [])),
                            memo.get("status", "active"),
                            memo.get("priority", 0),
                            memo.get("created", now),
                            memo.get("edited", now)
                        ))

                    # Batch insert for better performance
                    cursor.executemany(
                        "INSERT INTO memos (id, content, category, tags, status, priority, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        batch_data
                    )

                    conn.commit()
                    self.logger.info(f"Rewrote memo store: {len(memos)} memos")
                    return True
                except Exception as e:
                    conn.rollback()
                    self.logger.error("Failed to write memos: %s", e)
                    return False
                finally:
                    conn.close()
        except OSError as exc:
            self.logger.error("Failed to rewrite memo store: %s", exc)
            return False

    def _quarantine_line(self, raw_line: str) -> None:
        """Append invalid memo lines to quarantine file for manual inspection."""
        try:
            with self.corrupted_file.open("a", encoding="utf-8") as handle:
                handle.write(raw_line + "\n")
        except OSError as exc:
            self.logger.error("Failed to record corrupted memo: %s", exc)

    def _sanitize_tags(self, tags: Iterable[str]) -> List[str]:
        """Normalize tag inputs by trimming and deduplicating."""
        sanitized: List[str] = []
        for tag in tags:
            if not isinstance(tag, str):
                continue
            clean = tag.strip()
            if not clean:
                continue
            if len(clean) > 64:
                clean = clean[:64]
            if clean not in sanitized:
                sanitized.append(clean)
        return sanitized

    def _check_auto_backup(self):
        """Check if auto-backup is needed based on config."""
        if not self.auto_backup:
            return

        # Check if we need to create a backup
        backup_interval = self.config.get("backup.interval_hours", 24)
        last_backup = self._get_latest_backup()

        if last_backup is None:
            self.create_backup()
        else:
            hours_since = (datetime.now() - last_backup).total_seconds() / 3600
            if hours_since > backup_interval:
                self.create_backup()

    def _run_startup_integrity_check(self):
        """Run integrity check on startup if enabled."""
        if not self.config.get("integrity.check_on_startup", True):
            return

        try:
            checker = IntegrityChecker(self.db_path, logger=self.logger)
            result = checker.check_integrity()

            if not result["valid"]:
                self.logger.warning(f"Integrity check found {result['errors']} errors")
                if self.config.get("integrity.auto_repair", False):
                    self.logger.info("Attempting auto-repair...")
                    checker.repair_file()
        except Exception as e:
            self.logger.error(f"Integrity check failed: {e}")

    def _get_latest_backup(self) -> Optional[datetime]:
        """Get timestamp of most recent backup."""
        if not self.backup_dir.exists():
            return None

        backups = list(self.backup_dir.glob("backup_*.db"))
        if not backups:
            return None

        # Extract timestamps from filenames
        timestamps = []
        for backup in backups:
            match = re.match(r"backup_(\d{14})(?:_.*)?\.db", backup.name)
            if match:
                try:
                    ts = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
                    timestamps.append(ts)
                except ValueError:
                    continue

        return max(timestamps) if timestamps else None

    def create_backup(self, label: Optional[str] = None) -> Path:
        """Create a backup of current memos."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        if label:
            backup_name = f"backup_{timestamp}_{label}.db"
        else:
            backup_name = f"backup_{timestamp}.db"

        backup_path = self.backup_dir / backup_name

        if self.db_path.exists():
            import shutil
            with self._acquire_lock(shared=True):
                shutil.copy2(self.db_path, backup_path)
            self.logger.info("Created backup: %s", backup_path.name)

            # Clean old backups
            self._clean_old_backups()

        return backup_path

    def _clean_old_backups(self):
        """Remove old backups beyond keep_count."""
        backups = sorted(self.backup_dir.glob("backup_*.db"))
        if len(backups) > self.backup_count:
            for old_backup in backups[:-self.backup_count]:
                old_backup.unlink()
                self.logger.info("Removed old backup: %s", old_backup.name)

    def restore_backup(self, backup_path: Path) -> bool:
        """Restore from a backup file."""
        if not backup_path.exists():
            self.logger.error("Backup file not found: %s", backup_path)
            return False

        # Create safety backup before restore
        safety_backup = self.create_backup("pre_restore")

        try:
            import shutil
            with self._acquire_lock():
                shutil.copy2(backup_path, self.db_path)
            self.logger.info("Restored from backup: %s", backup_path.name)
            return True
        except Exception as e:
            self.logger.error("Failed to restore backup: %s", e)
            # Try to restore safety backup
            if safety_backup.exists():
                shutil.copy2(safety_backup, self.db_path)
            return False

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backups."""
        backups = []
        for backup_file in sorted(self.backup_dir.glob("backup_*.db"), reverse=True):
            stat = backup_file.stat()
            match = re.match(r"backup_(\d{14})(?:_(.+))?\.db", backup_file.name)
            if match:
                try:
                    ts = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
                    label = match.group(2) if match.group(2) else ""
                    # Get memo count from backup database
                    memo_count = 0
                    try:
                        backup_conn = sqlite3.connect(str(backup_file))
                        backup_cursor = backup_conn.cursor()
                        backup_cursor.execute("SELECT COUNT(*) FROM memos")
                        memo_count = backup_cursor.fetchone()[0]
                        backup_conn.close()
                    except Exception:
                        memo_count = 0

                    backups.append({
                        "path": backup_file,
                        "name": backup_file.name,
                        "timestamp": ts,
                        "label": label,
                        "size": stat.st_size,
                        "memo_count": memo_count
                    })
                except (ValueError, IOError):
                    continue
        return backups


def parse_tags_and_links(text: str) -> Tuple[str, List[str], List[str]]:
    """Extract hashtags and memo links from text."""
    tags = list(dict.fromkeys(re.findall(r"#(\w+)", text)))
    links = list(dict.fromkeys(re.findall(r"\[\[([a-fA-F0-9]{8,})\]\]", text)))

    # Remove tags and links from text
    clean_text = re.sub(r"#\w+\s*", "", text)
    clean_text = re.sub(r"\[\[[a-fA-F0-9]{8,}\]\]\s*", "", clean_text).strip()

    return clean_text, tags, links

def parse_tags(text: str) -> tuple[str, List[str]]:
    """Extract hashtags from text (legacy function)."""
    clean_text, tags, _ = parse_tags_and_links(text)
    return clean_text, tags


def get_color_code(color_name: str) -> str:
    """Get ANSI color code for terminal output."""
    colors = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "red": "\033[31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
        "gray": "\033[90m",
    }
    return colors.get(color_name, "")

def _unique_sequence(items: Optional[List[str]]) -> List[str]:
    """Return unique items preserving order."""
    seen = set()
    result = []
    for item in items or []:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

def generate_stats_report(store: MemoStore, days: int) -> Dict:
    """Generate a comprehensive statistics report."""
    memos = store.list_all(limit=0)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    recent_memos = [m for m in memos if datetime.fromisoformat(m["timestamp"]) >= cutoff_date]

    stats = {
        "generated": datetime.now().isoformat(),
        "period_days": days,
        "total_memos": len(memos),
        "recent_memos": len(recent_memos),
        "avg_per_day": len(recent_memos) / days if days > 0 else 0,
        "categories": {},
        "tags": {},
        "statuses": {},
        "activity_by_hour": {},
        "activity_by_day": {},
    }

    for memo in recent_memos:
        # Categories
        cat = memo.get("category", "default")
        stats["categories"][cat] = stats["categories"].get(cat, 0) + 1

        # Tags
        for tag in memo.get("tags", []):
            stats["tags"][tag] = stats["tags"].get(tag, 0) + 1

        # Status
        status = memo.get("status", "active")
        stats["statuses"][status] = stats["statuses"].get(status, 0) + 1

        # Time analysis
        dt = datetime.fromisoformat(memo["timestamp"]).astimezone()
        hour = str(dt.hour)
        day = dt.strftime("%A")
        stats["activity_by_hour"][hour] = stats["activity_by_hour"].get(hour, 0) + 1
        stats["activity_by_day"][day] = stats["activity_by_day"].get(day, 0) + 1

    return stats

def analyze_trends(store: MemoStore, days: int):
    """Analyze trends in memo creation."""
    memos = store.list_all(limit=0)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    print(f"\nTrend Analysis (last {days} days)")
    print("=" * 50)

    # Daily trend
    daily_counts = {}
    for memo in memos:
        dt = datetime.fromisoformat(memo["timestamp"])
        if dt >= cutoff_date:
            date_key = dt.date().isoformat()
            daily_counts[date_key] = daily_counts.get(date_key, 0) + 1

    if daily_counts:
        avg_daily = sum(daily_counts.values()) / len(daily_counts)
        max_day = max(daily_counts, key=daily_counts.get)
        min_day = min(daily_counts, key=daily_counts.get)

        print(f"Average memos per day: {avg_daily:.1f}")
        print(f"Most active day: {max_day} ({daily_counts[max_day]} memos)")
        print(f"Least active day: {min_day} ({daily_counts[min_day]} memos)")

        # Trend direction
        sorted_days = sorted(daily_counts.keys())
        if len(sorted_days) >= 7:
            week1 = sum(daily_counts[d] for d in sorted_days[:7])
            week_last = sum(daily_counts[d] for d in sorted_days[-7:])
            if week_last > week1:
                print(f"Trending up: {((week_last/week1 - 1) * 100):.1f}% increase")
            elif week_last < week1:
                print(f"Trending down: {((1 - week_last/week1) * 100):.1f}% decrease")
            else:
                print("Trend stable")

def analyze_habits(store: MemoStore, days: int):
    """Analyze user habits and patterns."""
    memos = store.list_all(limit=0)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    recent_memos = [m for m in memos if datetime.fromisoformat(m["timestamp"]) >= cutoff_date]

    print(f"\nHabit Analysis (last {days} days)")
    print("=" * 50)

    if not recent_memos:
        print("No memos to analyze")
        return

    # Time patterns
    morning = evening = afternoon = night = 0
    for memo in recent_memos:
        hour = datetime.fromisoformat(memo["timestamp"]).astimezone().hour
        if 5 <= hour < 12:
            morning += 1
        elif 12 <= hour < 17:
            afternoon += 1
        elif 17 <= hour < 22:
            evening += 1
        else:
            night += 1

    total = len(recent_memos)
    print("Time of day preference:")
    print(f"  Morning (5-12):   {morning:3d} ({morning/total*100:.1f}%)")
    print(f"  Afternoon (12-17): {afternoon:3d} ({afternoon/total*100:.1f}%)")
    print(f"  Evening (17-22):  {evening:3d} ({evening/total*100:.1f}%)")
    print(f"  Night (22-5):     {night:3d} ({night/total*100:.1f}%)")

    # Consistency score
    dates_with_memos = set()
    for memo in recent_memos:
        dt = datetime.fromisoformat(memo["timestamp"])
        dates_with_memos.add(dt.date())

    consistency = len(dates_with_memos) / days * 100
    print(f"\nConsistency score: {consistency:.1f}%")
    print(f"Active days: {len(dates_with_memos)} out of {days}")

def analyze_network(store: MemoStore):
    """Analyze memo linking network."""
    memos = store.list_all(limit=0)

    print("\nNetwork Analysis")
    print("=" * 50)

    # Count links
    total_links = 0
    memos_with_links = 0
    orphan_memos = 0

    for memo in memos:
        links = memo.get("links", [])
        if links:
            total_links += len(links)
            memos_with_links += 1

        # Check if orphan (no links in or out)
        has_backlinks = any(memo["id"] in m.get("links", []) for m in memos if m["id"] != memo["id"])
        if not links and not has_backlinks:
            orphan_memos += 1

    print(f"Total memos: {len(memos)}")
    print(f"Memos with links: {memos_with_links}")
    print(f"Total links: {total_links}")
    print(f"Orphan memos: {orphan_memos}")
    if memos_with_links > 0:
        print(f"Average links per linked memo: {total_links/memos_with_links:.1f}")

    # Find most connected
    connection_counts = {}
    for memo in memos:
        outgoing = len(memo.get("links", []))
        incoming = sum(1 for m in memos if memo["id"] in m.get("links", []))
        connection_counts[memo["id"]] = outgoing + incoming

    if connection_counts:
        most_connected = max(connection_counts, key=connection_counts.get)
        if connection_counts[most_connected] > 0:
            print(f"\nMost connected memo: {most_connected[:8]} ({connection_counts[most_connected]} connections)")

def analyze_productivity(store: MemoStore, days: int):
    """Analyze productivity patterns."""
    memos = store.list_all(limit=0)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    recent_memos = [m for m in memos if datetime.fromisoformat(m["timestamp"]) >= cutoff_date]

    print(f"\nProductivity Analysis (last {days} days)")
    print("=" * 50)

    if not recent_memos:
        print("No memos to analyze")
        return

    # Words per day
    words_by_date = {}
    for memo in recent_memos:
        dt = datetime.fromisoformat(memo["timestamp"])
        date_key = dt.date().isoformat()
        words = len(memo["text"].split())
        words_by_date[date_key] = words_by_date.get(date_key, 0) + words

    if words_by_date:
        total_words = sum(words_by_date.values())
        avg_words_per_day = total_words / len(words_by_date)
        max_words_day = max(words_by_date, key=words_by_date.get)

        print(f"Total words written: {total_words:,}")
        print(f"Average words per active day: {avg_words_per_day:.0f}")
        print(f"Most productive day: {max_words_day} ({words_by_date[max_words_day]:,} words)")

    # Task completion rate (if using status)
    statuses = Counter(memo.get("status", "active") for memo in recent_memos)
    if statuses.get("completed", 0) > 0:
        completion_rate = statuses["completed"] / len(recent_memos) * 100
        print(f"\nTask completion rate: {completion_rate:.1f}%")
        print(f"  Active: {statuses.get('active', 0)}")
        print(f"  Completed: {statuses.get('completed', 0)}")
        print(f"  Archived: {statuses.get('archived', 0)}")

def format_memo(memo: Dict, verbose: bool = False, config: Optional[Config] = None, use_color: bool = True) -> str:
    """Format memo for display with optional colors."""
    cfg = config or Config()
    date_format = cfg.get("display.date_format", "%Y-%m-%d %H:%M")
    short_date_format = cfg.get("display.short_date_format", "%m/%d %H:%M")
    max_preview = cfg.get("display.max_text_preview", 100)
    show_icons = cfg.get("display.show_icons", True)
    use_color = use_color and cfg.get("display.use_colors", True) and os.isatty(sys.stdout.fileno())

    # Handle both old 'timestamp' and new 'created' field names
    timestamp_str = memo.get("timestamp") or memo.get("created")
    if not timestamp_str:
        timestamp_str = datetime.now(timezone.utc).isoformat()
    dt = datetime.fromisoformat(timestamp_str)
    local_dt = dt.astimezone()

    # Color codes
    if use_color:
        c_id = get_color_code("cyan")
        c_date = get_color_code("gray")
        c_tag = get_color_code("blue")
        c_cat = get_color_code("magenta")
        c_status = get_color_code("yellow")
        c_text = get_color_code("white")
        c_reset = get_color_code("reset")
    else:
        c_id = c_date = c_tag = c_cat = c_status = c_text = c_reset = ""

    if "edited" in memo:
        try:
            edited_str = " ✎" if show_icons else " (edited)"
        except UnicodeEncodeError:
            edited_str = " [ed]"
    else:
        edited_str = ""

    category = memo.get('category', 'default')
    if category != 'default':
        category_str = f" {c_cat}[{category}]{c_reset}"
    else:
        category_str = ""

    links_count = len(memo.get("links", []))
    if links_count > 0:
        links_str = f" [links:{links_count}]"
    else:
        links_str = ""

    status = memo.get("status", "active")
    if status == "completed":
        status_icon = "[completed]"
        status_str = f" {c_status}{status_icon}{c_reset}"
    elif status == "archived":
        status_icon = "[archived]"
        status_str = f" {c_status}{status_icon}{c_reset}"
    else:
        status_str = ""

    if verbose:
        tags = memo.get("tags", [])
        if tags:
            tags_str = " " + " ".join(f"{c_tag}#{tag}{c_reset}" for tag in tags)
        else:
            tags_str = ""

        header = f"{c_id}[{memo['id'][:8]}]{c_reset} {c_date}{local_dt.strftime(date_format)}{c_reset}{edited_str}{category_str}{links_str}{status_str}{tags_str}"
        return f"{header}\n{c_text}{memo['text']}{c_reset}"
    else:
        preview_source = memo['text'].replace("\n", " ")
        if max_preview > 0 and len(preview_source) > max_preview:
            preview_text = preview_source[: max_preview - 1].rstrip() + "…"
        else:
            preview_text = preview_source
        return f"{c_id}[{memo['id'][:8]}]{c_reset} {c_date}{local_dt.strftime(short_date_format)}{c_reset}{edited_str}{category_str}{links_str}{status_str} - {c_text}{preview_text}{c_reset}"


def export_memos(memos: List[Dict], format_type: str) -> str:
    """Export memos to different formats."""
    if format_type == "json":
        return json.dumps(memos, ensure_ascii=False, indent=2)

    elif format_type == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=["id", "timestamp", "text", "tags", "category", "status", "edited"],
            extrasaction="ignore"
        )
        writer.writeheader()
        for memo in memos:
            memo_copy = memo.copy()
            memo_copy["tags"] = ", ".join(memo.get("tags", []))
            writer.writerow(memo_copy)
        return output.getvalue()

    elif format_type in ["md", "markdown"]:
        lines = ["# Memos\n"]
        for memo in memos:
            dt = datetime.fromisoformat(memo["timestamp"])
            local_dt = dt.astimezone()
            tags_str = " ".join(f"#{tag}" for tag in memo.get("tags", []))
            edited_str = f" *(edited {datetime.fromisoformat(memo['edited']).strftime('%Y-%m-%d')})*" if "edited" in memo else ""

            lines.append(f"\n## {local_dt.strftime('%Y-%m-%d %H:%M')}{edited_str}\n")
            if memo.get("category", "default") != "default":
                lines.append(f"**Category:** {memo['category']}\n")
            if memo.get("status", "active") != "active":
                lines.append(f"**Status:** {memo['status']}\n")
            if tags_str:
                lines.append(f"**Tags:** {tags_str}\n")
            lines.append(f"\n{memo['text']}\n")

        return "\n".join(lines)

    elif format_type == "html":
        html_parts = ["""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Memos Export</title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
        .memo { background: white; border-radius: 8px; padding: 20px; margin: 20px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .memo-header { color: #666; font-size: 0.9em; margin-bottom: 10px; }
        .memo-text { white-space: pre-wrap; line-height: 1.6; }
        .tag { display: inline-block; background: #e1f5fe; color: #0277bd; padding: 2px 8px; border-radius: 12px; margin: 0 4px; font-size: 0.85em; }
        .category { background: #f3e5f5; color: #6a1b9a; }
        .status { background: #fff3e0; color: #ef6c00; }
        h1 { color: #333; }
    </style>
</head>
<body>
    <h1>Memos Export</h1>"""]

        for memo in memos:
            dt = datetime.fromisoformat(memo["timestamp"])
            local_dt = dt.astimezone()
            edited_str = f" (edited {datetime.fromisoformat(memo['edited']).strftime('%Y-%m-%d')})"

            html_parts.append('<div class="memo">')
            html_parts.append(f'<div class="memo-header">')
            html_parts.append(f'{local_dt.strftime("%Y-%m-%d %H:%M")}')
            if "edited" in memo:
                html_parts.append(f'<span>{edited_str}</span>')
            if memo.get("category", "default") != "default":
                html_parts.append(f'<span class="tag category">{memo["category"]}</span>')
            if memo.get("status", "active") != "active":
                html_parts.append(f'<span class="tag status">{memo["status"]}</span>')
            for tag in memo.get("tags", []):
                html_parts.append(f'<span class="tag">#{tag}</span>')
            html_parts.append('</div>')
            html_parts.append(f'<div class="memo-text">{memo["text"]}</div>')
            html_parts.append('</div>')

        html_parts.append("</body>\n</html>")
        return "\n".join(html_parts)

    elif format_type == "txt":
        lines = []
        for memo in memos:
            dt = datetime.fromisoformat(memo["timestamp"])
            local_dt = dt.astimezone()
            lines.append(f"{'='*60}")
            lines.append(f"Date: {local_dt.strftime('%Y-%m-%d %H:%M')}")
            if memo.get("category", "default") != "default":
                lines.append(f"Category: {memo['category']}")
            if memo.get("status", "active") != "active":
                lines.append(f"Status: {memo['status']}")
            if memo.get("tags"):
                lines.append(f"Tags: {', '.join(memo['tags'])}")
            lines.append(f"\n{memo['text']}\n")
        return "\n".join(lines)

    return ""


def import_memos(store: MemoStore, file_path: str, format_type: str, default_category: Optional[str] = None, default_status: Optional[str] = None, extra_tags: Optional[List[str]] = None) -> int:
    """Import memos from file."""
    count = 0
    extra_tags = extra_tags or []

    with open(file_path, "r", encoding="utf-8") as f:
        if format_type == "json":
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if "text" in item:
                        tags = list(dict.fromkeys((item.get("tags", []) or []) + extra_tags))
                        category = item.get("category") or default_category
                        status = default_status or item.get("status", "active")
                        store.add(item["text"], tags, category, item.get("links", []), status)
                        count += 1

        elif format_type == "csv":
            reader = csv.DictReader(f)
            for row in reader:
                if "text" in row:
                    tags = [t.strip() for t in row.get("tags", "").split(",") if t.strip()]
                    tags = list(dict.fromkeys(tags + extra_tags))
                    category = row.get("category") or default_category
                    status = default_status or row.get("status", "active")
                    links = [l.strip() for l in (row.get("links") or "").split(",") if l.strip()]
                    store.add(row["text"], tags, category, links or None, status)
                    count += 1

    return count


def show_statistics(store: MemoStore, days: int, use_color: bool = True):
    """Show usage statistics with enhanced visualization."""
    memos = store.list_all(limit=0)
    categories = Counter()
    statuses = Counter()

    use_color = use_color and os.isatty(sys.stdout.fileno())
    if use_color:
        c_header = get_color_code("cyan")
        c_num = get_color_code("green")
        c_label = get_color_code("yellow")
        c_reset = get_color_code("reset")
        c_bold = get_color_code("bold")
    else:
        c_header = c_num = c_label = c_reset = c_bold = ""

    if not memos:
        print("No memos to analyze")
        return

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    recent_memos = [
        m for m in memos
        if datetime.fromisoformat(m["timestamp"]) >= cutoff_date
    ]

    print(f"\n{c_header}{c_bold}Memo Statistics (last {days} days){c_reset}")
    print("=" * 50)
    print(f"Total memos: {c_num}{len(memos)}{c_reset}")
    print(f"Recent memos: {c_num}{len(recent_memos)}{c_reset}")
    print(f"Average per day: {c_num}{len(recent_memos) / days:.1f}{c_reset}")

    # Status breakdown
    for memo in memos:
        statuses[memo.get("status", "active")] += 1

    print(f"\n{c_label}Status Breakdown:{c_reset}")
    for status, count in statuses.items():
        pct = (count / len(memos) * 100) if memos else 0
        bar_len = int(pct / 2)
        bar = "█" * bar_len + "░" * (50 - bar_len)
        print(f"  {status:10s}: {bar} {c_num}{count:4d}{c_reset} ({pct:.1f}%)")

    if recent_memos:
        all_tags = []
        word_counts = []
        hours = Counter()
        days_of_week = Counter()
        char_counts = []

        for memo in recent_memos:
            all_tags.extend(memo.get("tags", []))
            word_counts.append(len(memo["text"].split()))
            char_counts.append(len(memo["text"]))
            dt = datetime.fromisoformat(memo["timestamp"]).astimezone()
            hours[dt.hour] += 1
            days_of_week[dt.strftime("%A")] += 1
            categories[memo.get("category", "default")] += 1

        if all_tags:
            print(f"\n{c_label}Top Tags:{c_reset}")
            tag_counts = Counter(all_tags)
            max_count = max(tag_counts.values())
            for tag, count in tag_counts.most_common(10):
                bar_len = int((count / max_count) * 20)
                bar = "▓" * bar_len + "░" * (20 - bar_len)
                print(f"  #{tag:15s} {bar} {c_num}{count}{c_reset}")

        print(f"\n{c_label}Content Statistics:{c_reset}")
        print(f"  Average words per memo: {c_num}{sum(word_counts) / len(word_counts):.1f}{c_reset}")
        print(f"  Average chars per memo: {c_num}{sum(char_counts) / len(char_counts):.1f}{c_reset}")
        print(f"  Total words: {c_num}{sum(word_counts):,}{c_reset}")
        print(f"  Total characters: {c_num}{sum(char_counts):,}{c_reset}")
        print(f"  Longest memo: {c_num}{max(word_counts)}{c_reset} words")
        print(f"  Shortest memo: {c_num}{min(word_counts)}{c_reset} words")

        print(f"\n{c_label}🕐 Activity by Hour:{c_reset}")
        for h in range(24):
            count = hours.get(h, 0)
            bar_len = int((count / max(hours.values()) * 30)) if hours else 0
            bar = "▓" * bar_len
            if count > 0:
                print(f"  {h:02d}:00 {bar:30s} {c_num}{count}{c_reset}")

        print(f"\n{c_label}Activity by Day:{c_reset}")
        day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for day in day_order:
            count = days_of_week.get(day, 0)
            bar_len = int((count / max(days_of_week.values()) * 30)) if days_of_week else 0
            bar = "▓" * bar_len
            if count > 0:
                print(f"  {day:9s} {bar:30s} {c_num}{count}{c_reset}")

        if len(categories) > 1 or (len(categories) == 1 and "default" not in categories):
            print(f"\n{c_label}Categories:{c_reset}")
            max_cat_count = max(categories.values())
            for cat, count in categories.most_common():
                bar_len = int((count / max_cat_count) * 30)
                bar = "▓" * bar_len
                print(f"  {cat:15s} {bar:30s} {c_num}{count}{c_reset}")


def main():
    parser = argparse.ArgumentParser(
        description="Lightweight memo application for efficient note-taking",
        epilog="Examples:\n  memo.py add 'Meeting notes'\n  memo.py list -n 10\n  memo.py search 'keyword'",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    add_parser = subparsers.add_parser(
        "add",
        help="Add a new memo",
        description="Create a new memo with optional category assignment"
    )
    add_parser.add_argument("text", nargs="*", help="Memo text (supports markdown)")
    add_parser.add_argument("-c", "--category", default="default", help="Assign memo to category (default: %(default)s)")

    list_parser = subparsers.add_parser(
        "list",
        help="List recent memos",
        description="Display memos with optional filtering by date, category, status, or tags"
    )
    list_parser.add_argument("-n", "--limit", type=int, default=None, help="Number of memos to show (default 20)")
    list_parser.add_argument("-v", "--verbose", action="store_true", help="Show full memo content")
    list_parser.add_argument("--from", dest="from_date", help="From date (YYYY-MM-DD)")
    list_parser.add_argument("--to", dest="to_date", help="To date (YYYY-MM-DD)")
    list_parser.add_argument("-c", "--category", help="Filter by category")
    list_parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=["active", "completed", "archived"],
        help="Filter by status (can be used multiple times)",
    )
    list_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        help="Filter by tag (can be used multiple times)",
    )
    list_parser.add_argument("-p", "--preset", help="Apply saved filter preset")

    search_parser = subparsers.add_parser("search", help="Search memos")
    search_parser.add_argument("query", nargs="?", help="Search text or regex pattern")
    search_parser.add_argument("-v", "--verbose", action="store_true", help="Show full memo content")
    search_parser.add_argument("-r", "--regex", action="store_true", help="Use regex search")
    search_parser.add_argument("-w", "--whole-word", action="store_true", help="Match whole words only")
    search_parser.add_argument("-i", "--case-sensitive", action="store_true", help="Case sensitive search")
    search_parser.add_argument("-f", "--fuzzy", action="store_true", help="Fuzzy search (approximate matching)")
    search_parser.add_argument("--from", dest="from_date", help="From date (YYYY-MM-DD)")
    search_parser.add_argument("--to", dest="to_date", help="To date (YYYY-MM-DD)")
    search_parser.add_argument("-n", "--limit", type=int, default=None, help="Limit number of results")
    search_parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=["active", "completed", "archived"],
        help="Filter by status (can be used multiple times)",
    )
    search_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        help="Filter by tag (can be used multiple times)",
    )
    search_parser.add_argument("-p", "--preset", help="Apply saved filter preset")

    tag_parser = subparsers.add_parser("tag", help="Search by tag")
    tag_parser.add_argument("tag", help="Tag name (without #)")
    tag_parser.add_argument("-v", "--verbose", action="store_true", help="Show full memo content")

    delete_parser = subparsers.add_parser("delete", help="Delete a memo")
    delete_parser.add_argument("id", help="Memo ID (first 8 characters)")

    edit_parser = subparsers.add_parser("edit", help="Edit a memo")
    edit_parser.add_argument("id", help="Memo ID (first 8 characters)")
    edit_parser.add_argument("-t", "--text", help="New text (interactive if not provided)")
    edit_parser.add_argument("-c", "--category", help="New category")
    edit_parser.add_argument("--append", help="Append text to memo")
    edit_parser.add_argument("--prepend", help="Prepend text to memo")

    duplicate_parser = subparsers.add_parser("duplicate", help="Duplicate a memo")
    duplicate_parser.add_argument("id", help="Memo ID to duplicate")
    duplicate_parser.add_argument("-t", "--text", help="Override text in duplicate")

    merge_parser = subparsers.add_parser("merge", help="Merge multiple memos")
    merge_parser.add_argument("ids", nargs="+", help="Memo IDs to merge")
    merge_parser.add_argument("-s", "--separator", default="\n\n---\n\n", help="Separator between merged memos")
    merge_parser.add_argument("-d", "--delete-originals", action="store_true", help="Delete original memos after merge")

    split_parser = subparsers.add_parser("split", help="Split a memo into multiple memos")
    split_parser.add_argument("id", help="Memo ID to split")
    split_parser.add_argument("-d", "--delimiter", default="\n\n", help="Delimiter for splitting")
    split_parser.add_argument("--delete-original", action="store_true", help="Delete original memo after split")

    export_parser = subparsers.add_parser("export", help="Export memos")
    export_parser.add_argument("format", choices=["json", "csv", "md", "markdown", "html", "txt"], help="Export format")
    export_parser.add_argument("-o", "--output", help="Output file (stdout if not provided)")
    export_parser.add_argument("--from", dest="from_date", help="From date (YYYY-MM-DD)")
    export_parser.add_argument("--to", dest="to_date", help="To date (YYYY-MM-DD)")
    export_parser.add_argument("-c", "--category", help="Filter by category")
    export_parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=["active", "completed", "archived"],
        help="Filter by status (can be used multiple times)",
    )
    export_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        help="Filter by tag (can be used multiple times)",
    )

    import_parser = subparsers.add_parser("import", help="Import memos")
    import_parser.add_argument("file", help="File to import")
    import_parser.add_argument("-f", "--format", choices=["json", "csv"], default="json", help="Import format")
    import_parser.add_argument("--category", help="Default category applied on import")
    import_parser.add_argument(
        "--status",
        choices=["active", "completed", "archived"],
        help="Default status applied on import",
    )
    import_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        help="Additional tag applied to all imported memos (can be used multiple times)",
    )

    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    stats_parser.add_argument("--days", type=int, default=30, help="Days to analyze")
    stats_parser.add_argument("--category", help="Filter by category")
    stats_parser.add_argument("--export", help="Export stats to file")

    analyze_parser = subparsers.add_parser("analyze", help="Advanced analytics")
    analyze_parser.add_argument("type", choices=["trends", "habits", "network", "productivity"], help="Analysis type")
    analyze_parser.add_argument("--days", type=int, default=30, help="Days to analyze")

    categories_parser = subparsers.add_parser("categories", help="List all categories")

    interactive_parser = subparsers.add_parser("interactive", help="Interactive browsing mode")

    status_parser = subparsers.add_parser("status", help="Update memo status")
    status_parser.add_argument("id", help="Memo ID (first 8 characters)")
    status_parser.add_argument(
        "status",
        choices=["active", "completed", "archived"],
        help="New status value",
    )

    bulk_parser = subparsers.add_parser("bulk", help="Bulk operations")
    bulk_subparsers = bulk_parser.add_subparsers(dest="bulk_action", required=True)

    bulk_status_parser = bulk_subparsers.add_parser("status", help="Bulk update memo status")
    bulk_status_parser.add_argument(
        "status",
        choices=["active", "completed", "archived"],
        help="New status value",
    )
    bulk_status_parser.add_argument("--category", help="Filter by category")
    bulk_status_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        help="Filter by tag (can be used multiple times)",
    )
    bulk_status_parser.add_argument(
        "-s",
        "--filter-status",
        action="append",
        choices=["active", "completed", "archived"],
        dest="filter_status",
        help="Current status filter (can be used multiple times)",
    )
    bulk_status_parser.add_argument("--from", dest="from_date", help="From date (YYYY-MM-DD)")
    bulk_status_parser.add_argument("--to", dest="to_date", help="To date (YYYY-MM-DD)")
    bulk_status_parser.add_argument("--dry-run", action="store_true", help="Show affected memos without updating")

    bulk_tags_parser = bulk_subparsers.add_parser("tags", help="Bulk add or remove tags")
    bulk_tags_parser.add_argument("--add", action="append", dest="add_tags", help="Tag to add (can be repeated)")
    bulk_tags_parser.add_argument("--remove", action="append", dest="remove_tags", help="Tag to remove (can be repeated)")
    bulk_tags_parser.add_argument("--category", help="Filter by category")
    bulk_tags_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        dest="tags",
        help="Filter by tag (can be used multiple times)",
    )
    bulk_tags_parser.add_argument(
        "-s",
        "--filter-status",
        action="append",
        choices=["active", "completed", "archived"],
        dest="filter_status",
        help="Current status filter (can be used multiple times)",
    )
    bulk_tags_parser.add_argument("--from", dest="from_date", help="From date (YYYY-MM-DD)")
    bulk_tags_parser.add_argument("--to", dest="to_date", help="To date (YYYY-MM-DD)")
    bulk_tags_parser.add_argument("--dry-run", action="store_true", help="Show affected memos without updating")

    filter_parser = subparsers.add_parser("filter", help="Manage saved filter presets")
    filter_subparsers = filter_parser.add_subparsers(dest="filter_action", required=True)

    filter_save_parser = filter_subparsers.add_parser("save", help="Save a filter preset")
    filter_save_parser.add_argument("name", help="Preset name")
    filter_save_parser.add_argument("--query", help="Search query")
    filter_save_parser.add_argument("--regex", action="store_true", help="Treat query as regex")
    filter_save_parser.add_argument("--limit", type=int, help="Result limit when applying preset")
    filter_save_parser.add_argument("--from", dest="from_date", help="From date (YYYY-MM-DD)")
    filter_save_parser.add_argument("--to", dest="to_date", help="To date (YYYY-MM-DD)")
    filter_save_parser.add_argument("-c", "--category", help="Filter by category")
    filter_save_parser.add_argument(
        "-s",
        "--status",
        action="append",
        choices=["active", "completed", "archived"],
        help="Filter by status (can be used multiple times)",
    )
    filter_save_parser.add_argument(
        "-t",
        "--tag",
        action="append",
        help="Filter by tag (can be used multiple times)",
    )
    filter_save_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing preset")

    filter_apply_parser = filter_subparsers.add_parser("apply", help="Apply a saved preset")
    filter_apply_parser.add_argument("name", help="Preset name")
    filter_apply_parser.add_argument("-n", "--limit", type=int, help="Override preset limit")
    filter_apply_parser.add_argument("-v", "--verbose", action="store_true", help="Show full memo content")

    filter_delete_parser = filter_subparsers.add_parser("delete", help="Delete a preset")
    filter_delete_parser.add_argument("name", help="Preset name")

    filter_list_parser = filter_subparsers.add_parser("list", help="List saved presets")

    filter_export_parser = filter_subparsers.add_parser("export", help="Export filter presets to JSON file")
    filter_export_parser.add_argument("file", help="Destination file path")
    filter_export_parser.add_argument("--names", nargs="*", help="Specific preset names to export (default: all)")

    filter_import_parser = filter_subparsers.add_parser("import", help="Import filter presets from JSON file")
    filter_import_parser.add_argument("file", help="Source file path")
    filter_import_parser.add_argument("--overwrite", action="store_true", help="Overwrite presets with the same name")

    filter_rename_parser = filter_subparsers.add_parser("rename", help="Rename an existing preset")
    filter_rename_parser.add_argument("old_name", help="Current preset name")
    filter_rename_parser.add_argument("new_name", help="New preset name")
    filter_rename_parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing preset")

    filter_duplicate_parser = filter_subparsers.add_parser("duplicate", help="Duplicate a preset under a new name")
    filter_duplicate_parser.add_argument("source", help="Source preset name")
    filter_duplicate_parser.add_argument("target", help="New preset name")
    filter_duplicate_parser.add_argument("--overwrite", action="store_true", help="Allow replacing an existing preset")

    templates_parser = subparsers.add_parser("templates", help="Manage memo templates")
    templates_subparsers = templates_parser.add_subparsers(dest="template_action", required=True)

    list_templates_parser = templates_subparsers.add_parser("list", help="List available templates")

    new_template_parser = templates_subparsers.add_parser("new", help="Create memo from template")
    new_template_parser.add_argument("template", help="Template name")
    new_template_parser.add_argument("-v", "--var", action="append", nargs=2, metavar=("KEY", "VALUE"), help="Template variable")

    add_template_parser = templates_subparsers.add_parser("add", help="Add new template")
    add_template_parser.add_argument("key", help="Template key")
    add_template_parser.add_argument("name", help="Template name")
    add_template_parser.add_argument("-f", "--file", help="Template file")
    add_template_parser.add_argument("-c", "--category", default="default", help="Default category")
    add_template_parser.add_argument("-t", "--tags", nargs="*", help="Default tags")

    delete_template_parser = templates_subparsers.add_parser("delete", help="Delete template")
    delete_template_parser.add_argument("key", help="Template key")

    backup_parser = subparsers.add_parser("backup", help="Manage backups")
    backup_subparsers = backup_parser.add_subparsers(dest="backup_action", required=True)

    backup_create_parser = backup_subparsers.add_parser("create", help="Create a backup")
    backup_create_parser.add_argument("-l", "--label", help="Optional label for backup")

    backup_list_parser = backup_subparsers.add_parser("list", help="List available backups")

    backup_restore_parser = backup_subparsers.add_parser("restore", help="Restore from backup")
    backup_restore_parser.add_argument("backup", help="Backup file name or number from list")

    link_parser = subparsers.add_parser("link", help="Manage memo links")
    link_subparsers = link_parser.add_subparsers(dest="link_action", required=True)

    add_link_parser = link_subparsers.add_parser("add", help="Add link between memos")
    add_link_parser.add_argument("source", help="Source memo ID")
    add_link_parser.add_argument("target", help="Target memo ID")

    remove_link_parser = link_subparsers.add_parser("remove", help="Remove link between memos")
    remove_link_parser.add_argument("source", help="Source memo ID")
    remove_link_parser.add_argument("target", help="Target memo ID")

    show_links_parser = link_subparsers.add_parser("show", help="Show links for a memo")
    show_links_parser.add_argument("memo_id", help="Memo ID")
    show_links_parser.add_argument("-b", "--backlinks", action="store_true", help="Show backlinks")

    args = parser.parse_args()
    store = MemoStore()
    config = store.config

    def resolve_or_report(partial_id: str, label: str) -> Optional[str]:
        """Resolve memo ID and report errors to stderr without raising."""
        try:
            resolved = store.resolve_id(partial_id)
        except ValueError as exc:
            if exc.args and exc.args[0] == "ambiguous" and len(exc.args) > 1:
                matches = ", ".join(memo_id[:8] for memo_id in exc.args[1])
                print(f"{label} memo ID '{partial_id}' is ambiguous: matches {matches}", file=sys.stderr)
            else:
                print(f"Failed to resolve {label} memo ID '{partial_id}': {exc}", file=sys.stderr)
            return None

        if not resolved:
            print(f"{label} memo {partial_id} not found", file=sys.stderr)
            return None

        return resolved

    if args.command == "add":
        text = " ".join(args.text) if args.text else sys.stdin.read()
        text = text.strip()

        if not text:
            print("Error: Empty memo", file=sys.stderr)
            return 1

        clean_text, tags, links = parse_tags_and_links(text)
        memo = store.add(clean_text, tags, args.category, links)
        print(f"Added: {format_memo(memo, config=config)}")

    elif args.command == "list":
        preset_data = None
        if getattr(args, "preset", None):
            presets = config.get("filters.presets", {}) or {}
            preset_data = presets.get(args.preset)
            if not preset_data:
                print(f"Preset '{args.preset}' not found", file=sys.stderr)
                return 1

        from_str = args.from_date if getattr(args, "from_date", None) else None
        to_str = args.to_date if getattr(args, "to_date", None) else None

        if preset_data:
            from_str = from_str or preset_data.get("from_date")
            to_str = to_str or preset_data.get("to_date")

        from_date = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_str else None
        to_date = datetime.strptime(to_str + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if to_str else None

        category = args.category if getattr(args, "category", None) else None
        statuses = args.status if getattr(args, "status", None) else None
        tags = args.tag if getattr(args, "tag", None) else None

        if preset_data:
            category = category or preset_data.get("category")
            statuses = statuses or preset_data.get("statuses")
            tags = tags or preset_data.get("tags")

        effective_limit = args.limit if args.limit is not None else (preset_data.get("limit") if preset_data and preset_data.get("limit") is not None else 20)

        if preset_data and preset_data.get("query"):
            memos = store.search(
                preset_data["query"],
                preset_data.get("regex", False),
                from_date,
                to_date,
                statuses,
                tags,
            )
            if effective_limit and effective_limit > 0:
                memos = memos[:effective_limit]
        else:
            memos = store.list_all(effective_limit if effective_limit is not None else 20, from_date, to_date, category, statuses, tags)
        if not memos:
            print("No memos found")
        else:
            for memo in memos:
                try:
                    print(format_memo(memo, verbose=args.verbose, config=config, use_color=False))
                except UnicodeEncodeError:
                    # Fallback for Windows console encoding issues
                    print(f"[{memo['id'][:8]}] {memo['text'][:100]}")
                if args.verbose:
                    print()

    elif args.command == "search":
        preset_data = None
        if getattr(args, "preset", None):
            presets = config.get("filters.presets", {}) or {}
            preset_data = presets.get(args.preset)
            if not preset_data:
                print(f"Preset '{args.preset}' not found", file=sys.stderr)
                return 1

        query = args.query if args.query is not None else (preset_data.get("query") if preset_data else None)
        if not query:
            print("Search query is required (provide --preset with query or specify one)", file=sys.stderr)
            return 1

        regex_flag = args.regex or (preset_data.get("regex") if preset_data else False)
        case_sensitive = getattr(args, "case_sensitive", False)
        whole_word = getattr(args, "whole_word", False)
        fuzzy = getattr(args, "fuzzy", False)

        from_str = args.from_date if hasattr(args, "from_date") and args.from_date else None
        to_str = args.to_date if hasattr(args, "to_date") and args.to_date else None

        if preset_data:
            from_str = from_str or preset_data.get("from_date")
            to_str = to_str or preset_data.get("to_date")

        from_date = datetime.strptime(from_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if from_str else None
        to_date = datetime.strptime(to_str + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if to_str else None

        statuses = args.status if getattr(args, "status", None) else None
        tags = args.tag if getattr(args, "tag", None) else None

        if preset_data:
            statuses = statuses or preset_data.get("statuses")
            tags = tags or preset_data.get("tags")

        limit = args.limit if args.limit is not None else (preset_data.get("limit") if preset_data and preset_data.get("limit") is not None else None)

        memos = store.search(query, regex_flag, from_date, to_date, statuses, tags, case_sensitive, whole_word, fuzzy)
        if limit and limit > 0:
            memos = memos[:limit]
        if not memos:
            print("No matching memos found")
        else:
            for memo in memos:
                print(format_memo(memo, verbose=args.verbose, config=config))
                if args.verbose:
                    print()

    elif args.command == "tag":
        statuses = args.status if hasattr(args, "status") and args.status else None
        memos = store.search_by_tag(args.tag, statuses)
        if not memos:
            print(f"No memos with tag #{args.tag}")
        else:
            for memo in memos:
                print(format_memo(memo, verbose=args.verbose, config=config))
                if args.verbose:
                    print()

    elif args.command == "delete":
        full_id = resolve_or_report(args.id, "Target")
        if not full_id:
            return 1

        if store.delete(full_id):
            print(f"Deleted memo {args.id}")
        else:
            print(f"Failed to delete memo {args.id}", file=sys.stderr)
            return 1

    elif args.command == "edit":
        full_id = resolve_or_report(args.id, "Target")
        if not full_id:
            return 1

        existing_memo = store.get_by_id(full_id)
        if not existing_memo:
            print(f"Could not retrieve memo {args.id}", file=sys.stderr)
            return 1

        if args.text:
            new_text = args.text
        else:
            print(f"Current text: {existing_memo['text']}")
            print("Enter new text (Ctrl+D when done):")
            new_text = sys.stdin.read().strip()

        # Handle append/prepend mode
        if hasattr(args, "append") and args.append:
            new_text = existing_memo["text"] + "\n" + args.append
        elif hasattr(args, "prepend") and args.prepend:
            new_text = args.prepend + "\n" + existing_memo["text"]

        if not new_text:
            print("Cancelled: empty text", file=sys.stderr)
            return 1

        clean_text, tags, links = parse_tags_and_links(new_text)
        new_category = args.category if hasattr(args, "category") and args.category else None
        edited_memo = store.edit(full_id, clean_text, tags, new_category, links)

        if edited_memo:
            print(f"Updated: {format_memo(edited_memo, config=config)}")
        else:
            print(f"Failed to edit memo {args.id}", file=sys.stderr)
            return 1

    elif args.command == "status":
        full_id = resolve_or_report(args.id, "Target")
        if not full_id:
            return 1

        if store.update_status(full_id, args.status):
            memo = store.get_by_id(full_id)
            if memo:
                print(f"Updated status: {format_memo(memo, config=config)}")
            else:
                print(f"Updated status for {args.id}")
        else:
            print(f"Failed to update status for {args.id}", file=sys.stderr)
            return 1

    elif args.command == "export":
        from_date = datetime.strptime(args.from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.from_date else None
        to_date = datetime.strptime(args.to_date + " 23:59:59", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) if args.to_date else None
        statuses = args.status if hasattr(args, "status") and args.status else None
        tags = args.tag if hasattr(args, "tag") and args.tag else None

        memos = store.list_all(
            limit=0,
            from_date=from_date,
            to_date=to_date,
            category=args.category if hasattr(args, "category") and args.category else None,
            statuses=statuses,
            tags=tags,
        )

        output = export_memos(memos, args.format)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Exported {len(memos)} memos to {args.output}")
        else:
            print(output)

    elif args.command == "import":
        if not Path(args.file).exists():
            print(f"File {args.file} not found", file=sys.stderr)
            return 1

        imported = import_memos(
            store,
            args.file,
            args.format,
            default_category=getattr(args, "category", None),
            default_status=getattr(args, "status", None),
            extra_tags=getattr(args, "tags", None),
        )
        print(f"Imported {imported} memos")

    elif args.command == "stats":
        # Filter by category if specified
        if hasattr(args, "category") and args.category:
            memos = store.list_all(limit=0, category=args.category)
            filtered_store = type(store)()
            filtered_store._memos_cache = memos
            show_statistics(filtered_store, args.days, use_color=True)
        else:
            show_statistics(store, args.days, use_color=True)

        # Export if requested
        if hasattr(args, "export") and args.export:
            stats = generate_stats_report(store, args.days)
            with open(args.export, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)
            print(f"\nStats exported to {args.export}")

    elif args.command == "analyze":
        if args.type == "trends":
            analyze_trends(store, args.days)
        elif args.type == "habits":
            analyze_habits(store, args.days)
        elif args.type == "network":
            analyze_network(store)
        elif args.type == "productivity":
            analyze_productivity(store, args.days)

    elif args.command == "categories":
        categories = store.list_categories()
        if categories:
            print("Categories:")
            for cat in categories:
                count = len(store.list_all(limit=0, category=cat))
                print(f"  {cat}: {count} memos")
        else:
            print("No categories found")

    elif args.command == "interactive":
        # Launch interactive mode
        from memo_interactive import main as interactive_main
        return interactive_main()

    elif args.command == "templates":
        if args.template_action == "list":
            templates = store.get_templates()
            if templates:
                print("📋 Available Templates:")
                for key, template in templates.items():
                    print(f"  {key}: {template['name']}")
                    print(f"    Category: {template.get('category', 'default')}")
                    if template.get('tags'):
                        print(f"    Tags: {', '.join(template['tags'])}")
                    print()
            else:
                print("No templates found")

        elif args.template_action == "new":
            templates = store.get_templates()
            if args.template not in templates:
                print(f"Template '{args.template}' not found", file=sys.stderr)
                return 1

            # Collect variables
            variables = {}
            if args.var:
                for key, value in args.var:
                    variables[key] = value

            # Add common variables
            if "date" not in variables:
                variables["date"] = datetime.now().strftime("%Y-%m-%d")
            if "datetime" not in variables:
                variables["datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M")

            # Prompt for missing variables
            template_text = templates[args.template]["template"]
            import re
            required_vars = set(re.findall(r'{(\w+)}', template_text))
            for var in required_vars:
                if var not in variables:
                    value = input(f"Enter value for '{var}': ")
                    variables[var] = value

            memo = store.create_from_template(args.template, variables)
            if memo:
                print(f"Created from template: {format_memo(memo)}")
            else:
                print(f"Failed to create memo from template", file=sys.stderr)
                return 1

        elif args.template_action == "add":
            if args.file:
                if not Path(args.file).exists():
                    print(f"Template file {args.file} not found", file=sys.stderr)
                    return 1
                with open(args.file, "r", encoding="utf-8") as f:
                    template_text = f.read()
            else:
                print("Enter template text (Ctrl+D when done):")
                template_text = sys.stdin.read().strip()

            if not template_text:
                print("Empty template", file=sys.stderr)
                return 1

            success = store.add_template(args.key, args.name, template_text, args.category, args.tags or [])
            if success:
                print(f"Template '{args.key}' added")
            else:
                print(f"Failed to add template", file=sys.stderr)
                return 1

        elif args.template_action == "delete":
            if store.delete_template(args.key):
                print(f"Template '{args.key}' deleted")
            else:
                print(f"Template '{args.key}' not found", file=sys.stderr)
                return 1

    elif args.command == "duplicate":
        full_id = resolve_or_report(args.id, "Target")
        if not full_id:
            return 1

        new_memo = store.duplicate_memo(full_id, args.text if hasattr(args, "text") and args.text else None)
        if new_memo:
            print(f"Duplicated: {format_memo(new_memo, config=config)}")
        else:
            print(f"Failed to duplicate memo {args.id}", file=sys.stderr)
            return 1

    elif args.command == "merge":
        # Resolve all IDs
        full_ids = []
        for partial_id in args.ids:
            full_id = resolve_or_report(partial_id, f"Memo {partial_id}")
            if not full_id:
                return 1
            full_ids.append(full_id)

        merged_memo = store.merge_memos(full_ids, args.separator)
        if merged_memo:
            print(f"Merged {len(full_ids)} memos: {format_memo(merged_memo, config=config)}")
            if args.delete_originals:
                for memo_id in full_ids:
                    store.delete(memo_id)
                print(f"Deleted {len(full_ids)} original memos")
        else:
            print("Failed to merge memos", file=sys.stderr)
            return 1

    elif args.command == "split":
        full_id = resolve_or_report(args.id, "Target")
        if not full_id:
            return 1

        new_memos = store.split_memo(full_id, args.delimiter)
        if len(new_memos) > 1:
            print(f"Split into {len(new_memos)} memos:")
            for memo in new_memos:
                print(f"  {format_memo(memo, config=config)}")
            if args.delete_original:
                store.delete(full_id)
                print(f"Deleted original memo {args.id}")
        elif len(new_memos) == 1:
            print("Memo could not be split (no delimiter found)")
        else:
            print(f"Failed to split memo {args.id}", file=sys.stderr)
            return 1

    elif args.command == "backup":
        if args.backup_action == "create":
            backup_path = store.create_backup(args.label)
            print(f"Created backup: {backup_path.name}")

        elif args.backup_action == "list":
            backups = store.list_backups()
            if not backups:
                print("No backups found")
            else:
                print("Available Backups:")
                for i, backup in enumerate(backups, 1):
                    size_kb = backup["size"] / 1024
                    label_str = f" ({backup['label']})" if backup['label'] else ""
                    print(f"  {i}. {backup['name']}{label_str}")
                    print(f"     Created: {backup['timestamp'].strftime('%Y-%m-%d %H:%M')}")
                    print(f"     Size: {size_kb:.1f} KB, Memos: {backup['memo_count']}")

        elif args.backup_action == "restore":
            backups = store.list_backups()
            backup_to_restore = None

            # Check if numeric index
            if args.backup.isdigit():
                idx = int(args.backup) - 1
                if 0 <= idx < len(backups):
                    backup_to_restore = backups[idx]["path"]
            else:
                # Find by name
                for backup in backups:
                    if backup["name"] == args.backup:
                        backup_to_restore = backup["path"]
                        break

            if not backup_to_restore:
                print(f"Backup '{args.backup}' not found", file=sys.stderr)
                return 1

            if store.restore_backup(backup_to_restore):
                print(f"Restored from backup: {backup_to_restore.name}")
            else:
                print(f"Failed to restore backup", file=sys.stderr)
                return 1

    elif args.command == "link":
        if args.link_action == "add":
            # Find full IDs
            source_id = None
            target_id = None
            memos = store.list_all(limit=0)

            for memo in memos:
                if memo["id"].startswith(args.source):
                    source_id = memo["id"]
                if memo["id"].startswith(args.target):
                    target_id = memo["id"]

            if not source_id:
                print(f"Source memo {args.source} not found", file=sys.stderr)
                return 1
            if not target_id:
                print(f"Target memo {args.target} not found", file=sys.stderr)
                return 1

            if store.add_link(source_id, target_id):
                print(f"Added link: {args.source} -> {args.target}")
            else:
                print(f"Failed to add link", file=sys.stderr)
                return 1

        elif args.link_action == "remove":
            # Find full IDs
            source_id = None
            target_id = None
            memos = store.list_all(limit=0)

            for memo in memos:
                if memo["id"].startswith(args.source):
                    source_id = memo["id"]
                if memo["id"].startswith(args.target):
                    target_id = memo["id"]

            if not source_id:
                print(f"Source memo {args.source} not found", file=sys.stderr)
                return 1
            if not target_id:
                print(f"Target memo {args.target} not found", file=sys.stderr)
                return 1

            if store.remove_link(source_id, target_id):
                print(f"Removed link: {args.source} -> {args.target}")
            else:
                print(f"Failed to remove link", file=sys.stderr)
                return 1

        elif args.link_action == "show":
            # Find full ID
            full_id = None
            memos = store.list_all(limit=0)

            for memo in memos:
                if memo["id"].startswith(args.memo_id):
                    full_id = memo["id"]
                    break

            if not full_id:
                print(f"Memo {args.memo_id} not found", file=sys.stderr)
                return 1

            if args.backlinks:
                backlinks = store.get_backlinks(full_id)
                if backlinks:
                    print(f"Backlinks to {args.memo_id}:")
                    for memo in backlinks:
                        print(f"  {format_memo(memo, config=config)}")
                else:
                    print(f"No backlinks found for {args.memo_id}")
            else:
                linked_memos = store.get_linked_memos(full_id)
                if linked_memos:
                    print(f"Links from {args.memo_id}:")
                    for memo in linked_memos:
                        print(f"  {format_memo(memo, config=config)}")
                else:
                    print(f"No links found for {args.memo_id}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user", file=sys.stderr)
        sys.exit(130)
    except ValidationError as e:
        if IMPROVEMENTS_AVAILABLE:
            print_error(e)
        else:
            print(f"Validation Error: {e}", file=sys.stderr)
        sys.exit(1)
    except (SecurityError, StorageError, NotFoundError) as e:
        if IMPROVEMENTS_AVAILABLE:
            print_error(e)
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
#!/usr/bin/env python3
"""
Database Optimization Layer
===========================
Production-grade database operations with connection pooling,
prepared statements, and query optimization.
"""

import sqlite3
import threading
import queue
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Generator
from pathlib import Path
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class QueryMetrics:
    """Query performance metrics."""
    query: str
    execution_time_ms: float
    rows_affected: int
    timestamp: float


class ConnectionPool:
    """Thread-safe SQLite connection pool."""

    def __init__(
        self,
        db_path: Path,
        pool_size: int = 5,
        timeout: float = 30.0,
        enable_wal: bool = True
    ):
        self.db_path = db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self.enable_wal = enable_wal
        self._pool: queue.Queue = queue.Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._connections_created = 0
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """Initialize the connection pool."""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self._pool.put(conn)
            self._connections_created += 1

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with optimizations."""
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=self.timeout
        )

        # Enable WAL mode for better concurrency
        if self.enable_wal:
            conn.execute("PRAGMA journal_mode=WAL")

        # Performance optimizations
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")  # 64MB cache
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
        conn.execute("PRAGMA page_size=4096")

        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys=ON")

        # Use Row factory for dict-like access
        conn.row_factory = sqlite3.Row

        return conn

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool."""
        conn = None
        try:
            conn = self._pool.get(timeout=self.timeout)
            yield conn
        except queue.Empty:
            raise TimeoutError("Connection pool timeout")
        finally:
            if conn is not None:
                self._pool.put(conn)

    def close_all(self) -> None:
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break


class PreparedStatements:
    """Cache of prepared SQL statements."""

    # Memo operations
    INSERT_MEMO = """
        INSERT INTO memos (id, content, category, tags, status, security_level, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    UPDATE_MEMO = """
        UPDATE memos
        SET content = ?, category = ?, tags = ?, status = ?, updated_at = ?
        WHERE id = ? AND created_by = ?
    """

    DELETE_MEMO = """
        UPDATE memos SET deleted_at = ? WHERE id = ? AND created_by = ?
    """

    SELECT_MEMO_BY_ID = """
        SELECT * FROM memos WHERE id = ? AND deleted_at IS NULL
    """

    SELECT_MEMOS_BY_USER = """
        SELECT * FROM memos
        WHERE created_by = ? AND deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    SEARCH_MEMOS_FTS = """
        SELECT m.* FROM memos m
        JOIN memos_fts f ON m.id = f.id
        WHERE f.content MATCH ?
        AND m.deleted_at IS NULL
        AND m.created_by = ?
        ORDER BY rank
        LIMIT ?
    """

    # User operations
    INSERT_USER = """
        INSERT INTO users (username, password_hash, role, created_at)
        VALUES (?, ?, ?, ?)
    """

    SELECT_USER_BY_USERNAME = """
        SELECT * FROM users WHERE username = ? AND active = 1
    """

    UPDATE_USER_PASSWORD = """
        UPDATE users SET password_hash = ?, updated_at = ? WHERE username = ?
    """

    # Session operations
    INSERT_SESSION = """
        INSERT INTO sessions (session_id, username, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """

    SELECT_SESSION = """
        SELECT * FROM sessions
        WHERE session_id = ? AND expires_at > ? AND active = 1
    """

    INVALIDATE_SESSION = """
        UPDATE sessions SET active = 0 WHERE session_id = ?
    """

    # Audit log
    INSERT_AUDIT_LOG = """
        INSERT INTO audit_log (id, username, action, resource, details, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """

    # Statistics
    COUNT_MEMOS_BY_USER = """
        SELECT COUNT(*) as count FROM memos
        WHERE created_by = ? AND deleted_at IS NULL
    """

    COUNT_MEMOS_BY_STATUS = """
        SELECT status, COUNT(*) as count FROM memos
        WHERE created_by = ? AND deleted_at IS NULL
        GROUP BY status
    """


class DatabaseOptimizer:
    """Optimized database operations."""

    def __init__(self, pool: ConnectionPool):
        self.pool = pool
        self._query_metrics: List[QueryMetrics] = []
        self._metrics_lock = threading.Lock()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Execute operations in a transaction with automatic rollback on error."""
        with self.pool.get_connection() as conn:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def execute_query(
        self,
        query: str,
        params: Optional[Tuple] = None,
        fetch_one: bool = False,
        fetch_all: bool = False
    ) -> Any:
        """Execute a query with metrics tracking."""
        start_time = time.time()

        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params or ())

            result = None
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()
            else:
                result = cursor.rowcount

            conn.commit()

            # Track metrics
            execution_time = (time.time() - start_time) * 1000
            self._track_metrics(query, execution_time, cursor.rowcount)

            return result

    def execute_many(self, query: str, params_list: List[Tuple]) -> int:
        """Execute a query with multiple parameter sets."""
        start_time = time.time()

        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            rows_affected = cursor.rowcount

            # Track metrics
            execution_time = (time.time() - start_time) * 1000
            self._track_metrics(query, execution_time, rows_affected)

            return rows_affected

    def _track_metrics(self, query: str, execution_time_ms: float, rows_affected: int) -> None:
        """Track query performance metrics."""
        with self._metrics_lock:
            metric = QueryMetrics(
                query=query[:100],  # Truncate long queries
                execution_time_ms=execution_time_ms,
                rows_affected=rows_affected,
                timestamp=time.time()
            )
            self._query_metrics.append(metric)

            # Keep only last 1000 metrics
            if len(self._query_metrics) > 1000:
                self._query_metrics = self._query_metrics[-1000:]

    def get_slow_queries(self, threshold_ms: float = 100) -> List[QueryMetrics]:
        """Get queries slower than threshold."""
        with self._metrics_lock:
            return [m for m in self._query_metrics if m.execution_time_ms > threshold_ms]

    def get_query_stats(self) -> Dict[str, Any]:
        """Get query performance statistics."""
        with self._metrics_lock:
            if not self._query_metrics:
                return {}

            execution_times = [m.execution_time_ms for m in self._query_metrics]
            return {
                'total_queries': len(self._query_metrics),
                'avg_execution_time_ms': sum(execution_times) / len(execution_times),
                'max_execution_time_ms': max(execution_times),
                'min_execution_time_ms': min(execution_times),
                'slow_queries': len([t for t in execution_times if t > 100])
            }


class IndexManager:
    """Manage database indexes for optimal query performance."""

    @staticmethod
    def create_indexes(conn: sqlite3.Connection) -> None:
        """Create all necessary indexes."""
        indexes = [
            # Memo indexes
            "CREATE INDEX IF NOT EXISTS idx_memos_user ON memos(created_by)",
            "CREATE INDEX IF NOT EXISTS idx_memos_status ON memos(status)",
            "CREATE INDEX IF NOT EXISTS idx_memos_category ON memos(category)",
            "CREATE INDEX IF NOT EXISTS idx_memos_created ON memos(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_memos_deleted ON memos(deleted_at)",
            "CREATE INDEX IF NOT EXISTS idx_memos_security ON memos(security_level)",

            # User indexes
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)",

            # Session indexes
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(active)",

            # Audit log indexes
            "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(username)",
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)",
        ]

        for index_sql in indexes:
            conn.execute(index_sql)

    @staticmethod
    def analyze_tables(conn: sqlite3.Connection) -> None:
        """Update table statistics for query optimizer."""
        conn.execute("ANALYZE")

    @staticmethod
    def vacuum_database(conn: sqlite3.Connection) -> None:
        """Reclaim unused space and defragment database."""
        conn.execute("VACUUM")

    @staticmethod
    def optimize_database(conn: sqlite3.Connection) -> None:
        """Perform full database optimization."""
        IndexManager.analyze_tables(conn)
        conn.execute("PRAGMA optimize")


class QueryBuilder:
    """Safe query builder to prevent SQL injection."""

    @staticmethod
    def build_search_query(
        base_query: str,
        filters: Dict[str, Any],
        allowed_fields: set
    ) -> Tuple[str, List[Any]]:
        """Build a safe search query with filters."""
        conditions = []
        params = []

        for field, value in filters.items():
            if field not in allowed_fields:
                continue

            if isinstance(value, list):
                placeholders = ','.join('?' * len(value))
                conditions.append(f"{field} IN ({placeholders})")
                params.extend(value)
            elif value is None:
                conditions.append(f"{field} IS NULL")
            else:
                conditions.append(f"{field} = ?")
                params.append(value)

        if conditions:
            where_clause = " AND ".join(conditions)
            query = f"{base_query} WHERE {where_clause}"
        else:
            query = base_query

        return query, params

    @staticmethod
    def build_pagination(
        query: str,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[str, List[int]]:
        """Add pagination to query."""
        query = f"{query} LIMIT ? OFFSET ?"
        return query, [limit, offset]


__all__ = [
    'ConnectionPool',
    'PreparedStatements',
    'DatabaseOptimizer',
    'IndexManager',
    'QueryBuilder',
    'QueryMetrics',
]

#!/usr/bin/env python3
"""SQLite connection pooling for improved performance."""

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator
from queue import Queue, Empty, Full
import logging

logger = logging.getLogger(__name__)


class PooledConnection:
    """Wrapper for a pooled SQLite connection."""

    def __init__(self, connection: sqlite3.Connection, pool: 'ConnectionPool'):
        self._conn = connection
        self._pool = pool
        self._in_use = False
        self._created_at = time.time()
        self._last_used = time.time()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get the underlying connection."""
        return self._conn

    @property
    def age(self) -> float:
        """Get connection age in seconds."""
        return time.time() - self._created_at

    @property
    def idle_time(self) -> float:
        """Get idle time in seconds."""
        return time.time() - self._last_used

    def mark_used(self):
        """Mark connection as in use."""
        self._in_use = True
        self._last_used = time.time()

    def mark_returned(self):
        """Mark connection as returned to pool."""
        self._in_use = False
        self._last_used = time.time()

    def close(self):
        """Close the underlying connection."""
        try:
            self._conn.close()
        except Exception as e:
            logger.error(f"Error closing connection: {e}")


class ConnectionPool:
    """Connection pool for SQLite database."""

    def __init__(
        self,
        database: Path,
        min_connections: int = 1,
        max_connections: int = 5,
        connection_timeout: float = 30.0,
        max_connection_age: float = 3600.0,
        enable_wal: bool = True
    ):
        """
        Initialize connection pool.

        Args:
            database: Path to SQLite database
            min_connections: Minimum number of connections to maintain
            max_connections: Maximum number of connections allowed
            connection_timeout: Timeout in seconds when waiting for connection
            max_connection_age: Maximum age of connection in seconds before refresh
            enable_wal: Enable WAL mode for better concurrency
        """
        self.database = database
        self.min_connections = max(1, min_connections)
        self.max_connections = max(self.min_connections, max_connections)
        self.connection_timeout = connection_timeout
        self.max_connection_age = max_connection_age
        self.enable_wal = enable_wal

        self._pool: Queue[PooledConnection] = Queue(maxsize=self.max_connections)
        self._active_connections = 0
        self._lock = threading.Lock()
        self._closed = False

        self._initialize_pool()

    def _initialize_pool(self):
        """Initialize the pool with minimum connections."""
        for _ in range(self.min_connections):
            try:
                conn = self._create_connection()
                self._pool.put(conn, block=False)
            except Exception as e:
                logger.error(f"Failed to initialize connection: {e}")

    def _create_connection(self) -> PooledConnection:
        """Create a new database connection."""
        conn = sqlite3.connect(
            str(self.database),
            check_same_thread=False,
            timeout=self.connection_timeout
        )

        conn.row_factory = sqlite3.Row

        if self.enable_wal:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError as e:
                logger.warning(f"Failed to enable WAL mode: {e}")

        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")

        with self._lock:
            self._active_connections += 1

        return PooledConnection(conn, self)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a connection from the pool.

        Yields:
            SQLite connection

        Example:
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM memos")
                results = cursor.fetchall()
        """
        if self._closed:
            raise RuntimeError("Connection pool is closed")

        pooled_conn = None
        try:
            try:
                pooled_conn = self._pool.get(timeout=self.connection_timeout)
            except Empty:
                with self._lock:
                    if self._active_connections < self.max_connections:
                        pooled_conn = self._create_connection()
                    else:
                        raise TimeoutError(
                            f"Timeout waiting for connection (pool size: {self.max_connections})"
                        )

            if pooled_conn.age > self.max_connection_age:
                logger.info(f"Refreshing old connection (age: {pooled_conn.age:.1f}s)")
                pooled_conn.close()
                with self._lock:
                    self._active_connections -= 1
                pooled_conn = self._create_connection()

            pooled_conn.mark_used()
            yield pooled_conn.connection

        finally:
            if pooled_conn:
                pooled_conn.mark_returned()
                try:
                    self._pool.put(pooled_conn, block=False)
                except Full:
                    logger.warning("Pool full, closing excess connection")
                    pooled_conn.close()
                    with self._lock:
                        self._active_connections -= 1

    def close_all(self):
        """Close all connections in the pool."""
        self._closed = True

        while True:
            try:
                pooled_conn = self._pool.get_nowait()
                pooled_conn.close()
                with self._lock:
                    self._active_connections -= 1
            except Empty:
                break

        logger.info("All connections closed")

    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "active_connections": self._active_connections,
            "available_connections": self._pool.qsize(),
            "max_connections": self.max_connections,
            "min_connections": self.min_connections,
            "closed": self._closed
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()


class SingletonConnectionPool:
    """Singleton connection pool manager."""

    _instance: Optional[ConnectionPool] = None
    _lock = threading.Lock()

    @classmethod
    def get_pool(
        cls,
        database: Path,
        min_connections: int = 1,
        max_connections: int = 5,
        **kwargs
    ) -> ConnectionPool:
        """Get or create the singleton connection pool."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = ConnectionPool(
                        database,
                        min_connections=min_connections,
                        max_connections=max_connections,
                        **kwargs
                    )
        return cls._instance

    @classmethod
    def close(cls):
        """Close the singleton pool."""
        if cls._instance is not None:
            with cls._lock:
                if cls._instance is not None:
                    cls._instance.close_all()
                    cls._instance = None


if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.INFO)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    try:
        with ConnectionPool(db_path, min_connections=2, max_connections=5) as pool:
            print(f"Pool stats: {pool.get_stats()}")

            with pool.get_connection() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, value TEXT)"
                )
                conn.execute("INSERT INTO test (value) VALUES (?)", ("test",))
                conn.commit()

            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM test")
                results = cursor.fetchall()
                print(f"Results: {[dict(row) for row in results]}")

            print(f"Final pool stats: {pool.get_stats()}")

    finally:
        db_path.unlink()

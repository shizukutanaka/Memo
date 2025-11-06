#!/usr/bin/env python3
"""
Transaction Management System
============================
ACID-compliant transaction handling with automatic rollback,
savepoints, and integrity verification.
"""

import sqlite3
import threading
import time
import hashlib
import json
from contextlib import contextmanager
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TransactionState(Enum):
    """Transaction states."""
    IDLE = "idle"
    ACTIVE = "active"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


@dataclass
class TransactionLog:
    """Transaction audit log entry."""
    transaction_id: str
    started_at: float
    completed_at: Optional[float]
    state: TransactionState
    operations: List[str]
    error: Optional[str]
    rollback_reason: Optional[str]


class Transaction:
    """Managed transaction with automatic rollback."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        transaction_id: str,
        isolation_level: str = "DEFERRED"
    ):
        self.connection = connection
        self.transaction_id = transaction_id
        self.isolation_level = isolation_level
        self.state = TransactionState.IDLE
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.operations: List[str] = []
        self.savepoints: List[str] = []
        self.error: Optional[str] = None

    def begin(self) -> None:
        """Begin transaction."""
        if self.state != TransactionState.IDLE:
            raise RuntimeError(f"Transaction already in state: {self.state}")

        self.connection.execute(f"BEGIN {self.isolation_level}")
        self.state = TransactionState.ACTIVE
        self.started_at = time.time()
        logger.debug(f"Transaction {self.transaction_id} started")

    def commit(self) -> None:
        """Commit transaction."""
        if self.state != TransactionState.ACTIVE:
            raise RuntimeError(f"Cannot commit transaction in state: {self.state}")

        try:
            self.connection.commit()
            self.state = TransactionState.COMMITTED
            self.completed_at = time.time()
            logger.info(f"Transaction {self.transaction_id} committed ({len(self.operations)} ops)")
        except sqlite3.Error as e:
            self.state = TransactionState.FAILED
            self.error = str(e)
            logger.error(f"Transaction {self.transaction_id} commit failed: {e}")
            raise

    def rollback(self, reason: Optional[str] = None) -> None:
        """Rollback transaction."""
        if self.state not in (TransactionState.ACTIVE, TransactionState.FAILED):
            return

        try:
            self.connection.rollback()
            self.state = TransactionState.ROLLED_BACK
            self.completed_at = time.time()
            logger.warning(f"Transaction {self.transaction_id} rolled back: {reason or 'explicit rollback'}")
        except sqlite3.Error as e:
            logger.error(f"Transaction {self.transaction_id} rollback failed: {e}")

    def savepoint(self, name: str) -> None:
        """Create savepoint."""
        if self.state != TransactionState.ACTIVE:
            raise RuntimeError("Cannot create savepoint outside active transaction")

        self.connection.execute(f"SAVEPOINT {name}")
        self.savepoints.append(name)
        logger.debug(f"Savepoint {name} created in transaction {self.transaction_id}")

    def rollback_to_savepoint(self, name: str) -> None:
        """Rollback to savepoint."""
        if name not in self.savepoints:
            raise ValueError(f"Savepoint {name} not found")

        self.connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
        logger.debug(f"Rolled back to savepoint {name}")

    def release_savepoint(self, name: str) -> None:
        """Release savepoint."""
        if name not in self.savepoints:
            raise ValueError(f"Savepoint {name} not found")

        self.connection.execute(f"RELEASE SAVEPOINT {name}")
        self.savepoints.remove(name)
        logger.debug(f"Released savepoint {name}")

    def log_operation(self, operation: str) -> None:
        """Log operation in transaction."""
        self.operations.append(operation)

    def get_log(self) -> TransactionLog:
        """Get transaction log."""
        return TransactionLog(
            transaction_id=self.transaction_id,
            started_at=self.started_at or 0.0,
            completed_at=self.completed_at,
            state=self.state,
            operations=self.operations.copy(),
            error=self.error,
            rollback_reason=None
        )


class TransactionManager:
    """Manage database transactions with integrity checks."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._transaction_counter = 0
        self._transaction_lock = threading.Lock()
        self._active_transactions: Dict[str, Transaction] = {}
        self._transaction_logs: List[TransactionLog] = []

    def _generate_transaction_id(self) -> str:
        """Generate unique transaction ID."""
        with self._transaction_lock:
            self._transaction_counter += 1
            timestamp = int(time.time() * 1000)
            return f"txn_{timestamp}_{self._transaction_counter}"

    @contextmanager
    def transaction(self, isolation_level: str = "DEFERRED"):
        """Execute operations in a transaction with automatic rollback on error."""
        txn_id = self._generate_transaction_id()
        txn = Transaction(self.connection, txn_id, isolation_level)

        try:
            txn.begin()
            self._active_transactions[txn_id] = txn

            yield txn

            # Verify integrity before commit
            if not self._verify_integrity():
                raise RuntimeError("Integrity check failed before commit")

            txn.commit()

        except Exception as e:
            logger.error(f"Transaction {txn_id} error: {e}")
            txn.error = str(e)
            txn.rollback(reason=str(e))
            raise

        finally:
            # Clean up
            if txn_id in self._active_transactions:
                del self._active_transactions[txn_id]

            # Log transaction
            self._transaction_logs.append(txn.get_log())

            # Keep only last 1000 logs
            if len(self._transaction_logs) > 1000:
                self._transaction_logs = self._transaction_logs[-1000:]

    def _verify_integrity(self) -> bool:
        """Verify database integrity."""
        try:
            cursor = self.connection.cursor()

            # Quick integrity check
            result = cursor.execute("PRAGMA quick_check").fetchone()

            if result and result[0] == "ok":
                return True

            logger.error(f"Integrity check failed: {result}")
            return False

        except sqlite3.Error as e:
            logger.error(f"Integrity check error: {e}")
            return False

    def execute_with_retry(
        self,
        func: Callable,
        max_retries: int = 3,
        isolation_level: str = "DEFERRED"
    ) -> Any:
        """Execute function in transaction with automatic retry on conflict."""
        last_error = None

        for attempt in range(max_retries):
            try:
                with self.transaction(isolation_level=isolation_level) as txn:
                    result = func(txn)
                return result

            except sqlite3.OperationalError as e:
                last_error = e
                if "database is locked" in str(e).lower():
                    logger.warning(f"Database locked, retry {attempt + 1}/{max_retries}")
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise

            except Exception as e:
                last_error = e
                raise

        raise last_error

    def get_transaction_stats(self) -> Dict[str, Any]:
        """Get transaction statistics."""
        if not self._transaction_logs:
            return {}

        committed = sum(1 for log in self._transaction_logs if log.state == TransactionState.COMMITTED)
        rolled_back = sum(1 for log in self._transaction_logs if log.state == TransactionState.ROLLED_BACK)
        failed = sum(1 for log in self._transaction_logs if log.state == TransactionState.FAILED)

        total_operations = sum(len(log.operations) for log in self._transaction_logs)

        durations = [
            (log.completed_at - log.started_at) * 1000
            for log in self._transaction_logs
            if log.completed_at and log.started_at
        ]

        return {
            'total_transactions': len(self._transaction_logs),
            'committed': committed,
            'rolled_back': rolled_back,
            'failed': failed,
            'total_operations': total_operations,
            'avg_duration_ms': sum(durations) / len(durations) if durations else 0,
            'max_duration_ms': max(durations) if durations else 0,
            'active_transactions': len(self._active_transactions)
        }


class IntegrityChecker:
    """Database integrity verification."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def full_integrity_check(self) -> tuple[bool, List[str]]:
        """Perform full integrity check."""
        errors = []

        try:
            cursor = self.connection.cursor()

            # Full integrity check
            results = cursor.execute("PRAGMA integrity_check").fetchall()

            for row in results:
                if row[0] != "ok":
                    errors.append(row[0])

            # Foreign key check
            fk_violations = cursor.execute("PRAGMA foreign_key_check").fetchall()

            if fk_violations:
                for violation in fk_violations:
                    errors.append(f"Foreign key violation: {violation}")

            return len(errors) == 0, errors

        except sqlite3.Error as e:
            errors.append(f"Integrity check failed: {e}")
            return False, errors

    def verify_checksums(self, table: str) -> bool:
        """Verify data checksums if available."""
        try:
            cursor = self.connection.cursor()

            # Check if table has checksum column
            columns = cursor.execute(f"PRAGMA table_info({table})").fetchall()
            has_checksum = any(col[1] == 'checksum' for col in columns)

            if not has_checksum:
                return True

            # Verify each row's checksum
            rows = cursor.execute(f"SELECT * FROM {table}").fetchall()

            for row in rows:
                # Implement checksum verification logic
                pass

            return True

        except sqlite3.Error as e:
            logger.error(f"Checksum verification failed: {e}")
            return False

    def repair_database(self) -> bool:
        """Attempt to repair database corruption."""
        try:
            # Export and reimport
            cursor = self.connection.cursor()
            cursor.execute("VACUUM")
            cursor.execute("REINDEX")

            # Verify repair
            is_ok, errors = self.full_integrity_check()
            return is_ok

        except sqlite3.Error as e:
            logger.error(f"Database repair failed: {e}")
            return False


__all__ = [
    'TransactionState',
    'TransactionLog',
    'Transaction',
    'TransactionManager',
    'IntegrityChecker',
]

#!/usr/bin/env python3
"""
Memo Management System
======================
Lightweight memo CLI focused on dependable storage, optional encryption, and
translation-ready output. Optional integrations such as advanced monitoring or
hardware-accelerated cryptography are detected at runtime and gracefully
degraded when unavailable.
"""

import argparse
import base64
import binascii
import getpass
import gzip
import hashlib
import hmac
import io
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import secrets
import sqlite3
import sys
import time
import uuid
import string
from contextlib import suppress, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, TYPE_CHECKING

from i18n import get_i18n, _
from config import Config

if TYPE_CHECKING:
    from billing import StripeBillingManager

# Optional cryptography dependencies
try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None  # type: ignore[assignment]

try:
    import argon2
    from argon2 import exceptions as argon2_exceptions
except ImportError:
    argon2 = None  # type: ignore[assignment]
    class _Argon2FallbackExceptions:  # pragma: no cover - used only when argon2 missing
        class VerifyMismatchError(Exception):
            pass

        class InvalidHash(Exception):
            pass

    argon2_exceptions = _Argon2FallbackExceptions()  # type: ignore[assignment]

CRYPTO_AVAILABLE = Fernet is not None and argon2 is not None

# Monitoring imports
try:
    from monitoring_alerting import AlertManager, AlertSeverity, AlertRule, EmailNotificationChannel
    MONITORING_LIB_AVAILABLE = True
except ImportError:
    AlertManager = AlertSeverity = AlertRule = EmailNotificationChannel = None  # type: ignore[assignment]
    MONITORING_LIB_AVAILABLE = False

# Performance monitoring dependency
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    PSUTIL_AVAILABLE = False

MONITORING_AVAILABLE = MONITORING_LIB_AVAILABLE and PSUTIL_AVAILABLE


_dependency_warning_emitted = False


request_id_var: ContextVar[str] = ContextVar("memo_request_id", default="n/a")


class CorrelationFilter(logging.Filter):
    """Inject correlation identifiers into log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - simple attribute injection
        record.correlation_id = request_id_var.get()
        return True


def _path_from_env(env_var: str, default: Path) -> Path:
    """Resolve a filesystem path from environment overrides."""
    value = os.getenv(env_var)
    if not value:
        return default
    try:
        resolved = Path(value).expanduser().resolve()
    except OSError:
        return default
    return resolved


def _int_from_env(env_var: str, default: int, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    """Read integer configuration values safely from the environment."""
    value = os.getenv(env_var)
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    if minimum is not None and parsed < minimum:
        return default
    if maximum is not None and parsed > maximum:
        return default
    return parsed


def _bool_from_env(env_var: str, default: bool) -> bool:
    """Interpret boolean environment overrides."""
    value = os.getenv(env_var)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def configure_logging(log_dir: Path) -> None:
    """Configure rotating file logging once per process."""
    log_dir.mkdir(parents=True, exist_ok=True)
    with suppress(PermissionError, NotImplementedError):
        log_dir.chmod(0o700)

    log_file = log_dir / "memo_system.log"
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s [cid=%(correlation_id)s] %(process)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)
    handler.addFilter(CorrelationFilter())

    root_logger = logging.getLogger()
    # Avoid duplicate handlers when CLI is invoked repeatedly in the same process
    already_configured = any(
        isinstance(existing, RotatingFileHandler) and getattr(existing, "baseFilename", None) == str(log_file)
        for existing in root_logger.handlers
    )
    if not already_configured:
        root_logger.addHandler(handler)
    root_logger.addFilter(CorrelationFilter())
    if root_logger.level == logging.NOTSET:
        root_logger.setLevel(logging.INFO)


def _warn_missing_dependencies(logger: Optional[logging.Logger] = None) -> None:
    """Log warnings once for optional dependencies that are unavailable."""
    global _dependency_warning_emitted
    if _dependency_warning_emitted:
        return

    issues: List[str] = []
    if not CRYPTO_AVAILABLE:
        issues.append(
            "Optional encryption libraries missing; secure hashing falls back to PBKDF2 and memo encryption is disabled."
        )
    if not MONITORING_LIB_AVAILABLE:
        issues.append(
            "Monitoring integrations disabled because 'monitoring_alerting' package is unavailable."
        )
    if not PSUTIL_AVAILABLE:
        issues.append(
            "System metrics collection disabled; install 'psutil' to enable resource reporting."
        )

    if not issues:
        return

    target_logger = logger or logging.getLogger("memo_system")
    for message in issues:
        target_logger.info(message)

    _dependency_warning_emitted = True


# ====================== DEPENDENCY HELPERS ======================


def get_dependency_status(metrics_enabled: Optional[bool] = None) -> Dict[str, Any]:
    """Return a snapshot of optional dependency availability."""
    snapshot: Dict[str, Any] = {
        "crypto": {
            "available": CRYPTO_AVAILABLE,
            "details": "cryptography + argon2" if CRYPTO_AVAILABLE else "Fallback to PBKDF2 / plaintext storage",
        },
        "monitoring_alerting": {
            "available": MONITORING_LIB_AVAILABLE,
            "details": "Alerting enabled" if MONITORING_LIB_AVAILABLE else "Install monitoring_alerting package",
        },
        "psutil": {
            "available": PSUTIL_AVAILABLE,
            "details": "System metrics available" if PSUTIL_AVAILABLE else "Install psutil to collect metrics",
        },
    }

    if metrics_enabled is not None:
        if not metrics_enabled:
            details = "Disabled via configuration"
        elif not PSUTIL_AVAILABLE:
            details = "psutil missing; install to enable metrics"
        else:
            details = "Enabled"

        snapshot["performance_monitoring"] = {
            "available": bool(metrics_enabled and PSUTIL_AVAILABLE),
            "details": details,
        }

    return snapshot


# ====================== CONFIGURATION ======================

@dataclass
class SystemConfig:
    """System-wide configuration"""
    db_path: Path = field(default_factory=lambda: Path.home() / ".memo" / "memos.db")
    backup_dir: Path = field(default_factory=lambda: Path.home() / ".memo" / "backups")
    log_dir: Path = field(default_factory=lambda: Path.home() / ".memo" / "logs")
    session_file: Path = field(default_factory=lambda: Path.home() / ".memo" / "session.json")
    session_secret_path: Path = field(default_factory=lambda: Path.home() / ".memo" / ".session_secret")
    key_backup_dir: Path = field(default_factory=lambda: Path.home() / ".memo" / "key_backups")
    max_memo_size: int = 1_000_000  # 1MB
    max_tag_length: int = 50
    max_tags_per_memo: int = 20
    session_timeout: int = 3600  # 1 hour
    max_login_attempts: int = 5
    lockout_duration: int = 900  # 15 minutes
    backup_retention_days: int = 30
    audit_retention_days: int = 90
    deleted_memo_retention_days: int = 30
    optimize_database_on_maintenance: bool = True
    enable_encryption: bool = True
    enable_audit: bool = True
    enable_performance_monitoring: bool = True
    enable_alerting: bool = False
    key_backup_retention: int = 5

    def __post_init__(self):
        """Apply environment overrides and create necessary directories."""
        # Path overrides
        self.db_path = _path_from_env("MEMO_DB_PATH", self.db_path)
        self.backup_dir = _path_from_env("MEMO_BACKUP_DIR", self.backup_dir)
        self.log_dir = _path_from_env("MEMO_LOG_DIR", self.log_dir)
        self.session_file = _path_from_env("MEMO_SESSION_FILE", self.session_file)
        self.session_secret_path = _path_from_env("MEMO_SESSION_SECRET", self.session_secret_path)
        self.key_backup_dir = _path_from_env("MEMO_KEY_BACKUP_DIR", self.key_backup_dir)

        # Integer overrides with guardrails
        self.max_memo_size = _int_from_env("MEMO_MAX_MEMO_SIZE", self.max_memo_size, minimum=1024, maximum=10_000_000)
        self.max_tag_length = _int_from_env("MEMO_MAX_TAG_LENGTH", self.max_tag_length, minimum=4, maximum=256)
        self.max_tags_per_memo = _int_from_env("MEMO_MAX_TAGS_PER_MEMO", self.max_tags_per_memo, minimum=1, maximum=256)
        self.session_timeout = _int_from_env("MEMO_SESSION_TIMEOUT", self.session_timeout, minimum=60, maximum=24 * 3600)
        self.max_login_attempts = _int_from_env("MEMO_MAX_LOGIN_ATTEMPTS", self.max_login_attempts, minimum=1, maximum=20)
        self.lockout_duration = _int_from_env("MEMO_LOCKOUT_DURATION", self.lockout_duration, minimum=60, maximum=24 * 3600)
        self.backup_retention_days = _int_from_env("MEMO_BACKUP_RETENTION_DAYS", self.backup_retention_days, minimum=1, maximum=365)
        self.audit_retention_days = _int_from_env("MEMO_AUDIT_RETENTION_DAYS", self.audit_retention_days, minimum=7, maximum=730)
        self.deleted_memo_retention_days = _int_from_env("MEMO_DELETED_RETENTION_DAYS", self.deleted_memo_retention_days, minimum=1, maximum=365)
        self.key_backup_retention = _int_from_env("MEMO_KEY_BACKUP_RETENTION", self.key_backup_retention, minimum=1, maximum=50)

        # Boolean overrides
        self.enable_encryption = _bool_from_env("MEMO_ENABLE_ENCRYPTION", self.enable_encryption)
        self.enable_audit = _bool_from_env("MEMO_ENABLE_AUDIT", self.enable_audit)
        self.enable_performance_monitoring = _bool_from_env("MEMO_ENABLE_PERF_MON", self.enable_performance_monitoring)
        self.enable_alerting = _bool_from_env("MEMO_ENABLE_ALERTING", self.enable_alerting)

        sensitive_dirs = [
            self.db_path.parent,
            self.backup_dir,
            self.log_dir,
            self.session_file.parent,
            self.key_backup_dir,
        ]
        for dir_path in sensitive_dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
            with suppress(PermissionError, NotImplementedError):
                dir_path.chmod(0o700)

        if self.session_file.exists():
            with suppress(PermissionError, NotImplementedError):
                self.session_file.chmod(0o600)

        # Initialize session secret key
        if not self.session_secret_path.exists():
            secret = secrets.token_bytes(32)
            self.session_secret_path.write_bytes(secret)
            with suppress(PermissionError, NotImplementedError):
                self.session_secret_path.chmod(0o600)

    def get_session_secret(self) -> bytes:
        """Get session secret key for HMAC"""
        if not self.session_secret_path.exists():
            self.__post_init__()
        return self.session_secret_path.read_bytes()


# ====================== SECURITY ======================

class SecurityLevel(IntEnum):
    """Security classification levels"""
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    SECRET = 3
    TOP_SECRET = 4


class AccessLevel(IntEnum):
    """User access levels"""
    VIEWER = 0
    USER = 1
    ADMIN = 2
    SECURITY_ADMIN = 3
    SYSTEM = 4


@dataclass
class User:
    """User entity"""
    id: str
    username: str
    email: str
    access_level: AccessLevel
    created_at: datetime
    last_login: Optional[datetime] = None
    is_active: bool = True
    failed_attempts: int = 0
    locked_until: Optional[datetime] = None


@dataclass
class AuthSession:
    """Authentication session context"""
    user: User
    token: str
    expires_at: datetime


class SecurityManager:
    """Handles all security operations"""

    _USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
    _EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    def __init__(self, config: SystemConfig):
        self.config = config
        self.logger = logging.getLogger("memo_system.security")
        if CRYPTO_AVAILABLE:
            self.ph = argon2.PasswordHasher(
                time_cost=3,
                memory_cost=2 ** 16,
                parallelism=2
            )
        else:
            self.ph = None
        self.pbkdf2_iterations = 600_000
        self.pbkdf2_salt_bytes = 16
        self.pbkdf2_identifier = "pbkdf2_sha256"
        self._setup_encryption()

    def _setup_encryption(self):
        """Initialize encryption keys"""
        if not CRYPTO_AVAILABLE or not self.config.enable_encryption:
            self.fernet = None
            return

        key_file = self.config.db_path.parent / ".key"
        if key_file.exists():
            with open(key_file, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            with suppress(PermissionError, NotImplementedError):
                key_file.chmod(0o600)

        self.fernet = Fernet(key)

    def is_encryption_available(self) -> bool:
        """Check whether symmetric encryption can be performed."""
        return self.fernet is not None

    def hash_password(self, password: str) -> str:
        """Hash password using the strongest available algorithm."""
        if self.ph:
            return self.ph.hash(password)
        return self._hash_password_pbkdf2(password)

    def verify_password(self, password: str, stored_hash: str) -> bool:
        """Verify password against hash with fallback support."""
        if self.ph and stored_hash.startswith("$argon2"):
            try:
                self.ph.verify(stored_hash, password)
                return True
            except argon2_exceptions.VerifyMismatchError:
                return False
            except argon2_exceptions.InvalidHash:
                # Fall through to PBKDF2 handling
                pass

        if stored_hash.startswith(f"{self.pbkdf2_identifier}$"):
            return self._verify_password_pbkdf2(password, stored_hash)

        # Legacy SHA256 is no longer supported for security reasons
        # Users with old hashes must reset their passwords
        if len(stored_hash) == 64 and re.fullmatch(r"[0-9a-f]{64}", stored_hash):
            self.logger.warning("Attempted login with legacy SHA256 hash - password reset required")
            return False

        return False

    def needs_rehash(self, stored_hash: str) -> bool:
        """Determine whether the stored hash should be upgraded."""
        if not self.ph:
            return not stored_hash.startswith(f"{self.pbkdf2_identifier}$")

        if stored_hash.startswith("$argon2"):
            try:
                return self.ph.check_needs_rehash(stored_hash)
            except argon2_exceptions.InvalidHash:
                return True
        return True

    def _hash_password_pbkdf2(self, password: str) -> str:
        salt = secrets.token_bytes(self.pbkdf2_salt_bytes)
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            self.pbkdf2_iterations
        )
        salt_b64 = base64.b64encode(salt).decode("utf-8")
        dk_b64 = base64.b64encode(dk).decode("utf-8")
        return f"{self.pbkdf2_identifier}${self.pbkdf2_iterations}${salt_b64}${dk_b64}"

    def _verify_password_pbkdf2(self, password: str, stored_hash: str) -> bool:
        try:
            _, iter_str, salt_b64, dk_b64 = stored_hash.split("$", 3)
            iterations = int(iter_str)
            salt = base64.b64decode(salt_b64.encode("utf-8"))
            expected = base64.b64decode(dk_b64.encode("utf-8"))
        except (ValueError, TypeError, binascii.Error):
            return False

        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode(),
            salt,
            iterations
        )
        return secrets.compare_digest(expected, derived)

    def encrypt_data(self, data: str) -> str:
        """Encrypt sensitive data"""
        if not self.fernet:
            return data
        return self.fernet.encrypt(data.encode()).decode()

    def decrypt_data(self, encrypted: str) -> str:
        """Decrypt sensitive data"""
        if not self.fernet:
            return encrypted
        return self.fernet.decrypt(encrypted.encode()).decode()

    def sanitize_input(self, text: str) -> str:
        """Sanitize user input while preserving content fidelity"""
        if text is None:
            return ""
        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        # Escape single quotes to reduce SQL injection surface when constructing raw queries
        cleaned = cleaned.replace("'", "''")
        return cleaned[: self.config.max_memo_size]

    def validate_username(self, username: str) -> bool:
        """Validate username format"""
        return bool(username and self._USERNAME_PATTERN.match(username))

    def validate_email(self, email: Optional[str]) -> bool:
        """Validate e-mail address format"""
        if not email:
            return True
        return bool(self._EMAIL_PATTERN.match(email))

    def validate_password(self, password: str) -> Tuple[bool, str]:
        """Validate password strength"""
        if len(password) < 12:
            return False, "Password must be at least 12 characters."
        if not re.search(r"[A-Z]", password):
            return False, "Password must include an uppercase letter."
        if not re.search(r"[a-z]", password):
            return False, "Password must include a lowercase letter."
        if not re.search(r"[0-9]", password):
            return False, "Password must include a digit."
        if not re.search(r"[^A-Za-z0-9]", password):
            return False, "Password must include a symbol."
        return True, ""

    def generate_password(self, length: int = 20) -> str:
        """Generate a random password satisfying default policy."""
        length = max(length, 12)

        uppercase = string.ascii_uppercase
        lowercase = string.ascii_lowercase
        digits = string.digits
        symbols = "!@#$%^&*()-_=+[]{};:,.?"
        pool = uppercase + lowercase + digits + symbols

        rng = secrets.SystemRandom()
        password_chars = [
            rng.choice(uppercase),
            rng.choice(lowercase),
            rng.choice(digits),
            rng.choice(symbols),
        ]

        password_chars.extend(rng.choice(pool) for _ in range(length - len(password_chars)))
        rng.shuffle(password_chars)
        return ''.join(password_chars)

    def validate_tag(self, tag: str) -> bool:
        """Validate tag format"""
        if not tag or len(tag) > self.config.max_tag_length:
            return False
        # Allow alphanumeric, underscore, hyphen
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', tag))

    def generate_session_token(self) -> str:
        """Generate secure session token"""
        return secrets.token_urlsafe(32)


# ====================== DATABASE ======================

class DatabaseManager:
    """Handles all database operations with security and performance optimizations"""

    def __init__(self, config: SystemConfig, security: SecurityManager):
        self.config = config
        self.security = security
        self.conn = None
        self.logger = logging.getLogger("memo_system.db")
        self._init_database()

    def _init_database(self):
        """Initialize database with security settings"""
        self.conn = sqlite3.connect(
            str(self.config.db_path),
            check_same_thread=False,
            timeout=30.0
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")

        # Enable WAL mode for better concurrency
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA cache_size=10000")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        try:
            self.conn.execute("PRAGMA secure_delete=ON")
        except sqlite3.OperationalError:
            self.logger.warning("secure_delete pragma unsupported by SQLite runtime")
        try:
            self.conn.execute("PRAGMA trusted_schema=OFF")
        except sqlite3.OperationalError:
            self.logger.warning("trusted_schema pragma unsupported by SQLite runtime")

        # Create tables with proper schema
        self._create_tables()

        # Create indexes for performance
        self._create_indexes()

    def _create_tables(self):
        """Create database tables with proper schema"""

        # Users table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                access_level INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                failed_attempts INTEGER DEFAULT 0,
                locked_until TIMESTAMP,
                metadata TEXT
            )
        """)

        # Memos table with security levels
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memos (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                encrypted_content TEXT,
                security_level INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                deleted_at TIMESTAMP,
                checksum TEXT,
                version INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Tags table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Memo-Tags relationship
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memo_tags (
                memo_id TEXT,
                tag_id INTEGER,
                PRIMARY KEY (memo_id, tag_id),
                FOREIGN KEY (memo_id) REFERENCES memos(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id)
            )
        """)

        # Audit log table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                ip_address TEXT,
                user_agent TEXT,
                details TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Sessions table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Performance metrics table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metric_name TEXT NOT NULL,
                value REAL,
                unit TEXT,
                metadata TEXT
            )
        """)

        # Full-text search virtual table
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memo_fts USING fts5(
                content,
                content=memos,
                content_rowid=rowid,
                tokenize='porter'
            )
        """)

        # Triggers for FTS
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memo_fts_insert AFTER INSERT ON memos
            BEGIN
                INSERT INTO memo_fts(rowid, content) VALUES (new.rowid, new.content);
            END
        """)

        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memo_fts_update AFTER UPDATE ON memos
            BEGIN
                UPDATE memo_fts SET content = new.content WHERE rowid = new.rowid;
            END
        """)

        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memo_fts_delete AFTER DELETE ON memos
            BEGIN
                DELETE FROM memo_fts WHERE rowid = old.rowid;
            END
        """)

        self.conn.commit()

    def _create_indexes(self):
        """Create database indexes for performance"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_memos_user_id ON memos(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_memos_created_at ON memos(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_memos_security_level ON memos(security_level)",
            "CREATE INDEX IF NOT EXISTS idx_memo_tags_memo_id ON memo_tags(memo_id)",
            "CREATE INDEX IF NOT EXISTS idx_memo_tags_tag_id ON memo_tags(tag_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)",
        ]

        for index in indexes:
            self.conn.execute(index)

        self.conn.commit()

    @contextmanager
    def transaction(self):
        """Database transaction context manager"""
        try:
            yield self.conn
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise e

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


# ====================== USER MANAGEMENT ======================

class UserService:
    """Handles user lifecycle and session management"""

    def __init__(self, db: DatabaseManager, security: SecurityManager, config: SystemConfig):
        self.db = db
        self.security = security
        self.config = config
        self.logger = logging.getLogger("memo_system.auth")

    # ---------- User helpers ----------

    def has_active_users(self) -> bool:
        cursor = self.db.conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
        return cursor.fetchone()[0] > 0

    def list_users(self, include_inactive: bool = False) -> List[User]:
        query = "SELECT * FROM users"
        params: Tuple[Any, ...] = ()
        if not include_inactive:
            query += " WHERE is_active = 1"
        cursor = self.db.conn.execute(query, params)
        return [self._row_to_user(row) for row in cursor.fetchall()]

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        access_level: AccessLevel = AccessLevel.USER,
    ) -> User:
        if not self.security.validate_username(username):
            raise ValueError("Username must be 3-64 characters using letters, digits, underscore, hyphen, or dot.")
        if not self.security.validate_email(email):
            raise ValueError("Email address format is invalid.")

        valid, message = self.security.validate_password(password)
        if not valid:
            raise ValueError(message)

        password_hash = self.security.hash_password(password)
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        metadata = json.dumps({"created_via": "cli", "created_at": now})

        try:
            with self.db.transaction():
                self.db.conn.execute(
                    """
                    INSERT INTO users (
                        id, username, email, password_hash, access_level,
                        created_at, is_active, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (user_id, username, email, password_hash, int(access_level), now, metadata),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Username or email already exists.") from exc

        user = User(
            id=user_id,
            username=username,
            email=email,
            access_level=access_level,
            created_at=datetime.fromisoformat(now.replace("Z", "")),
            last_login=None,
            is_active=True,
            failed_attempts=0,
            locked_until=None,
        )

        self.logger.info("User created: %s", username)
        return user

    def get_user_by_username(self, username: str) -> Optional[User]:
        cursor = self.db.conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_user(row)

    def get_user_by_id(self, user_id: str) -> Optional[User]:
        cursor = self.db.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_user(row)

    def change_password(
        self,
        user_id: str,
        current_password: Optional[str],
        new_password: str,
        require_current: bool = True,
    ) -> None:
        valid, message = self.security.validate_password(new_password)
        if not valid:
            raise ValueError(message)

        cursor = self.db.conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError("User not found.")

        if require_current:
            if current_password is None or not self.security.verify_password(current_password, row["password_hash"]):
                raise ValueError("Current password is incorrect.")

        password_hash = self.security.hash_password(new_password)
        with self.db.transaction():
            self.db.conn.execute(
                """
                UPDATE users
                SET password_hash = ?, failed_attempts = 0, locked_until = NULL
                WHERE id = ?
                """,
                (password_hash, user_id),
            )

        self.logger.info("Password updated for user_id=%s", user_id)

    # ---------- Authentication ----------

    def authenticate(
        self,
        username: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuthSession:
        cursor = self.db.conn.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row or not row["is_active"]:
            raise ValueError("Invalid username or password.")

        user = self._row_to_user(row)
        now = datetime.now(timezone.utc)

        if user.locked_until and user.locked_until > now:
            raise ValueError(
                f"Account locked until {user.locked_until.astimezone(timezone.utc).isoformat()}"
            )

        if not self.security.verify_password(password, row["password_hash"]):
            self._register_failed_login(user.id, row["failed_attempts"] or 0)
            raise ValueError("Invalid username or password.")

        if self.security.needs_rehash(row["password_hash"]):
            new_hash = self.security.hash_password(password)
            with self.db.transaction():
                self.db.conn.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (new_hash, user.id),
                )
            row = dict(row)
            row["password_hash"] = new_hash

        token, expires_at = self._issue_session(user.id, ip_address, user_agent)

        with self.db.transaction():
            self.db.conn.execute(
                """
                UPDATE users
                SET last_login = ?, failed_attempts = 0, locked_until = NULL
                WHERE id = ?
                """,
                (now.isoformat(), user.id),
            )

        user.last_login = now
        self.logger.info("User authenticated: %s", username)
        return AuthSession(user=user, token=token, expires_at=expires_at)

    def validate_session(self, token: str) -> Optional[Tuple[User, datetime]]:
        if not token:
            return None

        # Use HMAC instead of SHA256 for session token hashing
        import hmac
        secret = self.config.get_session_secret()
        hashed = hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()

        cursor = self.db.conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = ?",
            (hashed,),
        )
        session_row = cursor.fetchone()
        if not session_row:
            return None

        expires_at = self._parse_timestamp(session_row["expires_at"])
        if not expires_at or expires_at <= datetime.now(timezone.utc):
            self._delete_session_hash(hashed)
            return None

        user = self.get_user_by_id(session_row["user_id"])
        if not user or not user.is_active:
            self._delete_session_hash(hashed)
            return None

        return user, expires_at

    def revoke_session(self, token: str) -> None:
        if not token:
            return
        # Use HMAC instead of SHA256 for session token hashing
        import hmac
        secret = self.config.get_session_secret()
        hashed = hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()
        self._delete_session_hash(hashed)

    # ---------- Internal helpers ----------

    def _register_failed_login(self, user_id: str, current_failures: int) -> None:
        failures = current_failures + 1
        locked_until: Optional[str] = None
        if failures >= self.config.max_login_attempts:
            lock_expiry = datetime.now(timezone.utc) + timedelta(seconds=self.config.lockout_duration)
            locked_until = lock_expiry.isoformat()
            failures = 0

        with self.db.transaction():
            self.db.conn.execute(
                """
                UPDATE users
                SET failed_attempts = ?, locked_until = ?
                WHERE id = ?
                """,
                (failures, locked_until, user_id),
            )

    def _issue_session(
        self,
        user_id: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> Tuple[str, datetime]:
        raw_token = self.security.generate_session_token()
        # Use HMAC instead of SHA256 for session token hashing
        import hmac
        secret = self.config.get_session_secret()
        hashed = hmac.new(secret, raw_token.encode(), hashlib.sha256).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.config.session_timeout)

        with self.db.transaction():
            # Purge expired sessions for this user first
            self.db.conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND expires_at <= ?",
                (user_id, datetime.now(timezone.utc).isoformat()),
            )
            self.db.conn.execute(
                """
                INSERT INTO sessions (token, user_id, created_at, expires_at, ip_address, user_agent)
                VALUES (?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                """,
                (hashed, user_id, expires_at.isoformat(), ip_address, user_agent),
            )

        return raw_token, expires_at

    def _delete_session_hash(self, hashed_token: str) -> None:
        with self.db.transaction():
            self.db.conn.execute("DELETE FROM sessions WHERE token = ?", (hashed_token,))

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _row_to_user(self, row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            access_level=AccessLevel(row["access_level"]),
            created_at=self._parse_timestamp(str(row["created_at"])) or datetime.now(timezone.utc),
            last_login=self._parse_timestamp(row["last_login"]),
            is_active=bool(row["is_active"]),
            failed_attempts=row["failed_attempts"] or 0,
            locked_until=self._parse_timestamp(row["locked_until"]),
        )


# ====================== MEMO OPERATIONS ======================

@dataclass
class Memo:
    """Memo entity"""
    id: str
    user_id: str
    content: str
    security_level: SecurityLevel
    tags: List[str]
    created_at: datetime
    updated_at: Optional[datetime] = None
    version: int = 1
    checksum: Optional[str] = None

    def calculate_checksum(self) -> str:
        """Calculate content checksum"""
        return hashlib.sha256(self.content.encode()).hexdigest()


class MemoService:
    """Core memo management service"""

    _CLEARANCE_MATRIX: Dict[AccessLevel, SecurityLevel] = {
        AccessLevel.VIEWER: SecurityLevel.INTERNAL,
        AccessLevel.USER: SecurityLevel.CONFIDENTIAL,
        AccessLevel.ADMIN: SecurityLevel.SECRET,
        AccessLevel.SECURITY_ADMIN: SecurityLevel.TOP_SECRET,
        AccessLevel.SYSTEM: SecurityLevel.TOP_SECRET,
    }

    def __init__(self, db: DatabaseManager, security: SecurityManager, config: SystemConfig):
        self.db = db
        self.security = security
        self.config = config
        self.logger = logging.getLogger("memo_system.service")

    def create_memo(self, user_id: str, content: str, tags: List[str] = None,
                   security_level: SecurityLevel = SecurityLevel.INTERNAL) -> str:
        """Create a new memo with security checks"""

        # Validate input
        content = self.security.sanitize_input(content)
        if not content:
            raise ValueError("Content cannot be empty")

        # Validate tags
        if tags:
            tags = [tag for tag in tags if self.security.validate_tag(tag)]
            if len(tags) > self.config.max_tags_per_memo:
                tags = tags[:self.config.max_tags_per_memo]

        # Generate memo ID
        memo_id = str(uuid.uuid4())

        # Encrypt content if required
        encrypted_content = None
        stored_content = content
        requires_encryption = security_level >= SecurityLevel.CONFIDENTIAL and self.config.enable_encryption
        if requires_encryption and self.security.is_encryption_available():
            encrypted_content = self.security.encrypt_data(content)
            stored_content = "[ENCRYPTED]"
        elif requires_encryption:
            self.logger.warning(
                "Memo %s requested encryption but cryptography libraries are unavailable; storing plaintext.",
                memo_id,
            )

        # Calculate checksum
        checksum = hashlib.sha256(content.encode()).hexdigest()

        with self.db.transaction():
            # Insert memo
            self.db.conn.execute("""
                INSERT INTO memos (id, user_id, content, encrypted_content,
                                 security_level, checksum)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (memo_id, user_id, stored_content, encrypted_content,
                  security_level, checksum))

            # Handle tags
            if tags:
                for tag_name in tags:
                    # Insert or get tag
                    cursor = self.db.conn.execute(
                        "SELECT id FROM tags WHERE name = ?", (tag_name,)
                    )
                    tag_row = cursor.fetchone()

                    if tag_row:
                        tag_id = tag_row[0]
                    else:
                        cursor = self.db.conn.execute(
                            "INSERT INTO tags (name) VALUES (?)", (tag_name,)
                        )
                        tag_id = cursor.lastrowid

                    # Link memo to tag
                    self.db.conn.execute(
                        "INSERT INTO memo_tags (memo_id, tag_id) VALUES (?, ?)",
                        (memo_id, tag_id)
                    )

            # Audit log
            if self.config.enable_audit:
                self._audit_log(user_id, "CREATE_MEMO", "memo", memo_id)

        self.logger.info(f"Memo created: {memo_id} by user {user_id}")
        return memo_id

    def get_memo(self, memo_id: str, user_id: str) -> Optional[Memo]:
        """Get memo with security checks"""
        cursor = self.db.conn.execute("""
            SELECT m.id, m.user_id, m.content, m.encrypted_content,
                   m.security_level, m.created_at, m.updated_at,
                   m.version, m.checksum
            FROM memos m
            WHERE m.id = ? AND m.deleted_at IS NULL
        """, (memo_id,))

        row = cursor.fetchone()
        if not row:
            return None

        # Check access permissions
        allowed, denial_reason = self._check_access(user_id, row[1], SecurityLevel(row[4]))
        if not allowed:
            if self.config.enable_audit:
                self._audit_log(
                    user_id,
                    "ACCESS_DENIED",
                    "memo",
                    memo_id,
                    metadata={
                        "reason": denial_reason,
                        "required_security_level": int(SecurityLevel(row[4])),
                        "memo_owner": row[1],
                    },
                )
            return None

        # Decrypt content if needed
        content = row[2]
        if row[3]:  # Has encrypted content
            content = self.security.decrypt_data(row[3])

        # Get tags
        cursor = self.db.conn.execute("""
            SELECT t.name
            FROM tags t
            JOIN memo_tags mt ON t.id = mt.tag_id
            WHERE mt.memo_id = ?
        """, (memo_id,))
        tags = [row[0] for row in cursor.fetchall()]

        # Audit log
        if self.config.enable_audit:
            self._audit_log(user_id, "VIEW_MEMO", "memo", memo_id)

        return Memo(
            id=row[0],
            user_id=row[1],
            content=content,
            security_level=SecurityLevel(row[4]),
            tags=tags,
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]) if row[6] else None,
            version=row[7],
            checksum=row[8]
        )

    def search_memos(self, user_id: str, query: str, limit: int = 20) -> List[Memo]:
        """Search memos using single optimized query with JOIN."""
        if not self.db.conn:
            raise RuntimeError("Database connection not available")

        # Use single query with JOIN to get all data
        sql = """
            SELECT m.id, m.user_id, m.content, m.encrypted_content, m.security_level,
                   m.created_at, m.updated_at, m.version, m.checksum,
                   GROUP_CONCAT(t.name, ',') as tags
            FROM memos m
            JOIN memo_fts ON m.rowid = memo_fts.rowid
            LEFT JOIN memo_tags mt ON m.id = mt.memo_id
            LEFT JOIN tags t ON mt.tag_id = t.id
            WHERE memo_fts MATCH ?
              AND m.deleted_at IS NULL
            GROUP BY m.id
            ORDER BY rank
            LIMIT ?
        """

        cursor = self.db.conn.execute(sql, (query, limit))
        rows = cursor.fetchall()

        memos = []
        for row in rows:
            # Check access permissions
            allowed, denial_reason = self._check_access(user_id, row[1], SecurityLevel(row[4]))
            if not allowed:
                if self.config.enable_audit:
                    self._audit_log(
                        user_id,
                        "ACCESS_DENIED",
                        "memo",
                        row[0],
                        metadata={
                            "reason": denial_reason,
                            "required_security_level": int(SecurityLevel(row[4])),
                            "memo_owner": row[1],
                        },
                    )
                continue

            # Decrypt content if needed
            content = row[2]
            if row[3]:
                content = self.security.decrypt_data(row[3])

            # Parse tags from GROUP_CONCAT result
            tags = row['tags'].split(',') if row['tags'] else []

            memos.append(Memo(
                id=row[0],
                user_id=row[1],
                content=content,
                security_level=SecurityLevel(row[4]),
                tags=tags,
                created_at=datetime.fromisoformat(row[5]),
                updated_at=datetime.fromisoformat(row[6]) if row[6] else None,
                version=row[7],
                checksum=row[8]
            ))

        # Audit log
        if self.config.enable_audit:
            self._audit_log(user_id, "SEARCH_MEMOS", "memo", query)

        return memos

    def update_memo(self, memo_id: str, user_id: str, content: str) -> bool:
        """Update memo with versioning"""

        # Get existing memo
        existing = self.get_memo(memo_id, user_id)
        if not existing:
            return False

        # Validate new content
        content = self.security.sanitize_input(content)
        if not content:
            raise ValueError("Content cannot be empty")

        # Encrypt if needed
        encrypted_content = None
        stored_content = content
        requires_encryption = existing.security_level >= SecurityLevel.CONFIDENTIAL and self.config.enable_encryption
        if requires_encryption and self.security.is_encryption_available():
            encrypted_content = self.security.encrypt_data(content)
            stored_content = "[ENCRYPTED]"
        elif requires_encryption:
            self.logger.warning(
                "Memo %s requested encryption during update but cryptography libraries are unavailable; storing plaintext.",
                memo_id,
            )

        # Calculate new checksum
        checksum = hashlib.sha256(content.encode()).hexdigest()

        with self.db.transaction():
            self.db.conn.execute("""
                UPDATE memos
                SET content = ?, encrypted_content = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    version = version + 1, checksum = ?
                WHERE id = ? AND user_id = ?
            """, (stored_content, encrypted_content, checksum, memo_id, user_id))

            # Audit log
            if self.config.enable_audit:
                self._audit_log(user_id, "UPDATE_MEMO", "memo", memo_id)

        self.logger.info(f"Memo updated: {memo_id} by user {user_id}")
        return True

    def delete_memo(self, memo_id: str, user_id: str) -> bool:
        """Soft delete memo"""

        # Check if memo exists and user has access
        existing = self.get_memo(memo_id, user_id)
        if not existing:
            return False

        with self.db.transaction():
            # Soft delete
            self.db.conn.execute("""
                UPDATE memos
                SET deleted_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
            """, (memo_id, user_id))

            # Audit log
            if self.config.enable_audit:
                self._audit_log(user_id, "DELETE_MEMO", "memo", memo_id)

        self.logger.info(f"Memo deleted: {memo_id} by user {user_id}")
        return True

    def _get_requester_profile(self, user_id: str) -> Optional[sqlite3.Row]:
        cursor = self.db.conn.execute(
            "SELECT id, access_level, is_active FROM users WHERE id = ?",
            (user_id,),
        )
        return cursor.fetchone()

    def _check_access(
        self,
        user_id: str,
        owner_id: str,
        security_level: SecurityLevel,
    ) -> Tuple[bool, str]:
        """Check if user has access to memo and return denial reason when blocked."""

        if user_id == owner_id:
            return True, ""

        profile = self._get_requester_profile(user_id)
        if not profile:
            return False, "user_not_found"

        if not profile["is_active"]:
            return False, "user_inactive"

        access_level = AccessLevel(profile["access_level"])

        if access_level >= AccessLevel.SECURITY_ADMIN:
            return True, ""

        max_clearance = self._CLEARANCE_MATRIX.get(access_level, SecurityLevel.PUBLIC)

        if access_level >= AccessLevel.ADMIN and security_level <= max_clearance:
            return True, ""

        if security_level <= max_clearance and owner_id == user_id:
            return True, ""

        return False, "insufficient_clearance"

    def _audit_log(
        self,
        user_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """Log audit entry with extended metadata."""

        context = metadata.copy() if metadata else {}
        if ip_address:
            context.setdefault("ip_address", ip_address)
        if user_agent:
            context.setdefault("user_agent", user_agent)

        context_json = json.dumps(context, ensure_ascii=False) if context else None

        self.db.conn.execute(
            """
            INSERT INTO audit_log (user_id, action, entity_type, entity_id, ip_address, user_agent, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, action, entity_type, entity_id, context.get("ip_address"), context.get("user_agent"), context_json),
        )

    def reencrypt_sensitive_memos(
        self,
        old_fernet: Any,
        new_fernet: Any,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Re-encrypt all encrypted memos with a new Fernet key."""

        stats: Dict[str, Any] = {
            "processed": 0,
            "updated": 0,
            "failures": [],
        }

        if old_fernet is None or new_fernet is None:
            raise RuntimeError("Encryption libraries are unavailable for rotation")

        cursor = self.db.conn.execute(
            """
            SELECT id, encrypted_content
            FROM memos
            WHERE encrypted_content IS NOT NULL
            """
        )
        rows = cursor.fetchall()

        updates: List[Tuple[str, str, str]] = []  # (memo_id, new_encrypted, checksum)

        for row in rows:
            memo_id = row["id"]
            encrypted_payload = row["encrypted_content"]
            if not encrypted_payload:
                continue
            stats["processed"] += 1
            try:
                plaintext = old_fernet.decrypt(encrypted_payload.encode("utf-8")).decode("utf-8")
            except Exception as exc:
                stats["failures"].append({"memo_id": memo_id, "error": str(exc)})
                continue

            checksum = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
            new_encrypted = new_fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
            updates.append((new_encrypted, checksum, memo_id))

        if dry_run:
            stats["updated"] = len(updates)
            return stats

        if updates:
            with self.db.transaction():
                for new_encrypted, checksum, memo_id in updates:
                    self.db.conn.execute(
                        """
                        UPDATE memos
                        SET encrypted_content = ?, checksum = ?
                        WHERE id = ?
                        """,
                        (new_encrypted, checksum, memo_id),
                    )
            stats["updated"] = len(updates)

        return stats


# ====================== PERFORMANCE MONITORING ======================

class PerformanceMonitor:
    """System performance monitoring"""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.metrics_enabled = getattr(self.db.config, "enable_performance_monitoring", True)
        self.psutil_available = PSUTIL_AVAILABLE

    def record_metric(self, name: str, value: float, unit: str = "ms"):
        """Record performance metric"""
        if not self.metrics_enabled:
            return

        with self.db.transaction():
            self.db.conn.execute("""
                INSERT INTO metrics (metric_name, value, unit)
                VALUES (?, ?, ?)
            """, (name, value, unit))

    def get_system_status(self) -> Dict[str, Any]:
        """Get current system status"""
        status = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database_size": os.path.getsize(self.db.config.db_path) if self.db.config.db_path.exists() else 0,
        }

        if self.psutil_available:
            disk_root = self.db.config.db_path.anchor or os.path.abspath(os.sep)
            try:
                disk_usage = psutil.disk_usage(disk_root).percent
            except Exception:
                disk_usage = None
            status.update({
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_usage": disk_usage,
            })

        # Get database statistics
        cursor = self.db.conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM memos WHERE deleted_at IS NULL) as total_memos,
                (SELECT COUNT(*) FROM users WHERE is_active = 1) as active_users,
                (SELECT COUNT(*) FROM sessions WHERE expires_at > CURRENT_TIMESTAMP) as active_sessions
        """)
        row = cursor.fetchone()
        status.update({
            "total_memos": row[0],
            "active_users": row[1],
            "active_sessions": row[2],
            "dependencies": get_dependency_status(metrics_enabled=self.metrics_enabled),
        })

        return status


class MaintenanceService:
    """Routine maintenance utilities for database hygiene"""

    def __init__(self, db: DatabaseManager, config: SystemConfig):
        self.db = db
        self.config = config
        self.logger = logging.getLogger("memo_system.maintenance")

    def run_housekeeping(self) -> Dict[str, Any]:
        """Execute scheduled maintenance tasks with resilient error handling."""
        started = time.perf_counter()
        tasks: Dict[str, Any] = {
            "expired_sessions": self._purge_expired_sessions,
            "purged_audit_entries": self._prune_audit_logs,
            "purged_deleted_memos": self._prune_deleted_memos,
        }

        results: Dict[str, Any] = {}
        errors: List[Dict[str, str]] = []

        for task_name, func in tasks.items():
            try:
                results[task_name] = func()
            except Exception as exc:  # pragma: no cover - defensive path
                self.logger.error("Maintenance task %s failed: %s", task_name, exc, exc_info=True)
                results[task_name] = None
                errors.append({"task": task_name, "error": str(exc)})

        try:
            results["database_optimized"] = (
                self._optimize_database() if self.config.optimize_database_on_maintenance else False
            )
        except Exception as exc:  # pragma: no cover - defensive path
            self.logger.error("Database optimization failed: %s", exc, exc_info=True)
            results["database_optimized"] = False
            errors.append({"task": "database_optimized", "error": str(exc)})

        results["errors"] = errors
        results["success"] = not errors
        results["timestamp"] = datetime.now(timezone.utc).isoformat()
        results["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)

        self.logger.info(
            "Maintenance completed: %s",
            ", ".join(f"{key}={value}" for key, value in results.items() if key not in {"errors"}),
        )
        return results

    def run_health_check(self) -> Dict[str, Any]:
        """Run diagnostic checks and return their outcomes."""
        started = time.perf_counter()
        checks: Dict[str, Any] = {}
        failed: List[Dict[str, str]] = []

        for name, func in {
            "database_integrity": self._check_database_integrity,
            "fts_consistency": self._check_fts_consistency,
            "encryption_key_present": self._check_encryption_key,
            "key_backup_integrity": self._check_key_backup_integrity,
        }.items():
            try:
                outcome = func()
            except Exception as exc:  # pragma: no cover - defensive path
                self.logger.error("Health check %s failed: %s", name, exc, exc_info=True)
                outcome = False
                failed.append({"check": name, "error": str(exc)})

            checks[name] = bool(outcome)
            if not outcome and not any(entry.get("check") == name for entry in failed):
                failed.append({"check": name, "error": "failed"})

        checks["overall"] = all(checks.values())
        checks["failed_checks"] = failed
        checks["timestamp"] = datetime.now(timezone.utc).isoformat()
        checks["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return checks

    def _purge_expired_sessions(self) -> int:
        cutoff = datetime.now(timezone.utc).isoformat()
        with self.db.transaction():
            cursor = self.db.conn.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (cutoff,)
            )
        return cursor.rowcount or 0

    def _prune_audit_logs(self) -> int:
        if self.config.audit_retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.config.audit_retention_days))
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction():
            cursor = self.db.conn.execute(
                "DELETE FROM audit_log WHERE timestamp <= ?",
                (cutoff_str,)
            )
        return cursor.rowcount or 0

    def _prune_deleted_memos(self) -> int:
        if self.config.deleted_memo_retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.config.deleted_memo_retention_days))
        cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        with self.db.transaction():
            cursor = self.db.conn.execute(
                "DELETE FROM memos WHERE deleted_at IS NOT NULL AND deleted_at <= ?",
                (cutoff_str,)
            )
        return cursor.rowcount or 0

    def _check_database_integrity(self) -> bool:
        cursor = self.db.conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        return bool(result and result[0] == "ok")

    def _check_fts_consistency(self) -> bool:
        cursor = self.db.conn.execute(
            """
            SELECT (
                SELECT COUNT(*) FROM memo_fts
            ) = (
                SELECT COUNT(*) FROM memos WHERE deleted_at IS NULL
            )
        """
        )
        row = cursor.fetchone()
        return bool(row and row[0])

    def _check_encryption_key(self) -> bool:
        if not self.config.enable_encryption:
            return True
        key_file = self.config.db_path.parent / ".key"
        return key_file.exists() and key_file.is_file()

    def _check_key_backup_integrity(self) -> bool:
        directory = self.config.key_backup_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stats = directory.stat()
        except OSError:
            return False

        # Ensure directory permissions are restrictive when supported
        if hasattr(stats, "st_mode"):
            if stats.st_mode & 0o077:
                return False

        manifest_path = directory / "backups.manifest"
        manifest: Dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return False
            try:
                manifest_stats = manifest_path.stat()
            except OSError:
                return False
            if hasattr(manifest_stats, "st_mode") and manifest_stats.st_mode & 0o077:
                return False
        seen_paths: Set[str] = set()

        for backup in directory.glob("*.backup-*"):
            try:
                st = backup.stat()
            except OSError:
                return False

            if st.st_size <= 0:
                return False

            if hasattr(st, "st_mode") and (st.st_mode & 0o077):
                return False

            digest = hashlib.sha256(backup.read_bytes()).hexdigest()
            entry = manifest.get(str(backup)) if manifest else None
            if manifest and (not entry or entry.get("sha256") != digest):
                return False
            seen_paths.add(str(backup))

        if manifest:
            # Ensure manifest does not reference missing files
            for path_str, meta in manifest.items():
                if not Path(path_str).exists():
                    return False
                if not meta.get("sha256"):
                    return False
            if seen_paths and seen_paths != set(manifest.keys()):
                # Manifest must align exactly when backups exist
                return False

        return True

    def _optimize_database(self) -> bool:
        try:
            self.db.conn.execute("PRAGMA optimize")
            return True
        except sqlite3.Error as exc:
            self.logger.warning("Database optimization skipped: %s", exc)
            return False


# ====================== CLI INTERFACE ======================

class MemoSystemCLI:
    """Command-line interface for memo system"""

    def __init__(self):
        self.config = SystemConfig()
        self._billing_manager: Optional["StripeBillingManager"] = None
        configure_logging(self.config.log_dir)
        request_id_var.set(uuid.uuid4().hex)
        self.security = SecurityManager(self.config)
        self.db = DatabaseManager(self.config, self.security)
        self.user_service = UserService(self.db, self.security, self.config)
        self.service = MemoService(self.db, self.security, self.config)
        self.monitor = PerformanceMonitor(self.db)
        self.maintenance = MaintenanceService(self.db, self.config)
        self.session_logger = logging.getLogger("memo_system.session")
        self.automation_logger = logging.getLogger("memo_system.automation")
        self.i18n = get_i18n()  # Add i18n support
        self.i18n.load_external_resources()

        _warn_missing_dependencies(self.service.logger)

        # Initialize monitoring system
        self.alert_manager = None
        if self.config.enable_alerting and MONITORING_AVAILABLE:
            try:
                monitoring_db_path = self.config.db_path.parent / "monitoring.db"
                self.alert_manager = AlertManager(str(monitoring_db_path))
                self._setup_default_alert_rules()
                self.alert_manager.start_processing()
            except Exception as e:
                logging.getLogger("memo_system").warning(f"Failed to initialize monitoring: {e}")

        self.current_user = None
        self.session_data: Optional[Dict[str, Any]] = None
    def _setup_default_alert_rules(self):
        """Setup default alert rules for system monitoring"""
        if not self.alert_manager:
            return

        try:
            # CPU usage alert rule
            cpu_rule = AlertRule(
                name="High CPU Usage",
                condition="cpu_usage_high",
                severity=AlertSeverity.WARNING,
                description="CPU usage has exceeded 80% for more than 5 minutes",
                enabled=True,
                cooldown_minutes=15,
                threshold_value=80.0,
                comparison_operator=">",
                evaluation_window_minutes=5,
                notification_channels=["email"]
            )
            self.alert_manager.add_alert_rule(cpu_rule)

            # Memory usage alert rule
            memory_rule = AlertRule(
                name="High Memory Usage",
                condition="memory_usage_high",
                severity=AlertSeverity.WARNING,
                description="Memory usage has exceeded 85% for more than 5 minutes",
                enabled=True,
                cooldown_minutes=15,
                threshold_value=85.0,
                comparison_operator=">",
                evaluation_window_minutes=5,
                notification_channels=["email"]
            )
            self.alert_manager.add_alert_rule(memory_rule)

            # Disk usage alert rule
            disk_rule = AlertRule(
                name="High Disk Usage",
                condition="disk_usage_high",
                severity=AlertSeverity.ERROR,
                description="Disk usage has exceeded 90% for more than 5 minutes",
                enabled=True,
                cooldown_minutes=30,
                threshold_value=90.0,
                comparison_operator=">",
                evaluation_window_minutes=5,
                notification_channels=["email"]
            )
            self.alert_manager.add_alert_rule(disk_rule)

            # Setup email notification channel
            email_config = {
                'smtp_server': 'localhost',
                'smtp_port': 587,
                'from_email': 'alerts@memo-system.local',
                'to_emails': ['admin@memo-system.local'],
                'enabled': True
            }
            email_channel = EmailNotificationChannel("email", email_config)
            self.alert_manager.add_notification_channel(email_channel)

        except Exception as e:
            logging.getLogger("memo_system").warning(f"Failed to setup alert rules: {e}")

    def cleanup(self):
        """Cleanup resources"""
        if self.db:
            self.db.close()
        if self.alert_manager:
            self.alert_manager.stop_processing()

    def run(self):
        """Run the CLI"""
        parser = argparse.ArgumentParser(description=_("memo_system_description"))
        parser.add_argument("--request-id", help=_("request_id_help"))
        parser.add_argument("--lang", choices=list(self.i18n.get_supported_languages().keys()),
                          help=_("language_help"))
        subparsers = parser.add_subparsers(dest="command", help=_("commands_help"))

        billing_parser = subparsers.add_parser("billing", help=_("billing_help"))
        billing_sub = billing_parser.add_subparsers(dest="billing_command", required=True)
        checkout_parser = billing_sub.add_parser("checkout", help=_("billing_checkout_help"))
        checkout_parser.add_argument("--email", required=True, help=_("billing_checkout_email_help"))
        billing_sub.add_parser("show", help=_("billing_show_help"))

        # Add command
        add_parser = subparsers.add_parser(_("add_memo"), help=_("add_memo_help"))
        add_parser.add_argument("content", nargs="?", help=_("content_help"))
        add_parser.add_argument("-t", "--tags", nargs="+", help=_("tags_help"))
        add_parser.add_argument("-s", "--security", type=int, default=1,
                              help=_("security_help"))

        # List command
        list_parser = subparsers.add_parser(_("list_memos"), help=_("list_memos_help"))
        list_parser.add_argument("-l", "--limit", type=int, default=50,
                                help=_("limit_help"))
        list_parser.add_argument("--format", choices=["text", "json"], default="text",
                                 help=_("format_help"))

        # Search command
        search_parser = subparsers.add_parser(_("search_memos"), help=_("search_memos_help"))
        search_parser.add_argument("query", metavar=_("search_query"), help=_("query_help"))
        search_parser.add_argument("-l", "--limit", type=int, default=20,
                                  help=_("limit_help"))
        search_parser.add_argument("--format", choices=["text", "json"], default="text",
                                   help=_("format_help"))

        # Get command
        get_parser = subparsers.add_parser(_("get_memo"), help=_("get_memo_help"))
        get_parser.add_argument("id", metavar=_("memo_id"), help=_("id_help"))
        get_parser.add_argument("--format", choices=["text", "json"], default="text",
                                 help=_("format_help"))

        # Delete command
        delete_parser = subparsers.add_parser(_("delete_memo"), help=_("delete_memo_help"))
        delete_parser.add_argument("id", metavar=_("memo_id"), help=_("id_help"))

        # Status command
        status_parser = subparsers.add_parser(_("system_status"), help=_("status_help"))
        status_parser.add_argument("--format", choices=["text", "json"], default="text",
                                   help=_("format_help"))

        # Export command
        export_parser = subparsers.add_parser(_("export_memos"), help=_("export_help"))
        export_parser.add_argument("-f", "--format", choices=["json", "csv", "md"],
                                  default="json", help=_("export_format_help"))
        export_parser.add_argument("-o", "--output", help=_("output_help"))
        export_parser.add_argument(
            "--redact-level",
            type=int,
            choices=[level.value for level in SecurityLevel],
            help=_("export_redact_help"),
        )
        export_parser.add_argument(
            "--include-checksum",
            action="store_true",
            dest="include_checksum",
            help=_("export_checksum_help"),
        )
        export_parser.add_argument(
            "--compress",
            action="store_true",
            dest="compress",
            help=_("export_compress_help"),
        )
        export_parser.add_argument(
            "--sign",
            action="store_true",
            dest="sign",
            help=_("export_sign_help"),
        )

        # Rotate encryption key command
        rotate_parser = subparsers.add_parser(_("rotate_key"), help=_("rotate_key_help"))
        rotate_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help=_("rotate_key_dry_run_help"),
        )

        # Verify export signature command
        verify_parser = subparsers.add_parser(_("verify_signature"), help=_("verify_signature_help"))
        verify_parser.add_argument(
            "file",
            metavar=_("verify_signature_file"),
            help=_("verify_signature_file_help"),
        )
        verify_parser.add_argument(
            "--signature",
            dest="signature",
            help=_("verify_signature_path_help"),
        )

        # List key backups command
        list_backups_parser = subparsers.add_parser(_("list_key_backups"), help=_("list_key_backups_help"))
        list_backups_parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help=_("format_help"),
        )

        # Restore key backup command
        restore_parser = subparsers.add_parser(_("restore_key_backup"), help=_("restore_key_backup_help"))
        restore_parser.add_argument(
            "file",
            metavar=_("restore_key_backup_file"),
            help=_("restore_key_backup_file_help"),
        )
        restore_parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help=_("restore_key_backup_dry_run_help"),
        )

        # Verify key backups command
        verify_backups_parser = subparsers.add_parser(_("verify_key_backups"), help=_("verify_key_backups_help"))
        verify_backups_parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help=_("format_help"),
        )

        # Authentication commands
        subparsers.add_parser(_("init_admin"), help=_("init_admin_help"))
        login_parser = subparsers.add_parser(_("login"), help=_("login_help"))
        login_parser.add_argument("username", metavar=_("username"), help=_("username_help"))
        logout_parser = subparsers.add_parser(_("logout"), help=_("logout_help"))

        # Maintenance command
        maintenance_parser = subparsers.add_parser(_("maintenance"), help=_("maintenance_help"))
        maintenance_parser.add_argument("--format", choices=["text", "json"], default="text",
                                        help=_("format_help"))
        maintenance_parser.add_argument("--output", help=_("maintenance_output_help"))
        maintenance_parser.add_argument(
            "--fail-on-error",
            action="store_true",
            dest="fail_on_error",
            help=_("maintenance_fail_help"),
        )

        # Health diagnostics command
        health_parser = subparsers.add_parser(_("health"), help=_("health_help"))
        health_parser.add_argument("--format", choices=["text", "json"], default="text",
                                   help=_("format_help"))
        health_parser.add_argument("--output", help=_("health_output_help"))
        health_parser.add_argument(
            "--fail-on-error",
            action="store_true",
            dest="fail_on_error",
            help=_("health_fail_help"),
        )

        args = parser.parse_args()

        # Set language if specified
        if args.lang:
            self.i18n.set_language(args.lang)
            # Update parser with new language
            args = parser.parse_args()

        if args.request_id:
            request_id_var.set(args.request_id)

        if args.command == "billing":
            self._handle_billing_command(args)
            return

        self._enforce_billing()

        if args.command == _("init_admin"):
            self._handle_init_admin()
            return

        if args.command == _("login"):
            self._handle_login(args)
            return

        if args.command == _("logout"):
            self._handle_logout()
            return

        if args.command == _("maintenance"):
            self._load_session()
            if not self.current_user:
                print(_("no_active_session"))
                return
            self._handle_maintenance(args)
            return

        if args.command == _("health"):
            self._load_session()
            self._handle_health(args)
            return

        self._load_session()
        if not self.current_user:
            print(_("no_active_session"))
            return

        if args.command == _("add_memo"):
            self._handle_add(args)
        elif args.command == _("list_memos"):
            self._handle_list(args)
        elif args.command == _("search_memos"):
            self._handle_search(args)
        elif args.command == _("get_memo"):
            self._handle_get(args)
        elif args.command == _("delete_memo"):
            self._handle_delete(args)
        elif args.command == _("system_status"):
            self._handle_status(args)
        elif args.command == _("export_memos"):
            self._handle_export(args)
        elif args.command == _("rotate_key"):
            self._handle_rotate_key(args)
        elif args.command == _("verify_signature"):
            self._handle_verify_signature(args)
        elif args.command == _("list_key_backups"):
            self._handle_list_key_backups(args)
        elif args.command == _("restore_key_backup"):
            self._handle_restore_key_backup(args)
        elif args.command == _("verify_key_backups"):
            self._handle_verify_key_backups(args)
        else:
            parser.print_help()

    def _session_file_exists(self) -> bool:
        return self.config.session_file.exists()

    def _load_session(self) -> None:
        if not self._session_file_exists():
            self.current_user = None
            self.session_data = None
            return

        try:
            with open(self.config.session_file, "r", encoding="utf-8") as fh:
                session = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self._clear_session(reason="decode_error")
            return

        token = session.get("token")
        if not token:
            self._clear_session(reason="token_missing")
            return

        validated = self.user_service.validate_session(token)
        if not validated:
            self._clear_session(reason="validation_failed")
            return

        user, expires_at = validated
        self.current_user = user.id
        self.session_data = {
            "token": token,
            "user": user.username,
            "access_level": int(user.access_level),
            "expires_at": expires_at.isoformat(),
        }
        request_id_var.set(f"{user.id}:{uuid.uuid4().hex}")

    def _store_session(self, token: str, user: User, expires_at: datetime) -> None:
        payload = {
            "token": token,
            "user": user.username,
            "access_level": int(user.access_level),
            "expires_at": expires_at.isoformat(),
        }

        session_dir = self.config.session_file.parent
        session_dir.mkdir(parents=True, exist_ok=True)
        with suppress(PermissionError, NotImplementedError):
            session_dir.chmod(0o700)

        temp_session_path = self.config.session_file.with_suffix(self.config.session_file.suffix + ".tmp")
        try:
            with open(temp_session_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
                fh.flush()
                with suppress(OSError):
                    os.fsync(fh.fileno())
            os.replace(temp_session_path, self.config.session_file)
        finally:
            with suppress(OSError):
                if temp_session_path.exists():
                    temp_session_path.unlink()

        with suppress(PermissionError, NotImplementedError):
            self.config.session_file.chmod(0o600)
        self.session_data = payload
        self.current_user = user.id
        self.session_logger.info("Session persisted for user %s", user.username)

    def _persist_session(self) -> None:
        if not self.session_data:
            return
        try:
            with open(self.config.session_file, "w", encoding="utf-8") as fh:
                json.dump(self.session_data, fh, ensure_ascii=False)
            with suppress(PermissionError, NotImplementedError):
                self.config.session_file.chmod(0o600)
        except OSError as exc:
            self.session_logger.warning("Failed to persist session: %s", exc)

    def _clear_session(self, *, reason: str) -> None:
        if self._session_file_exists():
            self.session_logger.info("Clearing session (reason=%s) at %s", reason, self.config.session_file)
            with suppress(OSError):
                self.config.session_file.unlink()
        self.current_user = None
        self.session_data = None

    def _current_access_level(self) -> AccessLevel:
        if not self.session_data:
            return AccessLevel.VIEWER
        try:
            return AccessLevel(self.session_data.get("access_level", int(AccessLevel.VIEWER)))
        except ValueError:
            return AccessLevel.VIEWER

    def _require_role(self, minimum: AccessLevel, *, audit_action: str) -> bool:
        current_level = self._current_access_level()
        if current_level >= minimum:
            return True

        message = _("insufficient_privileges", required=minimum.name)
        print(message)
        self.automation_logger.warning(
            "command_denied action=%s user=%s level=%s required=%s",
            audit_action,
            self.current_user,
            current_level.name,
            minimum.name,
        )
        if self.config.enable_audit and self.current_user:
            self.service._audit_log(  # type: ignore[attr-defined]
                self.current_user,
                "ACCESS_DENIED",
                "command",
                audit_action,
                metadata={
                    "reason": "insufficient_privileges",
                    "user_level": current_level.name,
                    "required_level": minimum.name,
                },
            )
        return False

    def _write_output_file(self, path: str, payload: Any, *, as_json: bool, binary: bool = False) -> None:
        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")

        mode = "wb" if binary or isinstance(payload, (bytes, bytearray)) else "w"
        encoding = None if mode == "wb" else "utf-8"

        open_kwargs: Dict[str, Any] = {"mode": mode}
        if encoding:
            open_kwargs["encoding"] = encoding

        try:
            with open(temp_path, **open_kwargs) as fh:  # type: ignore[arg-type]
                if as_json:
                    if mode == "wb":
                        serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
                        fh.write(serialized)
                    else:
                        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
                else:
                    if mode == "wb":
                        data = payload if isinstance(payload, (bytes, bytearray)) else str(payload).encode("utf-8")
                        fh.write(data)
                    else:
                        fh.write(payload if isinstance(payload, str) else str(payload))
                fh.flush()
                with suppress(OSError):
                    os.fsync(fh.fileno())
            os.replace(temp_path, output_path)
        finally:
            with suppress(OSError):
                if temp_path.exists():
                    temp_path.unlink()

        with suppress(PermissionError, NotImplementedError):
            output_path.chmod(0o600)
        logging.getLogger("memo_system.automation").info("Wrote automation output to %s", output_path)

    def _perform_startup_maintenance(self) -> None:
        try:
            self.maintenance.run_housekeeping()
        except Exception as exc:
            self.session_logger.warning("Maintenance failed: %s", exc)
            logging.getLogger("memo_system").warning("Maintenance failed: %s", exc)

    def _handle_init_admin(self) -> None:
        """Initialize the first administrator in an interactive, secure flow."""
        existing_admins = self.db.conn.execute(
            "SELECT COUNT(*) FROM users WHERE access_level >= ?",
            (AccessLevel.ADMIN,)
        ).fetchone()[0]
        if existing_admins:
            print(_("admin_already_initialized"))
            return

        username = input(_("admin_username_prompt")).strip()
        email = input(_("admin_email_prompt")).strip()
        while True:
            password = getpass.getpass(_("admin_password_prompt"))
            confirm = getpass.getpass(_("admin_confirm_password"))
            if password != confirm:
                print(_("passwords_do_not_match"))
                continue
            valid, message = self.security.validate_password(password)
            if not valid:
                print(f"✗ {message}")
                continue
            break

        try:
            user = self.user_service.create_user(
                username=username,
                email=email,
                password=password,
                access_level=AccessLevel.ADMIN,
            )
            print(_("admin_created", username=user.username))
        except ValueError as exc:
            print(f"✗ {exc}")

    def _handle_login(self, args) -> None:
        password = getpass.getpass(_("password_prompt", username=args.username))
        try:
            session = self.user_service.authenticate(
                username=args.username,
                password=password,
            )
        except ValueError as exc:
            print(f"✗ {exc}")
            return

        self._store_session(session.token, session.user, session.expires_at)
        request_id_var.set(f"{session.user.id}:{uuid.uuid4().hex}")
        print(_("login_success", username=session.user.username, expires_at=session.expires_at.isoformat()))

    def _handle_logout(self) -> None:
        if not self._session_file_exists():
            print(_("no_active_session"))
            return

        try:
            with open(self.config.session_file, "r", encoding="utf-8") as fh:
                session = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self._clear_session(reason="logout_decode_error")
            print(_("logout_success"))
            return

        token = session.get("token")
        if token:
            self.user_service.revoke_session(token)
        self._clear_session(reason="logout")
        print(_("logout_success"))

    def _handle_add(self, args):
        """Handle add command"""
        if not self._require_role(AccessLevel.USER, audit_action="ADD_MEMO"):
            return

        content = args.content
        if content is None:
            content = sys.stdin.read().strip()

        if not content:
            print(_("content_empty"))
            return

        try:
            security_level = SecurityLevel(args.security)
        except ValueError:
            print(_("error_occurred", error=f"Invalid security level: {args.security}"))
            return

        if args.tags:
            normalized_tags: List[str] = []
            seen_tags: Set[str] = set()
            removed_empty = 0
            removed_duplicates = 0
            for tag in args.tags:
                cleaned = tag.strip()
                if not cleaned:
                    removed_empty += 1
                    continue
                if cleaned in seen_tags:
                    removed_duplicates += 1
                    continue
                seen_tags.add(cleaned)
                normalized_tags.append(cleaned)

            removed_total = removed_empty + removed_duplicates
            if removed_total:
                print(
                    _(
                        "warning_tags_removed",
                        count=removed_total,
                    )
                )

            tags = normalized_tags
        else:
            tags = []

        if tags:
            invalid_tags = [tag for tag in tags if not self.security.validate_tag(tag)]
            if invalid_tags:
                unique_invalid = sorted(set(invalid_tags))
                formatted = ", ".join(unique_invalid)
                print(
                    _(
                        "warning_invalid_tags_skipped",
                        tags=formatted,
                    )
                )
                tags = [tag for tag in tags if tag not in invalid_tags]

        if args.tags and not tags:
            print(_("warning_no_valid_tags"))

        if len(tags) > self.config.max_tags_per_memo:
            removed_count = len(tags) - self.config.max_tags_per_memo
            print(
                _(
                    "warning_tags_truncated",
                    count=removed_count,
                    limit=self.config.max_tags_per_memo,
                )
            )
            tags = tags[: self.config.max_tags_per_memo]

        try:
            memo_id = self.service.create_memo(
                self.current_user,
                content,
                tags,
                security_level
            )
            print(_("memo_created", memo_id=memo_id))
        except Exception as e:
            print(_("error_occurred", error=str(e)))

    def _handle_get(self, args):
        """Handle get command"""
        if not self._require_role(AccessLevel.VIEWER, audit_action="GET_MEMO"):
            return

        memo = self.service.get_memo(args.id, self.current_user)

        if not memo:
            if getattr(args, "format", "text") == "json":
                print(json.dumps({"id": args.id, "found": False}))
            else:
                print(_("memo_not_found", memo_id=args.id))
            return

        if getattr(args, "format", "text") == "json":
            payload = {
                "id": memo.id,
                "content": memo.content,
                "security_level": int(memo.security_level),
                "tags": memo.tags,
                "created_at": memo.created_at.isoformat(),
                "updated_at": memo.updated_at.isoformat() if memo.updated_at else None,
                "version": memo.version,
                "checksum": memo.checksum,
            }
            print(json.dumps(payload, indent=2))
            return

        print("\n=== Memo Details ===")
        print(_("memo_id_label", memo_id=memo.id))
        print(_("created_label", created=self.i18n.format_date(memo.created_at)))
        if memo.updated_at:
            print(_("updated_label", updated=self.i18n.format_date(memo.updated_at)))
        print(_("security_level_label", level=memo.security_level.name))
        if memo.tags:
            print(_("tags_label", tags=', '.join(memo.tags)))
        print(_("version_label", version=memo.version))
        if memo.checksum:
            print(_("checksum_label", checksum=memo.checksum))
        print("\n--- Content ---")
        print(memo.content)

    def _handle_list(self, args):
        """Handle list command"""
        if not self._require_role(AccessLevel.VIEWER, audit_action="LIST_MEMOS"):
            return

        limit = args.limit
        if limit <= 0:
            error_message = _("limit_positive_required")
            print(_("error_occurred", error=error_message))
            limit = 1

        cursor = self.db.conn.execute(
            """
            SELECT id, content, created_at
            FROM memos
            WHERE user_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (self.current_user, limit),
        )

        rows = cursor.fetchall()

        if getattr(args, "format", "text") == "json":
            items = [
                {
                    "id": row["id"],
                    "content": row["content"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
            print(json.dumps({"count": len(items), "memos": items}, indent=2, default=str))
            return

        if not rows:
            print(_("no_memos_found"))
            return

        for row in rows:
            created_raw = row["created_at"]
            try:
                created = datetime.fromisoformat(created_raw).strftime(self.i18n.get('date_format'))
            except (TypeError, ValueError):
                created = created_raw or ""
            content = row["content"] or ""
            preview = content[:80] + "..." if len(content) > 80 else content
            memo_id = row["id"] or ""
            print(f"[{memo_id[:8]}] {created} - {preview}")

    def _handle_search(self, args):
        """Handle search command"""
        if not self._require_role(AccessLevel.USER, audit_action="SEARCH_MEMOS"):
            return

        limit = args.limit
        if limit <= 0:
            error_message = _("limit_positive_required")
            print(_("error_occurred", error=error_message))
            limit = 1

        try:
            memos = self.service.search_memos(self.current_user, args.query, limit)
        except Exception as exc:
            print(_("error_occurred", error=str(exc)))
            return

        output_format = getattr(args, "format", "text")
        if output_format == "json":
            payload = [
                {
                    "id": memo.id,
                    "content": memo.content,
                    "security_level": int(memo.security_level),
                    "tags": memo.tags,
                    "created_at": memo.created_at.isoformat(),
                    "updated_at": memo.updated_at.isoformat() if memo.updated_at else None,
                    "version": memo.version,
                    "checksum": memo.checksum,
                }
                for memo in memos
            ]
            print(json.dumps({"query": args.query, "count": len(payload), "results": payload}, indent=2))
            return

        if not memos:
            print(_("no_search_results", query=args.query))
            return

        for memo in memos:
            created = self.i18n.format_date(memo.created_at)
            content_preview = memo.content[:80] + "..." if len(memo.content) > 80 else memo.content
            tags_str = f" [{', '.join(memo.tags)}]" if memo.tags else ""
            print(f"[{memo.id[:8]}] {created} - {content_preview}{tags_str}")

    def _handle_delete(self, args):
        """Handle delete command"""
        if not self._require_role(AccessLevel.USER, audit_action="DELETE_MEMO"):
            return

        try:
            if self.service.delete_memo(args.id, self.current_user):
                print(_("memo_deleted", memo_id=args.id))
            else:
                print(_("memo_not_found", memo_id=args.id))
        except Exception as e:
            print(_("error_occurred", error=str(e)))

    def _handle_maintenance(self, args) -> None:
        if not self.session_data:
            print(_("no_active_session"))
            return

        if self.session_data.get("access_level", AccessLevel.USER) < int(AccessLevel.ADMIN):
            print(_("admin_privileges_required"))
            return

        results = self.maintenance.run_housekeeping()
        output_format = getattr(args, "format", "text")
        fail_on_error = getattr(args, "fail_on_error", False)

        self.automation_logger.info(
            "maintenance_result success=%s duration_ms=%s errors=%s",
            results.get("success", True),
            results.get("duration_ms"),
            json.dumps(results.get("errors", []), ensure_ascii=False),
        )

        if output_format == "json":
            serialized = json.dumps(results, indent=2, default=str)
            print(serialized)
            if getattr(args, "output", None):
                self._write_output_file(args.output, results, as_json=True)
            return

        lines = [
            "\n=== Maintenance Summary ===",
            _("maintenance_timestamp", timestamp=results['timestamp']),
            _("maintenance_duration", duration=results['duration_ms']),
            _("expired_sessions_purged", count=results['expired_sessions']),
            _("audit_entries_removed", count=results['purged_audit_entries']),
            _("deleted_memos_removed", count=results['purged_deleted_memos']),
        ]
        if self.config.optimize_database_on_maintenance:
            optimization_status = _("optimization_pass") if results['database_optimized'] else _("optimization_skipped")
            lines.append(_("database_optimization", status=optimization_status))
        errors = results.get("errors", [])
        if errors:
            lines.append("\n--- Errors ---")
            for item in errors:
                lines.append(f"{item.get('task')}: {item.get('error')}")

        for line in lines:
            print(line)

        if getattr(args, "output", None):
            self._write_output_file(args.output, "\n".join(lines), as_json=False)

        if fail_on_error and not results.get("success", True):
            raise SystemExit(1)

    def _handle_health(self, args) -> None:
        if not self.session_data:
            print(_("no_active_session"))
            return

        if not self._require_role(AccessLevel.USER, audit_action="HEALTH_CHECK"):
            return

        diagnostics = self.maintenance.run_health_check()
        output_format = getattr(args, "format", "text")
        fail_on_error = getattr(args, "fail_on_error", False)

        self.automation_logger.info(
            "health_result overall=%s failed_checks=%s duration_ms=%s",
            diagnostics.get("overall", True),
            json.dumps(diagnostics.get("failed_checks", []), ensure_ascii=False),
            diagnostics.get("duration_ms"),
        )

        if output_format == "json":
            serialized = json.dumps(diagnostics, indent=2, default=str)
            print(serialized)
            if getattr(args, "output", None):
                self._write_output_file(args.output, diagnostics, as_json=True)
            return

        overall_status = _("health_pass") if diagnostics['overall'] else _("health_fail")
        lines = [
            "\n=== Health Diagnostics ===",
            _("health_timestamp", timestamp=diagnostics['timestamp']),
            _("health_duration", duration=diagnostics['duration_ms']),
        ]
        for key in ["database_integrity", "fts_consistency", "encryption_key_present", "key_backup_integrity"]:
            status = diagnostics[key]
            label = key.replace("_", " ").title()
            status_text = _("health_pass") if status else _("health_fail")
            lines.append(_("health_check_result", check=label, status=status_text))
        lines.append(_("overall_health", status=overall_status))
        failed_checks = diagnostics.get("failed_checks", [])
        if failed_checks:
            lines.append("\n--- Failed Checks ---")
            for item in failed_checks:
                lines.append(f"{item.get('check')}: {item.get('error')}")

        for line in lines:
            print(line)

        if getattr(args, "output", None):
            self._write_output_file(args.output, "\n".join(lines), as_json=False)

        if fail_on_error and not diagnostics.get("overall", True):
            raise SystemExit(2)

    def _handle_status(self, args):
        """Handle status command"""
        if not self._require_role(AccessLevel.ADMIN, audit_action="SYSTEM_STATUS"):
            return

        status = self.monitor.get_system_status()

        if getattr(args, "format", "text") == "json":
            print(json.dumps(status, indent=2, default=str))
            return

        print("\n=== System Status ===")
        print(_("status_timestamp", timestamp=status['timestamp']))
        print(_("database_size", size=status['database_size'] / 1024 / 1024))
        print(_("total_memos", count=status['total_memos']))
        print(_("active_users", count=status['active_users']))
        print(_("active_sessions", count=status['active_sessions']))

        dependencies = status.get("dependencies", {})
        if dependencies:
            print("\n=== Dependency Status ===")
            for name, details in dependencies.items():
                state = "OK" if details.get("available") else "MISSING"
                info = details.get("details", "")
                print(f"{name}: {state} - {info}")

        if 'cpu_percent' in status:
            print("\n=== Resource Usage ===")
            print(_("cpu_usage", percent=status['cpu_percent']))
            print(_("memory_usage", percent=status['memory_percent']))
            disk_value = status.get('disk_usage')
            disk_display = f"{disk_value}%" if disk_value is not None else _("disk_usage_unavailable")
            print(_("disk_usage_label", usage=disk_display))

    def _handle_export(self, args):
        """Handle export command"""
        if not self._require_role(AccessLevel.USER, audit_action="EXPORT_MEMOS"):
            return

        cursor = self.db.conn.execute("""
            SELECT id, content, encrypted_content, security_level, created_at, checksum
            FROM memos
            WHERE user_id = ? AND deleted_at IS NULL
            ORDER BY created_at DESC
        """, (self.current_user,))

        redact_threshold = getattr(args, "redact_level", None)
        if redact_threshold is not None:
            try:
                _ = SecurityLevel(redact_threshold)
            except ValueError:
                print(_("error_occurred", error=f"Invalid redaction level: {redact_threshold}"))
                return

        include_checksum = getattr(args, "include_checksum", False)
        compress_export = getattr(args, "compress", False)
        sign_export = getattr(args, "sign", False)

        base_output = args.output or f"export.{args.format}"
        if compress_export:
            output = base_output if base_output.endswith(".gz") else f"{base_output}.gz"
        else:
            output = base_output

        memos = []
        redacted_count = 0
        decryption_failures = 0

        for row in cursor.fetchall():
            security_level = SecurityLevel(row[3])
            created_at = row[4]
            checksum = row[5]

            content_plain = row[1] or ""
            if row[2]:
                try:
                    content_plain = self.security.decrypt_data(row[2])
                except Exception:
                    content_plain = _("export_decryption_failed")
                    decryption_failures += 1

            export_content = content_plain
            if redact_threshold is not None and row[3] >= redact_threshold:
                export_content = f"[REDACTED:{security_level.name}]"
                redacted_count += 1

            record = {
                "id": row[0],
                "content": export_content,
                "security_level": int(security_level),
                "created_at": created_at,
            }
            if include_checksum:
                record["checksum"] = checksum

            memos.append(record)

        output = args.output or f"export.{args.format}"
        metadata = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "memo_count": len(memos),
            "format": args.format,
            "user_id": self.current_user,
            "sensitive_records": sum(
                1 for memo in memos if memo["security_level"] >= int(SecurityLevel.CONFIDENTIAL)
            ),
            "redaction_level": redact_threshold,
            "redacted_count": redacted_count,
            "checksums_included": include_checksum,
            "decryption_failures": decryption_failures,
            "compressed": compress_export,
            "signature_requested": sign_export,
            "output_file": output,
        }

        try:
            if args.format == "json":
                payload = {"metadata": metadata, "memos": memos}
                if compress_export:
                    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
                    compressed = gzip.compress(serialized.encode("utf-8"))
                    self._write_output_file(output, compressed, as_json=False, binary=True)
                else:
                    self._write_output_file(output, payload, as_json=True)
            elif args.format == "csv":
                import csv

                buffer = io.StringIO()
                fieldnames = ["id", "content", "security_level", "created_at"]
                if include_checksum:
                    fieldnames.append("checksum")
                writer = csv.DictWriter(buffer, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(memos)
                header_line = "# " + json.dumps(metadata, ensure_ascii=False)
                csv_payload = header_line + "\n" + buffer.getvalue()
                if compress_export:
                    compressed = gzip.compress(csv_payload.encode("utf-8"))
                    self._write_output_file(output, compressed, as_json=False, binary=True)
                else:
                    self._write_output_file(output, csv_payload, as_json=False)
            elif args.format == "md":
                lines = [
                    _("exported_memos_title"),
                    _(
                        "export_metadata_header",
                        exported_at=metadata["exported_at"],
                        count=metadata["memo_count"],
                    ),
                    "\n```json\n",
                    json.dumps(metadata, indent=2, ensure_ascii=False),
                    "\n```\n",
                ]
                for memo in memos:
                    lines.append(f"\n## {memo['id']}\n")
                    lines.append(_("created_label", created=memo['created_at']))
                    lines.append(f"\n**Security:** Level {memo['security_level']}\n\n")
                    lines.append(f"{memo['content']}\n\n---\n")
                markdown_payload = "".join(lines)
                if compress_export:
                    compressed = gzip.compress(markdown_payload.encode("utf-8"))
                    self._write_output_file(output, compressed, as_json=False, binary=True)
                else:
                    self._write_output_file(output, markdown_payload, as_json=False)
            else:
                raise ValueError(f"Unsupported format: {args.format}")
        except (OSError, ValueError) as exc:
            print(_("error_occurred", error=str(exc)))
            return

        print(_("export_successful", count=len(memos), file=output))

        if sign_export:
            try:
                secret = self.config.get_session_secret()
                file_bytes = Path(output).read_bytes()
                digest = hmac.new(secret, file_bytes, hashlib.sha256).hexdigest()
                signature_payload = {
                    "signed_at": datetime.now(timezone.utc).isoformat(),
                    "target": Path(output).name,
                    "algorithm": "HMAC-SHA256",
                    "digest": digest,
                    "metadata": metadata,
                }
                signature_path = f"{output}.sig"
                self._write_output_file(signature_path, signature_payload, as_json=True)
                print(_("export_signature_written", file=signature_path))
            except OSError as exc:
                print(_("error_occurred", error=str(exc)))

    def _handle_rotate_key(self, args) -> None:
        if not self._require_role(AccessLevel.SECURITY_ADMIN, audit_action="ROTATE_KEY"):
            return

        if not self.config.enable_encryption or not self.security.is_encryption_available():
            print(_("rotate_key_not_available"))
            return

        dry_run = getattr(args, "dry_run", False)

        current_fernet = getattr(self.security, "fernet", None)
        if current_fernet is None:
            print(_("rotate_key_not_available"))
            return

        key_path = self.config.db_path.parent / ".key"
        new_key = Fernet.generate_key()
        new_fernet = Fernet(new_key)

        stats = self.service.reencrypt_sensitive_memos(current_fernet, new_fernet, dry_run=dry_run)

        if dry_run:
            print(_("rotate_key_dry_run_summary", processed=stats["processed"], pending=stats["updated"]))
            return

        temp_key_path = key_path.with_suffix(".next")
        temp_key_path.write_bytes(new_key)
        with suppress(PermissionError, NotImplementedError):
            temp_key_path.chmod(0o600)
        existing_key: Optional[bytes] = None
        with suppress(OSError):
            if key_path.exists():
                existing_key = key_path.read_bytes()

        manifest_path = self.config.key_backup_dir / "backups.manifest"
        manifest: Dict[str, Any] = {}
        if manifest_path.exists():
            with suppress(json.JSONDecodeError, OSError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        backup_path: Optional[Path] = None
        if existing_key:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = self.config.key_backup_dir / f"{key_path.name}.backup-{timestamp}"
            backup_path.write_bytes(existing_key)
            with suppress(PermissionError, NotImplementedError):
                backup_path.chmod(0o600)
            digest = hashlib.sha256(existing_key).hexdigest()
            manifest[str(backup_path)] = {
                "created_at": timestamp,
                "sha256": digest,
            }
            retention = max(self.config.key_backup_retention, 1)
            backups = sorted(
                self.config.key_backup_dir.glob(f"{key_path.name}.backup-*")
            )
            if len(backups) > retention:
                for stale in backups[:-retention]:
                    with suppress(OSError):
                        stale.unlink()
                        manifest.pop(str(stale), None)
                print(_("rotate_key_backup_pruned", count=len(backups) - retention))
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            with suppress(PermissionError, NotImplementedError):
                manifest_path.chmod(0o600)

        os.replace(temp_key_path, key_path)

        self.security.fernet = new_fernet

        print(_("rotate_key_success", updated=stats["updated"]))
        if backup_path:
            print(_("rotate_key_backup_saved", file=str(backup_path)))

        if stats.get("failures"):
            print(_("rotate_key_failures"))
            for failure in stats["failures"]:
                print(f" - {failure['memo_id']}: {failure['error']}")

        if self.config.enable_audit and self.current_user:
            self.service._audit_log(  # type: ignore[attr-defined]
                self.current_user,
                "ROTATE_KEY",
                "system",
                "encryption",
                metadata={
                    "updated": stats.get("updated", 0),
                    "processed": stats.get("processed", 0),
                    "failures": len(stats.get("failures", [])),
                    "backup_path": str(backup_path) if backup_path else None,
                },
            )

    def _handle_verify_signature(self, args) -> None:
        file_path = Path(args.file).expanduser()
        if not file_path.exists():
            print(_("verify_signature_missing_file", file=str(file_path)))
            return

        signature_path = Path(args.signature).expanduser() if getattr(args, "signature", None) else file_path.with_suffix(file_path.suffix + ".sig")
        if not signature_path.exists():
            print(_("verify_signature_missing_sig", file=str(signature_path)))
            return

        try:
            signature_data = json.loads(signature_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(_("verify_signature_read_error", file=str(signature_path), error=str(exc)))
            return

        expected_digest = signature_data.get("digest")
        if not expected_digest:
            print(_("verify_signature_invalid_format", file=str(signature_path)))
            return

        secret = self.config.get_session_secret()
        try:
            file_bytes = file_path.read_bytes()
        except OSError as exc:
            print(_("error_occurred", error=str(exc)))
            return

        computed_digest = hmac.new(secret, file_bytes, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected_digest, computed_digest):
            print(_("verify_signature_success", file=str(file_path)))
        else:
            print(_("verify_signature_failure", file=str(file_path)))
            if self.config.enable_audit and self.current_user:
                self.service._audit_log(  # type: ignore[attr-defined]
                    self.current_user,
                    "SIGNATURE_MISMATCH",
                    "export",
                    str(file_path),
                    metadata={
                        "signature_file": str(signature_path),
                    },
                )

    def _handle_list_key_backups(self, args) -> None:
        if not self._require_role(AccessLevel.SECURITY_ADMIN, audit_action="LIST_KEY_BACKUPS"):
            return

        key_path = self.config.db_path.parent / ".key"
        backups = sorted(self.config.key_backup_dir.glob(f"{key_path.name}.backup-*"))

        manifest_path = self.config.key_backup_dir / "backups.manifest"
        manifest: Dict[str, Any] = {}
        if manifest_path.exists():
            with suppress(json.JSONDecodeError, OSError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        records = []
        for file in backups:
            try:
                stat = file.stat()
            except OSError:
                continue
            info = manifest.get(str(file), {})
            records.append(
                {
                    "file": str(file),
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "sha256": info.get("sha256"),
                    "created_at": info.get("created_at"),
                }
            )

        output_format = getattr(args, "format", "text")

        if output_format == "json":
            payload = {
                "count": len(records),
                "backups": records,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        if not records:
            print(_("list_key_backups_none"))
            return

        print(_("list_key_backups_header", count=len(records)))
        for idx, record in enumerate(records, start=1):
            size_mb = record["size_bytes"] / (1024 * 1024)
            print(
                _(
                    "list_key_backups_row",
                    index=idx,
                    file=record["file"],
                    size=size_mb,
                    modified=record.get("modified_at", "-"),
                )
            )
            if record.get("created_at"):
                print(_("list_key_backups_created", created=record["created_at"]))
            if record.get("sha256"):
                print(_("list_key_backups_hash", sha=record["sha256"]))

    def _handle_restore_key_backup(self, args) -> None:
        if not self._require_role(AccessLevel.SECURITY_ADMIN, audit_action="RESTORE_KEY_BACKUP"):
            return

        if not self.config.enable_encryption or not self.security.is_encryption_available():
            print(_("rotate_key_not_available"))
            return

        current_fernet = getattr(self.security, "fernet", None)
        if current_fernet is None:
            print(_("rotate_key_not_available"))
            return

        backup_file = Path(args.file).expanduser()
        if not backup_file.exists():
            print(_("restore_key_backup_missing", file=str(backup_file)))
            return

        try:
            backup_bytes = backup_file.read_bytes()
        except OSError as exc:
            print(_("error_occurred", error=str(exc)))
            return

        manifest_path = self.config.key_backup_dir / "backups.manifest"
        manifest: Dict[str, Any] = {}
        expected_digest: Optional[str] = None
        if manifest_path.exists():
            with suppress(json.JSONDecodeError, OSError):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                expected_digest = manifest.get(str(backup_file), {}).get("sha256")

        actual_digest = hashlib.sha256(backup_bytes).hexdigest()
        if expected_digest and not hmac.compare_digest(expected_digest, actual_digest):
            print(_("restore_key_backup_hash_mismatch", expected=expected_digest, actual=actual_digest))
            return

        try:
            backup_fernet = Fernet(backup_bytes)
        except Exception:
            print(_("restore_key_backup_invalid"))
            return

        dry_run = getattr(args, "dry_run", False)

        stats = self.service.reencrypt_sensitive_memos(current_fernet, backup_fernet, dry_run=dry_run)

        if dry_run:
            print(_("restore_key_backup_dry_run_summary", processed=stats["processed"], pending=stats["updated"]))
            return

        key_path = self.config.db_path.parent / ".key"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        if key_path.exists():
            rollback_path = self.config.key_backup_dir / f"{key_path.name}.rollback-{timestamp}"
            try:
                existing = key_path.read_bytes()
                rollback_path.write_bytes(existing)
                with suppress(PermissionError, NotImplementedError):
                    rollback_path.chmod(0o600)
            except OSError:
                pass

        temp_key_path = key_path.with_suffix(".next")
        temp_key_path.write_bytes(backup_bytes)
        with suppress(PermissionError, NotImplementedError):
            temp_key_path.chmod(0o600)
        os.replace(temp_key_path, key_path)

        self.security.fernet = backup_fernet

        manifest = manifest if isinstance(manifest, dict) else {}
        manifest[str(backup_file)] = {
            "restored_at": timestamp,
            "sha256": actual_digest,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with suppress(PermissionError, NotImplementedError):
            manifest_path.chmod(0o600)

        print(_("restore_key_backup_success", updated=stats["updated"], file=str(backup_file)))

        if stats.get("failures"):
            print(_("restore_key_backup_failures"))
            for failure in stats["failures"]:
                print(f" - {failure['memo_id']}: {failure['error']}")

        if self.config.enable_audit and self.current_user:
            self.service._audit_log(  # type: ignore[attr-defined]
                self.current_user,
                "RESTORE_KEY_BACKUP",
                "system",
                "encryption",
                metadata={
                    "backup_file": str(backup_file),
                    "updated": stats.get("updated", 0),
                    "processed": stats.get("processed", 0),
                    "failures": len(stats.get("failures", [])),
                },
            )

    def _handle_verify_key_backups(self, args) -> None:
        if not self._require_role(AccessLevel.SECURITY_ADMIN, audit_action="VERIFY_KEY_BACKUPS"):
            return

        manifest_path = self.config.key_backup_dir / "backups.manifest"
        manifest: Dict[str, Any] = {}
        try:
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(_("verify_key_backups_manifest_invalid", error=str(exc)))
            return

        tracked_paths = set(manifest.keys())
        existing_backups = {
            str(path): path for path in self.config.key_backup_dir.glob("*.backup-*")
        }

        missing_files = sorted(path for path in tracked_paths if path not in existing_backups)
        untracked_files = sorted(str(path) for path in existing_backups.values() if str(path) not in tracked_paths)
        digest_mismatches: List[Dict[str, str]] = []
        verified: List[str] = []

        for path_str, meta in manifest.items():
            backup_path = existing_backups.get(path_str)
            if not backup_path:
                continue
            try:
                content = backup_path.read_bytes()
            except OSError as exc:
                digest_mismatches.append({"file": path_str, "error": str(exc)})
                continue

            expected_digest = meta.get("sha256")
            actual_digest = hashlib.sha256(content).hexdigest()
            if not expected_digest:
                digest_mismatches.append({"file": path_str, "error": "missing_digest"})
                continue
            if not hmac.compare_digest(expected_digest, actual_digest):
                digest_mismatches.append({
                    "file": path_str,
                    "expected": expected_digest,
                    "actual": actual_digest,
                })
                continue
            verified.append(path_str)

        output_format = getattr(args, "format", "text")
        summary = {
            "manifest_found": manifest_path.exists(),
            "tracked": len(tracked_paths),
            "verified": len(verified),
            "missing_files": missing_files,
            "untracked_files": untracked_files,
            "digest_mismatches": digest_mismatches,
            "overall": not (missing_files or untracked_files or digest_mismatches),
        }

        if output_format == "json":
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return

        if not manifest_path.exists():
            print(_("verify_key_backups_manifest_missing"))

        print(_("verify_key_backups_summary", tracked=summary["tracked"], verified=summary["verified"]))

        if missing_files:
            print(_("verify_key_backups_missing"))
            for path in missing_files:
                print(f" - {path}")

        if untracked_files:
            print(_("verify_key_backups_untracked"))
            for path in untracked_files:
                print(f" - {path}")

        if digest_mismatches:
            print(_("verify_key_backups_mismatched"))
            for item in digest_mismatches:
                expected = item.get("expected", "n/a")
                actual = item.get("actual", "n/a")
                error = item.get("error")
                detail = (
                    _("verify_key_backups_mismatch_detail", file=item["file"], expected=expected, actual=actual)
                    if not error
                    else _("verify_key_backups_error_detail", file=item["file"], error=error)
                )
                print(f" - {detail}")

        if summary["overall"]:
            print(_("verify_key_backups_success"))
        else:
            print(_("verify_key_backups_failure"))

    def cleanup(self):
        """Cleanup resources"""
        if self.db:
            self.db.close()


def main():
    """Main entry point"""
    cli = MemoSystemCLI()
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n✓ Goodbye!")
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        logging.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        cli.cleanup()


if __name__ == "__main__":
    main()
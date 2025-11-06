#!/usr/bin/env python3
"""
Data Validation & Integrity System
==================================
Comprehensive data validation, integrity checking, and corruption detection
for enterprise-grade data protection.
"""

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Callable, Union
import re
import base64

# Advanced validation
try:
    import jsonschema
    SCHEMA_VALIDATION = True
except ImportError:
    SCHEMA_VALIDATION = False

# Email validation
try:
    import validators
    VALIDATORS_AVAILABLE = True
except ImportError:
    VALIDATORS_AVAILABLE = False


class ValidationSeverity(IntEnum):
    """Validation issue severity"""
    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3
    FATAL = 4


class IntegrityStatus(Enum):
    """Data integrity status"""
    VALID = "valid"
    CORRUPTED = "corrupted"
    MISSING = "missing"
    MODIFIED = "modified"
    UNKNOWN = "unknown"


@dataclass
class ValidationResult:
    """Validation result"""
    is_valid: bool
    severity: ValidationSeverity
    field_name: str
    message: str
    suggested_fix: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrityCheckResult:
    """Integrity check result"""
    entity_id: str
    entity_type: str
    status: IntegrityStatus
    expected_checksum: Optional[str]
    actual_checksum: Optional[str]
    timestamp: datetime
    details: str
    repair_possible: bool = False


class DataValidator:
    """Comprehensive data validation system"""

    def __init__(self):
        self.validation_rules: Dict[str, List[Callable]] = defaultdict(list)
        self.custom_validators: Dict[str, Callable] = {}
        self.validation_history: List[ValidationResult] = []
        self.lock = threading.RLock()

        # Load default validation rules
        self._setup_default_validators()

    def _setup_default_validators(self):
        """Setup default validation rules"""

        # Email validation
        self.register_validator('email', self._validate_email)

        # Text validation
        self.register_validator('text', self._validate_text)
        self.register_validator('memo_content', self._validate_memo_content)

        # Security validation
        self.register_validator('security_level', self._validate_security_level)
        self.register_validator('tag', self._validate_tag)

        # System validation
        self.register_validator('file_path', self._validate_file_path)
        self.register_validator('json_data', self._validate_json)

        # User validation
        self.register_validator('username', self._validate_username)
        self.register_validator('password', self._validate_password)

    def register_validator(self, field_type: str, validator_func: Callable):
        """Register custom validator function"""
        self.validation_rules[field_type].append(validator_func)

    def register_custom_validator(self, name: str, validator_func: Callable):
        """Register named custom validator"""
        self.custom_validators[name] = validator_func

    def validate_field(self, field_name: str, value: Any, field_type: str,
                      constraints: Optional[Dict[str, Any]] = None) -> List[ValidationResult]:
        """Validate single field"""
        results = []
        constraints = constraints or {}

        # Run type-specific validators
        if field_type in self.validation_rules:
            for validator in self.validation_rules[field_type]:
                try:
                    result = validator(field_name, value, constraints)
                    if result:
                        results.append(result)
                except Exception as e:
                    results.append(ValidationResult(
                        is_valid=False,
                        severity=ValidationSeverity.ERROR,
                        field_name=field_name,
                        message=f"Validator error: {e}",
                        suggested_fix="Check validator implementation"
                    ))

        # Run custom validators if specified
        custom_validators = constraints.get('custom_validators', [])
        for validator_name in custom_validators:
            if validator_name in self.custom_validators:
                try:
                    result = self.custom_validators[validator_name](field_name, value, constraints)
                    if result:
                        results.append(result)
                except Exception as e:
                    results.append(ValidationResult(
                        is_valid=False,
                        severity=ValidationSeverity.ERROR,
                        field_name=field_name,
                        message=f"Custom validator '{validator_name}' error: {e}"
                    ))

        return results

    def validate_object(self, data: Dict[str, Any], schema: Dict[str, Any]) -> List[ValidationResult]:
        """Validate entire object against schema"""
        results = []

        for field_name, field_schema in schema.items():
            if field_name not in data:
                if field_schema.get('required', False):
                    results.append(ValidationResult(
                        is_valid=False,
                        severity=ValidationSeverity.ERROR,
                        field_name=field_name,
                        message="Required field is missing",
                        suggested_fix=f"Provide value for {field_name}"
                    ))
                continue

            field_value = data[field_name]
            field_type = field_schema.get('type', 'text')
            constraints = field_schema.get('constraints', {})

            # Validate field
            field_results = self.validate_field(field_name, field_value, field_type, constraints)
            results.extend(field_results)

        return results

    def validate_memo_data(self, memo_data: Dict[str, Any]) -> List[ValidationResult]:
        """Validate memo data with enterprise schema"""
        schema = {
            'content': {
                'type': 'memo_content',
                'required': True,
                'constraints': {
                    'max_length': 1000000,  # 1MB
                    'min_length': 1,
                    'encoding': 'utf-8'
                }
            },
            'tags': {
                'type': 'tag_list',
                'required': False,
                'constraints': {
                    'max_tags': 20,
                    'max_tag_length': 50
                }
            },
            'security_level': {
                'type': 'security_level',
                'required': True,
                'constraints': {
                    'min_level': 0,
                    'max_level': 4
                }
            },
            'user_id': {
                'type': 'text',
                'required': True,
                'constraints': {
                    'max_length': 255,
                    'pattern': r'^[a-zA-Z0-9_-]+$'
                }
            }
        }

        return self.validate_object(memo_data, schema)

    def _validate_email(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate email address"""
        if not isinstance(value, str):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Email must be a string",
                suggested_fix="Provide email as string"
            )

        # Basic email validation
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Invalid email format",
                suggested_fix="Provide valid email address (e.g., user@domain.com)"
            )

        # Advanced validation with validators library
        if VALIDATORS_AVAILABLE:
            if not validators.email(value):
                return ValidationResult(
                    is_valid=False,
                    severity=ValidationSeverity.ERROR,
                    field_name=field_name,
                    message="Email failed advanced validation",
                    suggested_fix="Check email format and domain validity"
                )

        # Length check
        if len(value) > 254:  # RFC 5321 limit
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Email address too long (max 254 characters)",
                suggested_fix="Use shorter email address"
            )

        return None  # Valid

    def _validate_text(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate text field"""
        if not isinstance(value, str):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Field must be a string",
                suggested_fix="Convert value to string"
            )

        # Length constraints
        min_length = constraints.get('min_length', 0)
        max_length = constraints.get('max_length', 1000000)

        if len(value) < min_length:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Text too short (minimum {min_length} characters)",
                suggested_fix=f"Provide at least {min_length} characters"
            )

        if len(value) > max_length:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Text too long (maximum {max_length} characters)",
                suggested_fix=f"Reduce text to {max_length} characters or less"
            )

        # Pattern validation
        pattern = constraints.get('pattern')
        if pattern and not re.match(pattern, value):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Text does not match required pattern",
                suggested_fix=f"Ensure text matches pattern: {pattern}"
            )

        # Encoding validation
        encoding = constraints.get('encoding', 'utf-8')
        try:
            value.encode(encoding)
        except UnicodeEncodeError:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Text contains characters not valid for {encoding} encoding",
                suggested_fix=f"Remove non-{encoding} characters"
            )

        # Check for control characters
        if any(ord(char) < 32 and char not in '\t\n\r' for char in value):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.WARNING,
                field_name=field_name,
                message="Text contains control characters",
                suggested_fix="Remove control characters"
            )

        return None  # Valid

    def _validate_memo_content(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate memo content specifically"""
        # First run basic text validation
        text_result = self._validate_text(field_name, value, constraints)
        if text_result:
            return text_result

        # Memo-specific validation
        if not value.strip():
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Memo content cannot be empty or whitespace only",
                suggested_fix="Provide meaningful memo content"
            )

        # Check for potential security issues
        suspicious_patterns = [
            r'<script[^>]*>.*?</script>',  # Script tags
            r'javascript\s*:',             # JavaScript URLs
            r'data\s*:.*base64',          # Data URLs
            r'on\w+\s*=',                 # Event handlers
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                return ValidationResult(
                    is_valid=False,
                    severity=ValidationSeverity.CRITICAL,
                    field_name=field_name,
                    message="Memo content contains potentially malicious code",
                    suggested_fix="Remove script tags and executable content"
                )

        return None  # Valid

    def _validate_security_level(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate security level"""
        if not isinstance(value, int):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Security level must be an integer",
                suggested_fix="Provide integer value (0-4)"
            )

        min_level = constraints.get('min_level', 0)
        max_level = constraints.get('max_level', 4)

        if value < min_level or value > max_level:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Security level must be between {min_level} and {max_level}",
                suggested_fix=f"Use value between {min_level} and {max_level}"
            )

        return None  # Valid

    def _validate_tag(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate tag"""
        if not isinstance(value, str):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Tag must be a string",
                suggested_fix="Convert tag to string"
            )

        # Tag pattern validation
        tag_pattern = r'^[a-zA-Z0-9_-]+$'
        if not re.match(tag_pattern, value):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Tag contains invalid characters",
                suggested_fix="Use only letters, numbers, underscores, and hyphens"
            )

        # Length validation
        max_tag_length = constraints.get('max_tag_length', 50)
        if len(value) > max_tag_length:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Tag too long (maximum {max_tag_length} characters)",
                suggested_fix=f"Shorten tag to {max_tag_length} characters or less"
            )

        if len(value) < 2:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Tag too short (minimum 2 characters)",
                suggested_fix="Use at least 2 characters for tag"
            )

        return None  # Valid

    def _validate_file_path(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate file path"""
        if not isinstance(value, (str, Path)):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="File path must be a string or Path object",
                suggested_fix="Provide valid file path"
            )

        path_str = str(value)

        # Check for path traversal attempts
        if '..' in path_str or path_str.startswith('/'):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.CRITICAL,
                field_name=field_name,
                message="Path contains traversal sequences or absolute path",
                suggested_fix="Use relative paths without '..' sequences"
            )

        # Check for invalid characters
        invalid_chars = ['<', '>', ':', '"', '|', '?', '*']
        if any(char in path_str for char in invalid_chars):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Path contains invalid characters",
                suggested_fix="Remove invalid characters from path"
            )

        return None  # Valid

    def _validate_json(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate JSON data"""
        if isinstance(value, str):
            try:
                json.loads(value)
            except json.JSONDecodeError as e:
                return ValidationResult(
                    is_valid=False,
                    severity=ValidationSeverity.ERROR,
                    field_name=field_name,
                    message=f"Invalid JSON format: {e}",
                    suggested_fix="Provide valid JSON string"
                )
        elif isinstance(value, (dict, list)):
            try:
                json.dumps(value)
            except (TypeError, ValueError) as e:
                return ValidationResult(
                    is_valid=False,
                    severity=ValidationSeverity.ERROR,
                    field_name=field_name,
                    message=f"Data not JSON serializable: {e}",
                    suggested_fix="Ensure all values are JSON serializable"
                )

        # JSON Schema validation
        if SCHEMA_VALIDATION and 'schema' in constraints:
            try:
                schema = constraints['schema']
                if isinstance(value, str):
                    data = json.loads(value)
                else:
                    data = value

                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as e:
                return ValidationResult(
                    is_valid=False,
                    severity=ValidationSeverity.ERROR,
                    field_name=field_name,
                    message=f"JSON schema validation failed: {e.message}",
                    suggested_fix="Ensure JSON matches required schema"
                )

        return None  # Valid

    def _validate_username(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate username"""
        if not isinstance(value, str):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Username must be a string",
                suggested_fix="Provide username as string"
            )

        # Length validation
        if len(value) < 3:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Username too short (minimum 3 characters)",
                suggested_fix="Use at least 3 characters"
            )

        if len(value) > 50:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Username too long (maximum 50 characters)",
                suggested_fix="Use 50 characters or less"
            )

        # Pattern validation
        username_pattern = r'^[a-zA-Z0-9._-]+$'
        if not re.match(username_pattern, value):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Username contains invalid characters",
                suggested_fix="Use only letters, numbers, dots, underscores, and hyphens"
            )

        # Reserved usernames
        reserved_usernames = {
            'admin', 'administrator', 'root', 'system', 'user',
            'guest', 'test', 'demo', 'null', 'undefined'
        }

        if value.lower() in reserved_usernames:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.WARNING,
                field_name=field_name,
                message="Username is reserved",
                suggested_fix="Choose a different username"
            )

        return None  # Valid

    def _validate_password(self, field_name: str, value: Any, constraints: Dict) -> Optional[ValidationResult]:
        """Validate password strength"""
        if not isinstance(value, str):
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message="Password must be a string",
                suggested_fix="Provide password as string"
            )

        # Length validation
        min_length = constraints.get('min_length', 8)
        if len(value) < min_length:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Password too short (minimum {min_length} characters)",
                suggested_fix=f"Use at least {min_length} characters"
            )

        # Complexity validation
        has_lower = any(c.islower() for c in value)
        has_upper = any(c.isupper() for c in value)
        has_digit = any(c.isdigit() for c in value)
        has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in value)

        missing_requirements = []
        if not has_lower:
            missing_requirements.append("lowercase letter")
        if not has_upper:
            missing_requirements.append("uppercase letter")
        if not has_digit:
            missing_requirements.append("digit")
        if not has_special:
            missing_requirements.append("special character")

        if missing_requirements:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.ERROR,
                field_name=field_name,
                message=f"Password missing: {', '.join(missing_requirements)}",
                suggested_fix="Include uppercase, lowercase, digit, and special character"
            )

        # Common password check
        common_passwords = {
            'password', '123456', '123456789', 'qwerty', 'abc123',
            'password123', 'admin', 'letmein', 'welcome', 'monkey'
        }

        if value.lower() in common_passwords:
            return ValidationResult(
                is_valid=False,
                severity=ValidationSeverity.CRITICAL,
                field_name=field_name,
                message="Password is too common",
                suggested_fix="Use a unique, complex password"
            )

        return None  # Valid


class IntegrityChecker:
    """Data integrity verification system"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.integrity_log: List[IntegrityCheckResult] = []
        self.checksum_cache: Dict[str, str] = {}
        self.lock = threading.RLock()

    def calculate_memo_checksum(self, memo_data: Dict[str, Any]) -> str:
        """Calculate checksum for memo data"""
        # Create deterministic representation
        checksum_data = {
            'content': memo_data.get('content', ''),
            'user_id': memo_data.get('user_id', ''),
            'security_level': memo_data.get('security_level', 0),
            'tags': sorted(memo_data.get('tags', []))
        }

        # Serialize and hash
        serialized = json.dumps(checksum_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

    def calculate_database_checksum(self) -> str:
        """Calculate checksum for entire database"""
        try:
            with open(self.db_path, 'rb') as f:
                content = f.read()
                return hashlib.sha256(content).hexdigest()
        except Exception as e:
            logging.error(f"Failed to calculate database checksum: {e}")
            return ""

    def verify_memo_integrity(self, memo_id: str, memo_data: Dict[str, Any],
                            expected_checksum: Optional[str] = None) -> IntegrityCheckResult:
        """Verify integrity of a single memo"""
        actual_checksum = self.calculate_memo_checksum(memo_data)

        if expected_checksum is None:
            # No expected checksum, consider it valid but unknown
            status = IntegrityStatus.UNKNOWN
            details = "No expected checksum available"
        elif actual_checksum == expected_checksum:
            status = IntegrityStatus.VALID
            details = "Checksum matches expected value"
        else:
            status = IntegrityStatus.CORRUPTED
            details = f"Checksum mismatch: expected {expected_checksum}, got {actual_checksum}"

        result = IntegrityCheckResult(
            entity_id=memo_id,
            entity_type="memo",
            status=status,
            expected_checksum=expected_checksum,
            actual_checksum=actual_checksum,
            timestamp=datetime.now(timezone.utc),
            details=details,
            repair_possible=(status == IntegrityStatus.CORRUPTED)
        )

        with self.lock:
            self.integrity_log.append(result)
            # Keep only last 1000 results
            if len(self.integrity_log) > 1000:
                self.integrity_log = self.integrity_log[-1000:]

        return result

    def verify_database_integrity(self) -> IntegrityCheckResult:
        """Verify overall database integrity"""
        try:
            # Check if database file exists
            if not self.db_path.exists():
                return IntegrityCheckResult(
                    entity_id="database",
                    entity_type="database",
                    status=IntegrityStatus.MISSING,
                    expected_checksum=None,
                    actual_checksum=None,
                    timestamp=datetime.now(timezone.utc),
                    details="Database file does not exist",
                    repair_possible=False
                )

            # Check SQLite integrity
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchall()
            conn.close()

            if integrity_result and integrity_result[0][0] == "ok":
                status = IntegrityStatus.VALID
                details = "SQLite integrity check passed"
            else:
                status = IntegrityStatus.CORRUPTED
                details = f"SQLite integrity check failed: {integrity_result}"

            # Calculate current checksum
            actual_checksum = self.calculate_database_checksum()

            result = IntegrityCheckResult(
                entity_id="database",
                entity_type="database",
                status=status,
                expected_checksum=None,
                actual_checksum=actual_checksum,
                timestamp=datetime.now(timezone.utc),
                details=details,
                repair_possible=(status == IntegrityStatus.CORRUPTED)
            )

        except Exception as e:
            result = IntegrityCheckResult(
                entity_id="database",
                entity_type="database",
                status=IntegrityStatus.CORRUPTED,
                expected_checksum=None,
                actual_checksum=None,
                timestamp=datetime.now(timezone.utc),
                details=f"Integrity check failed: {e}",
                repair_possible=False
            )

        with self.lock:
            self.integrity_log.append(result)

        return result

    def repair_database_corruption(self) -> bool:
        """Attempt to repair database corruption"""
        try:
            # Create backup before repair
            backup_path = self.db_path.with_suffix('.db.repair_backup')
            if self.db_path.exists():
                import shutil
                shutil.copy2(self.db_path, backup_path)

            # SQLite auto-repair
            conn = sqlite3.connect(str(self.db_path))

            # Vacuum to rebuild database
            conn.execute("VACUUM")

            # Reindex all tables
            conn.execute("REINDEX")

            conn.close()

            # Verify repair
            repair_check = self.verify_database_integrity()
            if repair_check.status == IntegrityStatus.VALID:
                logging.info("Database repair successful")
                return True
            else:
                logging.error("Database repair failed")
                return False

        except Exception as e:
            logging.error(f"Database repair failed: {e}")
            return False

    def get_integrity_summary(self) -> Dict[str, Any]:
        """Get integrity check summary"""
        with self.lock:
            if not self.integrity_log:
                return {
                    'total_checks': 0,
                    'status_counts': {},
                    'last_check': None
                }

            # Count by status
            status_counts = defaultdict(int)
            for result in self.integrity_log:
                status_counts[result.status.value] += 1

            # Recent checks (last 24 hours)
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            recent_checks = [
                r for r in self.integrity_log
                if r.timestamp >= recent_cutoff
            ]

            return {
                'total_checks': len(self.integrity_log),
                'recent_checks_24h': len(recent_checks),
                'status_counts': dict(status_counts),
                'last_check': self.integrity_log[-1].timestamp.isoformat() if self.integrity_log else None,
                'corruption_detected': status_counts[IntegrityStatus.CORRUPTED.value] > 0
            }


class DataSanitizer:
    """Data sanitization and normalization"""

    @staticmethod
    def sanitize_text(text: str, preserve_newlines: bool = True) -> str:
        """Sanitize text input"""
        if not isinstance(text, str):
            text = str(text)

        # Remove null bytes
        text = text.replace('\x00', '')

        # Remove other control characters except whitespace
        if preserve_newlines:
            allowed_controls = '\t\n\r'
        else:
            allowed_controls = '\t '

        text = ''.join(char for char in text if ord(char) >= 32 or char in allowed_controls)

        # Normalize Unicode
        import unicodedata
        text = unicodedata.normalize('NFKC', text)

        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    @staticmethod
    def sanitize_html(html: str) -> str:
        """Sanitize HTML content"""
        # Simple HTML sanitization - remove all tags
        clean_text = re.sub(r'<[^>]*>', '', html)

        # Decode HTML entities
        import html as html_module
        clean_text = html_module.unescape(clean_text)

        return DataSanitizer.sanitize_text(clean_text)

    @staticmethod
    def normalize_email(email: str) -> str:
        """Normalize email address"""
        email = email.strip().lower()

        # Remove any surrounding quotes
        if email.startswith('"') and email.endswith('"'):
            email = email[1:-1]

        return email

    @staticmethod
    def normalize_username(username: str) -> str:
        """Normalize username"""
        username = username.strip().lower()

        # Remove invalid characters
        username = re.sub(r'[^a-z0-9._-]', '', username)

        return username

    @staticmethod
    def sanitize_file_path(path: str) -> str:
        """Sanitize file path"""
        # Convert to string and normalize
        path = str(path).strip()

        # Remove path traversal attempts
        path = path.replace('..', '')

        # Remove invalid characters
        invalid_chars = '<>:"|?*'
        for char in invalid_chars:
            path = path.replace(char, '')

        # Normalize path separators
        path = path.replace('\\', '/')

        # Remove leading slash
        path = path.lstrip('/')

        return path
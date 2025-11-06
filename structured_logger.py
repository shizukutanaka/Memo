#!/usr/bin/env python3
"""Structured logging with JSON output and correlation IDs."""

import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
from logging.handlers import RotatingFileHandler
import threading


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, include_traceback: bool = True):
        super().__init__()
        self.include_traceback = include_traceback

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        if hasattr(record, 'correlation_id'):
            log_data["correlation_id"] = record.correlation_id

        if hasattr(record, 'user_id'):
            log_data["user_id"] = record.user_id

        if hasattr(record, 'operation'):
            log_data["operation"] = record.operation

        if hasattr(record, 'duration_ms'):
            log_data["duration_ms"] = record.duration_ms

        if record.exc_info and self.include_traceback:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }

        if hasattr(record, 'extra_data') and record.extra_data:
            log_data["data"] = record.extra_data

        return json.dumps(log_data, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter for console output."""

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )


class CorrelationFilter(logging.Filter):
    """Add correlation ID to log records."""

    def __init__(self):
        super().__init__()
        self._local = threading.local()

    def set_correlation_id(self, correlation_id: str):
        """Set correlation ID for current thread."""
        self._local.correlation_id = correlation_id

    def get_correlation_id(self) -> Optional[str]:
        """Get correlation ID for current thread."""
        return getattr(self._local, 'correlation_id', None)

    def clear_correlation_id(self):
        """Clear correlation ID for current thread."""
        if hasattr(self._local, 'correlation_id'):
            delattr(self._local, 'correlation_id')

    def filter(self, record: logging.LogRecord) -> bool:
        """Add correlation ID to record."""
        record.correlation_id = self.get_correlation_id() or 'no-correlation-id'
        return True


class StructuredLogger:
    """Structured logger with correlation ID support."""

    def __init__(
        self,
        name: str,
        log_file: Optional[Path] = None,
        log_level: str = "INFO",
        max_bytes: int = 5 * 1024 * 1024,
        backup_count: int = 5,
        console_output: bool = True
    ):
        """
        Initialize structured logger.

        Args:
            name: Logger name
            log_file: Optional log file path
            log_level: Logging level
            max_bytes: Maximum log file size
            backup_count: Number of backup files to keep
            console_output: Whether to output to console
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        self.logger.handlers.clear()

        self.correlation_filter = CorrelationFilter()
        self.logger.addFilter(self.correlation_filter)

        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setFormatter(StructuredFormatter())
            self.logger.addHandler(file_handler)

        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(HumanReadableFormatter())
            self.logger.addHandler(console_handler)

    def set_correlation_id(self, correlation_id: str):
        """Set correlation ID for current thread."""
        self.correlation_filter.set_correlation_id(correlation_id)

    def get_correlation_id(self) -> Optional[str]:
        """Get correlation ID for current thread."""
        return self.correlation_filter.get_correlation_id()

    def clear_correlation_id(self):
        """Clear correlation ID for current thread."""
        self.correlation_filter.clear_correlation_id()

    def _log_with_extra(
        self,
        level: int,
        message: str,
        extra_data: Optional[Dict[str, Any]] = None,
        **kwargs
    ):
        """Log with extra data."""
        extra = kwargs.get('extra', {})
        if extra_data:
            extra['extra_data'] = extra_data
        kwargs['extra'] = extra
        self.logger.log(level, message, **kwargs)

    def debug(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log debug message."""
        self._log_with_extra(logging.DEBUG, message, data, **kwargs)

    def info(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log info message."""
        self._log_with_extra(logging.INFO, message, data, **kwargs)

    def warning(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log warning message."""
        self._log_with_extra(logging.WARNING, message, data, **kwargs)

    def error(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log error message."""
        self._log_with_extra(logging.ERROR, message, data, **kwargs)

    def critical(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log critical message."""
        self._log_with_extra(logging.CRITICAL, message, data, **kwargs)

    def log_operation(
        self,
        operation: str,
        duration_ms: float,
        success: bool = True,
        data: Optional[Dict[str, Any]] = None
    ):
        """Log an operation with timing information."""
        extra = {
            'operation': operation,
            'duration_ms': duration_ms,
            'success': success
        }
        if data:
            extra['extra_data'] = data

        level = logging.INFO if success else logging.ERROR
        message = f"Operation '{operation}' {'completed' if success else 'failed'} in {duration_ms:.2f}ms"
        self.logger.log(level, message, extra=extra)


class OperationTimer:
    """Context manager for timing operations."""

    def __init__(self, logger: StructuredLogger, operation: str, log_args: bool = False):
        """
        Initialize operation timer.

        Args:
            logger: Structured logger instance
            operation: Operation name
            log_args: Whether to log operation arguments
        """
        self.logger = logger
        self.operation = operation
        self.log_args = log_args
        self.start_time = 0
        self.data = {}

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        success = exc_type is None

        self.logger.log_operation(
            self.operation,
            duration_ms,
            success=success,
            data=self.data if self.data else None
        )

        return False

    def add_data(self, key: str, value: Any):
        """Add data to be logged with operation."""
        self.data[key] = value


if __name__ == "__main__":
    import uuid

    log_dir = Path.home() / ".memo" / "logs"
    logger = StructuredLogger(
        "memo_app",
        log_file=log_dir / "structured_test.log",
        log_level="DEBUG"
    )

    correlation_id = str(uuid.uuid4())
    logger.set_correlation_id(correlation_id)

    logger.info("Application started", data={"version": "1.0.0"})
    logger.debug("Debug information", data={"user": "test_user"})

    with OperationTimer(logger, "database_query") as timer:
        time.sleep(0.1)
        timer.add_data("rows", 42)
        timer.add_data("query", "SELECT * FROM memos")

    try:
        raise ValueError("Test error")
    except Exception:
        logger.error("An error occurred", data={"context": "test"}, exc_info=True)

    logger.clear_correlation_id()
    logger.info("Done")

"""Pytest configuration and fixtures for the test suite."""

import pytest
import tempfile
import shutil
from pathlib import Path
import os


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    temp_path = tempfile.mkdtemp()
    yield Path(temp_path)
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def test_db_path(temp_dir):
    """Provide a temporary database path for testing."""
    return temp_dir / "test_memos.db"


@pytest.fixture
def mock_home(temp_dir, monkeypatch):
    """Mock the home directory for testing."""
    memo_dir = temp_dir / ".memo"
    memo_dir.mkdir(parents=True, exist_ok=True)

    # Mock Path.home() to return our temp directory
    monkeypatch.setattr(Path, "home", lambda: temp_dir)

    return memo_dir


@pytest.fixture
def clean_environment(monkeypatch):
    """Provide a clean environment without user-specific settings."""
    # Clear memo-related environment variables
    env_vars = [
        "MEMO_CACHE_SIZE_MB",
        "MEMO_CACHE_TTL_SEC",
        "MEMO_MIN_PASSWORD_LENGTH",
        "MEMO_SESSION_TIMEOUT",
        "MEMO_BACKUP_ENCRYPTION",
        "MEMO_ENABLE_AUDIT_LOG",
        "MEMO_ENABLE_TWO_FACTOR_AUTH",
        "MEMO_ENABLE_IP_FILTERING",
        "MEMO_ALLOWED_IP_RANGES",
    ]

    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    return monkeypatch


@pytest.fixture
def sample_memo_data():
    """Provide sample memo data for testing."""
    return {
        "content": "Test memo content",
        "category": "test",
        "tags": ["testing", "sample"],
        "priority": 2,
        "status": "active"
    }


@pytest.fixture
def multiple_memos():
    """Provide multiple sample memos for testing."""
    return [
        {
            "content": "First test memo",
            "category": "work",
            "tags": ["project", "urgent"],
            "priority": 3
        },
        {
            "content": "Second test memo",
            "category": "personal",
            "tags": ["todo"],
            "priority": 1
        },
        {
            "content": "Third test memo about testing",
            "category": "development",
            "tags": ["testing", "quality"],
            "priority": 2
        }
    ]

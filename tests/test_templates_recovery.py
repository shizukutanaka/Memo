"""Regression tests for template file initialization and corruption recovery."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from memo import MemoStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    """MemoStore with its templates file repointed to an isolated temp path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    memo_store = MemoStore(data_file=tmp_path / "memos.db")
    memo_store.templates_file = tmp_path / "templates.json"
    return memo_store


def test_missing_templates_file_is_initialized_with_defaults(store):
    assert not store.templates_file.exists()

    templates = store.get_templates()

    assert "meeting" in templates
    assert store.templates_file.exists()


def test_empty_templates_file_recovers_defaults(store):
    store.templates_file.write_bytes(b"")

    templates = store.get_templates()

    assert "meeting" in templates
    assert not list(store.templates_file.parent.glob("templates.json.corrupt-*"))


def test_corrupt_templates_file_is_quarantined_and_defaults_restored(store):
    corrupt_content = b'{"meeting": invalid json'
    store.templates_file.write_bytes(corrupt_content)

    templates = store.get_templates()

    assert "meeting" in templates
    quarantine_files = list(store.templates_file.parent.glob("templates.json.corrupt-*"))
    assert len(quarantine_files) == 1
    assert quarantine_files[0].read_bytes() == corrupt_content


def test_add_template_succeeds_after_corruption_recovery(store):
    store.templates_file.write_bytes(b"not valid json")
    store.get_templates()

    assert store.add_template(
        "standup",
        "Standup Notes",
        "# Standup: {date}",
        category="meetings",
        tags=["standup"],
    )

    templates = store.get_templates()
    assert templates["standup"]["name"] == "Standup Notes"
    assert templates["standup"]["template"] == "# Standup: {date}"
    assert "meeting" in templates


def test_valid_templates_file_is_loaded_as_is(store):
    custom_templates = {
        "custom": {
            "name": "Custom Template",
            "template": "# Custom {title}",
            "category": "custom",
            "tags": ["custom"],
        }
    }
    store.templates_file.write_text(json.dumps(custom_templates), encoding="utf-8")

    assert store.get_templates() == custom_templates

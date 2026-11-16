"""Contract tests for the public library API (``memo_api``).

These tests pin the surface documented in ``docs/API.md``. If a change
removes or renames a public name, a public ``MemoStore`` method, or a
parameter of a key function, these tests fail on purpose: updating the
public API means updating this contract deliberately, in the same
change, together with ``docs/API.md``.
"""

import inspect
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import memo
import memo_api
import memo_errors

# The exact set of names memo_api promises to export.
EXPECTED_ALL = {
    "__version__",
    "MemoStore",
    "VALID_STATUSES",
    "export_memos",
    "import_memos",
    "generate_stats_report",
    "analyze_trends",
    "analyze_habits",
    "analyze_network",
    "analyze_productivity",
    "parse_tags",
    "parse_tags_and_links",
    "MemoError",
    "ValidationError",
    "MemoValidationError",
    "SecurityError",
    "StorageError",
    "NotFoundError",
    "DuplicateError",
    "RateLimitError",
}

# The exact set of public MemoStore methods covered by the API promise.
EXPECTED_STORE_METHODS = {
    "add",
    "add_batch",
    "add_link",
    "add_template",
    "archive_memo",
    "complete_memo",
    "create_backup",
    "create_from_template",
    "delete",
    "delete_template",
    "duplicate_memo",
    "edit",
    "get_backlinks",
    "get_by_id",
    "get_due_reminders",
    "get_linked_memos",
    "get_templates",
    "list_all",
    "list_backups",
    "list_categories",
    "list_reminders",
    "merge_memos",
    "remove_link",
    "resolve_id",
    "restore_backup",
    "search",
    "search_by_tag",
    "split_memo",
    "unarchive_memo",
    "update_reminder",
    "update_status",
    "update_status_bulk",
    "update_tags_bulk",
}

# Parameter names are part of the contract (callers may use keywords).
EXPECTED_SIGNATURES = {
    "MemoStore.add": ["self", "text", "tags", "category", "linked_memos", "status"],
    "MemoStore.list_all": [
        "self", "limit", "from_date", "to_date", "category", "statuses", "tags",
    ],
    "MemoStore.search": [
        "self", "query", "regex", "from_date", "to_date", "statuses",
        "tags", "case_sensitive", "whole_word", "fuzzy",
    ],
    "MemoStore.edit": [
        "self", "memo_id", "new_text", "new_tags", "new_category",
        "new_links", "new_status",
    ],
    "MemoStore.get_by_id": ["self", "memo_id"],
    "MemoStore.delete": ["self", "memo_id"],
    "export_memos": ["memos", "format_type"],
    "import_memos": [
        "store", "file_path", "format_type", "default_category",
        "default_status", "extra_tags",
    ],
    "generate_stats_report": ["store", "days"],
}

# Keys every memo record returned by the API must carry, whichever
# method produced it. (Read methods additionally include "checksum";
# add() does not, so it is not part of the guaranteed core.)
CORE_MEMO_KEYS = {
    "id",
    "content",
    "category",
    "tags",
    "status",
    "priority",
    "created_at",
    "updated_at",
}


def _params(func):
    return list(inspect.signature(func).parameters)


class TestSurface:
    def test_all_matches_contract(self):
        assert set(memo_api.__all__) == EXPECTED_ALL

    def test_every_export_exists(self):
        for name in EXPECTED_ALL:
            assert hasattr(memo_api, name), name

    def test_reexports_are_the_original_objects(self):
        assert memo_api.MemoStore is memo.MemoStore
        assert memo_api.export_memos is memo.export_memos
        assert memo_api.import_memos is memo.import_memos
        assert memo_api.generate_stats_report is memo.generate_stats_report
        assert memo_api.MemoValidationError is memo.MemoValidationError
        assert memo_api.VALID_STATUSES is memo.VALID_STATUSES
        for name in (
            "MemoError",
            "ValidationError",
            "SecurityError",
            "StorageError",
            "NotFoundError",
            "DuplicateError",
            "RateLimitError",
        ):
            assert getattr(memo_api, name) is getattr(memo_errors, name), name

    def test_version_is_semver_shaped(self):
        assert re.fullmatch(r"\d+\.\d+\.\d+", memo_api.__version__)

    def test_valid_statuses_values_kept(self):
        assert {"active", "completed", "archived"} <= set(memo_api.VALID_STATUSES)

    def test_error_hierarchy(self):
        assert issubclass(memo_api.MemoError, Exception)
        for cls in (
            memo_api.ValidationError,
            memo_api.SecurityError,
            memo_api.StorageError,
            memo_api.NotFoundError,
            memo_api.DuplicateError,
            memo_api.RateLimitError,
        ):
            assert issubclass(cls, memo_api.MemoError), cls
        assert issubclass(memo_api.MemoValidationError, ValueError)

    def test_store_public_methods_match_contract(self):
        actual = {
            name
            for name, member in inspect.getmembers(
                memo_api.MemoStore, inspect.isfunction
            )
            if not name.startswith("_")
        }
        assert actual == EXPECTED_STORE_METHODS

    @pytest.mark.parametrize("target", sorted(EXPECTED_SIGNATURES))
    def test_signatures(self, target):
        if target.startswith("MemoStore."):
            func = getattr(memo_api.MemoStore, target.split(".", 1)[1])
        else:
            func = getattr(memo_api, target)
        assert _params(func) == EXPECTED_SIGNATURES[target]


@pytest.fixture
def api_store(test_db_path, mock_home):
    return memo_api.MemoStore(data_file=test_db_path)


class TestBehaviour:
    def test_add_get_search_round_trip(self, api_store):
        memo = api_store.add(
            "Release notes for the public API", tags=["work"], category="work"
        )
        assert CORE_MEMO_KEYS <= set(memo)
        assert memo["content"] == "Release notes for the public API"
        assert memo["tags"] == ["work"]
        assert memo["status"] in memo_api.VALID_STATUSES

        fetched = api_store.get_by_id(memo["id"])
        assert fetched is not None
        assert CORE_MEMO_KEYS <= set(fetched)
        assert fetched["id"] == memo["id"]

        hits = api_store.search("public API")
        assert any(h["id"] == memo["id"] for h in hits)

        listed = api_store.list_all(limit=10)
        assert any(m["id"] == memo["id"] for m in listed)

    def test_add_empty_content_raises_validation_error(self, api_store):
        with pytest.raises(memo_api.ValidationError):
            api_store.add("")

    def test_export_import_round_trip(self, api_store, test_db_path):
        api_store.add("First exported memo", tags=["a"])
        api_store.add("Second exported memo", tags=["b"])

        text = memo_api.export_memos(api_store.list_all(limit=0), "json")
        payload = json.loads(text)
        assert len(payload) == 2

        export_file = test_db_path.parent / "export.json"
        export_file.write_text(text, encoding="utf-8")

        other = memo_api.MemoStore(data_file=test_db_path.parent / "other.db")
        count = memo_api.import_memos(other, str(export_file), "json")
        assert count == 2
        assert len(other.list_all(limit=0)) == 2

    def test_export_formats_exist(self, api_store):
        api_store.add("Format probe memo")
        memos = api_store.list_all(limit=0)
        for fmt in ("json", "csv", "md", "markdown", "html", "txt"):
            assert memo_api.export_memos(memos, fmt), fmt

    def test_stats_report_shape(self, api_store):
        api_store.add("Stats probe memo")
        stats = memo_api.generate_stats_report(api_store, 7)
        for key in (
            "generated",
            "period_days",
            "total_memos",
            "recent_memos",
            "avg_per_day",
            "categories",
            "tags",
            "statuses",
            "activity_by_hour",
            "activity_by_day",
        ):
            assert key in stats, key
        assert stats["total_memos"] == 1
        assert stats["period_days"] == 7

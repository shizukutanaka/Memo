# Memo Library API

Memo can be used as a Python library, not only as a CLI. This document
defines the **public API**: the names other programs may rely on, and
the compatibility promise that covers them. The surface described here
is pinned by `tests/test_public_api.py`; removing or renaming any part
of it fails that test suite.

> Note: `api_documentation.yaml` in the repository root describes a
> planned HTTP API. No HTTP server is implemented; the supported API is
> the Python import API defined here.

## Importing

Import from `memo_api` — that module is the whole public surface:

```python
from memo_api import MemoStore, export_memos, import_memos, ValidationError

store = MemoStore()                       # default: ~/.memo/memos.db
store = MemoStore(data_file=some_path)    # explicit SQLite file

memo = store.add("Release notes", tags=["work"], category="work")
hits = store.search("release")            # FTS5 search, BM25 ranked
text = export_memos(store.list_all(), "json")
```

`memo_api.__version__` reports the installed `memo-app` distribution
version (the version in `pyproject.toml` is the source of truth).

The library uses only the Python standard library, makes no network
calls, and stores data only in the SQLite file given to `MemoStore`.

## The public surface

### `MemoStore` (in `memo_api`, implemented in `memo`)

Constructor: `MemoStore(data_file: Optional[Path] = None)`.

All public methods below are part of the API. Methods whose names
start with an underscore are internal.

| Area | Methods |
| --- | --- |
| Create / read / update / delete | `add(text, tags=None, category=None, linked_memos=None, status=None)`, `get_by_id(memo_id)`, `resolve_id(partial_id)`, `edit(memo_id, new_text, new_tags=None, new_category=None, new_links=None, new_status=None)`, `delete(memo_id)`, `add_batch(memos, optimize_after=True)` |
| Listing / search | `list_all(limit=50, from_date=None, to_date=None, category=None, statuses=None, tags=None)`, `search(query, regex=False, from_date=None, to_date=None, statuses=None, tags=None, case_sensitive=False, whole_word=False, fuzzy=False)`, `search_by_tag(tag, statuses=None)`, `list_categories()` |
| Status | `update_status(memo_id, new_status)`, `update_status_bulk(memo_ids, new_status)`, `archive_memo(memo_id)`, `unarchive_memo(memo_id)`, `complete_memo(memo_id)`, `update_tags_bulk(memo_ids, add_tags=None, remove_tags=None)` |
| Combine | `duplicate_memo(memo_id, new_text=None)`, `merge_memos(memo_ids, separator="\n\n---\n\n")`, `split_memo(memo_id, delimiter="\n\n")` |
| Links | `get_linked_memos(memo_id)`, `get_backlinks(memo_id)`, `add_link(source_id, target_id)`, `remove_link(source_id, target_id)` |
| Templates | `get_templates()`, `create_from_template(template_key, variables)`, `add_template(key, name, template_text, category="default", tags=None)`, `delete_template(key)` |
| Reminders | `get_due_reminders(before=None, statuses=None)`, `list_reminders(from_time=None, to_time=None, statuses=None)`, `update_reminder(memo_id, reminder)` |
| Backup | `create_backup(label=None)`, `restore_backup(backup_path)`, `list_backups()` |

### Module-level functions (in `memo_api`)

| Function | Purpose |
| --- | --- |
| `export_memos(memos, format_type) -> str` | Render memo dicts as `json`, `csv`, `md`/`markdown`, `html`, or `txt`. An unknown format returns `""`. |
| `import_memos(store, file_path, format_type, default_category=None, default_status=None, extra_tags=None) -> int` | Import a `json` or `csv` file into a store; returns the number of memos imported. |
| `generate_stats_report(store, days) -> dict` | Aggregate counts with keys `generated`, `period_days`, `total_memos`, `recent_memos`, `avg_per_day`, `categories`, `tags`, `statuses`, `activity_by_hour`, `activity_by_day`. |
| `analyze_trends(store, days)`, `analyze_habits(store, days)`, `analyze_productivity(store, days)`, `analyze_network(store)` | Analysis helpers over a store. |
| `parse_tags(text)`, `parse_tags_and_links(text)` | Split inline `#tags` (and `[[links]]`) out of memo text. |

### Memo records

Methods that return memos return plain `dict`s. These keys are part of
the API and are always present:

| Key | Type | Notes |
| --- | --- | --- |
| `id` | str | Opaque unique identifier. Treat it as a string; do not parse it. |
| `content` | str | Memo text. |
| `category` | str | |
| `tags` | list[str] | |
| `status` | str | One of `VALID_STATUSES`. |
| `priority` | int | |
| `created_at`, `updated_at` | str | ISO 8601 timestamps (UTC). |

Records returned by the read methods (`get_by_id`, `list_all`,
`search`, …) additionally carry `checksum` (the SHA-256 hex digest of
the content); the dict returned by `add()` does not. Records may also
carry the compatibility aliases `text` (= `content`), `created` /
`timestamp` (= `created_at`), and `edited` (= `updated_at`), plus
optional fields such as `links` and `reminder`. New keys may be added
in minor releases; code should not require that a record has *only*
the keys above.

### Constants and errors

- `VALID_STATUSES` — the set `{"active", "completed", "archived"}`.
- Errors (all importable from `memo_api`):
  - `MemoError` — base class for library errors.
  - `ValidationError(MemoError)` — invalid input, e.g. `store.add("")`.
  - `SecurityError`, `StorageError`, `NotFoundError`, `DuplicateError`,
    `RateLimitError` — all subclass `MemoError`.
  - `MemoValidationError(ValueError)` — validation error type defined
    by the storage module itself.

## Compatibility policy

Memo follows semantic versioning (`MAJOR.MINOR.PATCH`, currently
1.1.0).

**Within a major version (all 1.x releases), the following will not
change incompatibly:**

- The names exported by `memo_api` (`memo_api.__all__`), including the
  `MemoStore` public methods listed above.
- Their signatures, including parameter names (callers may use keyword
  arguments).
- The memo record keys listed as part of the API, and the meaning of
  their values.
- The error hierarchy: a public error class will not change its base
  classes.
- The existing values of `VALID_STATUSES` (they will not be removed or
  renamed) and the accepted export/import format names.
- Existing databases: a database file written by any 1.x release can
  be opened by any later 1.x release without losing memos.

**Not covered by the promise** (may change in any release):

- Anything not re-exported by `memo_api`: the other top-level modules
  (`memo_core`, `memo_system`, `memo_search`, `memo_models`,
  `memo_utils`, `backup`, `cloud_sync`, …), CLI presentation helpers in
  `memo` (`format_memo`, `show_statistics`, `get_color_code`, `main`),
  `FileLock`, and every name starting with an underscore.
- The internal SQLite schema beyond the readability guarantee above.
- CLI output formatting (the CLI's commands and options are stable as
  a user interface, but exact text output is not an API).
- Behaviour that is documented as undefined, such as the return value
  of `export_memos` for an unknown format (currently `""`).

**Deprecation:** a public name will be marked deprecated in a minor
release (in its docstring and in the release notes) before it is
removed, and removal happens no earlier than the next major version.

**Adding** new names, methods, record keys, statuses, or formats is
not a breaking change and may happen in minor releases.

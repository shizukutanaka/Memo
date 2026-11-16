"""Public library API for Memo.

This module is the *only* supported import surface for using Memo as a
library from other Python programs::

    from memo_api import MemoStore, export_memos, ValidationError

    store = MemoStore()                      # ~/.memo/memos.db
    memo = store.add("Release notes", tags=["work"])
    hits = store.search("release")           # FTS5 full-text search
    text = export_memos(store.list_all(), "json")

Everything re-exported here is covered by the compatibility policy in
``docs/API.md``: within a major version these names, their signatures,
the memo record shape, and the error hierarchy will not change in a
backwards-incompatible way. Everything else in this repository (the
``memo`` module's remaining helpers, the other top-level modules, and
any name starting with an underscore) is an implementation detail and
may change in any release.

The implementation lives in :mod:`memo` and :mod:`memo_errors`; this
module only fixes the public surface in one place. It adds no behaviour
of its own and has no dependencies beyond the Python standard library.
"""

from memo import (
    MemoStore,
    MemoValidationError,
    VALID_STATUSES,
    analyze_habits,
    analyze_network,
    analyze_productivity,
    analyze_trends,
    export_memos,
    generate_stats_report,
    import_memos,
    parse_tags,
    parse_tags_and_links,
)
from memo_errors import (
    DuplicateError,
    MemoError,
    NotFoundError,
    RateLimitError,
    SecurityError,
    StorageError,
    ValidationError,
)

try:  # The distribution metadata is the single source of truth.
    from importlib.metadata import PackageNotFoundError, version

    try:
        __version__ = version("memo-app")
    except PackageNotFoundError:  # Running from a source checkout.
        __version__ = "1.1.0"
except ImportError:  # Python < 3.8 fallback; project requires >= 3.9.
    __version__ = "1.1.0"

__all__ = [
    # Version of the memo-app distribution (see pyproject.toml).
    "__version__",
    # Storage
    "MemoStore",
    "VALID_STATUSES",
    # Import / export / reporting (module-level functions)
    "export_memos",
    "import_memos",
    "generate_stats_report",
    "analyze_trends",
    "analyze_habits",
    "analyze_network",
    "analyze_productivity",
    # Text helpers
    "parse_tags",
    "parse_tags_and_links",
    # Errors
    "MemoError",
    "ValidationError",
    "MemoValidationError",
    "SecurityError",
    "StorageError",
    "NotFoundError",
    "DuplicateError",
    "RateLimitError",
]

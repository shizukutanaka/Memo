# Memo

A lightweight memo management CLI. Memos are stored in a local SQLite
database (`~/.memo/memos.db`) and full-text search uses SQLite FTS5
with BM25 ranking. The core application runs on the Python standard
library only.

## Requirements

- Python 3.9 or later

## Installation

```bash
git clone https://github.com/shizukutanaka/Memo.git
cd Memo
```

There is nothing to build and no required dependencies. Run the CLI
in place from the repository root:

```bash
python memo.py --help
```

## Usage

```bash
# Add a memo (optionally in a category)
python memo.py add "Test memo about github" -c work

# List recent memos
python memo.py list

# Full-text search
python memo.py search github

# Show statistics
python memo.py stats

# Export all memos as JSON (also: csv, md, html, txt)
python memo.py export json -o memos.json
```

Memos are identified by the ID shown in `list` output. Other commands
include `tag`, `edit`, `delete`, `duplicate`, `merge`, `split`,
`import`, `analyze`, `categories`, `status`, `bulk`, `filter`,
`templates`, `backup`, and `link`. Run `python memo.py --help` (or
`python memo.py <command> --help`) for the full list and options.

## Use as a library

Memo can also be imported from other Python programs. The supported
import surface is the `memo_api` module, covered by a compatibility
policy (see `docs/API.md`):

```python
from memo_api import MemoStore, export_memos

store = MemoStore()
store.add("Release notes", tags=["work"])
print(export_memos(store.list_all(), "json"))
```

## Optional extras

The `pyproject.toml` declares optional dependency sets for additional
modules: `tui` (Textual/Rich), `sync` (requests), `full` (both), and
`dev` (test/lint tooling).

## Tests

```bash
python -m pytest tests/
```

## License

MIT (see `LICENSE`).

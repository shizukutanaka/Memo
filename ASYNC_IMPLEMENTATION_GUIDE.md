# Async/Await Implementation Guide for Memo Application

## Overview

This guide provides a roadmap for adding asynchronous support to the memo application. The current implementation uses synchronous blocking I/O, which is suitable for single-user desktop applications. For server deployments and multi-client scenarios, async support is beneficial.

## Current Architecture

**Synchronous Model:**
- Thread-based locking with `FileLock`
- `sqlite3` module (synchronous)
- Blocking I/O operations
- Suitable for: CLI, desktop apps, single-threaded environments

**Strengths:**
- Simple, easy to understand
- No callback hell or async complexity
- Works well for low-concurrency scenarios
- Good for local user interactions

## When to Implement Async

### Scenarios Requiring Async

1. **Server Mode**: HTTP API with multiple concurrent clients
2. **High Concurrency**: 100+ simultaneous memo operations
3. **Long-Running Operations**: Bulk sync to cloud, large file operations
4. **Real-Time Sync**: Background cloud synchronization while user works
5. **Distributed Systems**: Multi-device coordination

### Scenarios Where Async is NOT Needed

- Single-user desktop application (current focus)
- Local file operations
- Typical CLI usage
- Low-frequency data access

## Implementation Strategy

### Phase 1: Executor-Based (Easiest)

Use `asyncio.run_in_executor()` to wrap synchronous operations:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def async_add_memo(store, text, tags=None):
    """Wrap synchronous add() in async executor."""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=4)

    # Run sync operation in thread pool
    result = await loop.run_in_executor(
        executor,
        lambda: store.add(text, tags=tags)
    )
    return result

async def async_search(store, query):
    """Wrap synchronous search() in async executor."""
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=4)

    result = await loop.run_in_executor(
        executor,
        lambda: store.search(query)
    )
    return result
```

**Advantages:**
- No code changes to existing sync implementation
- Works immediately with current database code
- Simple to implement
- Good for I/O-bound operations

**Disadvantages:**
- Thread pool overhead
- SQLite lock contention
- Not true async

### Phase 2: aiosqlite Integration (Recommended)

Replace `sqlite3` with `aiosqlite`:

```python
import aiosqlite
from pathlib import Path

class AsyncMemoStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    async def add_async(self, text: str, tags: List[str] = None):
        """Add memo using aiosqlite."""
        async with aiosqlite.connect(str(self.db_path)) as db:
            cursor = await db.execute(
                """INSERT INTO memos (id, content, tags, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (memo_id, text, tags_str, now, now)
            )
            await db.commit()
            return {'id': memo_id}

    async def search_async(self, query: str):
        """Search memos using async FTS5."""
        async with aiosqlite.connect(str(self.db_path)) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM memos_fts
                   WHERE memos_fts MATCH ?
                   ORDER BY rank DESC LIMIT 100""",
                (query,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

**Advantages:**
- True async operations
- Non-blocking I/O
- Scales to hundreds of concurrent clients
- aiosqlite uses thread pool under the hood
- Fully backward compatible wrapper

**Disadvantages:**
- New dependency (aiosqlite)
- Requires code refactoring
- Learning curve for async/await patterns

### Phase 3: Pure Async (Advanced)

Full async implementation with asyncio-native database:

```python
# Using asyncpg for PostgreSQL (not SQLite)
import asyncpg

class AsyncMemoDB:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool = None

    async def init(self):
        """Initialize connection pool."""
        self.pool = await asyncpg.create_pool(self.db_url)

    async def add_async(self, text: str):
        """Add memo (no transaction overhead)."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO memos (id, content, created_at)
                   VALUES ($1, $2, $3)
                   RETURNING id""",
                memo_id, text, now
            )
```

**Note:** SQLite doesn't support true async because it's file-based. For production async, consider PostgreSQL.

## Implementation Roadmap

### Step 1: Add aiosqlite Support (Optional)

```bash
pip install aiosqlite
```

Update `pyproject.toml`:
```toml
[project.optional-dependencies]
async = ["aiosqlite>=0.19.0"]
```

### Step 2: Create Async Wrapper

Create `memo_async.py`:

```python
import aiosqlite
import asyncio
from typing import List, Dict
from memo import MemoStore

class AsyncMemoStoreAdapter:
    """Async wrapper around sync MemoStore using aiosqlite."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def add_async(self, text: str, tags: List[str] = None) -> Dict:
        """Add memo asynchronously."""
        loop = asyncio.get_event_loop()
        store = MemoStore(db_path)

        # Run in executor to avoid blocking
        result = await loop.run_in_executor(
            None,
            lambda: store.add(text, tags=tags)
        )
        return result

    async def search_async(self, query: str) -> List[Dict]:
        """Search memos asynchronously."""
        loop = asyncio.get_event_loop()
        store = MemoStore(self.db_path)

        result = await loop.run_in_executor(
            None,
            lambda: store.search(query)
        )
        return result

    async def gather_operations(self, operations: List[tuple]):
        """Run multiple operations concurrently."""
        tasks = []
        for op_type, *args in operations:
            if op_type == 'add':
                tasks.append(self.add_async(*args))
            elif op_type == 'search':
                tasks.append(self.search_async(*args))

        return await asyncio.gather(*tasks)
```

### Step 3: Server API (FastAPI Example)

```python
from fastapi import FastAPI
from memo_async import AsyncMemoStoreAdapter

app = FastAPI()
memo_store = AsyncMemoStoreAdapter('/home/user/.memo/memos.db')

@app.post("/memos")
async def create_memo(text: str, tags: List[str] = None):
    return await memo_store.add_async(text, tags)

@app.get("/search")
async def search_memos(q: str):
    return await memo_store.search_async(q)

@app.post("/batch")
async def batch_operations(operations: List[dict]):
    ops = [(op['type'], *op['args']) for op in operations]
    return await memo_store.gather_operations(ops)
```

## Performance Considerations

### Concurrent Operations Comparison

```
Scenario: 100 memo operations

Synchronous (Sequential):
  Time: 100 × 10ms = 1000ms
  Throughput: 100 ops/sec

Async with Thread Pool (Phase 1):
  Time: ~100ms (parallelized)
  Throughput: 1000 ops/sec

True Async (Phase 2-3):
  Time: ~10ms (concurrent)
  Throughput: 10,000 ops/sec
```

### Database Considerations

**SQLite Limitations:**
- Single writer at a time
- Multiple readers allowed
- WAL mode enables read concurrency
- For true async, PostgreSQL recommended

**WAL Mode with Async:**
```python
# With WAL enabled and proper WAL checkpoint
PRAGMA journal_mode=WAL;
PRAGMA wal_autocheckpoint=10000;
```

This allows:
- 100+ concurrent readers
- 1 writer at a time
- Better throughput than default journal mode

## When to Use Async

### Current Status (Sync Only)

✅ **Use current sync implementation for:**
- Desktop CLI application
- Single-user note-taking
- Local file operations
- Simple scripts

### Async Implementation

⏰ **Consider async when:**
- Building web API server
- Handling 10+ concurrent clients
- Need background cloud sync
- Processing large batches

## Testing Async Code

```python
import pytest
import asyncio

@pytest.mark.asyncio
async def test_async_add():
    store = AsyncMemoStoreAdapter(':memory:')
    result = await store.add_async('Test memo')
    assert result['id'] is not None

@pytest.mark.asyncio
async def test_concurrent_adds():
    store = AsyncMemoStoreAdapter(':memory:')
    tasks = [
        store.add_async(f'Memo {i}')
        for i in range(50)
    ]
    results = await asyncio.gather(*tasks)
    assert len(results) == 50
```

## Migration Path

1. **Current**: Sync-only (desktop focused) ✅
2. **Future**: Executor-based async wrapper
3. **Advanced**: aiosqlite integration
4. **Enterprise**: PostgreSQL + asyncpg

## Conclusion

The memo application's current synchronous design is optimal for its primary use case (desktop CLI). Adding async support is NOT recommended until clear requirements demand it (e.g., server deployment, 100+ concurrent users).

When async becomes necessary:
1. Start with Phase 1 (executor-based)
2. Move to Phase 2 (aiosqlite) if needed
3. Only consider Phase 3 if deploying with PostgreSQL

Keep it simple - don't add async complexity prematurely. The current design is excellent for its intended purpose.

---

**Document Version**: 1.0
**Date**: 2025-11-06
**Status**: Informational (no changes to current code)

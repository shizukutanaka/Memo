#!/usr/bin/env python3
"""Delta synchronization with compression for efficient data transfer."""

import hashlib
import json
import zlib
import difflib
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class DeltaEntry:
    """Represents a delta (change) in data."""

    OPERATION_CREATE = "create"
    OPERATION_UPDATE = "update"
    OPERATION_DELETE = "delete"

    def __init__(
        self,
        memo_id: str,
        operation: str,
        data: Optional[Dict] = None,
        timestamp: Optional[float] = None
    ):
        """
        Initialize delta entry.

        Args:
            memo_id: Memo ID
            operation: Operation type (create, update, delete)
            data: Changed data
            timestamp: Operation timestamp
        """
        self.memo_id = memo_id
        self.operation = operation
        self.data = data or {}
        self.timestamp = timestamp or datetime.now(timezone.utc).timestamp()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "memo_id": self.memo_id,
            "operation": self.operation,
            "data": self.data,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DeltaEntry":
        """Create from dictionary."""
        return cls(
            memo_id=data["memo_id"],
            operation=data["operation"],
            data=data.get("data", {}),
            timestamp=data.get("timestamp")
        )


class DeltaTracker:
    """Tracks changes (deltas) for efficient sync."""

    def __init__(self, state_file: Path):
        """
        Initialize delta tracker.

        Args:
            state_file: File to store state
        """
        self.state_file = Path(state_file)
        self.state = self._load_state()
        self.deltas: List[DeltaEntry] = []

    def _load_state(self) -> Dict[str, Dict]:
        """Load previous state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")

        return {}

    def _save_state(self) -> None:
        """Save current state."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def record_create(self, memo_id: str, data: Dict) -> None:
        """Record memo creation."""
        # Store new state
        self.state[memo_id] = {
            "data": data,
            "checksum": self._checksum(data),
            "timestamp": datetime.now(timezone.utc).timestamp()
        }

        # Record delta
        delta = DeltaEntry(memo_id, DeltaEntry.OPERATION_CREATE, data)
        self.deltas.append(delta)

    def record_update(self, memo_id: str, data: Dict) -> None:
        """Record memo update."""
        if memo_id not in self.state:
            self.record_create(memo_id, data)
            return

        old_data = self.state[memo_id]["data"]
        new_checksum = self._checksum(data)
        old_checksum = self.state[memo_id].get("checksum")

        # Only record if actually changed
        if old_checksum != new_checksum:
            # Calculate diff
            diff_data = self._calculate_diff(old_data, data)

            self.state[memo_id] = {
                "data": data,
                "checksum": new_checksum,
                "timestamp": datetime.now(timezone.utc).timestamp()
            }

            # Record delta with only changed fields
            delta = DeltaEntry(memo_id, DeltaEntry.OPERATION_UPDATE, diff_data)
            self.deltas.append(delta)

    def record_delete(self, memo_id: str) -> None:
        """Record memo deletion."""
        if memo_id in self.state:
            delta = DeltaEntry(memo_id, DeltaEntry.OPERATION_DELETE)
            self.deltas.append(delta)

            del self.state[memo_id]

    def get_deltas(self, since: Optional[float] = None) -> List[DeltaEntry]:
        """
        Get deltas since timestamp.

        Args:
            since: Only return deltas after this timestamp

        Returns:
            List of deltas
        """
        if since is None:
            return self.deltas

        return [d for d in self.deltas if d.timestamp >= since]

    def clear_deltas(self) -> None:
        """Clear recorded deltas."""
        self.deltas.clear()
        self._save_state()

    @staticmethod
    def _checksum(data: Dict) -> str:
        """Calculate checksum of data."""
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(data_str.encode()).hexdigest()

    @staticmethod
    def _calculate_diff(old_data: Dict, new_data: Dict) -> Dict[str, Any]:
        """
        Calculate difference between two data dicts.

        Args:
            old_data: Old data
            new_data: New data

        Returns:
            Dictionary with only changed fields
        """
        diff = {}

        # Find changed/new fields
        for key, new_value in new_data.items():
            old_value = old_data.get(key)
            if old_value != new_value:
                diff[key] = new_value

        # Find deleted fields
        for key in old_data:
            if key not in new_data:
                diff[key] = None  # None indicates deletion

        return diff


class DeltaCompression:
    """Compress deltas for efficient transfer."""

    @staticmethod
    def compress_deltas(deltas: List[DeltaEntry]) -> bytes:
        """
        Compress deltas using zlib.

        Args:
            deltas: List of deltas

        Returns:
            Compressed bytes
        """
        # Serialize deltas
        data = json.dumps([d.to_dict() for d in deltas]).encode()

        # Compress
        compressed = zlib.compress(data, level=9)

        logger.info(
            f"Compressed {len(data)} bytes to {len(compressed)} bytes "
            f"({100 - (len(compressed)/len(data)*100):.1f}% reduction)"
        )

        return compressed

    @staticmethod
    def decompress_deltas(compressed: bytes) -> List[DeltaEntry]:
        """
        Decompress deltas.

        Args:
            compressed: Compressed bytes

        Returns:
            List of deltas
        """
        try:
            data = zlib.decompress(compressed)
            deltas_data = json.loads(data.decode())
            return [DeltaEntry.from_dict(d) for d in deltas_data]

        except Exception as e:
            logger.error(f"Failed to decompress deltas: {e}")
            return []

    @staticmethod
    def get_compression_ratio(original_size: int, compressed_size: int) -> float:
        """
        Calculate compression ratio.

        Args:
            original_size: Original size in bytes
            compressed_size: Compressed size in bytes

        Returns:
            Compression ratio (0-1, lower is better)
        """
        if original_size == 0:
            return 0

        return compressed_size / original_size


class DeltaSyncManager:
    """Manages delta-based synchronization."""

    def __init__(self, state_file: Path):
        """
        Initialize sync manager.

        Args:
            state_file: File to store sync state
        """
        self.tracker = DeltaTracker(state_file)
        self.last_sync = None

    def sync_local_changes(self, local_memos: List[Dict]) -> Tuple[List[DeltaEntry], int]:
        """
        Detect and track local changes.

        Args:
            local_memos: List of local memos

        Returns:
            Tuple of (deltas, size_bytes)
        """
        # Track current state
        current_ids = set()
        for memo in local_memos:
            memo_id = memo["id"]
            current_ids.add(memo_id)
            self.tracker.record_update(memo_id, memo)

        # Detect deletions
        previous_ids = set(self.tracker.state.keys())
        for memo_id in previous_ids - current_ids:
            self.tracker.record_delete(memo_id)

        # Get deltas
        deltas = self.tracker.get_deltas(since=self.last_sync)

        # Calculate size
        size = sum(len(json.dumps(d.to_dict()).encode()) for d in deltas)

        return deltas, size

    def apply_remote_deltas(self, deltas: List[DeltaEntry]) -> Dict[str, int]:
        """
        Apply remote deltas to local state.

        Args:
            deltas: Remote deltas

        Returns:
            Statistics (created, updated, deleted)
        """
        stats = {"created": 0, "updated": 0, "deleted": 0}

        for delta in deltas:
            if delta.operation == DeltaEntry.OPERATION_CREATE:
                self.tracker.state[delta.memo_id] = {
                    "data": delta.data,
                    "checksum": self.tracker._checksum(delta.data),
                    "timestamp": delta.timestamp
                }
                stats["created"] += 1

            elif delta.operation == DeltaEntry.OPERATION_UPDATE:
                if delta.memo_id in self.tracker.state:
                    old_data = self.tracker.state[delta.memo_id]["data"]
                    # Apply delta to old data
                    new_data = {**old_data, **delta.data}
                    self.tracker.state[delta.memo_id] = {
                        "data": new_data,
                        "checksum": self.tracker._checksum(new_data),
                        "timestamp": delta.timestamp
                    }
                    stats["updated"] += 1

            elif delta.operation == DeltaEntry.OPERATION_DELETE:
                if delta.memo_id in self.tracker.state:
                    del self.tracker.state[delta.memo_id]
                    stats["deleted"] += 1

        self.tracker._save_state()
        return stats

    def get_sync_stats(self) -> Dict[str, Any]:
        """Get synchronization statistics."""
        deltas = self.tracker.deltas

        if not deltas:
            return {"total_deltas": 0}

        # Count by operation
        operations = {}
        for delta in deltas:
            operations[delta.operation] = operations.get(delta.operation, 0) + 1

        # Calculate size
        uncompressed_size = sum(
            len(json.dumps(d.to_dict()).encode()) for d in deltas
        )
        compressed = DeltaCompression.compress_deltas(deltas)
        compression_ratio = DeltaCompression.get_compression_ratio(
            uncompressed_size, len(compressed)
        )

        return {
            "total_deltas": len(deltas),
            "operations": operations,
            "uncompressed_size_bytes": uncompressed_size,
            "compressed_size_bytes": len(compressed),
            "compression_ratio": compression_ratio,
            "saved_bytes": uncompressed_size - len(compressed)
        }


if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.INFO)

    # Test delta tracking
    print("=== Delta Tracking ===")
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json") as f:
        state_file = Path(f.name)

    tracker = DeltaTracker(state_file)

    # Record operations
    memo1 = {"id": "m001", "content": "Hello", "tags": ["greeting"]}
    memo2 = {"id": "m002", "content": "World", "tags": ["test"]}

    tracker.record_create("m001", memo1)
    tracker.record_create("m002", memo2)

    # Update memo
    updated_memo1 = {"id": "m001", "content": "Hello World", "tags": ["greeting", "updated"]}
    tracker.record_update("m001", updated_memo1)

    print(f"Deltas recorded: {len(tracker.deltas)}")
    for delta in tracker.deltas:
        print(f"  {delta.operation}: {delta.memo_id}")

    # Test compression
    print("\n=== Delta Compression ===")
    compressed = DeltaCompression.compress_deltas(tracker.deltas)
    original_size = sum(len(json.dumps(d.to_dict()).encode()) for d in tracker.deltas)

    print(f"Original: {original_size} bytes")
    print(f"Compressed: {len(compressed)} bytes")
    print(f"Ratio: {DeltaCompression.get_compression_ratio(original_size, len(compressed)):.2%}")

    # Test decompression
    decompressed = DeltaCompression.decompress_deltas(compressed)
    print(f"Decompressed: {len(decompressed)} deltas")

    # Test sync manager
    print("\n=== Delta Sync Manager ===")
    manager = DeltaSyncManager(state_file)

    local_memos = [memo1, memo2, updated_memo1]
    deltas, size = manager.sync_local_changes(local_memos)

    print(f"Detected {len(deltas)} local changes ({size} bytes)")

    stats = manager.get_sync_stats()
    print(f"Sync stats: {stats}")

    # Cleanup
    state_file.unlink()

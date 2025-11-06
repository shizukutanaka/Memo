#!/usr/bin/env python3
"""
Advanced Features Module for Enterprise Memo System
===================================================
Extends base system with advanced capabilities including
AI integration, real-time sync, and analytics.
"""

import asyncio
import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from queue import Queue, PriorityQueue
import heapq

# Cache implementation
class LRUCache:
    """Thread-safe LRU cache implementation"""

    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self.cache = {}
        self.order = []
        self.lock = threading.RLock()

    def get(self, key: str) -> Optional[Any]:
        """Get item from cache"""
        with self.lock:
            if key not in self.cache:
                return None

            # Move to end (most recently used)
            self.order.remove(key)
            self.order.append(key)
            return self.cache[key]

    def put(self, key: str, value: Any):
        """Add item to cache"""
        with self.lock:
            if key in self.cache:
                # Update existing
                self.order.remove(key)
            elif len(self.cache) >= self.capacity:
                # Remove least recently used
                oldest = self.order.pop(0)
                del self.cache[oldest]

            self.cache[key] = value
            self.order.append(key)

    def invalidate(self, key: str):
        """Remove item from cache"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.order.remove(key)

    def clear(self):
        """Clear entire cache"""
        with self.lock:
            self.cache.clear()
            self.order.clear()


# Real-time synchronization
class SyncManager:
    """Manages real-time synchronization across instances"""

    def __init__(self):
        self.sync_queue = Queue()
        self.subscribers = set()
        self.sync_thread = None
        self.running = False

    def start(self):
        """Start sync manager"""
        self.running = True
        self.sync_thread = threading.Thread(target=self._sync_worker, daemon=True)
        self.sync_thread.start()

    def stop(self):
        """Stop sync manager"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)

    def _sync_worker(self):
        """Background sync worker"""
        while self.running:
            try:
                if not self.sync_queue.empty():
                    event = self.sync_queue.get(timeout=1)
                    self._broadcast_event(event)
                time.sleep(0.1)
            except:
                continue

    def publish_event(self, event: Dict[str, Any]):
        """Publish sync event"""
        self.sync_queue.put({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event
        })

    def subscribe(self, callback):
        """Subscribe to sync events"""
        self.subscribers.add(callback)

    def unsubscribe(self, callback):
        """Unsubscribe from sync events"""
        self.subscribers.discard(callback)

    def _broadcast_event(self, event: Dict[str, Any]):
        """Broadcast event to all subscribers"""
        for callback in self.subscribers:
            try:
                callback(event)
            except:
                continue


# Advanced search with ranking
class SearchEngine:
    """Advanced search engine with relevance ranking"""

    def __init__(self):
        self.index = defaultdict(set)  # term -> set of document IDs
        self.documents = {}  # document ID -> content
        self.idf = {}  # Inverse document frequency cache
        self.lock = threading.RLock()

    def index_document(self, doc_id: str, content: str, metadata: Dict[str, Any] = None):
        """Index a document for searching"""
        with self.lock:
            # Store document
            self.documents[doc_id] = {
                "content": content,
                "metadata": metadata or {},
                "indexed_at": datetime.now(timezone.utc)
            }

            # Tokenize and index
            tokens = self._tokenize(content)
            for token in tokens:
                self.index[token].add(doc_id)

            # Update IDF cache
            self._update_idf()

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search documents with relevance ranking"""
        with self.lock:
            # Tokenize query
            query_tokens = self._tokenize(query)
            if not query_tokens:
                return []

            # Calculate TF-IDF scores
            scores = defaultdict(float)
            for token in query_tokens:
                if token in self.index:
                    idf = self.idf.get(token, 0)
                    for doc_id in self.index[token]:
                        doc_content = self.documents[doc_id]["content"]
                        tf = doc_content.lower().count(token) / len(doc_content.split())
                        scores[doc_id] += tf * idf

            # Sort by score and return top results
            sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]

            return [
                {
                    "id": doc_id,
                    "score": score,
                    "content": self.documents[doc_id]["content"],
                    "metadata": self.documents[doc_id]["metadata"]
                }
                for doc_id, score in sorted_results
            ]

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenize text for indexing"""
        # Simple tokenization - can be enhanced with NLP libraries
        import re
        tokens = re.findall(r'\b\w+\b', text.lower())
        # Remove stop words (simplified list)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        return set(token for token in tokens if token not in stop_words and len(token) > 2)

    def _update_idf(self):
        """Update inverse document frequency scores"""
        import math
        total_docs = len(self.documents)
        if total_docs == 0:
            return

        for term, doc_ids in self.index.items():
            # IDF = log(total documents / documents containing term)
            self.idf[term] = math.log(total_docs / len(doc_ids))


# Analytics engine
class AnalyticsEngine:
    """Analytics and reporting engine"""

    def __init__(self):
        self.metrics = defaultdict(list)
        self.lock = threading.RLock()

    def track_event(self, event_type: str, data: Any):
        """Track an analytics event"""
        with self.lock:
            self.metrics[event_type].append({
                "timestamp": datetime.now(timezone.utc),
                "data": data
            })

            # Keep only last 10000 events per type
            if len(self.metrics[event_type]) > 10000:
                self.metrics[event_type] = self.metrics[event_type][-10000:]

    def get_statistics(self, event_type: str = None, time_range: timedelta = None) -> Dict[str, Any]:
        """Get analytics statistics"""
        with self.lock:
            if event_type and event_type not in self.metrics:
                return {"error": "Event type not found"}

            # Calculate time cutoff
            cutoff = None
            if time_range:
                cutoff = datetime.now(timezone.utc) - time_range

            stats = {}
            event_types = [event_type] if event_type else self.metrics.keys()

            for evt_type in event_types:
                events = self.metrics[evt_type]

                # Filter by time range if specified
                if cutoff:
                    events = [e for e in events if e["timestamp"] >= cutoff]

                if not events:
                    stats[evt_type] = {"count": 0}
                    continue

                # Calculate statistics
                stats[evt_type] = {
                    "count": len(events),
                    "first": events[0]["timestamp"].isoformat() if events else None,
                    "last": events[-1]["timestamp"].isoformat() if events else None,
                }

                # Additional stats for numeric data
                numeric_values = []
                for event in events:
                    if isinstance(event["data"], (int, float)):
                        numeric_values.append(event["data"])

                if numeric_values:
                    stats[evt_type].update({
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "avg": sum(numeric_values) / len(numeric_values)
                    })

            return stats


# Backup and recovery manager
class BackupManager:
    """Advanced backup and recovery system"""

    def __init__(self, backup_dir: str):
        self.backup_dir = backup_dir
        self.backup_queue = PriorityQueue()
        self.running = False
        self.backup_thread = None

    def start(self):
        """Start backup manager"""
        self.running = True
        self.backup_thread = threading.Thread(target=self._backup_worker, daemon=True)
        self.backup_thread.start()

    def stop(self):
        """Stop backup manager"""
        self.running = False
        if self.backup_thread:
            self.backup_thread.join(timeout=5)

    def schedule_backup(self, data: Any, priority: int = 5):
        """Schedule a backup operation"""
        # Lower priority number = higher priority
        self.backup_queue.put((priority, time.time(), data))

    def _backup_worker(self):
        """Background backup worker"""
        while self.running:
            try:
                if not self.backup_queue.empty():
                    priority, timestamp, data = self.backup_queue.get(timeout=1)
                    self._perform_backup(data, timestamp)
                time.sleep(1)
            except:
                continue

    def _perform_backup(self, data: Any, timestamp: float):
        """Perform actual backup"""
        import gzip
        import json

        backup_file = f"{self.backup_dir}/backup_{int(timestamp)}.gz"

        try:
            # SECURITY FIX: Use JSON instead of pickle to prevent RCE
            # Compress and save
            with gzip.open(backup_file, 'wt', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"Backup failed: {e}")

    def restore(self, backup_file: str) -> Optional[Any]:
        """Restore from backup"""
        import gzip
        import json

        try:
            # SECURITY FIX: Use JSON instead of pickle to prevent RCE
            with gzip.open(backup_file, 'rt', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Restore failed: {e}")
            return None


# Rate limiting
class RateLimiter:
    """Rate limiting for API endpoints"""

    def __init__(self, max_requests: int = 100, time_window: int = 60):
        """
        Initialize rate limiter

        Args:
            max_requests: Maximum requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self.lock = threading.RLock()

    def is_allowed(self, identifier: str) -> bool:
        """Check if request is allowed"""
        with self.lock:
            now = time.time()

            # Clean old requests
            self.requests[identifier] = [
                req_time for req_time in self.requests[identifier]
                if now - req_time < self.time_window
            ]

            # Check limit
            if len(self.requests[identifier]) >= self.max_requests:
                return False

            # Add current request
            self.requests[identifier].append(now)
            return True

    def reset(self, identifier: str):
        """Reset rate limit for identifier"""
        with self.lock:
            if identifier in self.requests:
                del self.requests[identifier]


# Task scheduler
class TaskScheduler:
    """Advanced task scheduling system"""

    def __init__(self):
        self.tasks = []  # Min heap of (run_time, task)
        self.running = False
        self.scheduler_thread = None
        self.lock = threading.RLock()

    def start(self):
        """Start scheduler"""
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_worker, daemon=True)
        self.scheduler_thread.start()

    def stop(self):
        """Stop scheduler"""
        self.running = False
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)

    def schedule_task(self, task: callable, delay: float = 0, recurring: bool = False,
                     interval: float = None):
        """Schedule a task for execution"""
        with self.lock:
            run_time = time.time() + delay
            heapq.heappush(self.tasks, (run_time, task, recurring, interval))

    def _scheduler_worker(self):
        """Background scheduler worker"""
        while self.running:
            with self.lock:
                now = time.time()

                # Process due tasks
                while self.tasks and self.tasks[0][0] <= now:
                    run_time, task, recurring, interval = heapq.heappop(self.tasks)

                    # Execute task in separate thread
                    threading.Thread(target=self._execute_task, args=(task,), daemon=True).start()

                    # Reschedule if recurring
                    if recurring and interval:
                        next_run = now + interval
                        heapq.heappush(self.tasks, (next_run, task, recurring, interval))

            time.sleep(0.1)

    def _execute_task(self, task: callable):
        """Execute a scheduled task"""
        try:
            task()
        except Exception as e:
            print(f"Task execution failed: {e}")


# Data migration utilities
class DataMigrator:
    """Handles data migration between versions"""

    @staticmethod
    def migrate_database(db_path: str, from_version: str, to_version: str):
        """Migrate database schema between versions"""
        migrations = {
            ("1.0", "2.0"): DataMigrator._migrate_1_to_2,
            ("2.0", "3.0"): DataMigrator._migrate_2_to_3,
            ("3.0", "4.0"): DataMigrator._migrate_3_to_4,
        }

        migration_key = (from_version, to_version)
        if migration_key in migrations:
            migrations[migration_key](db_path)
        else:
            raise ValueError(f"No migration path from {from_version} to {to_version}")

    @staticmethod
    def _migrate_1_to_2(db_path: str):
        """Migration from version 1.0 to 2.0"""
        import sqlite3
        conn = sqlite3.connect(db_path)

        # Add new columns
        conn.execute("ALTER TABLE memos ADD COLUMN checksum TEXT")
        conn.execute("ALTER TABLE memos ADD COLUMN version INTEGER DEFAULT 1")

        conn.commit()
        conn.close()

    @staticmethod
    def _migrate_2_to_3(db_path: str):
        """Migration from version 2.0 to 3.0"""
        import sqlite3
        conn = sqlite3.connect(db_path)

        # Add security features
        conn.execute("ALTER TABLE memos ADD COLUMN security_level INTEGER DEFAULT 0")
        conn.execute("ALTER TABLE memos ADD COLUMN encrypted_content TEXT")

        conn.commit()
        conn.close()

    @staticmethod
    def _migrate_3_to_4(db_path: str):
        """Migration from version 3.0 to 4.0"""
        import sqlite3
        conn = sqlite3.connect(db_path)

        # Add performance indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memos_checksum ON memos(checksum)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)")

        conn.commit()
        conn.close()


# Export functionality
class DataExporter:
    """Export data in various formats"""

    @staticmethod
    def export_json(data: List[Dict], output_file: str):
        """Export data as JSON"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str, ensure_ascii=False)

    @staticmethod
    def export_csv(data: List[Dict], output_file: str):
        """Export data as CSV"""
        import csv

        if not data:
            return

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

    @staticmethod
    def export_markdown(data: List[Dict], output_file: str):
        """Export data as Markdown"""
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Exported Data\n\n")

            for item in data:
                f.write("## Entry\n\n")
                for key, value in item.items():
                    f.write(f"**{key}:** {value}\n")
                f.write("\n---\n\n")

    @staticmethod
    def export_html(data: List[Dict], output_file: str):
        """Export data as HTML"""
        html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Exported Data</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .entry { border: 1px solid #ddd; padding: 10px; margin: 10px 0; }
        .field { margin: 5px 0; }
        .field-name { font-weight: bold; }
    </style>
</head>
<body>
    <h1>Exported Data</h1>
    {entries}
</body>
</html>
        """

        entries_html = ""
        for item in data:
            entry_html = '<div class="entry">'
            for key, value in item.items():
                entry_html += f'<div class="field"><span class="field-name">{key}:</span> {value}</div>'
            entry_html += '</div>'
            entries_html += entry_html

        html_content = html_template.format(entries=entries_html)

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
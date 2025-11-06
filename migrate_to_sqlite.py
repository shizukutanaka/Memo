#!/usr/bin/env python3
"""
Memo System SQLite Migration Tool
==================================

JSONLベースのストレージからSQLiteへ移行するスクリプト
SQLiteに移行することで、O(n)ファイル操作をO(1)またはO(log n)に改善
"""

import json
import sqlite3
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import logging
import shutil

class SQLiteMigrationTool:
    """SQLite移行ツール"""

    def __init__(self, jsonl_path: Path, sqlite_path: Path):
        self.jsonl_path = jsonl_path
        self.sqlite_path = sqlite_path
        self.backup_path = jsonl_path.with_suffix('.jsonl.backup')

        # ロギング設定
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def create_schema(self, conn: sqlite3.Connection) -> None:
        """SQLiteスキーマを作成"""
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=1000")
        conn.execute("PRAGMA temp_store=MEMORY")

        # memosテーブル
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memos (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'default',
                tags TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                priority INTEGER DEFAULT 0,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                linked_memos TEXT DEFAULT '',
                checksum TEXT
            );

            -- 全文検索用仮想テーブル
            CREATE VIRTUAL TABLE IF NOT EXISTS memos_fts USING fts5(
                id UNINDEXED,
                content,
                category,
                tags,
                tokenize='porter unicode61'
            );

            -- インデックス
            CREATE INDEX IF NOT EXISTS idx_memos_category ON memos(category);
            CREATE INDEX IF NOT EXISTS idx_memos_status ON memos(status);
            CREATE INDEX IF NOT EXISTS idx_memos_priority ON memos(priority);
            CREATE INDEX IF NOT EXISTS idx_memos_created_at ON memos(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memos_updated_at ON memos(updated_at DESC);

            -- 設定テーブル
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME NOT NULL
            );

            -- テンプレートテーブル
            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'templates',
                tags TEXT DEFAULT '',
                created_at DATETIME NOT NULL
            );
        """)

    def parse_jsonl_line(self, line: str) -> Optional[Dict[str, Any]]:
        """JSONL行をパース"""
        line = line.strip()
        if not line:
            return None

        try:
            return json.loads(line)
        except json.JSONDecodeError as e:
            self.logger.warning(f"JSON decode error: {e}, line: {line[:100]}...")
            return None

    def migrate_memos(self, conn: sqlite3.Connection) -> int:
        """メモデータを移行"""
        migrated_count = 0

        if not self.jsonl_path.exists():
            self.logger.info("JSONL file does not exist, skipping memo migration")
            return 0

        self.logger.info(f"Migrating memos from {self.jsonl_path}")

        with open(self.jsonl_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                memo_data = self.parse_jsonl_line(line)
                if not memo_data:
                    continue

                try:
                    # データ構造の正規化
                    memo_id = memo_data.get('id', f'migrated_{line_num}')
                    content = memo_data.get('text', memo_data.get('content', ''))
                    category = memo_data.get('category', 'default')
                    tags = memo_data.get('tags', [])
                    status = memo_data.get('status', 'active')
                    priority = memo_data.get('priority', 0)
                    created_at = memo_data.get('created_at', datetime.now(timezone.utc).isoformat())
                    updated_at = memo_data.get('updated_at', created_at)
                    linked_memos = memo_data.get('linked_memos', [])
                    checksum = memo_data.get('checksum', '')

                    # タグを文字列に変換
                    if isinstance(tags, list):
                        tags_str = ','.join(str(tag) for tag in tags)
                    else:
                        tags_str = str(tags)

                    # リンクされたメモを文字列に変換
                    if isinstance(linked_memos, list):
                        linked_str = ','.join(str(link) for link in linked_memos)
                    else:
                        linked_str = str(linked_memos)

                    # メモを挿入
                    conn.execute("""
                        INSERT INTO memos (id, content, category, tags, status, priority,
                                         created_at, updated_at, linked_memos, checksum)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (memo_id, content, category, tags_str, status, priority,
                          created_at, updated_at, linked_str, checksum))

                    # FTSテーブルに挿入
                    conn.execute("""
                        INSERT INTO memos_fts (id, content, category, tags)
                        VALUES (?, ?, ?, ?)
                    """, (memo_id, content, category, tags_str))

                    migrated_count += 1

                    if migrated_count % 100 == 0:
                        self.logger.info(f"Migrated {migrated_count} memos...")

                except Exception as e:
                    self.logger.error(f"Error migrating memo at line {line_num}: {e}")
                    continue

        return migrated_count

    def migrate_templates(self, conn: sqlite3.Connection) -> int:
        """テンプレートデータを移行"""
        migrated_count = 0
        templates_file = self.jsonl_path.parent / "templates.json"

        if not templates_file.exists():
            self.logger.info("Templates file does not exist, skipping template migration")
            return 0

        self.logger.info(f"Migrating templates from {templates_file}")

        try:
            with open(templates_file, 'r', encoding='utf-8') as f:
                templates_data = json.load(f)

            for template_id, template_data in templates_data.items():
                try:
                    name = template_data.get('name', f'template_{template_id}')
                    content = template_data.get('content', '')
                    category = template_data.get('category', 'templates')
                    tags = template_data.get('tags', [])
                    created_at = template_data.get('created_at', datetime.now(timezone.utc).isoformat())

                    # タグを文字列に変換
                    if isinstance(tags, list):
                        tags_str = ','.join(str(tag) for tag in tags)
                    else:
                        tags_str = str(tags)

                    conn.execute("""
                        INSERT INTO templates (id, name, content, category, tags, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (template_id, name, content, category, tags_str, created_at))

                    migrated_count += 1

                except Exception as e:
                    self.logger.error(f"Error migrating template {template_id}: {e}")
                    continue

        except json.JSONDecodeError as e:
            self.logger.error(f"Error reading templates file: {e}")

        return migrated_count

    def create_backup(self) -> bool:
        """JSONLファイルのバックアップを作成"""
        if not self.jsonl_path.exists():
            return True

        try:
            shutil.copy2(self.jsonl_path, self.backup_path)
            self.logger.info(f"Created backup: {self.backup_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            return False

    def migrate(self) -> bool:
        """移行を実行"""
        self.logger.info("Starting SQLite migration...")

        # バックアップ作成
        if not self.create_backup():
            return False

        try:
            # SQLite接続
            conn = sqlite3.connect(str(self.sqlite_path))

            # スキーマ作成
            self.create_schema(conn)

            # データ移行
            memos_count = self.migrate_memos(conn)
            templates_count = self.migrate_templates(conn)

            # コミット
            conn.commit()
            conn.close()

            self.logger.info("Migration completed successfully!")
            self.logger.info(f"Migrated {memos_count} memos and {templates_count} templates")

            return True

        except Exception as e:
            self.logger.error(f"Migration failed: {e}")
            return False

    def verify_migration(self) -> bool:
        """移行結果を検証"""
        if not self.sqlite_path.exists():
            self.logger.error("SQLite database not found")
            return False

        try:
            conn = sqlite3.connect(str(self.sqlite_path))

            # メモ数の確認
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memos")
            sqlite_count = cursor.fetchone()[0]

            # JSONLファイルの行数確認
            jsonl_count = 0
            if self.jsonl_path.exists():
                with open(self.jsonl_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            jsonl_count += 1

            conn.close()

            self.logger.info(f"Verification: JSONL had {jsonl_count} lines, SQLite has {sqlite_count} memos")

            if abs(sqlite_count - jsonl_count) > max(1, jsonl_count * 0.1):  # 10%以内の誤差を許容
                self.logger.warning("Migration count mismatch - manual verification recommended")
                return False

            return True

        except Exception as e:
            self.logger.error(f"Verification failed: {e}")
            return False


def main():
    """メイン関数"""
    if len(sys.argv) != 3:
        print("Usage: python migrate_to_sqlite.py <jsonl_file> <sqlite_file>")
        sys.exit(1)

    jsonl_path = Path(sys.argv[1])
    sqlite_path = Path(sys.argv[2])

    # 移行ツールの実行
    migrator = SQLiteMigrationTool(jsonl_path, sqlite_path)

    if migrator.migrate():
        if migrator.verify_migration():
            print("✅ Migration completed successfully!")
            return 0
        else:
            print("⚠️  Migration completed but verification failed")
            return 1
    else:
        print("❌ Migration failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

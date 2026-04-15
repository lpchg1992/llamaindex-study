#!/usr/bin/env python3
"""
临时数据库迁移脚本，用于修复项目过程中数据、数据库变化导致的问题，补充正确的数据到数据表。

通过 _schema_migrations 表跟踪迁移执行状态，确保每个迁移只执行一次。
可通过 `python scripts/migrate.py` 独立运行，或由 DatabaseManager 在初始化时自动调用。

迁移列表：
- 001_vendor_to_vendor_id: vendor 列重命名为 vendor_id
- 002_add_zotero_doc_id: 添加 zotero_doc_id 字段和索引
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text


def _get_engine():
    from kb_core.database import get_db
    return get_db().engine


def _ensure_migrations_table():
    engine = _get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at REAL NOT NULL
            )
        """)


def _is_migration_applied(migration_id: str) -> bool:
    engine = _get_engine()
    with engine.begin() as conn:
        result = conn.exec_driver_sql(
            "SELECT 1 FROM _schema_migrations WHERE id = ?",
            (migration_id,)
        )
        return result.fetchone() is not None


def _record_migration(migration_id: str) -> None:
    import time
    engine = _get_engine()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO _schema_migrations (id, applied_at) VALUES (?, ?)",
            (migration_id, time.time())
        )


def _migrate_001_vendor_to_vendor_id() -> None:
    if _is_migration_applied("001_vendor_to_vendor_id"):
        return
    engine = _get_engine()
    from sqlalchemy import inspect
    insp = inspect(engine)
    if "models" not in insp.get_table_names():
        _record_migration("001_vendor_to_vendor_id")
        return
    columns = {c["name"] for c in insp.get_columns("models")}
    if "vendor" not in columns or "vendor_id" in columns:
        _record_migration("001_vendor_to_vendor_id")
        return
    print("检测到旧版 models 表，正在迁移数据...")
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE models RENAME TO models_old")
        conn.exec_driver_sql("""
            CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY,
                vendor_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                is_default INTEGER DEFAULT 0,
                config TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.exec_driver_sql("""
            INSERT INTO models (id, vendor_id, name, type, is_active, is_default, config, created_at, updated_at)
            SELECT id, vendor, name, type, is_active, is_default, config, created_at, updated_at FROM models_old
        """)
        conn.exec_driver_sql("DROP TABLE models_old")
    _record_migration("001_vendor_to_vendor_id")
    print("001_vendor_to_vendor_id 迁移完成")


def _migrate_002_add_zotero_doc_id() -> None:
    if _is_migration_applied("002_add_zotero_doc_id"):
        return
    engine = _get_engine()
    from sqlalchemy import inspect
    insp = inspect(engine)
    if "documents" not in insp.get_table_names():
        _record_migration("002_add_zotero_doc_id")
        return
    columns = {c["name"] for c in insp.get_columns("documents")}
    if "zotero_doc_id" not in columns:
        print("迁移 documents 表：添加 zotero_doc_id 列")
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE documents ADD COLUMN zotero_doc_id TEXT"
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS idx_documents_zotero_doc_id ON documents(zotero_doc_id)"
            )
        _backfill_zotero_doc_id()
    _record_migration("002_add_zotero_doc_id")
    print("002_add_zotero_doc_id 迁移完成")


def _backfill_zotero_doc_id() -> None:
    engine = _get_engine()
    with engine.begin() as conn:
        result = conn.exec_driver_sql(
            "SELECT id FROM documents WHERE zotero_doc_id IS NULL AND id LIKE 'zotero_%'"
        )
        rows = result.fetchall()
    if not rows:
        print("没有需要回填的 zotero_doc_id 记录")
        return
    updated = 0
    for row in rows:
        doc_id = row[0]
        m = re.match(r"^zotero_(\d+)", doc_id)
        if m:
            zotero_doc_id = m.group(1)
            with engine.begin() as conn:
                conn.exec_driver_sql(
                    "UPDATE documents SET zotero_doc_id = ? WHERE id = ?",
                    (zotero_doc_id, doc_id)
                )
            updated += 1
    print(f"回填 zotero_doc_id 完成，共更新 {updated} 条记录")


def run_all_migrations() -> None:
    _ensure_migrations_table()
    _migrate_001_vendor_to_vendor_id()
    _migrate_002_add_zotero_doc_id()


if __name__ == "__main__":
    run_all_migrations()

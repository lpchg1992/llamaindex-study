#!/usr/bin/env python3
"""
任务队列数据库迁移脚本

通过 _schema_migrations 表跟踪迁移执行状态，确保每个迁移只执行一次。
可通过 `python scripts/migrate_task_queue.py` 独立运行。

迁移列表：
- 001_add_last_heartbeat: 添加 last_heartbeat 列
- 002_add_file_progress: 添加 file_progress 列
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _get_engine():
    from rag.config import get_settings
    from sqlalchemy import create_engine

    settings = get_settings()
    db_path = Path(settings.data_dir).expanduser()
    db_path.mkdir(parents=True, exist_ok=True)
    db_path = db_path / "tasks.db"
    return create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"timeout": 30, "check_same_thread": False},
    )


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


def _migrate_001_add_last_heartbeat() -> None:
    if _is_migration_applied("001_add_last_heartbeat"):
        return
    engine = _get_engine()
    from sqlalchemy import inspect
    insp = inspect(engine)
    if "tasks" not in insp.get_table_names():
        _record_migration("001_add_last_heartbeat")
        return
    columns = {c["name"] for c in insp.get_columns("tasks")}
    if "last_heartbeat" not in columns:
        print("迁移 tasks 表：添加 last_heartbeat 列")
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN last_heartbeat REAL")
    _record_migration("001_add_last_heartbeat")
    print("001_add_last_heartbeat 迁移完成")


def _migrate_002_add_file_progress() -> None:
    if _is_migration_applied("002_add_file_progress"):
        return
    engine = _get_engine()
    from sqlalchemy import inspect
    insp = inspect(engine)
    if "tasks" not in insp.get_table_names():
        _record_migration("002_add_file_progress")
        return
    columns = {c["name"] for c in insp.get_columns("tasks")}
    if "file_progress" not in columns:
        print("迁移 tasks 表：添加 file_progress 列")
        with engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN file_progress TEXT")
    _record_migration("002_add_file_progress")
    print("002_add_file_progress 迁移完成")


def run_all_migrations() -> None:
    _ensure_migrations_table()
    _migrate_001_add_last_heartbeat()
    _migrate_002_add_file_progress()


if __name__ == "__main__":
    run_all_migrations()
"""
统一 SQLite 数据库模块

管理项目中所有适合用数据库存储的数据：
1. 同步状态 - 文件哈希、修改时间、doc_id
2. 去重记录 - 文件哈希、doc_id、chunk_count
3. 处理进度 - 当前进度、断点信息
4. 知识库元数据 - 名称、描述、配置

使用方式：
```python
from kb.database import get_db, SyncStateDB, DedupStateDB, ProgressDB

# 获取数据库连接
db = get_db()

# 同步状态管理
sync_db = SyncStateDB(db)
sync_db.update_state("kb_id", "/path/file.md", "hash123", "doc_id")
records = sync_db.get_records("kb_id")

# 去重状态管理
dedup_db = DedupStateDB(db)
is_duplicate = dedup_db.check_hash("kb_id", "hash123")

# 进度管理
progress_db = ProgressDB(db)
progress_db.update("kb_id", current=5, total=10)
```

数据库 Schema：
- sync_states: 文件同步状态
- dedup_records: 去重记录
- progress: 处理进度
- knowledge_bases: 知识库元数据
"""

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Generator

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


# ==================== 数据库路径 ====================

def get_db_path() -> Path:
    """获取数据库路径"""
    settings = get_settings()
    data_dir = Path(settings.data_dir or "/Users/luopingcheng/.llamaindex").expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "project.db"


# ==================== 连接管理 ====================

class DatabaseManager:
    """数据库管理器（单例）"""
    
    _instance: Optional["DatabaseManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        
        self.db_path = get_db_path()
        self._local = threading.local()
        self._init_database()
    
    def _init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        try:
            self._create_tables(conn)
        finally:
            conn.close()
    
    def _create_tables(self, conn: sqlite3.Connection):
        """创建所有表"""
        cursor = conn.cursor()
        
        # 1. 同步状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                hash TEXT NOT NULL,
                mtime REAL NOT NULL,
                doc_id TEXT NOT NULL,
                last_synced REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(kb_id, file_path)
            )
        """)
        
        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sync_kb_id ON sync_states(kb_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_sync_hash ON sync_states(kb_id, hash)
        """)
        
        # 2. 去重记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dedup_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                hash TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                chunk_count INTEGER DEFAULT 0,
                mtime REAL NOT NULL,
                last_processed REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(kb_id, file_path)
            )
        """)
        
        # 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedup_kb_id ON dedup_records(kb_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedup_hash ON dedup_records(kb_id, hash)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedup_doc_id ON dedup_records(kb_id, doc_id)
        """)
        
        # 3. 处理进度表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT UNIQUE NOT NULL,
                task_type TEXT NOT NULL,
                current INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                processed_items TEXT DEFAULT '[]',
                failed_items TEXT DEFAULT '[]',
                started_at REAL,
                completed_at REAL,
                last_updated REAL NOT NULL
            )
        """)
        
        # 4. 知识库元数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                source_type TEXT NOT NULL,
                persist_path TEXT,
                tags TEXT DEFAULT '[]',
                config TEXT DEFAULT '{}',
                is_active INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        
        # 5. 任务历史表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                result TEXT,
                error TEXT,
                started_at REAL,
                completed_at REAL,
                created_at REAL NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_history_kb_id ON task_history(kb_id)
        """)
        
        conn.commit()
    
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取线程安全的数据库连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), timeout=30)
            self._local.conn.row_factory = sqlite3.Row
        try:
            yield self._local.conn
        except Exception:
            self._local.conn.rollback()
            raise
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行 SQL"""
        with self.get_connection() as conn:
            return conn.execute(sql, params)
    
    def executemany(self, sql: str, params_list: List[tuple]) -> sqlite3.Cursor:
        """批量执行 SQL"""
        with self.get_connection() as conn:
            return conn.executemany(sql, params_list)
    
    def commit(self):
        """提交事务"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.commit()
    
    def vacuum(self):
        """整理数据库"""
        with self.get_connection() as conn:
            conn.execute("VACUUM")


# 全局实例
_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """获取数据库管理器实例"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


@contextmanager
def get_cursor() -> Generator[sqlite3.Cursor, None, None]:
    """获取数据库游标（便捷函数）"""
    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            pass


# ==================== 同步状态管理 ====================

class SyncStateDB:
    """同步状态数据库操作"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def update_state(
        self,
        kb_id: str,
        file_path: str,
        hash: str,
        mtime: float,
        doc_id: str,
    ) -> bool:
        """
        更新同步状态
        
        Args:
            kb_id: 知识库 ID
            file_path: 文件相对路径
            hash: 文件哈希
            mtime: 修改时间
            doc_id: 文档 ID
            
        Returns:
            是否是新插入
        """
        now = time.time()
        
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO sync_states 
                (kb_id, file_path, hash, mtime, doc_id, last_synced, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id, file_path) DO UPDATE SET
                    hash = excluded.hash,
                    mtime = excluded.mtime,
                    doc_id = excluded.doc_id,
                    last_synced = excluded.last_synced,
                    updated_at = excluded.updated_at
            """, (kb_id, file_path, hash, mtime, doc_id, now, now, now))
            
            return cursor.rowcount > 0
    
    def bulk_update(self, kb_id: str, records: List[Dict[str, Any]]) -> int:
        """
        批量更新同步状态
        
        Args:
            kb_id: 知识库 ID
            records: 记录列表
            
        Returns:
            更新数量
        """
        if not records:
            return 0
        
        now = time.time()
        
        with self.db.get_connection() as conn:
            cursor = conn.executemany("""
                INSERT INTO sync_states 
                (kb_id, file_path, hash, mtime, doc_id, last_synced, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id, file_path) DO UPDATE SET
                    hash = excluded.hash,
                    mtime = excluded.mtime,
                    doc_id = excluded.doc_id,
                    last_synced = excluded.last_synced,
                    updated_at = excluded.updated_at
            """, [
                (kb_id, r["file_path"], r["hash"], r["mtime"], r["doc_id"], now, now, now)
                for r in records
            ])
            
            return cursor.rowcount
    
    def get_state(self, kb_id: str, file_path: str) -> Optional[Dict[str, Any]]:
        """获取同步状态"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM sync_states WHERE kb_id = ? AND file_path = ?
            """, (kb_id, file_path))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_records(self, kb_id: str) -> List[Dict[str, Any]]:
        """获取知识库的所有同步记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM sync_states WHERE kb_id = ? ORDER BY updated_at DESC
            """, (kb_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_hash_map(self, kb_id: str) -> Dict[str, str]:
        """获取 file_path -> hash 映射"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT file_path, hash FROM sync_states WHERE kb_id = ?
            """, (kb_id,))
            
            return {row["file_path"]: row["hash"] for row in cursor.fetchall()}
    
    def get_doc_id_map(self, kb_id: str) -> Dict[str, str]:
        """获取 file_path -> doc_id 映射"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT file_path, doc_id FROM sync_states WHERE kb_id = ?
            """, (kb_id,))
            
            return {row["file_path"]: row["doc_id"] for row in cursor.fetchall()}
    
    def has_hash(self, kb_id: str, hash: str) -> bool:
        """检查哈希是否存在"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM sync_states WHERE kb_id = ? AND hash = ? LIMIT 1
            """, (kb_id, hash))
            
            return cursor.fetchone() is not None
    
    def get_by_hash(self, kb_id: str, hash: str) -> Optional[Dict[str, Any]]:
        """根据哈希获取记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM sync_states WHERE kb_id = ? AND hash = ? LIMIT 1
            """, (kb_id, hash))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def remove(self, kb_id: str, file_path: str) -> bool:
        """删除同步状态"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM sync_states WHERE kb_id = ? AND file_path = ?
            """, (kb_id, file_path))
            
            return cursor.rowcount > 0
    
    def remove_many(self, kb_id: str, file_paths: List[str]) -> int:
        """批量删除同步状态"""
        if not file_paths:
            return 0
        
        placeholders = ",".join(["?"] * len(file_paths))
        with self.db.get_connection() as conn:
            cursor = conn.execute(f"""
                DELETE FROM sync_states WHERE kb_id = ? AND file_path IN ({placeholders})
            """, [kb_id] + file_paths)
            
            return cursor.rowcount
    
    def clear(self, kb_id: str) -> int:
        """清空知识库的同步状态"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM sync_states WHERE kb_id = ?
            """, (kb_id,))
            
            return cursor.rowcount
    
    def cleanup_orphaned(self, kb_id: str, valid_doc_ids: Set[str]) -> int:
        """清理孤立的记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM sync_states 
                WHERE kb_id = ? AND doc_id NOT IN ({})
            """.format(",".join(["?"] * len(valid_doc_ids))),
                [kb_id] + list(valid_doc_ids)
            )
            
            return cursor.rowcount
    
    def get_stats(self, kb_id: str) -> Dict[str, int]:
        """获取统计信息"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) as total FROM sync_states WHERE kb_id = ?
            """, (kb_id,))
            
            return {"total": cursor.fetchone()["total"]}


# ==================== 去重记录管理 ====================

class DedupStateDB:
    """去重记录数据库操作"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def add_record(
        self,
        kb_id: str,
        file_path: str,
        hash: str,
        doc_id: str,
        chunk_count: int = 0,
    ) -> bool:
        """
        添加去重记录
        
        Args:
            kb_id: 知识库 ID
            file_path: 文件路径
            hash: 文件哈希
            doc_id: 文档 ID
            chunk_count: chunk 数量
            
        Returns:
            是否成功
        """
        now = time.time()
        mtime = time.time()
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute("""
                    INSERT OR REPLACE INTO dedup_records 
                    (kb_id, file_path, hash, doc_id, chunk_count, mtime, last_processed, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (kb_id, file_path, hash, doc_id, chunk_count, mtime, now, now, now))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"   ⚠️  add_record 错误: {e}")
            return False
    
    def bulk_add(self, kb_id: str, records: List[Dict[str, Any]]) -> int:
        """
        批量添加去重记录
        
        Args:
            kb_id: 知识库 ID
            records: 记录列表
            
        Returns:
            添加数量
        """
        if not records:
            return 0
        
        now = time.time()
        
        with self.db.get_connection() as conn:
            cursor = conn.executemany("""
                INSERT INTO dedup_records 
                (kb_id, file_path, hash, doc_id, chunk_count, mtime, last_processed, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id, file_path) DO UPDATE SET
                    hash = excluded.hash,
                    doc_id = excluded.doc_id,
                    chunk_count = excluded.chunk_count,
                    last_processed = excluded.last_processed,
                    updated_at = excluded.updated_at
            """, [
                (kb_id, r["file_path"], r["hash"], r["doc_id"], r.get("chunk_count", 0), r.get("mtime", now), now, now, now)
                for r in records
            ])
            
            return cursor.rowcount
    
    def check_hash(self, kb_id: str, hash: str) -> bool:
        """检查哈希是否存在"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM dedup_records WHERE kb_id = ? AND hash = ? LIMIT 1
            """, (kb_id, hash))
            
            return cursor.fetchone() is not None
    
    def get_by_hash(self, kb_id: str, hash: str) -> Optional[Dict[str, Any]]:
        """根据哈希获取记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM dedup_records WHERE kb_id = ? AND hash = ? LIMIT 1
            """, (kb_id, hash))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_by_doc_id(self, kb_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
        """根据 doc_id 获取记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM dedup_records WHERE kb_id = ? AND doc_id = ? LIMIT 1
            """, (kb_id, doc_id))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_records(self, kb_id: str) -> List[Dict[str, Any]]:
        """获取知识库的所有去重记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM dedup_records WHERE kb_id = ? ORDER BY updated_at DESC
            """, (kb_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def get_hash_set(self, kb_id: str) -> Set[str]:
        """获取知识库的所有哈希集合"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT hash FROM dedup_records WHERE kb_id = ?
            """, (kb_id,))
            
            return {row["hash"] for row in cursor.fetchall()}
    
    def update_chunk_count(self, kb_id: str, doc_id: str, chunk_count: int) -> bool:
        """更新 chunk 数量"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE dedup_records 
                SET chunk_count = ?, updated_at = ?
                WHERE kb_id = ? AND doc_id = ?
            """, (chunk_count, time.time(), kb_id, doc_id))
            
            return cursor.rowcount > 0
    
    def remove(self, kb_id: str, file_path: str) -> bool:
        """删除去重记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM dedup_records WHERE kb_id = ? AND file_path = ?
            """, (kb_id, file_path))
            
            return cursor.rowcount > 0
    
    def remove_many(self, kb_id: str, file_paths: List[str]) -> int:
        """批量删除去重记录"""
        if not file_paths:
            return 0
        
        placeholders = ",".join(["?"] * len(file_paths))
        with self.db.get_connection() as conn:
            cursor = conn.execute(f"""
                DELETE FROM dedup_records WHERE kb_id = ? AND file_path IN ({placeholders})
            """, [kb_id] + file_paths)
            
            return cursor.rowcount
    
    def clear(self, kb_id: str) -> int:
        """清空知识库的去重记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM dedup_records WHERE kb_id = ?
            """, (kb_id,))
            
            return cursor.rowcount
    
    def get_stats(self, kb_id: str) -> Dict[str, int]:
        """获取统计信息"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(chunk_count) as total_chunks
                FROM dedup_records WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            return {
                "total": row["total"] or 0,
                "total_chunks": row["total_chunks"] or 0,
            }


# ==================== 进度管理 ====================

class ProgressDB:
    """处理进度数据库操作"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def get_or_create(self, kb_id: str, task_type: str = "import") -> Dict[str, Any]:
        """获取或创建进度记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            
            # 创建新记录
            now = time.time()
            conn.execute("""
                INSERT INTO progress 
                (kb_id, task_type, current, total, processed_items, failed_items, last_updated)
                VALUES (?, ?, 0, 0, '[]', '[]', ?)
            """, (kb_id, task_type, now))
            
            return {
                "kb_id": kb_id,
                "task_type": task_type,
                "current": 0,
                "total": 0,
                "processed_items": [],
                "failed_items": [],
                "last_updated": now,
            }
    
    def update(
        self,
        kb_id: str,
        current: int = None,
        total: int = None,
        processed_items: List[str] = None,
        failed_items: List[str] = None,
        task_type: str = "import",
    ) -> Dict[str, Any]:
        """
        更新进度
        
        Args:
            kb_id: 知识库 ID
            current: 当前进度
            total: 总数
            processed_items: 已处理项目列表
            failed_items: 失败项目列表
            task_type: 任务类型
            
        Returns:
            更新后的记录
        """
        now = time.time()
        
        with self.db.get_connection() as conn:
            # 获取现有记录
            cursor = conn.execute("""
                SELECT * FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            
            if not row:
                # 创建新记录
                conn.execute("""
                    INSERT INTO progress 
                    (kb_id, task_type, current, total, processed_items, failed_items, last_updated)
                    VALUES (?, ?, ?, ?, '[]', '[]', ?)
                """, (kb_id, task_type, current or 0, total or 0, now))
                
                return {
                    "kb_id": kb_id,
                    "current": current or 0,
                    "total": total or 0,
                    "processed_items": [],
                    "failed_items": [],
                }
            
            # 更新现有记录
            current_value = current if current is not None else row["current"]
            total_value = total if total is not None else row["total"]
            
            # 合并已处理项目
            existing_processed = json.loads(row["processed_items"] or "[]")
            existing_failed = json.loads(row["failed_items"] or "[]")
            
            if processed_items is not None:
                existing_processed.extend(processed_items)
            if failed_items is not None:
                existing_failed.extend(failed_items)
            
            conn.execute("""
                UPDATE progress SET
                    current = ?,
                    total = ?,
                    processed_items = ?,
                    failed_items = ?,
                    last_updated = ?
                WHERE kb_id = ?
            """, (
                current_value,
                total_value,
                json.dumps(existing_processed, ensure_ascii=False),
                json.dumps(existing_failed, ensure_ascii=False),
                now,
                kb_id
            ))
            
            return {
                "kb_id": kb_id,
                "current": current_value,
                "total": total_value,
                "processed_items": existing_processed,
                "failed_items": existing_failed,
                "last_updated": now,
            }
    
    def add_processed(self, kb_id: str, item_id: str) -> int:
        """添加已处理项目"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT processed_items FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            if not row:
                return 0
            
            items = json.loads(row["processed_items"] or "[]")
            if item_id not in items:
                items.append(item_id)
                conn.execute("""
                    UPDATE progress SET processed_items = ?, last_updated = ? WHERE kb_id = ?
                """, (json.dumps(items), time.time(), kb_id))
                return 1
            return 0
    
    def add_failed(self, kb_id: str, item_id: str) -> int:
        """添加失败项目"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT failed_items FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            if not row:
                return 0
            
            items = json.loads(row["failed_items"] or "[]")
            if item_id not in items:
                items.append(item_id)
                conn.execute("""
                    UPDATE progress SET failed_items = ?, last_updated = ? WHERE kb_id = ?
                """, (json.dumps(items), time.time(), kb_id))
                return 1
            return 0
    
    def increment(self, kb_id: str, delta: int = 1) -> int:
        """增加当前进度"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE progress SET current = current + ?, last_updated = ? WHERE kb_id = ?
            """, (delta, time.time(), kb_id))
            
            return cursor.rowcount
    
    def mark_started(self, kb_id: str, total: int = 0) -> Dict[str, Any]:
        """标记任务开始"""
        now = time.time()
        
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            
            if row:
                conn.execute("""
                    UPDATE progress SET 
                        started_at = ?,
                        current = 0,
                        total = ?,
                        processed_items = '[]',
                        failed_items = '[]',
                        last_updated = ?
                    WHERE kb_id = ?
                """, (now, total, now, kb_id))
            else:
                conn.execute("""
                    INSERT INTO progress 
                    (kb_id, task_type, current, total, processed_items, failed_items, started_at, last_updated)
                    VALUES (?, 'import', 0, ?, '[]', '[]', ?, ?)
                """, (kb_id, total, now, now))
            
            return self.get_or_create(kb_id)
    
    def mark_completed(self, kb_id: str) -> Dict[str, Any]:
        """标记任务完成"""
        now = time.time()
        
        with self.db.get_connection() as conn:
            conn.execute("""
                UPDATE progress SET completed_at = ?, last_updated = ? WHERE kb_id = ?
            """, (now, now, kb_id))
            
            cursor = conn.execute("""
                SELECT * FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {}
    
    def reset(self, kb_id: str) -> bool:
        """重置进度"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            return cursor.rowcount > 0
    
    def get(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """获取进度记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM progress WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    def get_all(self) -> List[Dict[str, Any]]:
        """获取所有进度记录"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM progress ORDER BY last_updated DESC
            """)
            
            return [dict(row) for row in cursor.fetchall()]


# ==================== 知识库元数据管理 ====================

class KnowledgeBaseMetaDB:
    """知识库元数据数据库操作"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    def upsert(
        self,
        kb_id: str,
        name: str,
        description: str = "",
        source_type: str = "unknown",
        persist_path: str = "",
        tags: List[str] = None,
        config: Dict[str, Any] = None,
    ) -> bool:
        """创建或更新知识库元数据"""
        now = time.time()
        
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO knowledge_bases 
                (kb_id, name, description, source_type, persist_path, tags, config, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kb_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    source_type = excluded.source_type,
                    persist_path = excluded.persist_path,
                    tags = excluded.tags,
                    config = excluded.config,
                    updated_at = excluded.updated_at
            """, (
                kb_id,
                name,
                description,
                source_type,
                persist_path,
                json.dumps(tags or [], ensure_ascii=False),
                json.dumps(config or {}, ensure_ascii=False),
                now,
                now
            ))
            
            return cursor.rowcount > 0
    
    def get(self, kb_id: str) -> Optional[Dict[str, Any]]:
        """获取知识库元数据"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM knowledge_bases WHERE kb_id = ?
            """, (kb_id,))
            
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
    
    def get_all(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """获取所有知识库元数据"""
        with self.db.get_connection() as conn:
            if active_only:
                cursor = conn.execute("""
                    SELECT * FROM knowledge_bases WHERE is_active = 1 ORDER BY updated_at DESC
                """)
            else:
                cursor = conn.execute("""
                    SELECT * FROM knowledge_bases ORDER BY updated_at DESC
                """)
            
            return [self._row_to_dict(row) for row in cursor.fetchall()]
    
    def set_active(self, kb_id: str, is_active: bool) -> bool:
        """设置知识库激活状态"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                UPDATE knowledge_bases SET is_active = ?, updated_at = ? WHERE kb_id = ?
            """, (1 if is_active else 0, time.time(), kb_id))
            
            return cursor.rowcount > 0
    
    def delete(self, kb_id: str) -> bool:
        """删除知识库元数据"""
        with self.db.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM knowledge_bases WHERE kb_id = ?
            """, (kb_id,))
            
            return cursor.rowcount > 0
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """行转字典"""
        data = dict(row)
        
        # 解析 JSON 字段
        if "tags" in data and isinstance(data["tags"], str):
            try:
                data["tags"] = json.loads(data["tags"])
            except json.JSONDecodeError:
                data["tags"] = []
        
        if "config" in data and isinstance(data["config"], str):
            try:
                data["config"] = json.loads(data["config"])
            except json.JSONDecodeError:
                data["config"] = {}
        
        return data


# ==================== 便捷函数 ====================

def init_sync_db() -> SyncStateDB:
    """获取同步状态数据库操作实例"""
    return SyncStateDB(get_db())


def init_dedup_db() -> DedupStateDB:
    """获取去重记录数据库操作实例"""
    return DedupStateDB(get_db())


def init_progress_db() -> ProgressDB:
    """获取进度数据库操作实例"""
    return ProgressDB(get_db())


def init_kb_meta_db() -> KnowledgeBaseMetaDB:
    """获取知识库元数据数据库操作实例"""
    return KnowledgeBaseMetaDB(get_db())

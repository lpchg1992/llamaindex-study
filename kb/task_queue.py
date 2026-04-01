"""
任务队列系统

基于 SQLite 的轻量级任务队列，支持：
- 任务提交、查询、取消
- 实时进度更新
- 后台任务执行
- 断点续传
"""

import asyncio
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from llamaindex_study.config import get_settings


class TaskStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"  # 等待中
    RUNNING = "running"  # 执行中
    PAUSED = "paused"  # 已暂停
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消


class TaskType(str, Enum):
    """任务类型"""

    ZOTERO = "zotero"  # Zotero 导入
    OBSIDIAN = "obsidian"  # Obsidian 导入
    GENERIC = "generic"  # 通用文件导入
    INITIALIZE = "initialize"  # 初始化知识库（清空数据）


@dataclass
class Task:
    """任务对象"""

    task_id: str
    task_type: str  # 任务类型
    status: str  # 状态
    kb_id: str  # 知识库 ID
    params: Dict[str, Any]  # 任务参数

    # 进度信息
    progress: int = 0  # 百分比 (0-100)
    current: int = 0  # 当前处理项
    total: int = 0  # 总项数
    message: str = ""  # 当前状态消息

    # 结果
    result: Optional[Dict] = None  # 结果数据
    error: Optional[str] = None  # 错误信息

    # 时间
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # 来源
    source: str = ""  # 来源描述

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status,
            "kb_id": self.kb_id,
            "params": self.params,
            "progress": self.progress,
            "current": self.current,
            "total": self.total,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "source": self.source,
        }


class TaskQueue:
    """
    任务队列管理器

    使用 SQLite 存储任务状态，支持：
    - 任务提交
    - 进度更新
    - 状态查询
    - 任务取消
    """

    _instance = None
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

        # 数据库路径
        settings = get_settings()
        self.db_path = Path(settings.data_dir).expanduser()
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_path / "tasks.db"

        # 初始化数据库
        self._init_db()

        # 活跃任务锁
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._task_events: Dict[str, asyncio.Event] = {}

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        # 启用 WAL 模式以支持并发
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                kb_id TEXT NOT NULL,
                params TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                current INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                result TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                source TEXT DEFAULT ''
            )
        """)

        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_kb_id ON tasks(kb_id)
        """)

        conn.commit()
        conn.close()

    def _row_to_task(self, row: tuple) -> Task:
        """行转任务对象"""
        return Task(
            task_id=row[0],
            task_type=row[1],
            status=row[2],
            kb_id=row[3],
            params=json.loads(row[4]),
            progress=row[5],
            current=row[6],
            total=row[7],
            message=row[8] or "",
            result=json.loads(row[9]) if row[9] else None,
            error=row[10],
            created_at=row[11],
            started_at=row[12],
            completed_at=row[13],
            source=row[14] or "",
        )

    def submit_task(
        self,
        task_type: str,
        kb_id: str,
        params: Dict[str, Any],
        source: str = "",
    ) -> str:
        """
        提交任务

        Args:
            task_type: 任务类型
            kb_id: 知识库 ID
            params: 任务参数
            source: 来源描述

        Returns:
            task_id
        """
        task_id = str(uuid.uuid4())[:8]

        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO tasks (
                task_id, task_type, status, kb_id, params, 
                progress, current, total, message, source, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                task_id,
                task_type,
                TaskStatus.PENDING.value,
                kb_id,
                json.dumps(params, ensure_ascii=False),
                0,
                0,
                0,
                "任务已提交",
                source,
                time.time(),
            ),
        )

        conn.commit()
        conn.close()

        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return self._row_to_task(row)
        return None

    def list_tasks(
        self,
        kb_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Task]:
        """列出任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        query = "SELECT * FROM tasks WHERE 1=1"
        params = []

        if kb_id:
            query += " AND kb_id = ?"
            params.append(kb_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_task(row) for row in rows]

    def update_progress(
        self,
        task_id: str,
        progress: int = None,
        current: int = None,
        total: int = None,
        message: str = None,
    ):
        """更新进度"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        updates = []
        params = []

        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if current is not None:
            updates.append("current = ?")
            params.append(current)
        if total is not None:
            updates.append("total = ?")
            params.append(total)
        if message is not None:
            updates.append("message = ?")
            params.append(message)

        if updates:
            params.append(task_id)
            cursor.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?", params
            )

        conn.commit()
        conn.close()

    def start_task(self, task_id: str):
        """开始任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE tasks 
            SET status = ?, started_at = ?, message = ?
            WHERE task_id = ?
        """,
            (TaskStatus.RUNNING.value, time.time(), "开始执行", task_id),
        )

        conn.commit()
        conn.close()

    def complete_task(self, task_id: str, result: Dict = None, error: str = None):
        """完成任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        status = TaskStatus.FAILED.value if error else TaskStatus.COMPLETED.value
        message = f"失败: {error}" if error else "已完成"

        cursor.execute(
            """
            UPDATE tasks 
            SET status = ?, completed_at = ?, message = ?, 
                result = ?, error = ?, progress = ?
            WHERE task_id = ?
        """,
            (
                status,
                time.time(),
                message,
                json.dumps(result, ensure_ascii=False) if result else None,
                error,
                100 if not error else None,
                task_id,
            ),
        )

        conn.commit()
        conn.close()

        # 通知等待者
        if task_id in self._task_events:
            self._task_events[task_id].set()

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        task = self.get_task(task_id)
        if not task:
            return False

        # 只能取消等待中的任务
        if task.status != TaskStatus.PENDING.value:
            return False

        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE tasks 
            SET status = ?, completed_at = ?, message = ?
            WHERE task_id = ? AND status = ?
        """,
            (
                TaskStatus.CANCELLED.value,
                time.time(),
                "已取消",
                task_id,
                TaskStatus.PENDING.value,
            ),
        )

        affected = cursor.rowcount
        conn.commit()
        conn.close()

        return affected > 0

    def update_status(self, task_id: str, status: str, message: str = ""):
        """更新任务状态"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE tasks 
            SET status = ?, message = ?
            WHERE task_id = ?
        """,
            (status, message, task_id),
        )

        conn.commit()
        conn.close()

    def get_pending(self, limit: int = 10) -> List[Task]:
        """获取待处理任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM tasks 
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
        """,
            (TaskStatus.PENDING.value, limit),
        )

        rows = cursor.fetchall()
        conn.close()

        return [self._row_to_task(row) for row in rows]

    def get_running_count(self) -> int:
        """获取正在运行的任务数量"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM tasks 
            WHERE status = ?
        """,
            (TaskStatus.RUNNING.value,),
        )

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        affected = cursor.rowcount

        conn.commit()
        conn.close()

        return affected > 0

    def cleanup_old_tasks(self, days: int = 7):
        """清理旧任务"""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        cursor = conn.cursor()

        cutoff = time.time() - (days * 24 * 60 * 60)

        cursor.execute(
            """
            DELETE FROM tasks 
            WHERE completed_at < ? AND status IN (?, ?, ?)
        """,
            (
                cutoff,
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ),
        )

        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted


# 全局实例
task_queue = TaskQueue()

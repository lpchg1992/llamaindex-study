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
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    update,
    create_engine,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    scoped_session,
    sessionmaker,
)

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
    last_heartbeat: Optional[float] = None  # 心跳时间

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
            "last_heartbeat": self.last_heartbeat,
            "source": self.source,
        }


class TaskBase(DeclarativeBase):
    pass


class TaskRecord(TaskBase):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_kb_id", "kb_id"),
    )
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    completed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_heartbeat: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 心跳时间
    source: Mapped[str] = mapped_column(Text, default="", nullable=False)


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

        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
        )
        self._session_factory = scoped_session(
            sessionmaker(
                bind=self.engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
            )
        )

        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        self._init_db()

        # 活跃任务锁
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._task_events: Dict[str, asyncio.Event] = {}

    def _init_db(self):
        TaskBase.metadata.create_all(self.engine)
        self._migrate_add_last_heartbeat()

    def _migrate_add_last_heartbeat(self):
        """迁移：添加 last_heartbeat 列（如果不存在）"""
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        columns = [c["name"] for c in inspector.get_columns("tasks")]
        if "last_heartbeat" not in columns:
            with self.engine.begin() as conn:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN last_heartbeat REAL")

    @contextmanager
    def _session_scope(self) -> Session:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _row_to_task(self, row: TaskRecord) -> Task:
        return Task(
            task_id=row.task_id,
            task_type=row.task_type,
            status=row.status,
            kb_id=row.kb_id,
            params=json.loads(row.params or "{}"),
            progress=row.progress,
            current=row.current,
            total=row.total,
            message=row.message or "",
            result=json.loads(row.result) if row.result else None,
            error=row.error,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            last_heartbeat=row.last_heartbeat,
            source=row.source or "",
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
        with self._session_scope() as session:
            session.add(
                TaskRecord(
                    task_id=task_id,
                    task_type=task_type,
                    status=TaskStatus.PENDING.value,
                    kb_id=kb_id,
                    params=json.dumps(params, ensure_ascii=False),
                    progress=0,
                    current=0,
                    total=0,
                    message="任务已提交",
                    source=source,
                    created_at=time.time(),
                )
            )

        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            return self._row_to_task(row) if row else None

    def list_tasks(
        self,
        kb_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Task]:
        """列出任务"""
        with self._session_scope() as session:
            stmt = select(TaskRecord)
            if kb_id:
                stmt = stmt.where(TaskRecord.kb_id == kb_id)
            if status:
                stmt = stmt.where(TaskRecord.status == status)
            rows = session.scalars(
                stmt.order_by(TaskRecord.created_at.desc()).limit(limit)
            ).all()
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
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            if progress is not None:
                row.progress = progress
            if current is not None:
                row.current = current
            if total is not None:
                row.total = total
            if message is not None:
                row.message = message

    def start_task(self, task_id: str):
        """开始任务"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.status = TaskStatus.RUNNING.value
            row.started_at = time.time()
            row.message = "开始执行"

    def complete_task(self, task_id: str, result: Dict = None, error: str = None):
        """完成任务"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.status = (
                TaskStatus.FAILED.value if error else TaskStatus.COMPLETED.value
            )
            row.completed_at = time.time()
            row.message = f"失败: {error}" if error else "已完成"
            row.result = json.dumps(result, ensure_ascii=False) if result else None
            row.error = error
            if not error:
                row.progress = 100

        # 通知等待者
        if task_id in self._task_events:
            self._task_events[task_id].set()

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row or row.status != TaskStatus.PENDING.value:
                return False
            row.status = TaskStatus.CANCELLED.value
            row.completed_at = time.time()
            row.message = "已取消"
            return True

    def update_status(self, task_id: str, status: str, message: str = ""):
        """更新任务状态"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.status = status
            row.message = message

    def get_pending(self, limit: int = 10) -> List[Task]:
        """获取待处理任务"""
        with self._session_scope() as session:
            rows = session.scalars(
                select(TaskRecord)
                .where(TaskRecord.status == TaskStatus.PENDING.value)
                .order_by(TaskRecord.created_at.asc())
                .limit(limit)
            ).all()
            return [self._row_to_task(row) for row in rows]

    def get_running_count(self) -> int:
        """获取正在运行的任务数量"""
        with self._session_scope() as session:
            count = session.scalar(
                select(func.count())
                .select_from(TaskRecord)
                .where(TaskRecord.status == TaskStatus.RUNNING.value)
            )
            return int(count or 0)

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        with self._session_scope() as session:
            result = session.execute(
                delete(TaskRecord).where(TaskRecord.task_id == task_id)
            )
            return (result.rowcount or 0) > 0

    def cleanup_old_tasks(self, days: int = 7):
        """清理旧任务"""
        cutoff = time.time() - (days * 24 * 60 * 60)
        with self._session_scope() as session:
            result = session.execute(
                delete(TaskRecord).where(
                    TaskRecord.completed_at < cutoff,
                    TaskRecord.status.in_(
                        [
                            TaskStatus.COMPLETED.value,
                            TaskStatus.FAILED.value,
                            TaskStatus.CANCELLED.value,
                        ]
                    ),
                )
            )
            return result.rowcount or 0

    def update_heartbeat(self, task_id: str):
        """更新任务心跳"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.last_heartbeat = time.time()

    def get_stale_tasks(self, timeout_seconds: float = 300) -> List["Task"]:
        """获取超时任务（RUNNING 但心跳过期的任务）"""
        cutoff = time.time() - timeout_seconds
        with self._session_scope() as session:
            rows = session.scalars(
                select(TaskRecord)
                .where(
                    TaskRecord.status == TaskStatus.RUNNING.value,
                    TaskRecord.last_heartbeat < cutoff,
                )
                .order_by(TaskRecord.started_at.asc())
            ).all()
            return [self._row_to_task(row) for row in rows]

    def recover_stale_tasks(self, timeout_seconds: float = 300) -> int:
        """恢复超时任务为 PENDING 状态，返回恢复的任务数量"""
        cutoff = time.time() - timeout_seconds
        with self._session_scope() as session:
            result = session.execute(
                update(TaskRecord)
                .where(
                    TaskRecord.status == TaskStatus.RUNNING.value,
                    TaskRecord.last_heartbeat < cutoff,
                )
                .values(
                    status=TaskStatus.PENDING.value,
                    message="任务超时已恢复",
                )
            )
            return result.rowcount or 0

    def get_tasks_needing_recovery(self) -> List["Task"]:
        """获取需要恢复的任务（数据库是 RUNNING 但没有心跳的）"""
        with self._session_scope() as session:
            rows = session.scalars(
                select(TaskRecord)
                .where(
                    TaskRecord.status == TaskStatus.RUNNING.value,
                    TaskRecord.last_heartbeat.is_(None),
                )
                .order_by(TaskRecord.started_at.asc())
            ).all()
            return [self._row_to_task(row) for row in rows]


# 全局实例
task_queue = TaskQueue()

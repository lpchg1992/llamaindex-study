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
from typing import Any, Dict, List, Optional, Tuple

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

from rag.config import get_settings


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
    REVECTOR = "revector"  # 重新向量化未成功向量化的 chunks
    CHECK_MARK_FAILED = "check_mark_failed"  # 检查并标记缺失向量的 chunks 为失败


class FileStatus(str, Enum):
    """文件处理状态"""

    PENDING = "pending"  # 等待处理
    PROCESSING = "processing"  # 处理中（解析）
    EMBEDDING = "embedding"  # 嵌入生成中
    WRITING = "writing"  # 写入数据库中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消（用户单独取消）


@dataclass
class FileProgressItem:
    """单个文件的进度跟踪"""

    file_id: str  # 唯一标识
    file_name: str  # 显示名称
    status: str = FileStatus.PENDING.value  # 处理状态
    total_chunks: int = 0  # 总 chunk 数
    processed_chunks: int = 0  # 已处理 chunk 数
    db_written: bool = False  # 是否已写入数据库
    error: Optional[str] = None  # 错误信息
    started_at: Optional[float] = None  # 开始时间
    completed_at: Optional[float] = None  # 完成时间

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "status": self.status,
            "total_chunks": self.total_chunks,
            "processed_chunks": self.processed_chunks,
            "db_written": self.db_written,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FileProgressItem":
        return cls(
            file_id=d["file_id"],
            file_name=d["file_name"],
            status=d.get("status", FileStatus.PENDING.value),
            total_chunks=d.get("total_chunks", 0),
            processed_chunks=d.get("processed_chunks", 0),
            db_written=d.get("db_written", False),
            error=d.get("error"),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
        )


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

    # 文件级进度
    file_progress: Optional[List[Dict[str, Any]]] = None  # List[FileProgressItem]

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
            "file_progress": self.file_progress,
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
    file_progress: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
        self._migrate_add_file_progress()

    def _migrate_add_last_heartbeat(self):
        """迁移：添加 last_heartbeat 列（如果不存在）"""
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        columns = [c["name"] for c in inspector.get_columns("tasks")]
        if "last_heartbeat" not in columns:
            with self.engine.begin() as conn:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN last_heartbeat REAL")

    def _migrate_add_file_progress(self):
        """迁移：添加 file_progress 列（如果不存在）"""
        from sqlalchemy import inspect

        inspector = inspect(self.engine)
        columns = [c["name"] for c in inspector.get_columns("tasks")]
        if "file_progress" not in columns:
            with self.engine.begin() as conn:
                conn.exec_driver_sql("ALTER TABLE tasks ADD COLUMN file_progress TEXT")

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
        file_progress = None
        if row.file_progress:
            try:
                file_progress = json.loads(row.file_progress)
            except json.JSONDecodeError:
                file_progress = None

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
            file_progress=file_progress,
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

            if result is None:
                result = {}

            skipped = result.get("skipped", 0)
            has_failure = bool(error) or skipped > 0

            row.status = TaskStatus.FAILED.value if has_failure else TaskStatus.COMPLETED.value
            row.completed_at = time.time()

            last_message = row.message

            if error:
                row.message = f"失败: {error}"
            else:
                success = result.get("success", 0)
                if skipped > 0:
                    row.message = f"部分完成: {success} 成功, {skipped} 失败"
                else:
                    row.message = "已完成"

            result["last_message"] = last_message

            row.result = json.dumps(result, ensure_ascii=False) if result else None
            row.error = error
            if not error:
                processed = result.get("processed_chunks", 0) if result else 0
                total = result.get("total_chunks", 0) if result else 0
                row.progress = (
                    int(processed / total * 100)
                    if total > 0
                    else (99 if processed > 0 else row.progress)
                )

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

    def set_file_progress(self, task_id: str, files: List[Dict[str, Any]]):
        """初始化文件列表（在任务开始时调用）"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return
            row.file_progress = json.dumps(files, ensure_ascii=False)

    def get_file_progress(self, task_id: str) -> List[Dict[str, Any]]:
        """获取任务的文件进度列表"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row or not row.file_progress:
                return []
            try:
                return json.loads(row.file_progress)
            except json.JSONDecodeError:
                return []

    def update_file_progress(
        self,
        task_id: str,
        file_id: str,
        status: str = None,
        processed_chunks: int = None,
        total_chunks: int = None,
        db_written: bool = None,
        error: str = None,
        file_name: str = None,
    ):
        """更新单个文件的进度"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return

            files = []
            if row.file_progress:
                try:
                    files = json.loads(row.file_progress)
                except json.JSONDecodeError:
                    files = []

            for f in files:
                if f.get("file_id") == file_id:
                    if status is not None:
                        f["status"] = status
                    if processed_chunks is not None:
                        f["processed_chunks"] = processed_chunks
                    if total_chunks is not None:
                        f["total_chunks"] = total_chunks
                    if db_written is not None:
                        f["db_written"] = db_written
                    if error is not None:
                        f["error"] = error
                    if file_name is not None:
                        f["file_name"] = file_name
                    if (
                        status == FileStatus.PROCESSING.value
                        and f.get("started_at") is None
                    ):
                        f["started_at"] = time.time()
                    if status in (
                        FileStatus.COMPLETED.value,
                        FileStatus.FAILED.value,
                        FileStatus.CANCELLED.value,
                    ):
                        f["completed_at"] = time.time()
                    break

            row.file_progress = json.dumps(files, ensure_ascii=False)

    def cancel_file(self, task_id: str, file_id: str) -> bool:
        """取消单个文件（标记为 cancelled，后续跳过）"""
        with self._session_scope() as session:
            row = session.get(TaskRecord, task_id)
            if not row:
                return False

            files = []
            if row.file_progress:
                try:
                    files = json.loads(row.file_progress)
                except json.JSONDecodeError:
                    return False

            for f in files:
                if f.get("file_id") == file_id:
                    current_status = f.get("status")
                    if current_status in (
                        FileStatus.COMPLETED.value,
                        FileStatus.FAILED.value,
                        FileStatus.CANCELLED.value,
                    ):
                        return False
                    f["status"] = FileStatus.CANCELLED.value
                    f["completed_at"] = time.time()
                    row.file_progress = json.dumps(files, ensure_ascii=False)
                    return True

            return False

    def get_file_status(self, task_id: str, file_id: str) -> Optional[str]:
        """获取单个文件的状态"""
        files = self.get_file_progress(task_id)
        for f in files:
            if f.get("file_id") == file_id:
                return f.get("status")
        return None

    def compute_chunk_progress(self, task_id: str) -> Tuple[int, int]:
        """计算 chunk 进度，返回 (已处理, 总数)"""
        files = self.get_file_progress(task_id)
        total_chunks = sum(f.get("total_chunks", 0) for f in files)
        processed_chunks = sum(f.get("processed_chunks", 0) for f in files)
        return processed_chunks, total_chunks


# 全局实例
task_queue = TaskQueue()

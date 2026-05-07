import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    scoped_session,
    sessionmaker,
)

from rag.config import get_settings
from rag.logger import get_logger

logger = get_logger(__name__)


def get_db_path() -> Path:
    settings = get_settings()
    data_dir = Path(settings.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "project.db"


class Base(DeclarativeBase):
    pass


class ProgressModel(Base):
    __tablename__ = "progress"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    current: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_items: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    failed_items: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    completed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_updated: Mapped[float] = mapped_column(Float, nullable=False)


class KnowledgeBaseMetaModel(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    persist_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    topics: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    source_paths: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    source_tags: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    config: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class TaskHistoryModel(Base):
    __tablename__ = "task_history"
    __table_args__ = (Index("idx_history_kb_id", "kb_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    completed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class VendorModel(Base):
    __tablename__ = "vendors"
    __table_args__ = (Index("idx_vendors_active", "is_active"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    api_base: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class ModelModel(Base):
    __tablename__ = "models"
    __table_args__ = (
        Index("idx_models_vendor_id", "vendor_id"),
        Index("idx_models_type", "type"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    vendor_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_default: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    config: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)


class DocumentModel(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_kb_id", "kb_id"),
        Index("idx_documents_hash", "file_hash"),
        Index("idx_documents_zotero_doc_id", "zotero_doc_id"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    source_file: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    file_hash: Mapped[str] = mapped_column(String, nullable=False)
    zotero_doc_id: Mapped[str] = mapped_column(String, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String, default="")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    total_chars: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)


class ChunkModel(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("idx_chunks_doc_id", "doc_id"),
        Index("idx_chunks_kb_id", "kb_id"),
        Index("idx_chunks_parent", "parent_chunk_id"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text)
    text_length: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    parent_chunk_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    hierarchy_level: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    embedding_generated: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[float] = mapped_column(Float)


def _json_dump(data: Any, default: Any) -> str:
    if data is None:
        data = default
    return json.dumps(data, ensure_ascii=False)


def _json_load(data: Optional[str], default: Any) -> Any:
    if not data:
        return default
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return default


class DatabaseManager:
    """
    SQLite 数据库管理器（单例模式）

    初始化流程:
        get_db() → __new__() → __init__() → _register_sqlite_pragmas() → _init_database()
                                                               ↓
                                                    scripts/migrate.run_all_migrations()

    数据流:
        调用方 → session_scope() → Session → CRUD → commit/rollback → close()

    self vs cls:
        cls._instance: 类属性，所有实例共享（单例标志）
        self._initialized: 实例属性，首次初始化后防止重复执行
        hasattr(self, "_initialized"): 先查实例属性，再查类属性，所以能检测到
    """
    _instance: Optional["DatabaseManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        """线程安全的单例实现（双检锁）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        初始化数据库连接池和迁移（仅执行一次）
        首次调用 get_db() 时触发，后续调用因 _initialized 存在而直接返回
        """
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self.db_path = get_db_path()
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
        )
        # scoped_session: 线程本地存储，同线程多次调用获同一 Session
        # autoflush=False: 手动 flush，避免隐式 SQL
        # autocommit=False: 手动提交
        # expire_on_commit=False: 提交后不 expire 对象
        self._session_factory = scoped_session(
            sessionmaker(
                bind=self.engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
            )
        )
        self._register_sqlite_pragmas()
        # 新建不存在的表
        Base.metadata.create_all(self.engine)

    def _register_sqlite_pragmas(self) -> None:
        """
        每次建立新连接时自动设置 SQLite PRAGMA
        - journal_mode=WAL: 支持并发读写
        - busy_timeout=30000: 30秒，避免数据库忙时直接报错
        """
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    # Session 生命周期管理器：自动 commit/rollback，线程安全
    # 用法: with db.session_scope() as session: session.execute(...)
    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        获取线程安全的 Session，自动管理事务
        用法: with db.session_scope() as session: session.execute(...)
        成功: 自动 commit 并 close
        异常: 自动 rollback 并 close
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def get_connection(self):
        """
        获取原始数据库连接（engine.begin()，自动管理事务）
        与 session_scope 的区别: 无 Session 包装，直接使用 SQLAlchemy Connection 对象
        应用场景: 执行原生 SQL、DDL、批量写入等不需要 ORM 的场景
        """
        with self.engine.begin() as conn:
            yield conn

    def execute(self, sql: str, params: tuple | dict = ()):
        """
        执行单条原生 SQL（自动事务）
        应用场景: 快速执行 DDL、count 查询等简单操作
        """
        with self.engine.begin() as conn:
            return conn.exec_driver_sql(sql, params)

    def executemany(self, sql: str, params_list: List[tuple]):
        """
        批量执行同一 SQL（自动事务）
        应用场景: 批量插入、批量更新
        注意: 非真正的 executemany，手动循环执行每条
        """
        with self.engine.begin() as conn:
            cursor = None
            for params in params_list:
                cursor = conn.exec_driver_sql(sql, params)
            return cursor

    def commit(self):
        """空实现（兼容旧代码）"""
        return None

    def vacuum(self):
        """
        压缩 SQLite 数据库文件（回收删除记录占用的空间）
        应用场景: 大量删除数据后执行，减小数据库文件体积
        注意: VACUUM 在单独的事务中执行，较慢
        """
        with self.engine.begin() as conn:
            conn.exec_driver_sql("VACUUM")


_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


class VendorDB:
    """供应商数据库访问层"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db

    def upsert(
        self,
        vendor_id: str,
        name: str,
        api_base: str = None,
        api_key: str = None,
        is_active: bool = True,
    ) -> bool:
        """插入或更新供应商
        
        Args:
            vendor_id: 供应商唯一标识
            name: 供应商名称
            api_base: API 基础 URL
            api_key: API 密钥
            is_active: 是否激活
            
        Returns:
            是否成功
        """
        now = time.time()
        stmt = sqlite_insert(VendorModel).values(
            id=vendor_id,
            name=name,
            api_base=api_base,
            api_key=api_key,
            is_active=1 if is_active else 0,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[VendorModel.id],
            set_={
                "name": stmt.excluded.name,
                "api_base": stmt.excluded.api_base,
                "api_key": stmt.excluded.api_key,
                "is_active": stmt.excluded.is_active,
                "updated_at": now,
            },
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        return True

    def get(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        """获取供应商详情
        
        Args:
            vendor_id: 供应商 ID
            
        Returns:
            供应商信息字典，不存在返回 None
        """
        with self.db.session_scope() as session:
            row = session.get(VendorModel, vendor_id)
            if not row:
                return None
            return {
                "id": row.id,
                "name": row.name,
                "api_base": row.api_base,
                "api_key": row.api_key,
                "is_active": bool(row.is_active),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    def get_all(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """获取所有供应商列表
        
        Args:
            active_only: 是否只返回激活的供应商
            
        Returns:
            供应商列表
        """
        with self.db.session_scope() as session:
            stmt = select(VendorModel)
            if active_only:
                stmt = stmt.where(VendorModel.is_active == 1)
            stmt = stmt.order_by(VendorModel.name)
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "api_base": row.api_base,
                    "api_key": row.api_key,
                    "is_active": bool(row.is_active),
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]

    def delete(self, vendor_id: str) -> bool:
        """删除供应商
        
        Args:
            vendor_id: 供应商 ID
            
        Returns:
            是否成功删除
        """
        with self.db.session_scope() as session:
            result = session.execute(
                delete(VendorModel).where(VendorModel.id == vendor_id)
            )
            return (result.rowcount or 0) > 0

    def set_active(self, vendor_id: str, is_active: bool) -> bool:
        """设置供应商激活状态
        
        Args:
            vendor_id: 供应商 ID
            is_active: 是否激活
            
        Returns:
            是否成功
        """
        with self.db.session_scope() as session:
            result = session.execute(
                update(VendorModel)
                .where(VendorModel.id == vendor_id)
                .values(is_active=1 if is_active else 0, updated_at=time.time())
            )
            return (result.rowcount or 0) > 0


class ModelDB:
    """模型数据库访问层"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db

    def upsert(
        self,
        model_id: str,
        vendor_id: str,
        name: str,
        type: str,
        is_active: bool = True,
        is_default: bool = False,
        config: dict = None,
    ) -> bool:
        """插入或更新模型
        
        Args:
            model_id: 模型唯一标识
            vendor_id: 供应商 ID
            name: 模型名称
            type: 模型类型 (embedding/llm)
            is_active: 是否激活
            is_default: 是否为默认模型
            config: 模型配置
            
        Returns:
            是否成功
        """
        now = time.time()
        stmt = sqlite_insert(ModelModel).values(
            id=model_id,
            vendor_id=vendor_id,
            name=name,
            type=type,
            is_active=1 if is_active else 0,
            is_default=1 if is_default else 0,
            config=_json_dump(config, {}),
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ModelModel.id],
            set_={
                "vendor_id": stmt.excluded.vendor_id,
                "name": stmt.excluded.name,
                "type": stmt.excluded.type,
                "is_active": stmt.excluded.is_active,
                "is_default": stmt.excluded.is_default,
                "config": stmt.excluded.config,
                "updated_at": now,
            },
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        return True

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        """获取模型详情
        
        Args:
            model_id: 模型 ID
            
        Returns:
            模型信息字典，不存在返回 None
        """
        with self.db.session_scope() as session:
            row = session.get(ModelModel, model_id)
            if not row:
                return None
            return {
                "id": row.id,
                "vendor_id": row.vendor_id,
                "name": row.name,
                "type": row.type,
                "is_active": bool(row.is_active),
                "is_default": bool(row.is_default),
                "config": _json_load(row.config, {}),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    def get_all(
        self, active_only: bool = True, type: str = None
    ) -> List[Dict[str, Any]]:
        """获取所有模型列表
        
        Args:
            active_only: 是否只返回激活的模型
            type: 按模型类型过滤
            
        Returns:
            模型列表
        """
        with self.db.session_scope() as session:
            stmt = select(ModelModel)
            if active_only:
                stmt = stmt.where(ModelModel.is_active == 1)
            if type:
                stmt = stmt.where(ModelModel.type == type)
            stmt = stmt.order_by(ModelModel.type, ModelModel.name)
            rows = session.scalars(stmt).all()
            return [
                {
                    "id": row.id,
                    "vendor_id": row.vendor_id,
                    "name": row.name,
                    "type": row.type,
                    "is_active": bool(row.is_active),
                    "is_default": bool(row.is_default),
                    "config": _json_load(row.config, {}),
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
                for row in rows
            ]

    def get_by_type(self, type: str) -> List[Dict[str, Any]]:
        """按类型获取模型列表
        
        Args:
            type: 模型类型
            
        Returns:
            激活的该类型模型列表
        """
        return self.get_all(active_only=True, type=type)

    def get_default(self, type: str = None) -> Optional[Dict[str, Any]]:
        """获取默认模型
        
        Args:
            type: 模型类型（可选）
            
        Returns:
            默认模型信息
        """
        with self.db.session_scope() as session:
            stmt = select(ModelModel).where(ModelModel.is_default == 1)
            if type:
                stmt = stmt.where(ModelModel.type == type)
            row = session.scalars(stmt.limit(1)).first()
            if not row:
                return None
            return {
                "id": row.id,
                "vendor_id": row.vendor_id,
                "name": row.name,
                "type": row.type,
                "is_active": bool(row.is_active),
                "is_default": bool(row.is_default),
                "config": _json_load(row.config, {}),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }

    def delete(self, model_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(ModelModel).where(ModelModel.id == model_id)
            )
            return (result.rowcount or 0) > 0

    def set_default(self, model_id: str) -> bool:
        with self.db.session_scope() as session:
            model = session.get(ModelModel, model_id)
            if not model:
                return False
            session.execute(
                update(ModelModel)
                .where(ModelModel.type == model.type)
                .values(is_default=0)
            )
            result = session.execute(
                update(ModelModel).where(ModelModel.id == model_id).values(is_default=1)
            )
            return (result.rowcount or 0) > 0


def init_vendor_db() -> VendorDB:
    return VendorDB(get_db())


def init_model_db() -> ModelDB:
    return ModelDB(get_db())


@contextmanager
def get_cursor():
    with get_db().get_connection() as conn:
        yield conn


class ProgressDB:
    """导入进度数据库访问层"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: ProgressModel) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "task_type": row.task_type,
            "current": row.current,
            "total": row.total,
            "processed_items": _json_load(row.processed_items, []),
            "failed_items": _json_load(row.failed_items, []),
            "started_at": row.started_at,
            "completed_at": row.completed_at,
            "last_updated": row.last_updated,
        }

    def get_or_create(self, kb_id: str, task_type: str = "import") -> Dict[str, Any]:
        """获取或创建进度记录
        
        Args:
            kb_id: 知识库 ID
            task_type: 任务类型
            
        Returns:
            进度记录
        """
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            if row:
                return self._to_dict(row)
            now = time.time()
            row = ProgressModel(
                kb_id=kb_id,
                task_type=task_type,
                current=0,
                total=0,
                processed_items="[]",
                failed_items="[]",
                last_updated=now,
            )
            session.add(row)
            session.flush()
            return self._to_dict(row)

    def update(
        self,
        kb_id: str,
        current: int = None,
        total: int = None,
        processed_items: List[str] = None,
        failed_items: List[str] = None,
        task_type: str = "import",
    ) -> Dict[str, Any]:
        now = time.time()
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            if not row:
                row = ProgressModel(
                    kb_id=kb_id,
                    task_type=task_type,
                    current=current or 0,
                    total=total or 0,
                    processed_items="[]",
                    failed_items="[]",
                    last_updated=now,
                )
                session.add(row)
                session.flush()
                return self._to_dict(row)

            row.current = current if current is not None else row.current
            row.total = total if total is not None else row.total
            merged_processed = _json_load(row.processed_items, [])
            merged_failed = _json_load(row.failed_items, [])
            if processed_items is not None:
                merged_processed.extend(processed_items)
            if failed_items is not None:
                merged_failed.extend(failed_items)
            row.processed_items = _json_dump(merged_processed, [])
            row.failed_items = _json_dump(merged_failed, [])
            row.last_updated = now
            return self._to_dict(row)

    def add_processed(self, kb_id: str, item_id: str) -> int:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            if not row:
                return 0
            items = _json_load(row.processed_items, [])
            if item_id in items:
                return 0
            items.append(item_id)
            row.processed_items = _json_dump(items, [])
            row.last_updated = time.time()
            return 1

    def add_failed(self, kb_id: str, item_id: str) -> int:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            if not row:
                return 0
            items = _json_load(row.failed_items, [])
            if item_id in items:
                return 0
            items.append(item_id)
            row.failed_items = _json_dump(items, [])
            row.last_updated = time.time()
            return 1

    def increment(self, kb_id: str, delta: int = 1) -> int:
        with self.db.session_scope() as session:
            result = session.execute(
                update(ProgressModel)
                .where(ProgressModel.kb_id == kb_id)
                .values(
                    current=ProgressModel.current + delta,
                    last_updated=time.time(),
                )
            )
            return result.rowcount or 0

    def mark_started(self, kb_id: str, total: int = 0) -> Dict[str, Any]:
        now = time.time()
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            if row:
                row.started_at = now
                row.current = 0
                row.total = total
                row.processed_items = "[]"
                row.failed_items = "[]"
                row.last_updated = now
                row.completed_at = None
            else:
                row = ProgressModel(
                    kb_id=kb_id,
                    task_type="import",
                    current=0,
                    total=total,
                    processed_items="[]",
                    failed_items="[]",
                    started_at=now,
                    last_updated=now,
                )
                session.add(row)
                session.flush()
            return self._to_dict(row)

    def mark_completed(self, kb_id: str) -> Dict[str, Any]:
        now = time.time()
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            if not row:
                return {}
            row.completed_at = now
            row.last_updated = now
            return self._to_dict(row)

    def reset(self, kb_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(ProgressModel).where(ProgressModel.kb_id == kb_id)
            )
            return (result.rowcount or 0) > 0

    def get(self, kb_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(ProgressModel).where(ProgressModel.kb_id == kb_id)
            ).first()
            return self._to_dict(row) if row else None

    def get_all(self) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ProgressModel).order_by(ProgressModel.last_updated.desc())
            ).all()
            return [self._to_dict(row) for row in rows]


class KnowledgeBaseMetaDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: KnowledgeBaseMetaModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "name": row.name,
            "description": row.description or "",
            "source_type": row.source_type,
            "persist_path": row.persist_path or "",
            "tags": _json_load(row.tags, []),
            "topics": _json_load(row.topics, []),
            "source_paths": _json_load(row.source_paths, []),
            "source_tags": _json_load(row.source_tags, []),
            "config": _json_load(row.config, {}),
            "is_active": row.is_active,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def upsert(
        self,
        kb_id: str,
        name: str,
        description: str = "",
        source_type: str = "unknown",
        persist_path: str = "",
        tags: List[str] = None,
        topics: List[str] = None,
        source_paths: List[str] = None,
        source_tags: List[str] = None,
        config: Dict[str, Any] = None,
    ) -> bool:
        now = time.time()
        stmt = sqlite_insert(KnowledgeBaseMetaModel).values(
            kb_id=kb_id,
            name=name,
            description=description,
            source_type=source_type,
            persist_path=persist_path,
            tags=_json_dump(tags, []),
            topics=_json_dump(topics, []),
            source_paths=_json_dump(source_paths, []),
            source_tags=_json_dump(source_tags, []),
            config=_json_dump(config, {}),
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[KnowledgeBaseMetaModel.kb_id],
            set_={
                "name": stmt.excluded.name,
                "description": stmt.excluded.description,
                "source_type": stmt.excluded.source_type,
                "persist_path": stmt.excluded.persist_path,
                "tags": stmt.excluded.tags,
                "topics": stmt.excluded.topics,
                "source_paths": stmt.excluded.source_paths,
                "source_tags": stmt.excluded.source_tags,
                "config": stmt.excluded.config,
                "is_active": 1,
                "updated_at": now,
            },
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        return True

    def get(self, kb_id: str, active_only: bool = True) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            stmt = select(KnowledgeBaseMetaModel).where(
                KnowledgeBaseMetaModel.kb_id == kb_id
            )
            if active_only:
                stmt = stmt.where(KnowledgeBaseMetaModel.is_active == 1)
            row = session.scalars(stmt).first()
            return self._to_dict(row) if row else None

    def get_all(self, active_only: bool = True) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            stmt = select(KnowledgeBaseMetaModel)
            if active_only:
                stmt = stmt.where(KnowledgeBaseMetaModel.is_active == 1)
            stmt = stmt.order_by(KnowledgeBaseMetaModel.updated_at.desc())
            rows = session.scalars(stmt).all()
            return [self._to_dict(row) for row in rows]

    def set_active(self, kb_id: str, is_active: bool) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(KnowledgeBaseMetaModel)
                .where(KnowledgeBaseMetaModel.kb_id == kb_id)
                .values(is_active=1 if is_active else 0, updated_at=time.time())
            )
            return (result.rowcount or 0) > 0

    def delete(self, kb_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(KnowledgeBaseMetaModel).where(
                    KnowledgeBaseMetaModel.kb_id == kb_id
                )
            )
            return (result.rowcount or 0) > 0

    def update_info(
        self,
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        updates: Dict[str, Any] = {"updated_at": time.time()}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description

        if len(updates) == 1:
            return False

        with self.db.session_scope() as session:
            result = session.execute(
                update(KnowledgeBaseMetaModel)
                .where(KnowledgeBaseMetaModel.kb_id == kb_id)
                .values(**updates)
            )
            return (result.rowcount or 0) > 0

    def update_topics(self, kb_id: str, topics: List[str]) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(KnowledgeBaseMetaModel)
                .where(KnowledgeBaseMetaModel.kb_id == kb_id)
                .values(topics=_json_dump(topics, []), updated_at=time.time())
            )
            return (result.rowcount or 0) > 0

    def get_topics(self, kb_id: str) -> List[str]:
        with self.db.session_scope() as session:
            topics = session.scalar(
                select(KnowledgeBaseMetaModel.topics)
                .where(KnowledgeBaseMetaModel.kb_id == kb_id)
                .limit(1)
            )
            return _json_load(topics, [])

    def seed_from_registry(
        self, kb_configs: List[Dict[str, Any]], source_type: str = "obsidian"
    ) -> int:
        count = 0
        for kb in kb_configs:
            persist_path = kb.get("persist_path") or kb.get("persist_name", "")
            self.upsert(
                kb_id=kb["id"],
                name=kb.get("name", kb["id"]),
                description=kb.get("description", ""),
                source_type=source_type,
                persist_path=persist_path,
                tags=kb.get("tags", []),
                topics=kb.get("topics", []),
                source_paths=kb.get("source_paths", []),
                source_tags=kb.get("source_tags", []),
            )
            count += 1
        return count


class DocumentDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: DocumentModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "source_file": row.source_file,
            "source_path": row.source_path,
            "file_hash": row.file_hash,
            "zotero_doc_id": row.zotero_doc_id,
            "file_size": row.file_size,
            "mime_type": row.mime_type,
            "chunk_count": row.chunk_count,
            "total_chars": row.total_chars,
            "metadata": _json_load(row.metadata_json, {}),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create(
        self,
        kb_id: str,
        source_file: str,
        source_path: str,
        file_hash: str,
        file_size: int = 0,
        mime_type: str = "",
        metadata: Dict[str, Any] = None,
        doc_id: Optional[str] = None,
        zotero_doc_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        if doc_id is None:
            doc_id = f"doc_{now}_{hash(source_file) % 100000:05d}"
        stmt = sqlite_insert(DocumentModel).values(
            id=doc_id,
            kb_id=kb_id,
            source_file=source_file,
            source_path=source_path,
            file_hash=file_hash,
            zotero_doc_id=zotero_doc_id,
            file_size=file_size,
            mime_type=mime_type,
            chunk_count=0,
            total_chars=0,
            metadata_json=_json_dump(metadata, {}),
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[DocumentModel.id],
            set_={
                "source_file": stmt.excluded.source_file,
                "source_path": stmt.excluded.source_path,
                "file_hash": stmt.excluded.file_hash,
                "zotero_doc_id": stmt.excluded.zotero_doc_id,
                "file_size": stmt.excluded.file_size,
                "mime_type": stmt.excluded.mime_type,
                "metadata_json": stmt.excluded.metadata_json,
                "updated_at": now,
            },
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        return self.get(doc_id)

    def get(self, doc_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.get(DocumentModel, doc_id)
            return self._to_dict(row) if row else None

    def get_by_zotero_doc_id(
        self, kb_id: str, zotero_doc_id: str
    ) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(DocumentModel).where(
                    DocumentModel.kb_id == kb_id,
                    DocumentModel.zotero_doc_id == zotero_doc_id,
                )
            ).first()
            return self._to_dict(row) if row else None

    def get_by_source_path(
        self, kb_id: str, source_path: str
    ) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(DocumentModel).where(
                    DocumentModel.kb_id == kb_id,
                    DocumentModel.source_path == source_path,
                )
            ).first()
            return self._to_dict(row) if row else None

    def get_by_kb(self, kb_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(DocumentModel)
                .where(DocumentModel.kb_id == kb_id)
                .order_by(DocumentModel.updated_at.desc())
            ).all()
            return [self._to_dict(row) for row in rows]

    def update_stats(
        self, doc_id: str, chunk_count: int = None, total_chars: int = None
    ) -> bool:
        with self.db.session_scope() as session:
            updates = {"updated_at": time.time()}
            # Always query actual chunk count from chunks table to ensure accuracy
            # (create_bulk uses INSERT OR IGNORE so passed count may be inaccurate)
            actual_count = (
                session.scalar(
                    select(func.count())
                    .select_from(ChunkModel)
                    .where(ChunkModel.doc_id == doc_id)
                )
                or 0
            )
            updates["chunk_count"] = actual_count
            if total_chars is not None:
                updates["total_chars"] = total_chars
            else:
                # Recalculate total_chars from actual chunks
                actual_chars = (
                    session.scalar(
                        select(func.sum(ChunkModel.text_length))
                        .select_from(ChunkModel)
                        .where(ChunkModel.doc_id == doc_id)
                    )
                    or 0
                )
                updates["total_chars"] = actual_chars
            result = session.execute(
                update(DocumentModel)
                .where(DocumentModel.id == doc_id)
                .values(**updates)
            )
            return (result.rowcount or 0) > 0

    def delete(self, doc_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(DocumentModel).where(DocumentModel.id == doc_id)
            )
            return (result.rowcount or 0) > 0

    def get_stats(self, kb_id: str) -> Dict[str, int]:
        with self.db.session_scope() as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(DocumentModel)
                    .where(DocumentModel.kb_id == kb_id)
                )
                or 0
            )
            total_chunks = (
                session.scalar(
                    select(func.sum(DocumentModel.chunk_count)).where(
                        DocumentModel.kb_id == kb_id
                    )
                )
                or 0
            )
            return {"document_count": int(total), "total_chunks": int(total_chunks)}


class ChunkDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: ChunkModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "doc_id": row.doc_id,
            "kb_id": row.kb_id,
            "text": row.text,
            "text_length": row.text_length,
            "chunk_index": row.chunk_index,
            "parent_chunk_id": row.parent_chunk_id,
            "hierarchy_level": row.hierarchy_level,
            "metadata": _json_load(row.metadata_json, {}),
            "embedding_generated": row.embedding_generated,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create(
        self,
        doc_id: str,
        kb_id: str,
        text: str,
        chunk_index: int = 0,
        parent_chunk_id: str = None,
        hierarchy_level: int = 0,
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        chunk_id = f"chunk_{now}_{hash(text[:50]) % 100000:05d}"
        stmt = sqlite_insert(ChunkModel).values(
            id=chunk_id,
            doc_id=doc_id,
            kb_id=kb_id,
            text=text,
            text_length=len(text),
            chunk_index=chunk_index,
            parent_chunk_id=parent_chunk_id,
            hierarchy_level=hierarchy_level,
            metadata_json=_json_dump(metadata or {}, {}),
            embedding_generated=0,
            created_at=now,
            updated_at=now,
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        return self.get(chunk_id)

    def create_bulk(self, chunks: List[Dict[str, Any]]) -> int:
        if not chunks:
            return 0
        now = time.time()
        with self.db.session_scope() as session:
            for chunk in chunks:
                stmt = sqlite_insert(ChunkModel).values(
                    id=chunk.get(
                        "id", f"chunk_{now}_{hash(chunk['text'][:50]) % 100000:05d}"
                    ),
                    doc_id=chunk["doc_id"],
                    kb_id=chunk["kb_id"],
                    text=chunk["text"],
                    text_length=len(chunk["text"]),
                    chunk_index=chunk.get("chunk_index", 0),
                    parent_chunk_id=chunk.get("parent_chunk_id"),
                    hierarchy_level=chunk.get("hierarchy_level", 0),
                    metadata_json=_json_dump(chunk.get("metadata", {}), {}),
                    embedding_generated=chunk.get("embedding_generated", 0),
                    created_at=now,
                    updated_at=now,
                )
                session.execute(stmt)
        return len(chunks)

    def get(self, chunk_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.get(ChunkModel, chunk_id)
            return self._to_dict(row) if row else None

    def get_by_doc(
        self, doc_id: str, offset: int = 0, limit: int = 50
    ) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.doc_id == doc_id)
                .order_by(ChunkModel.chunk_index, ChunkModel.hierarchy_level)
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._to_dict(row) for row in rows]

    def count_by_doc(self, doc_id: str) -> int:
        """Count total chunks for a document."""
        with self.db.session_scope() as session:
            count = session.scalar(
                select(func.count())
                .select_from(ChunkModel)
                .where(ChunkModel.doc_id == doc_id)
            )
            return int(count) if count else 0

    def count_by_doc_filtered(self, doc_id: str, embedding_status: int) -> int:
        """Count chunks for a document filtered by embedding status."""
        with self.db.session_scope() as session:
            count = session.scalar(
                select(func.count())
                .select_from(ChunkModel)
                .where(
                    ChunkModel.doc_id == doc_id,
                    ChunkModel.embedding_generated == embedding_status,
                )
            )
            return int(count) if count else 0

    def get_by_doc_filtered(
        self, doc_id: str, embedding_status: int, offset: int = 0, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get chunks for a document filtered by embedding status."""
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(
                    ChunkModel.doc_id == doc_id,
                    ChunkModel.embedding_generated == embedding_status,
                )
                .order_by(ChunkModel.chunk_index, ChunkModel.hierarchy_level)
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_by_kb(self, kb_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.kb_id == kb_id)
                .order_by(ChunkModel.updated_at.desc())
                .limit(limit)
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_children(self, parent_chunk_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.parent_chunk_id == parent_chunk_id)
                .order_by(ChunkModel.chunk_index)
            ).all()
            return [self._to_dict(row) for row in rows]

    def update_text(self, chunk_id: str, new_text: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id == chunk_id)
                .values(
                    text=new_text,
                    text_length=len(new_text),
                    embedding_generated=0,
                    updated_at=time.time(),
                )
            )
            return (result.rowcount or 0) > 0

    def mark_embedded(self, chunk_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id == chunk_id)
                .values(embedding_generated=1, updated_at=time.time())
            )
            return (result.rowcount or 0) > 0

    def mark_embedded_bulk(self, chunk_ids: List[str]) -> int:
        if not chunk_ids:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id.in_(chunk_ids))
                .values(embedding_generated=1, updated_at=time.time())
            )
            return result.rowcount or 0

    def mark_failed_bulk(self, chunk_ids: List[str]) -> int:
        if not chunk_ids:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id.in_(chunk_ids))
                .values(embedding_generated=2, updated_at=time.time())
            )
            return result.rowcount or 0

    def mark_success_bulk(self, chunk_ids: List[str]) -> int:
        if not chunk_ids:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id.in_(chunk_ids))
                .values(embedding_generated=1, updated_at=time.time())
            )
            return result.rowcount or 0

    def get_failed_chunks(self, kb_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 2)
                .limit(limit)
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_embedding_stats(self, kb_id: str) -> Dict[str, int]:
        with self.db.session_scope() as session:
            total = (
                session.scalar(
                    select(func.count(ChunkModel.id)).where(ChunkModel.kb_id == kb_id)
                )
                or 0
            )
            success = (
                session.scalar(
                    select(func.count(ChunkModel.id)).where(
                        ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 1
                    )
                )
                or 0
            )
            failed = (
                session.scalar(
                    select(func.count(ChunkModel.id)).where(
                        ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 2
                    )
                )
                or 0
            )
            pending = (
                session.scalar(
                    select(func.count(ChunkModel.id)).where(
                        ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 0
                    )
                )
                or 0
            )
            return {
                "total": total,
                "success": success,
                "failed": failed,
                "pending": pending,
            }

    def update_parent(self, chunk_id: str, new_parent_id: Optional[str]) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(ChunkModel)
                .where(ChunkModel.id == chunk_id)
                .values(parent_chunk_id=new_parent_id, updated_at=time.time())
            )
            return (result.rowcount or 0) > 0

    def delete(self, chunk_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(ChunkModel).where(ChunkModel.id == chunk_id)
            )
            return (result.rowcount or 0) > 0

    def delete_by_doc(self, doc_id: str) -> int:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(ChunkModel).where(ChunkModel.doc_id == doc_id)
            )
            return result.rowcount or 0

    def get_unembedded(self, kb_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 0)
                .limit(limit)
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_embedded(self, kb_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get chunks with embedding_generated=1 (success)"""
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.kb_id == kb_id, ChunkModel.embedding_generated == 1)
                .limit(limit)
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_doc_embedding_stats(self, kb_id: str) -> List[Dict[str, Any]]:
        """Get per-document embedding stats by checking LanceDB presence.

        Returns list of dicts with doc_id, total_chunks, in_lance_count, missing_count
        """
        from kb_storage.lance_crud import LanceCRUDService
        from .services import VectorStoreService

        docs = []
        with self.db.session_scope() as session:
            result = session.execute(
                select(ChunkModel.doc_id, func.count(ChunkModel.id).label("total"))
                .where(ChunkModel.kb_id == kb_id)
                .group_by(ChunkModel.doc_id)
            ).all()
            for row in result:
                docs.append({"doc_id": row[0], "total": row[1]})

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            lance_store = vs._get_lance_vector_store()
            lance_table = lance_store._connection.open_table(lance_store._table_name)
            lance_ids = set(lance_table.to_pandas()["id"].tolist())
        except Exception:
            lance_ids = set()

        result = []
        for doc in docs:
            doc_id = doc["doc_id"]
            total = doc["total"]

            with self.db.session_scope() as session:
                chunk_ids = session.scalars(
                    select(ChunkModel.id).where(ChunkModel.doc_id == doc_id)
                ).all()
                chunk_ids = [c for c in chunk_ids]

            in_lance = len([cid for cid in chunk_ids if cid in lance_ids])
            result.append(
                {
                    "doc_id": doc_id,
                    "total": total,
                    "in_lance": in_lance,
                    "missing": total - in_lance,
                }
            )

        return result

    def mark_chunks_missing_from_lance(
        self, kb_id: str, limit: int = 100000
    ) -> Dict[str, int]:
        """Check all chunks against LanceDB and mark those missing as failed.

        Returns dict with marked count
        """
        from kb_storage.lance_crud import LanceCRUDService
        from .services import VectorStoreService

        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel).where(ChunkModel.kb_id == kb_id).limit(limit)
            ).all()
            chunks = [self._to_dict(row) for row in rows]

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            lance_store = vs._get_lance_vector_store()
            lance_table = lance_store._connection.open_table(lance_store._table_name)
            lance_ids = set(lance_table.to_pandas()["id"].tolist())
        except Exception:
            lance_ids = set()

        to_mark_failed = []
        for chunk in chunks:
            if chunk["embedding_generated"] != 2:
                if chunk["id"] not in lance_ids:
                    to_mark_failed.append(chunk["id"])

        if to_mark_failed:
            self.mark_failed_bulk(to_mark_failed)

        return {"marked_failed": len(to_mark_failed), "total_checked": len(chunks)}


def init_progress_db() -> ProgressDB:
    return ProgressDB(get_db())


def init_kb_meta_db() -> KnowledgeBaseMetaDB:
    return KnowledgeBaseMetaDB(get_db())


def init_document_db() -> DocumentDB:
    return DocumentDB(get_db())


def init_chunk_db() -> ChunkDB:
    return ChunkDB(get_db())

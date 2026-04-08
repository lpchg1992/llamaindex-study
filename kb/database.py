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
    inspect,
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

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


def get_db_path() -> Path:
    settings = get_settings()
    data_dir = Path(settings.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "project.db"


class Base(DeclarativeBase):
    pass


class SyncStateModel(Base):
    __tablename__ = "sync_states"
    __table_args__ = (
        UniqueConstraint("kb_id", "file_path", name="uq_sync_kb_file"),
        Index("idx_sync_kb_id", "kb_id"),
        Index("idx_sync_hash", "kb_id", "hash"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False)
    mtime: Mapped[float] = mapped_column(Float, nullable=False)
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    last_synced: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class DedupRecordModel(Base):
    __tablename__ = "dedup_records"
    __table_args__ = (
        UniqueConstraint("kb_id", "file_path", name="uq_dedup_kb_file"),
        Index("idx_dedup_kb_id", "kb_id"),
        Index("idx_dedup_hash", "kb_id", "hash"),
        Index("idx_dedup_doc_id", "kb_id", "doc_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False)
    doc_id: Mapped[str] = mapped_column(String, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mtime: Mapped[float] = mapped_column(Float, nullable=False)
    last_processed: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


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


class CategoryRuleModel(Base):
    __tablename__ = "kb_category_rules"
    __table_args__ = (
        UniqueConstraint("kb_id", "rule_type", "pattern", name="uq_rule_key"),
        Index("idx_rules_kb_id", "kb_id"),
        Index("idx_rules_type", "rule_type"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    rule_type: Mapped[str] = mapped_column(String, nullable=False)
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


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
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    source_file: Mapped[str] = mapped_column(String, nullable=False)
    source_path: Mapped[str] = mapped_column(String, nullable=False)
    file_hash: Mapped[str] = mapped_column(String, nullable=False)
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
        self._register_sqlite_pragmas()
        self._init_database()

    def _register_sqlite_pragmas(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    def _init_database(self) -> None:
        Base.metadata.create_all(self.engine)
        self._migrate_legacy_models_table()

    def _migrate_legacy_models_table(self) -> None:
        insp = inspect(self.engine)
        if "models" not in insp.get_table_names():
            return
        columns = {c["name"] for c in insp.get_columns("models")}
        if "vendor" not in columns or "vendor_id" in columns:
            return
        logger.warning("检测到旧版 models 表，正在迁移数据...")
        with self.engine.begin() as conn:
            conn.exec_driver_sql("ALTER TABLE models RENAME TO models_old")
            conn.exec_driver_sql(
                """
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
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO models (id, vendor_id, name, type, is_active, is_default, config, created_at, updated_at)
                SELECT id, vendor, name, type, is_active, is_default, config, created_at, updated_at FROM models_old
                """
            )
            conn.exec_driver_sql("DROP TABLE models_old")
        logger.warning("models 表迁移完成")

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
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
        with self.engine.begin() as conn:
            yield conn

    def execute(self, sql: str, params: tuple | dict = ()):
        with self.engine.begin() as conn:
            return conn.exec_driver_sql(sql, params)

    def executemany(self, sql: str, params_list: List[tuple]):
        with self.engine.begin() as conn:
            cursor = None
            for params in params_list:
                cursor = conn.exec_driver_sql(sql, params)
            return cursor

    def commit(self):
        return None

    def vacuum(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("VACUUM")


_db_manager: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


class VendorDB:
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
        with self.db.session_scope() as session:
            result = session.execute(
                delete(VendorModel).where(VendorModel.id == vendor_id)
            )
            return (result.rowcount or 0) > 0

    def set_active(self, vendor_id: str, is_active: bool) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(VendorModel)
                .where(VendorModel.id == vendor_id)
                .values(is_active=1 if is_active else 0, updated_at=time.time())
            )
            return (result.rowcount or 0) > 0


class ModelDB:
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
        return self.get_all(active_only=True, type=type)

    def get_default(self, type: str = None) -> Optional[Dict[str, Any]]:
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


class SyncStateDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: SyncStateModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "file_path": row.file_path,
            "hash": row.hash,
            "mtime": row.mtime,
            "doc_id": row.doc_id,
            "last_synced": row.last_synced,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def update_state(
        self, kb_id: str, file_path: str, hash: str, mtime: float, doc_id: str
    ) -> bool:
        now = time.time()
        stmt = sqlite_insert(SyncStateModel).values(
            kb_id=kb_id,
            file_path=file_path,
            hash=hash,
            mtime=mtime,
            doc_id=doc_id,
            last_synced=now,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SyncStateModel.kb_id, SyncStateModel.file_path],
            set_={
                "hash": stmt.excluded.hash,
                "mtime": stmt.excluded.mtime,
                "doc_id": stmt.excluded.doc_id,
                "last_synced": stmt.excluded.last_synced,
                "updated_at": now,
            },
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        return True

    def bulk_update(self, kb_id: str, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        now = time.time()
        with self.db.session_scope() as session:
            for r in records:
                stmt = sqlite_insert(SyncStateModel).values(
                    kb_id=kb_id,
                    file_path=r["file_path"],
                    hash=r["hash"],
                    mtime=r["mtime"],
                    doc_id=r["doc_id"],
                    last_synced=now,
                    created_at=now,
                    updated_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[SyncStateModel.kb_id, SyncStateModel.file_path],
                    set_={
                        "hash": stmt.excluded.hash,
                        "mtime": stmt.excluded.mtime,
                        "doc_id": stmt.excluded.doc_id,
                        "last_synced": stmt.excluded.last_synced,
                        "updated_at": now,
                    },
                )
                session.execute(stmt)
        return len(records)

    def get_state(self, kb_id: str, file_path: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(SyncStateModel).where(
                    SyncStateModel.kb_id == kb_id,
                    SyncStateModel.file_path == file_path,
                )
            ).first()
            return self._to_dict(row) if row else None

    def get_records(self, kb_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(SyncStateModel)
                .where(SyncStateModel.kb_id == kb_id)
                .order_by(SyncStateModel.updated_at.desc())
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_hash_map(self, kb_id: str) -> Dict[str, str]:
        with self.db.session_scope() as session:
            rows = session.execute(
                select(SyncStateModel.file_path, SyncStateModel.hash).where(
                    SyncStateModel.kb_id == kb_id
                )
            ).all()
            return {file_path: hash_value for file_path, hash_value in rows}

    def get_doc_id_map(self, kb_id: str) -> Dict[str, str]:
        with self.db.session_scope() as session:
            rows = session.execute(
                select(SyncStateModel.file_path, SyncStateModel.doc_id).where(
                    SyncStateModel.kb_id == kb_id
                )
            ).all()
            return {file_path: doc_id for file_path, doc_id in rows}

    def has_hash(self, kb_id: str, hash: str) -> bool:
        with self.db.session_scope() as session:
            return (
                session.scalars(
                    select(SyncStateModel.id)
                    .where(SyncStateModel.kb_id == kb_id, SyncStateModel.hash == hash)
                    .limit(1)
                ).first()
                is not None
            )

    def get_by_hash(self, kb_id: str, hash: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(SyncStateModel)
                .where(SyncStateModel.kb_id == kb_id, SyncStateModel.hash == hash)
                .limit(1)
            ).first()
            return self._to_dict(row) if row else None

    def remove(self, kb_id: str, file_path: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(SyncStateModel).where(
                    SyncStateModel.kb_id == kb_id, SyncStateModel.file_path == file_path
                )
            )
            return (result.rowcount or 0) > 0

    def remove_many(self, kb_id: str, file_paths: List[str]) -> int:
        if not file_paths:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                delete(SyncStateModel).where(
                    SyncStateModel.kb_id == kb_id,
                    SyncStateModel.file_path.in_(file_paths),
                )
            )
            return result.rowcount or 0

    def clear(self, kb_id: str) -> int:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(SyncStateModel).where(SyncStateModel.kb_id == kb_id)
            )
            return result.rowcount or 0

    def cleanup_orphaned(self, kb_id: str, valid_doc_ids: Set[str]) -> int:
        with self.db.session_scope() as session:
            stmt = delete(SyncStateModel).where(SyncStateModel.kb_id == kb_id)
            if valid_doc_ids:
                stmt = stmt.where(~SyncStateModel.doc_id.in_(list(valid_doc_ids)))
            result = session.execute(stmt)
            return result.rowcount or 0

    def get_stats(self, kb_id: str) -> Dict[str, int]:
        with self.db.session_scope() as session:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(SyncStateModel)
                    .where(SyncStateModel.kb_id == kb_id)
                )
                or 0
            )
            return {"total": int(total)}


class DedupStateDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: DedupRecordModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "file_path": row.file_path,
            "hash": row.hash,
            "doc_id": row.doc_id,
            "chunk_count": row.chunk_count,
            "mtime": row.mtime,
            "last_processed": row.last_processed,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def add_record(
        self, kb_id: str, file_path: str, hash: str, doc_id: str, chunk_count: int = 0
    ) -> bool:
        now = time.time()
        stmt = sqlite_insert(DedupRecordModel).values(
            kb_id=kb_id,
            file_path=file_path,
            hash=hash,
            doc_id=doc_id,
            chunk_count=chunk_count,
            mtime=now,
            last_processed=now,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[DedupRecordModel.kb_id, DedupRecordModel.file_path],
            set_={
                "hash": stmt.excluded.hash,
                "doc_id": stmt.excluded.doc_id,
                "chunk_count": stmt.excluded.chunk_count,
                "mtime": stmt.excluded.mtime,
                "last_processed": stmt.excluded.last_processed,
                "updated_at": now,
            },
        )
        try:
            with self.db.session_scope() as session:
                session.execute(stmt)
            return True
        except Exception as e:
            logger.warning(f"add_record 错误: {e}")
            return False

    def bulk_add(self, kb_id: str, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        now = time.time()
        with self.db.session_scope() as session:
            for r in records:
                stmt = sqlite_insert(DedupRecordModel).values(
                    kb_id=kb_id,
                    file_path=r["file_path"],
                    hash=r["hash"],
                    doc_id=r["doc_id"],
                    chunk_count=r.get("chunk_count", 0),
                    mtime=r.get("mtime", now),
                    last_processed=now,
                    created_at=now,
                    updated_at=now,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[DedupRecordModel.kb_id, DedupRecordModel.file_path],
                    set_={
                        "hash": stmt.excluded.hash,
                        "doc_id": stmt.excluded.doc_id,
                        "chunk_count": stmt.excluded.chunk_count,
                        "mtime": stmt.excluded.mtime,
                        "last_processed": stmt.excluded.last_processed,
                        "updated_at": now,
                    },
                )
                session.execute(stmt)
        return len(records)

    def check_hash(self, kb_id: str, hash: str) -> bool:
        with self.db.session_scope() as session:
            return (
                session.scalars(
                    select(DedupRecordModel.id)
                    .where(
                        DedupRecordModel.kb_id == kb_id, DedupRecordModel.hash == hash
                    )
                    .limit(1)
                ).first()
                is not None
            )

    def get_by_hash(self, kb_id: str, hash: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(DedupRecordModel)
                .where(DedupRecordModel.kb_id == kb_id, DedupRecordModel.hash == hash)
                .limit(1)
            ).first()
            return self._to_dict(row) if row else None

    def get_by_doc_id(self, kb_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            row = session.scalars(
                select(DedupRecordModel)
                .where(
                    DedupRecordModel.kb_id == kb_id, DedupRecordModel.doc_id == doc_id
                )
                .limit(1)
            ).first()
            return self._to_dict(row) if row else None

    def get_records(self, kb_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(DedupRecordModel)
                .where(DedupRecordModel.kb_id == kb_id)
                .order_by(DedupRecordModel.updated_at.desc())
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_hash_set(self, kb_id: str) -> Set[str]:
        with self.db.session_scope() as session:
            rows = session.execute(
                select(DedupRecordModel.hash).where(DedupRecordModel.kb_id == kb_id)
            ).all()
            return {hash_value for (hash_value,) in rows}

    def update_chunk_count(self, kb_id: str, doc_id: str, chunk_count: int) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                update(DedupRecordModel)
                .where(
                    DedupRecordModel.kb_id == kb_id, DedupRecordModel.doc_id == doc_id
                )
                .values(chunk_count=chunk_count, updated_at=time.time())
            )
            return (result.rowcount or 0) > 0

    def remove(self, kb_id: str, file_path: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(DedupRecordModel).where(
                    DedupRecordModel.kb_id == kb_id,
                    DedupRecordModel.file_path == file_path,
                )
            )
            return (result.rowcount or 0) > 0

    def remove_many(self, kb_id: str, file_paths: List[str]) -> int:
        if not file_paths:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                delete(DedupRecordModel).where(
                    DedupRecordModel.kb_id == kb_id,
                    DedupRecordModel.file_path.in_(file_paths),
                )
            )
            return result.rowcount or 0

    def clear(self, kb_id: str) -> int:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(DedupRecordModel).where(DedupRecordModel.kb_id == kb_id)
            )
            return result.rowcount or 0

    def get_stats(self, kb_id: str) -> Dict[str, int]:
        with self.db.session_scope() as session:
            row = session.execute(
                select(
                    func.count(DedupRecordModel.id),
                    func.sum(DedupRecordModel.chunk_count),
                ).where(DedupRecordModel.kb_id == kb_id)
            ).first()
            return {
                "total": int(row[0] or 0),
                "total_chunks": int(row[1] or 0),
            }


class ProgressDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: ProgressModel) -> Dict[str, Any]:
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


class CategoryRuleDB:
    def __init__(self, db: DatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: CategoryRuleModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "rule_type": row.rule_type,
            "pattern": row.pattern,
            "description": row.description or "",
            "priority": row.priority,
            "is_active": row.is_active,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def add_rule(
        self,
        kb_id: str,
        rule_type: str,
        pattern: str,
        description: str = "",
        priority: int = 0,
    ) -> bool:
        now = time.time()
        stmt = sqlite_insert(CategoryRuleModel).values(
            kb_id=kb_id,
            rule_type=rule_type,
            pattern=pattern,
            description=description,
            priority=priority,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                CategoryRuleModel.kb_id,
                CategoryRuleModel.rule_type,
                CategoryRuleModel.pattern,
            ],
            set_={
                "description": stmt.excluded.description,
                "priority": stmt.excluded.priority,
                "is_active": 1,
                "updated_at": now,
            },
        )
        try:
            with self.db.session_scope() as session:
                session.execute(stmt)
            return True
        except Exception as e:
            logger.warning(f"添加分类规则失败: {e}")
            return False

    def get_rules_for_kb(self, kb_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(CategoryRuleModel)
                .where(
                    CategoryRuleModel.kb_id == kb_id, CategoryRuleModel.is_active == 1
                )
                .order_by(CategoryRuleModel.priority.desc())
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_rules_by_type(self, rule_type: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(CategoryRuleModel)
                .where(
                    CategoryRuleModel.rule_type == rule_type,
                    CategoryRuleModel.is_active == 1,
                )
                .order_by(CategoryRuleModel.kb_id, CategoryRuleModel.priority.desc())
            ).all()
            return [self._to_dict(row) for row in rows]

    def get_all_rules(self) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(CategoryRuleModel)
                .where(CategoryRuleModel.is_active == 1)
                .order_by(CategoryRuleModel.kb_id, CategoryRuleModel.priority.desc())
            ).all()
            return [self._to_dict(row) for row in rows]

    def delete_rule(self, kb_id: str, rule_type: str, pattern: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(CategoryRuleModel).where(
                    CategoryRuleModel.kb_id == kb_id,
                    CategoryRuleModel.rule_type == rule_type,
                    CategoryRuleModel.pattern == pattern,
                )
            )
            return (result.rowcount or 0) > 0

    def delete_rules_for_kb(self, kb_id: str) -> int:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(CategoryRuleModel).where(CategoryRuleModel.kb_id == kb_id)
            )
            return result.rowcount or 0

    def seed_initial_rules(self, knowledge_bases: List[Dict[str, Any]]) -> int:
        count = 0
        for kb in knowledge_bases:
            kb_id = kb.get("id")
            source_paths = kb.get("source_paths", [])
            source_tags = kb.get("source_tags", [])
            for i, path in enumerate(source_paths):
                if self.add_rule(
                    kb_id=kb_id,
                    rule_type="folder_path",
                    pattern=path,
                    description=f"文件夹路径匹配: {path}",
                    priority=100 - i,
                ):
                    count += 1
            for i, tag in enumerate(source_tags):
                if self.add_rule(
                    kb_id=kb_id,
                    rule_type="tag",
                    pattern=tag,
                    description=f"标签匹配: {tag}",
                    priority=50 - i,
                ):
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
        doc_id: str = None,
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
            if chunk_count is not None:
                updates["chunk_count"] = chunk_count
            if total_chars is not None:
                updates["total_chars"] = total_chars
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
            "embedding_generated": bool(row.embedding_generated),
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

    def get_by_doc(self, doc_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel)
                .where(ChunkModel.doc_id == doc_id)
                .order_by(ChunkModel.chunk_index, ChunkModel.hierarchy_level)
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


def init_sync_db() -> SyncStateDB:
    return SyncStateDB(get_db())


def init_dedup_db() -> DedupStateDB:
    return DedupStateDB(get_db())


def init_progress_db() -> ProgressDB:
    return ProgressDB(get_db())


def init_kb_meta_db() -> KnowledgeBaseMetaDB:
    return KnowledgeBaseMetaDB(get_db())


def init_category_rule_db() -> CategoryRuleDB:
    return CategoryRuleDB(get_db())


def init_document_db() -> DocumentDB:
    return DocumentDB(get_db())


def init_chunk_db() -> ChunkDB:
    return ChunkDB(get_db())

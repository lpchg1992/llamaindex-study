"""
SQLite storage for RAGAS evaluation results.
"""

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
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


def get_eval_db_path() -> Path:
    settings = get_settings()
    data_dir = Path(settings.data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "eval_results.db"


class EvalBase(DeclarativeBase):
    pass


class EvalRunModel(EvalBase):
    __tablename__ = "eval_runs"
    __table_args__ = (Index("idx_eval_runs_kb_id", "kb_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    metrics: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    completed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class EvalQuestionModel(EvalBase):
    __tablename__ = "eval_test_questions"
    __table_args__ = (Index("idx_test_questions_kb_id", "kb_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_id: Mapped[str] = mapped_column(String, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


def _json_dump(data: Any) -> str:
    if data is None:
        return "{}"
    return json.dumps(data, ensure_ascii=False)


def _json_load(data: Optional[str], default: Any = None) -> Any:
    if not data:
        return default
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return default


class EvalDatabaseManager:
    _instance: Optional["EvalDatabaseManager"] = None
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
        self.db_path = get_eval_db_path()
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
        EvalBase.metadata.create_all(self.engine)

    def _register_sqlite_pragmas(self) -> None:
        @event.listens_for(self.engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

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


_eval_db_manager: Optional[EvalDatabaseManager] = None


def get_eval_db() -> EvalDatabaseManager:
    global _eval_db_manager
    if _eval_db_manager is None:
        _eval_db_manager = EvalDatabaseManager()
    return _eval_db_manager


class EvalRunDB:
    def __init__(self, db: EvalDatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: EvalRunModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "metrics": _json_load(row.metrics, []),
            "summary": _json_load(row.summary, {}),
            "status": row.status,
            "error": row.error,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }

    def create(
        self,
        run_id: str,
        kb_id: str,
        metrics: List[str],
        summary: Dict[str, Any],
        status: str = "pending",
    ) -> Dict[str, Any]:
        now = time.time()
        stmt = sqlite_insert(EvalRunModel).values(
            id=run_id,
            kb_id=kb_id,
            metrics=_json_dump(metrics),
            summary=_json_dump(summary),
            status=status,
            created_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[EvalRunModel.id],
            set_={
                "kb_id": stmt.excluded.kb_id,
                "metrics": stmt.excluded.metrics,
                "summary": stmt.excluded.summary,
                "status": stmt.excluded.status,
                "created_at": stmt.excluded.created_at,
            },
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        result = self.get(run_id)
        if result is None:
            result = {
                "id": run_id,
                "kb_id": kb_id,
                "metrics": metrics,
                "summary": summary,
                "status": status,
                "error": None,
                "created_at": now,
                "completed_at": None,
            }
        return result

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self.db.session_scope() as session:
            stmt = select(EvalRunModel).where(EvalRunModel.id == run_id)
            row = session.scalars(stmt).first()
            return self._to_dict(row) if row else None

    def get_by_kb(self, kb_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            stmt = (
                select(EvalRunModel)
                .where(EvalRunModel.kb_id == kb_id)
                .order_by(EvalRunModel.created_at.desc())
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [self._to_dict(row) for row in rows]

    def get_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            stmt = (
                select(EvalRunModel)
                .order_by(EvalRunModel.created_at.desc())
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [self._to_dict(row) for row in rows]

    def update_result(
        self,
        run_id: str,
        summary: Dict[str, Any],
        status: str = "completed",
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self.db.session_scope() as session:
            result = session.execute(
                update(EvalRunModel)
                .where(EvalRunModel.id == run_id)
                .values(
                    summary=_json_dump(summary),
                    status=status,
                    error=error,
                    completed_at=now,
                )
            )
            if result.rowcount == 0:
                return None
        return self.get(run_id)

    def delete(self, run_id: str) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(EvalRunModel).where(EvalRunModel.id == run_id)
            )
            return (result.rowcount or 0) > 0


class TestQuestionDB:
    def __init__(self, db: EvalDatabaseManager):
        self.db = db

    @staticmethod
    def _to_dict(row: EvalQuestionModel) -> Dict[str, Any]:
        return {
            "id": row.id,
            "kb_id": row.kb_id,
            "query": row.query,
            "reference_answer": row.reference_answer,
            "created_at": row.created_at,
        }

    def create(
        self,
        kb_id: str,
        query: str,
        reference_answer: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        stmt = sqlite_insert(EvalQuestionModel).values(
            kb_id=kb_id,
            query=query,
            reference_answer=reference_answer,
            created_at=now,
        )
        with self.db.session_scope() as session:
            session.execute(stmt)
        with self.db.session_scope() as session:
            row = session.scalars(
                select(EvalQuestionModel)
                .where(
                    EvalQuestionModel.kb_id == kb_id,
                    EvalQuestionModel.query == query,
                )
                .order_by(EvalQuestionModel.id.desc())
                .limit(1)
            ).first()
            return self._to_dict(row) if row else {}

    def create_batch(
        self,
        questions: List[Dict[str, Any]],
    ) -> int:
        if not questions:
            return 0
        now = time.time()
        with self.db.session_scope() as session:
            for q in questions:
                stmt = sqlite_insert(EvalQuestionModel).values(
                    kb_id=q["kb_id"],
                    query=q["query"],
                    reference_answer=q.get("reference_answer"),
                    created_at=now,
                )
                session.execute(stmt)
        return len(questions)

    def get_by_kb(self, kb_id: str) -> List[Dict[str, Any]]:
        with self.db.session_scope() as session:
            stmt = (
                select(EvalQuestionModel)
                .where(EvalQuestionModel.kb_id == kb_id)
                .order_by(EvalQuestionModel.created_at.desc())
            )
            rows = session.scalars(stmt).all()
            return [self._to_dict(row) for row in rows]

    def delete(self, question_id: int) -> bool:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(EvalQuestionModel).where(EvalQuestionModel.id == question_id)
            )
            return (result.rowcount or 0) > 0

    def delete_by_kb(self, kb_id: str) -> int:
        with self.db.session_scope() as session:
            result = session.execute(
                delete(EvalQuestionModel).where(EvalQuestionModel.kb_id == kb_id)
            )
            return result.rowcount or 0


def init_eval_run_db() -> EvalRunDB:
    return EvalRunDB(get_eval_db())


def init_test_question_db() -> TestQuestionDB:
    return TestQuestionDB(get_eval_db())
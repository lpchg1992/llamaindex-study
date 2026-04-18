"""
Token 统计持久化数据库

按天存储 token 使用统计，支持历史查询。
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    scoped_session,
    sessionmaker,
)
from sqlalchemy import event


class TokenStatsBase(DeclarativeBase):
    pass


class DailyTokenStatsModel(TokenStatsBase):
    __tablename__ = "daily_token_stats"
    __table_args__ = (
        Index("idx_daily_date", "date"),
        Index("idx_daily_vendor", "vendor_id"),
        Index("idx_daily_date_vendor", "date", "vendor_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String, nullable=False)
    vendor_id: Mapped[str] = mapped_column(String, nullable=False)
    model_type: Mapped[str] = mapped_column(String, nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)


class RAGTraceEventModel(TokenStatsBase):
    __tablename__ = "rag_trace_events"
    __table_args__ = (
        Index("idx_trace_date", "date"),
        Index("idx_trace_query", "query"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[str] = mapped_column(String, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    retrieval_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retrieval_scores: Mapped[str] = mapped_column(Text, default="[]")
    source_node_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


def get_token_stats_db_path() -> Path:
    data_dir = Path.home() / ".llamaindex" / "stats"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "token_stats.db"


class TokenStatsDB:
    _instance: Optional["TokenStatsDB"] = None
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
        self.db_path = get_token_stats_db_path()
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
        TokenStatsBase.metadata.create_all(self.engine)

    @property
    def session(self):
        return self._session_factory()

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def get_last_persisted_stats(
        self,
        vendor_id: str,
        model_type: str,
        model_id: str,
        record_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if record_date is None:
            record_date = self._today()

        session = self.session
        try:
            existing = (
                session.query(DailyTokenStatsModel)
                .filter(
                    DailyTokenStatsModel.date == record_date,
                    DailyTokenStatsModel.vendor_id == vendor_id,
                    DailyTokenStatsModel.model_type == model_type,
                    DailyTokenStatsModel.model_id == model_id,
                )
                .first()
            )
            if existing:
                return {
                    "call_count": existing.call_count,
                    "prompt_tokens": existing.prompt_tokens,
                    "completion_tokens": existing.completion_tokens,
                    "total_tokens": existing.total_tokens,
                    "error_count": existing.error_count,
                }
            return None
        finally:
            session.close()

    def increment_daily_stats(
        self,
        vendor_id: str,
        model_type: str,
        model_id: str,
        delta_call_count: int,
        delta_prompt_tokens: int,
        delta_completion_tokens: int,
        delta_total_tokens: int,
        delta_error_count: int,
        record_date: Optional[str] = None,
    ) -> None:
        if record_date is None:
            record_date = self._today()

        session = self.session
        try:
            existing = (
                session.query(DailyTokenStatsModel)
                .filter(
                    DailyTokenStatsModel.date == record_date,
                    DailyTokenStatsModel.vendor_id == vendor_id,
                    DailyTokenStatsModel.model_type == model_type,
                    DailyTokenStatsModel.model_id == model_id,
                )
                .first()
            )

            if existing:
                existing.call_count += delta_call_count
                existing.prompt_tokens += delta_prompt_tokens
                existing.completion_tokens += delta_completion_tokens
                existing.total_tokens += delta_total_tokens
                existing.error_count += delta_error_count
                existing.updated_at = time.time()
            else:
                new_record = DailyTokenStatsModel(
                    date=record_date,
                    vendor_id=vendor_id,
                    model_type=model_type,
                    model_id=model_id,
                    call_count=delta_call_count,
                    prompt_tokens=delta_prompt_tokens,
                    completion_tokens=delta_completion_tokens,
                    total_tokens=delta_total_tokens,
                    error_count=delta_error_count,
                    created_at=time.time(),
                    updated_at=time.time(),
                )
                session.add(new_record)

            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    def upsert_daily_stats(
        self,
        vendor_id: str,
        model_type: str,
        model_id: str,
        call_count: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        error_count: int,
        record_date: Optional[str] = None,
    ) -> None:
        if record_date is None:
            record_date = self._today()

        session = self.session
        try:
            existing = (
                session.query(DailyTokenStatsModel)
                .filter(
                    DailyTokenStatsModel.date == record_date,
                    DailyTokenStatsModel.vendor_id == vendor_id,
                    DailyTokenStatsModel.model_type == model_type,
                    DailyTokenStatsModel.model_id == model_id,
                )
                .first()
            )

            if existing:
                existing.call_count = call_count
                existing.prompt_tokens = prompt_tokens
                existing.completion_tokens = completion_tokens
                existing.total_tokens = total_tokens
                existing.error_count = error_count
                existing.updated_at = time.time()
            else:
                new_record = DailyTokenStatsModel(
                    date=record_date,
                    vendor_id=vendor_id,
                    model_type=model_type,
                    model_id=model_id,
                    call_count=call_count,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    error_count=error_count,
                    created_at=time.time(),
                    updated_at=time.time(),
                )
                session.add(new_record)

            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    def get_daily_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        vendor_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        session = self.session
        try:
            query = select(DailyTokenStatsModel)
            if start_date:
                query = query.where(DailyTokenStatsModel.date >= start_date)
            if end_date:
                query = query.where(DailyTokenStatsModel.date <= end_date)
            if vendor_id:
                query = query.where(DailyTokenStatsModel.vendor_id == vendor_id)
            query = query.order_by(DailyTokenStatsModel.date.desc())

            result = session.execute(query).fetchall()
            return [row._asdict() for row in result]
        finally:
            session.close()

    def get_total_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = self.session
        try:
            query = select(
                func.sum(DailyTokenStatsModel.call_count).label("total_calls"),
                func.sum(DailyTokenStatsModel.prompt_tokens).label(
                    "total_prompt_tokens"
                ),
                func.sum(DailyTokenStatsModel.completion_tokens).label(
                    "total_completion_tokens"
                ),
                func.sum(DailyTokenStatsModel.total_tokens).label("total_tokens"),
                func.sum(DailyTokenStatsModel.error_count).label("total_errors"),
            )
            if start_date:
                query = query.where(DailyTokenStatsModel.date >= start_date)
            if end_date:
                query = query.where(DailyTokenStatsModel.date <= end_date)

            result = session.execute(query).fetchone()
            return {
                "total_calls": result.total_calls or 0,
                "total_prompt_tokens": result.total_prompt_tokens or 0,
                "total_completion_tokens": result.total_completion_tokens or 0,
                "total_tokens": result.total_tokens or 0,
                "total_errors": result.total_errors or 0,
            }
        finally:
            session.close()

    def get_stats_by_vendor(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        session = self.session
        try:
            # First get per-model stats
            model_query = select(
                DailyTokenStatsModel.vendor_id,
                DailyTokenStatsModel.model_type,
                DailyTokenStatsModel.model_id,
                func.sum(DailyTokenStatsModel.call_count).label("call_count"),
                func.sum(DailyTokenStatsModel.prompt_tokens).label("prompt_tokens"),
                func.sum(DailyTokenStatsModel.completion_tokens).label(
                    "completion_tokens"
                ),
                func.sum(DailyTokenStatsModel.total_tokens).label("total_tokens"),
                func.sum(DailyTokenStatsModel.error_count).label("error_count"),
            )
            if start_date:
                model_query = model_query.where(DailyTokenStatsModel.date >= start_date)
            if end_date:
                model_query = model_query.where(DailyTokenStatsModel.date <= end_date)
            model_query = model_query.group_by(
                DailyTokenStatsModel.vendor_id,
                DailyTokenStatsModel.model_type,
                DailyTokenStatsModel.model_id,
            )

            model_result = session.execute(model_query).fetchall()

            # Group by vendor and build nested structure
            vendors: Dict[str, Dict[str, Any]] = {}
            for row in model_result:
                vendor_id = row.vendor_id
                if vendor_id not in vendors:
                    vendors[vendor_id] = {
                        "vendor_id": vendor_id,
                        "models": [],
                        "total_calls": 0,
                        "total_prompt_tokens": 0,
                        "total_completion_tokens": 0,
                        "total_tokens": 0,
                        "total_errors": 0,
                    }
                vendors[vendor_id]["models"].append(
                    {
                        "model_type": row.model_type,
                        "model_id": row.model_id,
                        "call_count": row.call_count or 0,
                        "prompt_tokens": row.prompt_tokens or 0,
                        "completion_tokens": row.completion_tokens or 0,
                        "total_tokens": row.total_tokens or 0,
                        "error_count": row.error_count or 0,
                    }
                )
                vendors[vendor_id]["total_calls"] += row.call_count or 0
                vendors[vendor_id]["total_prompt_tokens"] += row.prompt_tokens or 0
                vendors[vendor_id]["total_completion_tokens"] += (
                    row.completion_tokens or 0
                )
                vendors[vendor_id]["total_tokens"] += row.total_tokens or 0
                vendors[vendor_id]["total_errors"] += row.error_count or 0

            return list(vendors.values())
        finally:
            session.close()

    def get_daily_dates(self) -> List[str]:
        session = self.session
        try:
            query = (
                select(DailyTokenStatsModel.date)
                .distinct()
                .order_by(DailyTokenStatsModel.date.desc())
            )
            result = session.execute(query).fetchall()
            return [row.date for row in result]
        finally:
            session.close()

    def insert_trace_event(
        self,
        timestamp: str,
        query: str,
        duration_ms: float,
        retrieval_count: int,
        retrieval_scores: List[float],
        source_node_count: int,
        llm_input_tokens: int,
        llm_output_tokens: int,
        embedding_tokens: int,
        total_tokens: int,
        error: Optional[str] = None,
        record_date: Optional[str] = None,
    ) -> None:
        if record_date is None:
            record_date = self._today()

        session = self.session
        try:
            stmt = sqlite_insert(RAGTraceEventModel).values(
                date=record_date,
                timestamp=timestamp,
                query=query,
                duration_ms=duration_ms,
                retrieval_count=retrieval_count,
                retrieval_scores=json.dumps(retrieval_scores, ensure_ascii=False),
                source_node_count=source_node_count,
                llm_input_tokens=llm_input_tokens,
                llm_output_tokens=llm_output_tokens,
                embedding_tokens=embedding_tokens,
                total_tokens=total_tokens,
                error=error,
                created_at=time.time(),
            )
            session.execute(stmt)
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    def get_trace_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        session = self.session
        try:
            query = select(RAGTraceEventModel)
            if start_date:
                query = query.where(RAGTraceEventModel.date >= start_date)
            if end_date:
                query = query.where(RAGTraceEventModel.date <= end_date)
            query = query.order_by(RAGTraceEventModel.timestamp.desc()).limit(limit)

            result = session.execute(query).fetchall()
            events = []
            for row in result:
                d = row._asdict()
                d["retrieval_scores"] = json.loads(d["retrieval_scores"])
                events.append(d)
            return events
        finally:
            session.close()

    def delete_old_traces(self, before_date: str) -> int:
        session = self.session
        try:
            count = (
                session.query(RAGTraceEventModel)
                .filter(RAGTraceEventModel.date < before_date)
                .delete()
            )
            session.commit()
            return count
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()


_token_stats_db: Optional[TokenStatsDB] = None


def init_token_stats_db() -> TokenStatsDB:
    global _token_stats_db
    if _token_stats_db is None:
        _token_stats_db = TokenStatsDB()
    return _token_stats_db


def get_token_stats_db() -> TokenStatsDB:
    global _token_stats_db
    if _token_stats_db is None:
        _token_stats_db = TokenStatsDB()
    return _token_stats_db

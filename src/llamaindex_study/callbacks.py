"""
LlamaIndex 可观测性模块
"""

import threading
import time
import json
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from llama_index.core.callbacks.base import CallbackManager
from llama_index.core.callbacks.schema import CBEventType
from llama_index.core.callbacks.token_counting import TokenCountingHandler
from llama_index.core.callbacks.base_handler import BaseCallbackHandler

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModelCallStats:
    """单个模型的调用统计"""

    vendor_id: str
    model_type: str  # "llm", "embedding", "reranker"
    model_id: str
    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def add_tokens(self, prompt: int = 0, completion: int = 0):
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += prompt + completion

    def increment_call(self):
        self.call_count += 1

    def increment_error(self):
        self.error_count += 1


class ModelCallStatsCollection:
    """模型调用统计收集器，按 (vendor_id, model_type, model_id) 分组"""

    _lock = threading.Lock()

    def __init__(self):
        self._stats: Dict[Tuple[str, str, str], ModelCallStats] = {}

    def _make_key(
        self, vendor_id: str, model_type: str, model_id: str
    ) -> Tuple[str, str, str]:
        return (vendor_id, model_type, model_id)

    def get_or_create(
        self, vendor_id: str, model_type: str, model_id: str
    ) -> ModelCallStats:
        key = self._make_key(vendor_id, model_type, model_id)
        with self._lock:
            if key not in self._stats:
                self._stats[key] = ModelCallStats(
                    vendor_id=vendor_id,
                    model_type=model_type,
                    model_id=model_id,
                )
            return self._stats[key]

    def record_llm_call(
        self,
        vendor_id: str,
        model_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error: bool = False,
    ):
        """记录一次 LLM 调用"""
        stats = self.get_or_create(vendor_id, "llm", model_id)
        with self._lock:
            stats.increment_call()
            stats.add_tokens(prompt=prompt_tokens, completion=completion_tokens)
            if error:
                stats.increment_error()

    def record_embedding_call(
        self,
        vendor_id: str,
        model_id: str,
        token_count: int = 0,
        error: bool = False,
    ):
        """记录一次 Embedding 调用"""
        stats = self.get_or_create(vendor_id, "embedding", model_id)
        with self._lock:
            stats.increment_call()
            stats.add_tokens(prompt=token_count, completion=0)
            if error:
                stats.increment_error()

    def record_reranker_call(
        self,
        vendor_id: str,
        model_id: str,
        token_count: int = 0,
        error: bool = False,
    ):
        """记录一次 Reranker 调用"""
        stats = self.get_or_create(vendor_id, "reranker", model_id)
        with self._lock:
            stats.increment_call()
            stats.add_tokens(prompt=token_count, completion=0)
            if error:
                stats.increment_error()

    def get_all_stats(self) -> List[Dict[str, Any]]:
        """获取所有统计，按 vendor_id 分组"""
        with self._lock:
            result = []
            for key, stats in self._stats.items():
                result.append(stats.to_dict())
            return result

    def get_by_vendor(self, vendor_id: str) -> List[Dict[str, Any]]:
        """获取指定供应商的所有统计"""
        with self._lock:
            result = []
            for key, stats in self._stats.items():
                if stats.vendor_id == vendor_id:
                    result.append(stats.to_dict())
            return result

    def get_vendors(self) -> List[str]:
        """获取所有供应商 ID 列表"""
        with self._lock:
            return list(set(s.vendor_id for s in self._stats.values()))

    def reset(self):
        """重置所有统计"""
        with self._lock:
            self._stats.clear()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，按供应商分组"""
        with self._lock:
            vendors = {}
            for key, stats in self._stats.items():
                vendor_id = stats.vendor_id
                if vendor_id not in vendors:
                    vendors[vendor_id] = {"vendor_id": vendor_id, "models": []}
                vendors[vendor_id]["models"].append(stats.to_dict())

            # 计算每个供应商的汇总
            for vendor_id, vendor_data in vendors.items():
                models = vendor_data["models"]
                vendor_data["total_calls"] = sum(m["call_count"] for m in models)
                vendor_data["total_prompt_tokens"] = sum(
                    m["prompt_tokens"] for m in models
                )
                vendor_data["total_completion_tokens"] = sum(
                    m["completion_tokens"] for m in models
                )
                vendor_data["total_tokens"] = sum(m["total_tokens"] for m in models)
                vendor_data["total_errors"] = sum(m["error_count"] for m in models)

            return {
                "vendors": list(vendors.values()),
                "total_calls": sum(v["total_calls"] for v in vendors.values()),
                "total_tokens": sum(v["total_tokens"] for v in vendors.values()),
            }


# 全局模型调用统计实例
_model_call_stats: Optional[ModelCallStatsCollection] = None


def get_model_call_stats() -> ModelCallStatsCollection:
    global _model_call_stats
    if _model_call_stats is None:
        _model_call_stats = ModelCallStatsCollection()
    return _model_call_stats


def record_model_call(
    vendor_id: str,
    model_type: str,
    model_id: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    error: bool = False,
):
    """记录一次模型调用（全局入口）"""
    stats = get_model_call_stats()
    if model_type == "llm":
        stats.record_llm_call(
            vendor_id, model_id, prompt_tokens, completion_tokens, error
        )
    elif model_type == "embedding":
        stats.record_embedding_call(vendor_id, model_id, prompt_tokens, error)
    elif model_type == "reranker":
        stats.record_reranker_call(vendor_id, model_id, prompt_tokens, error)


def reset_model_call_stats():
    """重置模型调用统计"""
    stats = get_model_call_stats()
    stats.reset()


@dataclass
class RAGTraceEvent:
    timestamp: str
    query: str
    duration_ms: float
    retrieval_count: int
    retrieval_scores: List[float]
    source_node_count: int
    llm_input_tokens: int
    llm_output_tokens: int
    embedding_tokens: int
    total_tokens: int
    error: Optional[str] = None


@dataclass
class RAGStats:
    total_queries: int = 0
    total_retrieval_count: int = 0
    total_llm_input_tokens: int = 0
    total_llm_output_tokens: int = 0
    total_embedding_tokens: int = 0
    total_duration_ms: float = 0.0
    errors: int = 0
    trace_events: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_avg_duration_ms(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.total_duration_ms / self.total_queries


class RAGCallbackHandler(BaseCallbackHandler):
    def __init__(
        self,
        trace_file: Optional[Path] = None,
        max_trace_events: int = 1000,
    ):
        super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
        self._stats = RAGStats()
        self._current_event: Optional[RAGTraceEvent] = None
        self._trace_file = trace_file
        self._max_trace_events = max_trace_events
        self._event_start_time: Optional[float] = None
        self._retrieval_count = 0
        self._retrieval_scores: List[float] = []
        self._source_node_count = 0

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        pass

    def end_trace(
        self,
        trace_id: Optional[str] = None,
        trace_map: Optional[Dict] = None,
    ) -> None:
        pass

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
        parent_id: Optional[str] = None,
    ) -> str:
        if event_type == CBEventType.QUERY:
            self._event_start_time = time.time()
            query = ""
            if payload and "query" in payload:
                query = payload["query"]
            self._current_event = RAGTraceEvent(
                timestamp=datetime.now().isoformat(),
                query=query[:200] if query else "",
                duration_ms=0.0,
                retrieval_count=0,
                retrieval_scores=[],
                source_node_count=0,
                llm_input_tokens=0,
                llm_output_tokens=0,
                embedding_tokens=0,
                total_tokens=0,
            )
            self._retrieval_count = 0
            self._retrieval_scores = []
            self._source_node_count = 0
        return event_id

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: Optional[Dict[str, Any]] = None,
        event_id: str = "",
    ) -> None:
        if self._current_event is None:
            return

        if event_type == CBEventType.RETRIEVE:
            if payload:
                nodes = payload.get("nodes", [])
                self._retrieval_count += len(nodes)
                for node in nodes:
                    score = (
                        node.get("score", 0.0)
                        if isinstance(node, dict)
                        else getattr(node, "score", 0.0)
                    )
                    self._retrieval_scores.append(score)

        elif event_type == CBEventType.SYNTHESIZE:
            if payload:
                source_nodes = payload.get("source_nodes", [])
                self._source_node_count = len(source_nodes)

        elif event_type == CBEventType.QUERY:
            if self._event_start_time:
                duration_ms = (time.time() - self._event_start_time) * 1000
                self._current_event.duration_ms = duration_ms
                self._current_event.retrieval_count = self._retrieval_count
                self._current_event.retrieval_scores = self._retrieval_scores[:10]
                self._current_event.source_node_count = self._source_node_count
                self._update_stats(self._current_event)

    def _update_stats(self, event: RAGTraceEvent) -> None:
        self._stats.total_queries += 1
        self._stats.total_retrieval_count += event.retrieval_count
        self._stats.total_duration_ms += event.duration_ms
        if event.error:
            self._stats.errors += 1
        trace_dict = asdict(event)
        self._stats.trace_events.append(trace_dict)
        if len(self._stats.trace_events) > self._max_trace_events:
            self._stats.trace_events = self._stats.trace_events[
                -self._max_trace_events :
            ]
        if self._trace_file:
            self._write_trace(event)

    def _write_trace(self, event: RAGTraceEvent) -> None:
        if not self._trace_file:
            return
        try:
            self._trace_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"写入追踪日志失败: {e}")

    def get_stats(self) -> RAGStats:
        return self._stats

    def reset_stats(self) -> None:
        self._stats = RAGStats()
        if self._trace_file and self._trace_file.exists():
            self._trace_file.unlink()


class LlamaCallbackManager:
    def __init__(self, trace_dir: Optional[Path] = None):
        self._token_counter = TokenCountingHandler()
        self._rag_handler = RAGCallbackHandler(
            trace_file=trace_dir / "rag_trace.jsonl" if trace_dir else None
        )
        self._callback_manager = CallbackManager(
            [self._token_counter, self._rag_handler]
        )

    @property
    def callback_manager(self) -> CallbackManager:
        return self._callback_manager

    def get_token_counter(self) -> TokenCountingHandler:
        return self._token_counter

    def get_rag_stats(self) -> RAGStats:
        return self._rag_handler.get_stats()

    def reset(self) -> None:
        self._token_counter.reset_counts()
        self._rag_handler.reset_stats()


_global_callback_manager: Optional[LlamaCallbackManager] = None
_trace_dir: Optional[Path] = None


def setup_callbacks(trace_dir: Optional[str] = None) -> LlamaCallbackManager:
    global _global_callback_manager, _trace_dir
    if trace_dir:
        _trace_dir = Path(trace_dir)
    else:
        _trace_dir = Path.home() / ".llamaindex" / "traces"
    _global_callback_manager = LlamaCallbackManager(trace_dir=_trace_dir)
    return _global_callback_manager


def get_callback_manager() -> Optional[LlamaCallbackManager]:
    return _global_callback_manager


def get_token_counter() -> Optional[TokenCountingHandler]:
    if _global_callback_manager:
        return _global_callback_manager.get_token_counter()
    return None


def get_rag_stats() -> Optional[RAGStats]:
    if _global_callback_manager:
        return _global_callback_manager.get_rag_stats()
    return None


def reset_callbacks() -> None:
    if _global_callback_manager:
        _global_callback_manager.reset()


def get_trace_dir() -> Optional[Path]:
    return _trace_dir


class QueryCallbackContext:
    def __init__(self):
        self._callback_manager: Optional[LlamaCallbackManager] = None

    def __enter__(self) -> "QueryCallbackContext":
        global _global_callback_manager
        if _global_callback_manager is None:
            setup_callbacks()
        self._callback_manager = _global_callback_manager
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass

    def get_stats(self) -> Optional[RAGStats]:
        if self._callback_manager:
            return self._callback_manager.get_rag_stats()
        return None

    def get_token_counts(self) -> Dict[str, int]:
        counter = get_token_counter()
        if counter:
            return counter.get_total_token_counts()
        return {}


def format_token_stats(token_counts: Dict[str, int]) -> str:
    prompt = token_counts.get("prompt_tokens", 0)
    completion = token_counts.get("completion_tokens", 0)
    total = token_counts.get("total_tokens", 0)
    return f"Token: prompt={prompt:,}, completion={completion:,}, total={total:,}"


def format_rag_stats(stats: RAGStats) -> str:
    return "\n".join(
        [
            "=== RAG 统计 ===",
            f"总查询数: {stats.total_queries}",
            f"总检索节点数: {stats.total_retrieval_count}",
            f"平均耗时: {stats.get_avg_duration_ms():.2f}ms",
            f"LLM Input Tokens: {stats.total_llm_input_tokens:,}",
            f"LLM Output Tokens: {stats.total_llm_output_tokens:,}",
            f"Embedding Tokens: {stats.total_embedding_tokens:,}",
            f"错误数: {stats.errors}",
        ]
    )

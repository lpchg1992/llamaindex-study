"""
并行 Embedding 处理器

使用 asyncio + ThreadPoolExecutor 实现真正的并行处理
支持多端点（本地+远程）同时工作
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

from llama_index.embeddings.ollama import OllamaEmbedding
from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

settings = get_settings()
EMBEDDING_MODEL = settings.ollama_embed_model
EMBEDDING_DIM = 1024
MAX_RETRIES = settings.ollama_max_retries
RETRY_DELAY = settings.ollama_retry_delay


# Embedding 结果类型
EmbeddingResult = Tuple[str, List[float], Optional[str]]


class EmbeddingEndpoint:
    """Embedding 端点配置"""
    
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url
        self.avg_latency = 0.0
        self.inflight = 0


class ParallelEmbeddingProcessor:
    """
    并行 Embedding 处理器
    
    特点：
    - 使用 ThreadPoolExecutor 实现真正的并行
    - 支持多端点（本地+远程）同时工作
    - 使用 asyncio 调度，无阻塞等待
    - 失败重试机制
    """
    
    _instance: Optional["ParallelEmbeddingProcessor"] = None
    
    def __new__(cls) -> "ParallelEmbeddingProcessor":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        endpoint_configs = settings.get_ollama_endpoints()
        self.endpoints = [EmbeddingEndpoint(name, url) for name, url in endpoint_configs]
        if not self.endpoints:
            self.endpoints = [EmbeddingEndpoint("本地", settings.ollama_base_url)]

        if settings.ollama_remote_url and settings.ollama_remote_url == settings.ollama_local_url:
            logger.warning("OLLAMA_REMOTE_URL 与 OLLAMA_LOCAL_URL 相同，并行模式将退化为单端点")

        self._executor = ThreadPoolExecutor(max_workers=len(self.endpoints))
        self._models: Dict[str, OllamaEmbedding] = {}
        self._stats: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        self._failures: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        self._lock = threading.Lock()

        endpoint_info = ", ".join(f"{ep.name}:{ep.url}" for ep in self.endpoints)
        logger.info(f"并行 Embedding 处理器初始化完成，端点: {endpoint_info}")
    
    def _get_model(self, ep_url: str) -> OllamaEmbedding:
        """获取或创建 embed 模型"""
        if ep_url not in self._models:
            self._models[ep_url] = OllamaEmbedding(
                model_name=EMBEDDING_MODEL,
                base_url=ep_url
            )
        return self._models[ep_url]
    
    def _get_embedding_with_retry(self, text: str, ep: EmbeddingEndpoint) -> EmbeddingResult:
        """带重试的 embedding 获取"""
        last_error: Optional[str] = None

        for attempt in range(MAX_RETRIES):
            try:
                start = time.perf_counter()
                with self._lock:
                    ep.inflight += 1
                model = self._get_model(ep.url)
                embedding = model.get_text_embedding(text)
                latency = time.perf_counter() - start
                with self._lock:
                    self._stats[ep.name] += 1
                    ep.avg_latency = (
                        latency if ep.avg_latency == 0 else (ep.avg_latency * 0.7 + latency * 0.3)
                    )
                return (ep.name, embedding, None)
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES - 1:
                    logger.debug(f"[{ep.name}] Embedding 失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
                    time.sleep(RETRY_DELAY)
                else:
                    with self._lock:
                        self._failures[ep.name] += 1
            finally:
                with self._lock:
                    ep.inflight = max(0, ep.inflight - 1)
        
        logger.warning(f"[{ep.name}] Embedding 最终失败: {last_error}")
        return (ep.name, [0.0] * EMBEDDING_DIM, f"重试{MAX_RETRIES}次后失败: {last_error}")

    def _rank_endpoints(self, planned_counts: Optional[Dict[str, int]] = None) -> List[EmbeddingEndpoint]:
        """按当前负载和历史延迟对端点排序"""
        planned_counts = planned_counts or {}
        with self._lock:
            return sorted(
                self.endpoints,
                key=lambda ep: (
                    planned_counts.get(ep.name, 0),
                    ep.inflight,
                    self._failures.get(ep.name, 0),
                    self._stats.get(ep.name, 0),
                    ep.avg_latency if ep.avg_latency > 0 else 0,
                    ep.name,
                ),
            )

    def _should_fanout(self, text: str) -> bool:
        """判断是否值得多端点竞争"""
        if len(self.endpoints) <= 1:
            return False
        text_length = len(text)
        return text_length >= settings.ollama_fanout_text_threshold

    def _select_endpoints_for_text(
        self,
        text: str,
        planned_counts: Optional[Dict[str, int]] = None,
    ) -> List[EmbeddingEndpoint]:
        """为文本选择最合适的端点策略"""
        ranked = self._rank_endpoints(planned_counts)
        if not ranked:
            return self.endpoints[:1]
        if self._should_fanout(text):
            return ranked[: min(2, len(ranked))]
        return ranked[:1]
    
    async def get_embedding(self, text: str, ep_name: str) -> EmbeddingResult:
        """异步获取单个 embedding"""
        ep = next((e for e in self.endpoints if e.name == ep_name), self.endpoints[0])

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: self._get_embedding_with_retry(text, ep)
        )
    
    async def process_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量处理文本列表，并行竞争模式
        
        每个文本同时向所有端点发送请求，谁先完成用谁的结果
        这样可以充分利用两个端点的并行能力
        
        Args:
            texts: 文本列表
            
        Returns:
            List[EmbeddingResult] - [(ep_name, embedding, error), ...]
        """
        if not texts:
            return []

        async def get_embedding_from_any_endpoint(
            text: str,
            selected_endpoints: List[EmbeddingEndpoint],
        ) -> EmbeddingResult:
            """向所有端点并发请求，返回最快成功的"""
            if len(selected_endpoints) == 1:
                return await self.get_embedding(text, selected_endpoints[0].name)

            loop = asyncio.get_running_loop()
            tasks = [
                loop.run_in_executor(
                    self._executor,
                    lambda ep=ep: self._get_embedding_with_retry(text, ep),
                )
                for ep in selected_endpoints
            ]

            fallback: Optional[EmbeddingResult] = None
            for future in asyncio.as_completed(tasks):
                result = await future
                if fallback is None:
                    fallback = result
                _, embedding, error = result
                if error is None and embedding:
                    for pending in tasks:
                        if not pending.done():
                            pending.cancel()
                    return result

            return fallback or (self.endpoints[0].name, [0.0] * EMBEDDING_DIM, "所有端点都失败")

        planned_counts = {ep.name: 0 for ep in self.endpoints}
        tasks = []
        for text in texts:
            selected_endpoints = self._select_endpoints_for_text(text, planned_counts)
            for ep in selected_endpoints:
                planned_counts[ep.name] = planned_counts.get(ep.name, 0) + 1
            tasks.append(get_embedding_from_any_endpoint(text, selected_endpoints))
        return await asyncio.gather(*tasks)

    async def aget_text_embedding(self, text: str) -> List[float]:
        """异步获取单条文本的 embedding"""
        _, embedding, _ = (await self.process_batch([text]))[0]
        return embedding

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """异步批量获取 embeddings"""
        return [embedding for _, embedding, _ in await self.process_batch(texts)]

    def _run_sync(self, coro):
        """在同步环境中运行协程"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: Dict[str, object] = {}
        error: Dict[str, BaseException] = {}

        def runner() -> None:
            try:
                result["value"] = asyncio.run(coro)
            except BaseException as exc:
                error["value"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()

        if "value" in error:
            raise error["value"]
        return result.get("value")

    def get_text_embedding(self, text: str) -> List[float]:
        """同步获取单条文本的 embedding"""
        return self._run_sync(self.aget_text_embedding(text))

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """同步批量获取 embeddings"""
        return self._run_sync(self.aget_text_embeddings(texts))
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def get_failure_stats(self) -> Dict[str, int]:
        """获取失败统计"""
        return self._failures.copy()

    def get_endpoint_snapshot(self) -> List[Dict[str, float | int | str]]:
        """获取端点负载快照"""
        with self._lock:
            return [
                {
                    "name": ep.name,
                    "url": ep.url,
                    "avg_latency": round(ep.avg_latency, 4),
                    "inflight": ep.inflight,
                    "success": self._stats.get(ep.name, 0),
                    "failure": self._failures.get(ep.name, 0),
                }
                for ep in self.endpoints
            ]
    
    def reset_stats(self) -> None:
        """重置统计"""
        for key in self._stats:
            self._stats[key] = 0
        for key in self._failures:
            self._failures[key] = 0
    
    def shutdown(self) -> None:
        """关闭线程池"""
        self._executor.shutdown(wait=True)


# 全局实例
_parallel_processor: Optional[ParallelEmbeddingProcessor] = None


def get_parallel_processor() -> ParallelEmbeddingProcessor:
    """获取并行处理器实例"""
    global _parallel_processor
    if _parallel_processor is None:
        _parallel_processor = ParallelEmbeddingProcessor()
    return _parallel_processor


def create_parallel_embedding_model() -> ParallelEmbeddingProcessor:
    """创建兼容 LlamaIndex 接口的并行 Embedding 模型"""
    return get_parallel_processor()

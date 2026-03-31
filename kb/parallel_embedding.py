"""
并行 Embedding 处理器

使用 asyncio + ThreadPoolExecutor 实现真正的并行处理
支持多端点（本地+远程）同时工作
采用队列机制 + 自适应负载均衡：处理快的端点分配更多任务
"""

import asyncio
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
from typing import AsyncIterator, Dict, List, Optional, Tuple

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
        self.chunks_completed = 0
        self.total_time = 0.0


class ParallelEmbeddingProcessor:
    """
    并行 Embedding 处理器（自适应负载均衡）

    特点：
    - 队列机制：所有 chunk 进入共享队列
    - 自适应分配：处理快的端点分配更多任务
    - 无竞争：每个 chunk 只会被一个端点处理
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
        self.endpoints = [
            EmbeddingEndpoint(name, url) for name, url in endpoint_configs
        ]
        if not self.endpoints:
            self.endpoints = [EmbeddingEndpoint("本地", settings.ollama_base_url)]

        if (
            settings.ollama_remote_url
            and settings.ollama_remote_url == settings.ollama_local_url
        ):
            logger.warning(
                "OLLAMA_REMOTE_URL 与 OLLAMA_LOCAL_URL 相同，并行模式将退化为单端点"
            )

        self._executor = ThreadPoolExecutor(max_workers=len(self.endpoints))
        self._models: Dict[str, OllamaEmbedding] = {}
        self._stats: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        self._failures: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        self._lock = threading.Lock()
        self._chunk_queue: deque = deque()
        self._results: Dict[int, EmbeddingResult] = {}
        self._pending_count = 0

        endpoint_info = ", ".join(f"{ep.name}:{ep.url}" for ep in self.endpoints)
        logger.info(f"并行 Embedding 处理器初始化完成，端点: {endpoint_info}")

    def _get_model(self, ep_url: str) -> OllamaEmbedding:
        """获取或创建 embed 模型"""
        if ep_url not in self._models:
            self._models[ep_url] = OllamaEmbedding(
                model_name=EMBEDDING_MODEL, base_url=ep_url
            )
        return self._models[ep_url]

    def _get_embedding_with_retry(
        self, text: str, ep: EmbeddingEndpoint
    ) -> EmbeddingResult:
        """带重试的 embedding 获取"""
        last_error: Optional[str] = None

        for attempt in range(MAX_RETRIES):
            try:
                start = time.perf_counter()
                with self._lock:
                    ep.inflight += 1

                embedding = self._call_ollama_embed(ep.url, text)

                latency = time.perf_counter() - start
                with self._lock:
                    self._stats[ep.name] += 1
                    ep.chunks_completed += 1
                    ep.total_time += latency
                    ep.avg_latency = (
                        latency
                        if ep.avg_latency == 0
                        else (ep.avg_latency * 0.7 + latency * 0.3)
                    )
                return (ep.name, embedding, None)
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES - 1:
                    logger.debug(
                        f"[{ep.name}] Embedding 失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}"
                    )
                    time.sleep(RETRY_DELAY)
                else:
                    with self._lock:
                        self._failures[ep.name] += 1
            finally:
                with self._lock:
                    ep.inflight = max(0, ep.inflight - 1)

        logger.warning(f"[{ep.name}] Embedding 最终失败: {last_error}")
        return (
            ep.name,
            [0.0] * EMBEDDING_DIM,
            f"重试{MAX_RETRIES}次后失败: {last_error}",
        )

    def _call_ollama_embed(self, url: str, text: str) -> List[float]:
        """直接调用 Ollama /api/embed 端点"""
        import httpx

        model_name = EMBEDDING_MODEL
        if not model_name.endswith(":latest"):
            model_name = f"{model_name}:latest"

        payload = {
            "model": model_name,
            "input": text[:8192],
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{url}/api/embed", json=payload)
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            result = response.json()
            return result["embedding"]

    def _get_best_endpoint(self) -> EmbeddingEndpoint:
        """选择当前最优的端点（基于速度和负载）"""
        with self._lock:
            best_ep = self.endpoints[0]
            best_score = float("inf")

            for ep in self.endpoints:
                if ep.inflight >= 3:
                    continue
                if len(self.endpoints) > 1 and ep.total_time > 0:
                    throughput = ep.chunks_completed / ep.total_time
                    score = 1.0 / throughput if throughput > 0 else float("inf")
                    score += ep.inflight * 0.5
                else:
                    score = ep.inflight

                if score < best_score:
                    best_score = score
                    best_ep = ep

            return best_ep

    async def get_embedding(self, text: str, ep_name: str) -> EmbeddingResult:
        """异步获取单个 embedding"""
        ep = next((e for e in self.endpoints if e.name == ep_name), self.endpoints[0])

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self._get_embedding_with_retry(text, ep)
        )

    async def process_batch_streaming(
        self, texts: List[str], base_idx: int = 0
    ) -> AsyncIterator[Tuple[int, EmbeddingResult]]:
        """
        流式处理文本列表（按完成顺序yield）

        与 process_batch 不同，这个方法会在每个 embedding 完成后立即 yield，
        而不是等待所有完成。适合需要边处理边写入的场景。

        Args:
            texts: 文本列表
            base_idx: 起始索引（用于多批次场景）

        Yields:
            (index, (ep_name, embedding, error))
        """
        if not texts:
            return

        self._chunk_queue = deque(range(len(texts)))
        futures: List[Tuple[int, asyncio.Task]] = []

        for i in range(len(texts)):
            ep = self._get_best_endpoint()
            coro = self._run_embedding_in_thread(texts[i], ep)
            task = asyncio.create_task(coro)
            futures.append((i, task))

        for _, coro in asyncio.as_completed([f for _, f in futures]):
            idx = next(i for i, t in futures if t == coro)
            try:
                result = await coro
                yield (base_idx + idx, result)
            except Exception as e:
                logger.warning(f"Embedding 流式处理失败 idx={idx}: {e}")
                yield (
                    base_idx + idx,
                    (self.endpoints[0].name, [0.0] * EMBEDDING_DIM, str(e)),
                )

    async def _run_embedding_in_thread(
        self, text: str, ep: "EmbeddingEndpoint"
    ) -> EmbeddingResult:
        """在线程池中运行 embedding（保持线程安全）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, lambda: self._get_embedding_with_retry(text, ep)
        )

    async def process_batch(self, texts: List[str]) -> List[EmbeddingResult]:
        """
        批量处理文本列表（自适应负载均衡）

        使用队列机制：
        1. 所有 chunk 入队
        2. 每个端点处理完一个后自动取下一个
        3. 快的端点自然处理更多 chunk

        Args:
            texts: 文本列表

        Returns:
            List[EmbeddingResult] - [(ep_name, embedding, error), ...]
        """
        if not texts:
            return []

        loop = asyncio.get_running_loop()
        results: List[EmbeddingResult] = [None] * len(texts)
        completed = 0
        lock = threading.Lock()

        def worker(ep: EmbeddingEndpoint) -> None:
            nonlocal completed
            while True:
                chunk_idx = None
                with self._lock:
                    if self._chunk_queue:
                        chunk_idx = self._chunk_queue.popleft()
                    elif completed >= len(texts):
                        return

                if chunk_idx is None:
                    time.sleep(0.01)
                    continue

                result = self._get_embedding_with_retry(texts[chunk_idx], ep)
                results[chunk_idx] = result

                with lock:
                    completed += 1

        self._chunk_queue = deque(range(len(texts)))
        threads = []
        for ep in self.endpoints:
            for _ in range(2):
                t = threading.Thread(target=worker, args=(ep,), daemon=True)
                t.start()
                threads.append(t)

        for t in threads:
            t.join(timeout=300)

        return [
            r
            if r is not None
            else (self.endpoints[0].name, [0.0] * EMBEDDING_DIM, "处理超时")
            for r in results
        ]

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
            result = []
            for ep in self.endpoints:
                throughput = (
                    ep.chunks_completed / ep.total_time if ep.total_time > 0 else 0
                )
                result.append(
                    {
                        "name": ep.name,
                        "url": ep.url,
                        "avg_latency": round(ep.avg_latency, 4),
                        "inflight": ep.inflight,
                        "completed": ep.chunks_completed,
                        "throughput": round(throughput, 4),
                        "success": self._stats.get(ep.name, 0),
                        "failure": self._failures.get(ep.name, 0),
                    }
                )
            return result

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

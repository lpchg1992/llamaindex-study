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
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger
from llamaindex_study.ollama_utils import OllamaEmbedder, create_ollama_embedding

logger = get_logger(__name__)

settings = get_settings()
EMBEDDING_DIM = 1024


def _get_default_embedding_model_name() -> str:
    from llamaindex_study.embedding_service import get_default_embedding_from_registry

    model_name, _ = get_default_embedding_from_registry()
    return model_name


# Embedding 结果类型
EmbeddingResult = Tuple[str, List[float], Optional[str]]


class EmbeddingEndpoint:
    """Embedding 端点配置（包含模型信息）"""

    def __init__(
        self,
        name: str,
        url: str,
        model_id: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        self.name = name
        self.url = url
        self.model_id = model_id
        self.model_name = model_name
        self.is_healthy = True
        self.avg_latency = 0.0
        self.inflight = 0
        self.chunks_completed = 0
        self.total_time = 0.0
        self.last_error: Optional[str] = None


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

        self._executor = ThreadPoolExecutor(max_workers=4)
        self._models: Dict[str, OllamaEmbedder] = {}
        self._lock = threading.Lock()
        self._model_name: str = _get_default_embedding_model_name()
        self._consecutive_failures: Dict[str, int] = {}
        self._chunk_queue: deque = deque()
        self._results: Dict[int, EmbeddingResult] = {}
        self._pending_count = 0

        self.endpoints = self._load_embedding_endpoints()
        if not self.endpoints:
            endpoint_configs = settings.get_ollama_endpoints()
            self.endpoints = [
                EmbeddingEndpoint(name, url) for name, url in endpoint_configs
            ]

        for ep in self.endpoints:
            self._consecutive_failures[ep.name] = 0

        self._stats: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        self._failures: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}

        if len(self.endpoints) == 1:
            logger.info(
                f"单端点模式: {self.endpoints[0].name} ({self.endpoints[0].url})"
            )
        else:
            endpoint_info = ", ".join(f"{ep.name}:{ep.url}" for ep in self.endpoints)
            logger.info(f"多端点并行模式: {endpoint_info}")

        # 健康检查任务
        self._health_check_task: Optional[asyncio.Task] = None
        self._health_check_interval: float = 30.0  # 每30秒检查一次
        self._failure_threshold: int = 3  # 连续3次失败才标记为不健康

    def start_health_checks(self) -> None:
        """启动持续健康检查循环（在有事件循环的环境中调用）"""
        if self._health_check_task is not None:
            return

        try:
            loop = asyncio.get_running_loop()
            self._health_check_task = loop.create_task(self._health_check_loop())
            logger.info("健康检查循环已启动")
        except RuntimeError:
            logger.warning("无法启动健康检查循环：没有运行中的事件循环")

    def _load_embedding_endpoints(self) -> List["EmbeddingEndpoint"]:
        """从数据库加载 embedding 端点（带健康检查）"""
        from llamaindex_study.config import get_model_registry
        from kb.database import init_vendor_db

        registry = get_model_registry()
        vendor_db = init_vendor_db()

        endpoints = []
        for model_info in registry.get_by_type("embedding"):
            vendor_id = model_info.get("vendor_id", "")
            if vendor_id == "siliconflow":
                continue
            vendor_info = vendor_db.get(vendor_id) if vendor_id else None
            if not vendor_info:
                continue

            base_url = vendor_info.get("api_base")
            if not base_url:
                continue

            model_name = model_info["name"]
            if not model_name.endswith(":latest"):
                model_name = f"{model_name}:latest"

            ep = EmbeddingEndpoint(
                name=f"{vendor_info['name']}({model_info['id']})",
                url=base_url,
                model_id=model_info["id"],
                model_name=model_name,
            )

            is_healthy = self._health_check(base_url, model_name)
            if is_healthy:
                ep.is_healthy = True
                logger.debug(f"端点健康检查通过: {ep.name} ({base_url})")
            else:
                ep.is_healthy = True
                self._consecutive_failures[ep.name] = 0
                logger.warning(
                    f"端点 {ep.name} ({base_url}) 初始检查未通过，将在健康检查循环中重试"
                )

            endpoints.append(ep)

        # 添加 SiliconFlow 端点（跳过健康检查，始终可用）
        sf_model_info = registry.get_model("siliconflow/bge-m3")
        if sf_model_info:
            vendor_info = vendor_db.get("siliconflow")
            if vendor_info and vendor_info.get("api_base"):
                sf_ep = EmbeddingEndpoint(
                    name="SiliconFlow(siliconflow/bge-m3)",
                    url="siliconflow://",
                    model_id="siliconflow/bge-m3",
                    model_name="Pro/BAAI/bge-m3",
                )
                sf_ep.is_healthy = True
                endpoints.append(sf_ep)
                logger.info("SiliconFlow embedding 端点已添加（跳过健康检查）")

        healthy_count = sum(1 for ep in endpoints if ep.is_healthy)
        logger.info(
            f"从数据库加载了 {len(endpoints)} 个 embedding 端点（{healthy_count} 个健康）"
        )
        return endpoints

    def _health_check_with_retry(self, url: str, model_name: str) -> bool:
        """验证端点是否可用（仅检查 Ollama 服务是否启动）"""
        import httpx

        max_retries = 3
        initial_delay = 2.0
        backoff_factor = 1.5
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                response = httpx.get(f"{url}/api/tags", timeout=10.0)
                if response.status_code == 200:
                    return True
                elif response.status_code == 503:
                    logger.debug(
                        f"端点 {url} 服务加载中 (尝试 {attempt + 1}/{max_retries})，等待 {delay:.1f}s"
                    )
                    time.sleep(delay)
                    delay *= backoff_factor
                else:
                    return False
            except Exception as e:
                logger.debug(f"健康检查失败 {url}: {e}")
                if attempt == max_retries - 1:
                    return False
                time.sleep(delay)
                delay *= backoff_factor
        return False

    def _health_check(self, url: str, model_name: str, timeout: float = 5.0) -> bool:
        """验证端点是否可用（发送小文本测试）- 兼容旧接口"""
        return self._health_check_with_retry(url, model_name)

    async def _health_check_loop(self):
        """持续健康检查循环 - 定期检查所有端点的健康状态"""
        while True:
            try:
                for ep in self.endpoints:
                    if ep.url == "siliconflow://":
                        continue

                    is_healthy = await asyncio.get_event_loop().run_in_executor(
                        None, lambda e=ep: self._sync_health_check_with_retry(e)
                    )

                    with self._lock:
                        if is_healthy:
                            if not ep.is_healthy:
                                logger.info(f"[{ep.name}] 端点恢复，已标记为健康")
                            ep.is_healthy = True
                            ep.last_error = None
                            self._consecutive_failures[ep.name] = 0
                        else:
                            self._consecutive_failures[ep.name] += 1
                            if (
                                self._consecutive_failures[ep.name]
                                >= self._failure_threshold
                            ):
                                if ep.is_healthy:
                                    logger.warning(
                                        f"[{ep.name}] 连续 {self._consecutive_failures[ep.name]} 次健康检查失败，标记为不健康"
                                    )
                                ep.is_healthy = False

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")

            await asyncio.sleep(self._health_check_interval)

    def _sync_health_check(self, ep: EmbeddingEndpoint) -> bool:
        """同步健康检查（在线程池中运行）- 兼容旧接口"""
        return self._sync_health_check_with_retry(ep)

    def _sync_health_check_with_retry(self, ep: EmbeddingEndpoint) -> bool:
        """同步健康检查（仅检查 Ollama 服务是否启动）"""
        max_retries = 3
        initial_delay = 2.0
        backoff_factor = 1.5
        delay = initial_delay

        for attempt in range(max_retries):
            try:
                response = httpx.get(f"{ep.url}/api/tags", timeout=10.0)
                if response.status_code == 200:
                    return True
                elif response.status_code == 503:
                    time.sleep(delay)
                    delay *= backoff_factor
                else:
                    return False
            except Exception:
                if attempt == max_retries - 1:
                    return False
                time.sleep(delay)
                delay *= backoff_factor
        return False

    def set_model_by_model_id(self, model_id: str) -> None:
        """根据模型ID设置当前使用的 embedding 模型

        Args:
            model_id: 模型ID (如 ollama/bge-m3:latest, ollama_homepc/bge-m3:latest)
        """
        from llamaindex_study.config import get_model_registry
        from kb.database import init_vendor_db

        registry = get_model_registry()
        model_info = registry.get_model(model_id)
        if not model_info:
            raise ValueError(f"模型不存在: {model_id}")

        vendor_id = model_info.get("vendor_id", "")
        vendor_db = init_vendor_db()
        vendor_info = vendor_db.get(vendor_id) if vendor_id else None

        base_url = (
            vendor_info.get("api_base") if vendor_info else None
        ) or settings.ollama_base_url

        model_name = model_info["name"]
        if not model_name.endswith(":latest"):
            model_name = f"{model_name}:latest"

        self._model_name = model_name

        needs_update = any(
            ep.url.rstrip("/") != base_url.rstrip("/") for ep in self.endpoints
        )

        if needs_update:
            self.endpoints = [
                EmbeddingEndpoint(f"{ep.name}({model_id})", base_url)
                for ep in self.endpoints
            ]
            logger.info(f"端点已更新为: {base_url}")

        self._models.clear()
        logger.info(f"Embedding 模型已切换为: {model_id} ({self._model_name})")

    def _get_model(self, ep: EmbeddingEndpoint) -> Any:
        cache_key = f"{ep.url}:{ep.model_name}"
        if cache_key not in self._models:
            if ep.url == "siliconflow://":
                from llamaindex_study.ollama_utils import create_siliconflow_embedding

                self._models[cache_key] = create_siliconflow_embedding(
                    model=ep.model_name or "Pro/BAAI/bge-m3"
                )
            else:
                self._models[cache_key] = create_ollama_embedding(
                    model=ep.model_name or self._model_name, base_url=ep.url
                )
        return self._models[cache_key]

    def _get_embedding_with_retry(
        self, text: str, ep: EmbeddingEndpoint
    ) -> EmbeddingResult:
        """获取 embedding

        策略：
        - SiliconFlow 端点：直接调用，无重试（云服务稳定）
        - Unhealthy Ollama 端点：直接路由到 SiliconFlow
        - Healthy Ollama 端点：调用 OllamaEmbedder（含 503 重试），
          失败后标记为 unhealthy 并路由到 SiliconFlow
        """
        sf_ep = next((e for e in self.endpoints if e.url == "siliconflow://"), None)

        def call_sf() -> EmbeddingResult:
            if sf_ep is None:
                return (ep.name, [0.0] * EMBEDDING_DIM, "SiliconFlow 端点不可用")
            model = self._get_model(sf_ep)
            try:
                emb = model.get_text_embedding(text[:8192])
                return (sf_ep.name, emb, None)
            except Exception as sf_err:
                logger.warning(f"SiliconFlow fallback 也失败: {sf_err}")
                return (sf_ep.name, [0.0] * EMBEDDING_DIM, str(sf_err))

        if ep.url == "siliconflow://":
            return call_sf()

        if not ep.is_healthy:
            return call_sf()

        try:
            start = time.perf_counter()
            with self._lock:
                ep.inflight += 1

            embedding = self._call_ollama_embed(ep, text)

            latency = time.perf_counter() - start
            with self._lock:
                self._stats[ep.name] += 1
                self._consecutive_failures[ep.name] = 0
                ep.chunks_completed += 1
                ep.total_time += latency
                ep.avg_latency = (
                    latency
                    if ep.avg_latency == 0
                    else (ep.avg_latency * 0.7 + latency * 0.3)
                )
            return (ep.name, embedding, None)
        except Exception as e:
            with self._lock:
                self._failures[ep.name] += 1
                self._consecutive_failures[ep.name] += 1

                if self._consecutive_failures[ep.name] >= self._failure_threshold:
                    ep.is_healthy = False
                    ep.last_error = str(e)
                    logger.warning(
                        f"[{ep.name}] 连续 {self._consecutive_failures[ep.name]} 次失败，"
                        f"已标记为不健康: {e}"
                    )

            logger.warning(
                f"[{ep.name}] Ollama embedding 失败，切换到 SiliconFlow: {e}"
            )
            return call_sf()
        finally:
            with self._lock:
                ep.inflight = max(0, ep.inflight - 1)

    def _call_ollama_embed(self, ep: EmbeddingEndpoint, text: str) -> List[float]:
        """通过缓存的 OllamaEmbedder 获取 embedding"""
        model = self._get_model(ep)
        return model.get_text_embedding(text[:8192])

    def _get_best_endpoint(self) -> EmbeddingEndpoint:
        """选择当前最优的端点（基于健康状态、速度和负载）

        规则：
        - 只从 is_healthy=True 的端点中选择
        - SiliconFlow 端点始终视为健康（跳过健康检查）
        - 如果所有 Ollama 端点都不健康但 SiliconFlow 可用，尝试重新检查 Ollama 后再决定
        - 绝不会强制使用 unhealthy 的 Ollama 端点
        """
        with self._lock:
            healthy_eps = [
                ep
                for ep in self.endpoints
                if ep.is_healthy and ep.url != "siliconflow://"
            ]

            if healthy_eps:
                best_ep = healthy_eps[0]
                best_score = float("inf")

                for ep in healthy_eps:
                    if ep.inflight >= 3:
                        continue
                    if len(healthy_eps) > 1 and ep.total_time > 0:
                        throughput = ep.chunks_completed / ep.total_time
                        score = 1.0 / throughput if throughput > 0 else float("inf")
                        score += ep.inflight * 0.5
                    else:
                        score = ep.inflight

                    if score < best_score:
                        best_score = score
                        best_ep = ep

                return best_ep

            unhealthy_eps = [
                ep
                for ep in self.endpoints
                if not ep.is_healthy and ep.url != "siliconflow://"
            ]
            if unhealthy_eps:
                logger.warning(f"所有 Ollama 端点不健康，尝试重新检查...")
                for ep in unhealthy_eps:
                    is_healthy = self._sync_health_check_with_retry(ep)
                    if is_healthy:
                        ep.is_healthy = True
                        ep.last_error = None
                        self._consecutive_failures[ep.name] = 0
                        logger.info(f"[{ep.name}] 重新检查成功，标记为健康")
                        return ep

            sf_ep = next(
                (ep for ep in self.endpoints if ep.url == "siliconflow://"), None
            )
            if sf_ep:
                logger.warning("所有 Ollama 端点不健康，回退到 SiliconFlow")
                return sf_ep

            logger.error("无可用端点（包含 SiliconFlow）")
            return self.endpoints[0]

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
        task_to_future: Dict[asyncio.Task, int] = {}

        for i in range(len(texts)):
            ep = self._get_best_endpoint()
            coro = self._run_embedding_in_thread(texts[i], ep)
            task = asyncio.create_task(coro)
            futures.append((i, task))
            task_to_future[task] = i

        async def wait_for(task: asyncio.Task) -> Tuple[int, EmbeddingResult]:
            idx = task_to_future[task]
            try:
                result = await task
                return (base_idx + idx, result)
            except Exception as e:
                logger.warning(f"Embedding 流式处理失败 idx={idx}: {e}")
                return (
                    base_idx + idx,
                    (self.endpoints[0].name, [0.0] * EMBEDDING_DIM, str(e)),
                )

        for f in asyncio.as_completed([wait_for(t) for _, t in futures]):
            yield await f

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
        chunk_queue: deque = deque(range(len(texts)))

        def worker(ep: EmbeddingEndpoint) -> None:
            nonlocal completed
            while True:
                chunk_idx = None
                with self._lock:
                    if chunk_queue:
                        chunk_idx = chunk_queue.popleft()
                    elif completed >= len(texts):
                        return

                if chunk_idx is None:
                    time.sleep(0.01)
                    continue

                result = self._get_embedding_with_retry(texts[chunk_idx], ep)
                results[chunk_idx] = result

                with lock:
                    completed += 1

        threads = []
        for ep in self.endpoints:
            if not ep.is_healthy:
                continue
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

    async def async_shutdown(self) -> None:
        """异步关闭（取消健康检查循环）"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
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

"""
并行 Embedding 处理器

从数据库（ModelRegistry + VendorDB）加载所有 embedding 模型端点，
使用多线程 + 自适应负载均衡并行处理。

端点加载：
  - registry.get_by_type("embedding") 获取所有 embedding 模型
  - 根据 vendor_id 从 VendorDB 获取 api_base
  - 每个模型创建 EmbeddingEndpoint，逐一健康检查
  - SiliconFlow 作为 fallback 始终可用

负载均衡：
  - _get_best_endpoint() 选择健康端点
  - inflight >= 3 的端点跳过，避免过载
  - Ollama 全部不健康 → 自动切换 SiliconFlow

健康检查：
  - 后台 asyncio 任务每 30 秒检查所有端点
  - GET /api/tags，3 次重试，指数退避
  - 连续 3 次失败标记为 unhealthy
"""

import asyncio
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from queue import Queue, Empty
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import httpx

from rag.config import get_settings
from rag.logger import get_logger
from rag.embedding_factory import create_ollama_embedding

logger = get_logger(__name__)

settings = get_settings()

def _get_default_embedding_model_name() -> str:
    from rag.embedding_service import get_default_embedding_from_registry

    model_name, _ = get_default_embedding_from_registry()
    return model_name


# Embedding 结果类型
EmbeddingResult = Tuple[str, List[float], Optional[str]]


class EmbeddingEndpoint:
    """Embedding 端点配置（包含模型信息和维度）"""

    def __init__(
        self,
        name: str,
        url: str,
        model_id: Optional[str] = None,
        model_name: Optional[str] = None,
        dimensions: int = 1024,
    ) -> None:
        self.name = name
        self.url = url
        self.model_id = model_id
        self.model_name = model_name
        self.dimensions = dimensions
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
        self._models: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._model_name: str = _get_default_embedding_model_name()
        self._consecutive_failures: Dict[str, int] = {}
        self._chunk_queue: deque = deque()
        self._results: Dict[int, EmbeddingResult] = {}
        self._pending_count = 0

        self.endpoints = self._load_embedding_endpoints()
        if not self.endpoints:
            endpoint_configs = settings.get_ollama_endpoints()
            for name, url in endpoint_configs:
                ep = EmbeddingEndpoint(name, url)
                is_healthy = self._health_check(url, self._model_name)
                ep.is_healthy = is_healthy
                if not is_healthy:
                    logger.warning(f"端点 {name} ({url}) 健康检查失败，将在未来重试")
                self.endpoints.append(ep)

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
        self._failure_threshold: int = 15  # 连续15次失败才标记为不健康（高度信任 Ollama）

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

    def refresh_endpoints(self) -> None:
        """重新加载端点配置（vendor 变更后调用）"""
        logger.info("刷新 embedding 端点配置")
        new_endpoints = self._load_embedding_endpoints()
        self.endpoints = new_endpoints
        self._stats = {ep.name: 0 for ep in self.endpoints}
        self._failures = {ep.name: 0 for ep in self.endpoints}
        for ep in self.endpoints:
            self._consecutive_failures[ep.name] = 0
        self._models.clear()
        logger.info(f"端点已刷新，共 {len(self.endpoints)} 个端点")

    def _load_embedding_endpoints(self) -> List["EmbeddingEndpoint"]:
        """从数据库加载 embedding 端点（带健康检查）"""
        from rag.config import get_model_registry
        from kb_core.database import init_vendor_db

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

            # 从模型配置读取 dimensions
            model_dim = model_info.get("config", {}).get("dimensions", 1024)

            ep = EmbeddingEndpoint(
                name=f"{vendor_info['name']}({model_info['id']})",
                url=base_url,
                model_id=model_info["id"],
                model_name=model_name,
                dimensions=model_dim,
            )

            is_healthy = self._health_check(base_url, model_name)
            ep.is_healthy = is_healthy
            if is_healthy:
                logger.debug(f"端点健康检查通过: {ep.name} ({base_url})")
            else:
                self._consecutive_failures[ep.name] = 0
                logger.warning(
                    f"端点 {ep.name} ({base_url}) 初始检查未通过，将在健康检查循环中重试"
                )

            endpoints.append(ep)

        # 添加 SiliconFlow 端点（跳过健康检查，始终可用）
        sf_models = [m for m in registry.get_by_type("embedding") if m.get("vendor_id") == "siliconflow"]
        sf_model_info = None
        for m in sf_models:
            if m.get("is_default"):
                sf_model_info = m
                break
        if not sf_model_info and sf_models:
            sf_model_info = sf_models[0]

        if sf_model_info:
            vendor_info = vendor_db.get("siliconflow")
            if vendor_info and vendor_info.get("api_base"):
                model_id = sf_model_info["id"]
                api_model = sf_model_info.get("config", {}).get("api_model") or f"Pro/BAAI/{sf_model_info['name']}"
                sf_dim = sf_model_info.get("config", {}).get("dimensions", 1024)
                sf_ep = EmbeddingEndpoint(
                    name=f"SiliconFlow({model_id})",
                    url="siliconflow://",
                    model_id=model_id,
                    model_name=api_model,
                    dimensions=sf_dim,
                )
                sf_ep.is_healthy = True
                endpoints.append(sf_ep)
                logger.info(f"SiliconFlow embedding 端点已添加: {model_id}（跳过健康检查）")

        healthy_count = sum(1 for ep in endpoints if ep.is_healthy)
        logger.info(
            f"从数据库加载了 {len(endpoints)} 个 embedding 端点（{healthy_count} 个健康）"
        )
        return endpoints

    def _health_check_with_retry(self, url: str, model_name: str) -> bool:
        """验证端点可用性（检查 Ollama 服务和指定模型）"""
        import httpx

        max_retries = 3
        initial_delay = 2.0
        backoff_factor = 1.5
        delay = initial_delay

        transport = httpx.HTTPTransport(proxy=None)
        with httpx.Client(transport=transport) as client:
            for attempt in range(max_retries):
                try:
                    response = client.get(f"{url}/api/tags", timeout=10.0)
                    if response.status_code == 200:
                        data = response.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        if model_name not in models:
                            logger.warning(
                                f"端点 {url} 模型 {model_name} 未找到，可用模型: {models[:5]}..."
                            )
                            return False
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
        import httpx
        max_retries = 3
        initial_delay = 2.0
        backoff_factor = 1.5
        delay = initial_delay

        transport = httpx.HTTPTransport(proxy=None)
        with httpx.Client(transport=transport) as client:
            for attempt in range(max_retries):
                try:
                    response = client.get(f"{ep.url}/api/tags", timeout=10.0)
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
        from rag.config import get_model_registry
        from kb_core.database import init_vendor_db

        registry = get_model_registry()
        model_info = registry.get_model(model_id)
        if not model_info:
            raise ValueError(f"模型不存在: {model_id}")

        vendor_id = model_info.get("vendor_id", "")
        vendor_db = init_vendor_db()
        vendor_info = vendor_db.get(vendor_id) if vendor_id else None

        if not vendor_info or not vendor_info.get("api_base"):
            raise ValueError(f"Vendor {vendor_id} not configured. Run: uv run llamaindex-study vendor add --help")
        base_url = vendor_info["api_base"]

        model_name = model_info["name"]
        if not model_name.endswith(":latest"):
            model_name = f"{model_name}:latest"

        self._model_name = model_name

        needs_update = any(
            ep.url.rstrip("/") != base_url.rstrip("/") for ep in self.endpoints
        )

        if needs_update:
            self.endpoints = [
                EmbeddingEndpoint(f"{ep.name}({model_id})", base_url, model_id=model_id, model_name=model_name)
                for ep in self.endpoints
            ]
            logger.info(f"端点已更新为: {base_url}")

        self._models.clear()
        logger.info(f"Embedding 模型已切换为: {model_id} ({self._model_name})")

    def _get_model(self, ep: EmbeddingEndpoint) -> Any:
        """获取或创建缓存的 embedding 模型实例

        Args:
            ep: Embedding 端点

        Returns:
            OllamaEmbedder 或 SiliconFlow embedding 实例
        """
        cache_key = f"{ep.url}:{ep.model_name}"
        if cache_key not in self._models:
            if ep.url == "siliconflow://":
                from rag.embedding_factory import create_siliconflow_embedding

                self._models[cache_key] = create_siliconflow_embedding(
                    model=ep.model_name or "Pro/BAAI/bge-m3",
                    dimensions=ep.dimensions,
                    internal_model_id=ep.model_id,
                )
            else:
                self._models[cache_key] = create_ollama_embedding(
                    model=ep.model_name or self._model_name,
                    base_url=ep.url,
                    model_id=ep.model_id,
                )
        return self._models[cache_key]

    def _record_embedding(self, ep: EmbeddingEndpoint, token_count: int, error: bool):
        """记录 embedding 调用统计（用于计费和监控）

        Args:
            ep: Embedding 端点
            token_count: 处理的 token 数量
            error: 是否发生错误
        """
        try:
            from rag.embedding_factory import _record_embedding_call

            if ep.url == "siliconflow://":
                vendor_id = "siliconflow"
            elif ep.model_id and "/" in ep.model_id:
                vendor_id = ep.model_id.split("/")[0]
            else:
                vendor_id = "ollama"
            model_id_for_record = ep.model_id if ep.model_id else f"{vendor_id}/unknown"
            _record_embedding_call(vendor_id, model_id_for_record, token_count, error)
        except Exception as e:
            logger.warning(f"Failed to record embedding call for {model_id_for_record}: {e}")

    def _get_embedding_with_retry(
        self, text: str, ep: EmbeddingEndpoint
    ) -> EmbeddingResult:
        """获取 embedding（含持久重试）

        策略：
        - SiliconFlow 端点：直接调用，无重试（云服务稳定）
        - Unhealthy Ollama 端点：直接路由到 SiliconFlow
        - Healthy Ollama 端点：调用 OllamaEmbedder（含 503 重试），
          失败后标记为 unhealthy 并路由到 SiliconFlow
        - 快速重试全部耗尽后：进入持久重试模式（固定间隔 4s，最多 100 轮），
          确保最终成功而非放弃
        """
        sf_ep = next((e for e in self.endpoints if e.url == "siliconflow://"), None)

        def call_sf() -> EmbeddingResult:
            text_len = len(text[:8192])
            if sf_ep is None:
                self._record_embedding(ep, 0, True)
                logger.error(
                    f"[Fallback] SiliconFlow 端点未配置，embedding 失败 (text_len={text_len})"
                )
                return (ep.name, [0.0] * ep.dimensions, "SiliconFlow 端点不可用")
            model = self._get_model(sf_ep)
            max_retries = 5
            for retry in range(max_retries):
                try:
                    emb = model.get_text_embedding(text[:8192])
                    if all(v == 0.0 for v in emb):
                        if retry < max_retries - 1:
                            wait = (retry + 1) * 3.0
                            logger.warning(
                                f"[{sf_ep.name}] SiliconFlow 返回零向量，"
                                f"重试 {retry + 1}/{max_retries - 1} (等待 {wait:.1f}s, text_len={text_len})"
                            )
                            time.sleep(wait)
                            continue
                        logger.warning(
                            f"[{sf_ep.name}] SiliconFlow 返回零向量"
                            f" (已重试 {max_retries} 次, text_len={text_len})，尝试 Ollama 兜底..."
                        )
                        break
                    self._record_embedding(sf_ep, text_len, False)
                    return (sf_ep.name, emb, None)
                except Exception as sf_err:
                    if retry < max_retries - 1:
                        wait = (retry + 1) * 1.5
                        logger.warning(
                            f"[{sf_ep.name}] SiliconFlow 异常，"
                            f"重试 {retry + 1}/{max_retries - 1} (等待 {wait:.1f}s, text_len={text_len}): "
                            f"{type(sf_err).__name__}: {sf_err}"
                        )
                        time.sleep(wait)
                        continue
                    logger.error(
                        f"[{sf_ep.name}] SiliconFlow fallback 失败"
                        f" (text_len={text_len}): {type(sf_err).__name__}: {sf_err}"
                    )

            # 快速尝试所有 Ollama 端点（即使标记为 unhealthy）
            ollama_eps = [e for e in self.endpoints if e.url != "siliconflow://"]
            for ollama_ep in ollama_eps:
                try:
                    emb = self._call_ollama_embed(ollama_ep, text)
                    if emb and not all(v == 0.0 for v in emb):
                        with self._lock:
                            ollama_ep.is_healthy = True
                            ollama_ep.last_error = None
                            self._consecutive_failures[ollama_ep.name] = 0
                        logger.info(
                            f"[{ollama_ep.name}] Ollama 兜底成功，已恢复为健康 (text_len={text_len})"
                        )
                        self._record_embedding(ollama_ep, text_len, False)
                        return (ollama_ep.name, emb, None)
                except Exception as ollama_err:
                    logger.debug(f"[{ollama_ep.name}] 兜底尝试失败: {ollama_err}")

            max_persistent_rounds = 100
            persistent_delay = 4.0
            logger.warning(
                f"快速重试全部耗尽 (text_len={text_len})，进入持久重试模式 "
                f"(最多 {max_persistent_rounds} 轮，固定间隔 {persistent_delay:.0f}s)"
            )
            for round_num in range(1, max_persistent_rounds + 1):
                time.sleep(persistent_delay)

                model = self._get_model(sf_ep)
                for _retry in range(3):
                    try:
                        emb = model.get_text_embedding(text[:8192])
                        if emb and not all(v == 0.0 for v in emb):
                            self._record_embedding(sf_ep, text_len, False)
                            logger.info(
                                f"[{sf_ep.name}] 持久重试成功 "
                                f"(第 {round_num} 轮, text_len={text_len})"
                            )
                            return (sf_ep.name, emb, None)
                    except Exception:
                        time.sleep(1.0)

                for ollama_ep in ollama_eps:
                    try:
                        emb = self._call_ollama_embed(ollama_ep, text)
                        if emb and not all(v == 0.0 for v in emb):
                            with self._lock:
                                ollama_ep.is_healthy = True
                                ollama_ep.last_error = None
                                self._consecutive_failures[ollama_ep.name] = 0
                            self._record_embedding(ollama_ep, text_len, False)
                            logger.info(
                                f"[{ollama_ep.name}] 持久重试成功 "
                                f"(第 {round_num} 轮, text_len={text_len})"
                            )
                            return (ollama_ep.name, emb, None)
                    except Exception:
                        continue

                if round_num % 10 == 0:
                    logger.warning(
                        f"持久重试中 (第 {round_num}/{max_persistent_rounds} 轮, "
                        f"间隔 {persistent_delay:.0f}s, text_len={text_len})"
                    )

            self._record_embedding(sf_ep, 0, True)
            logger.error(
                f"持久重试 {max_persistent_rounds} 轮后仍然失败，放弃 (text_len={text_len})"
            )
            return (
                sf_ep.name,
                [0.0] * sf_ep.dimensions,
                f"所有端点持久重试 {max_persistent_rounds} 轮均失败",
            )

        if ep.url == "siliconflow://":
            return call_sf()

        if not ep.is_healthy:
            try:
                embedding = self._call_ollama_embed(ep, text)
                if embedding and not all(v == 0.0 for v in embedding):
                    with self._lock:
                        ep.is_healthy = True
                        ep.last_error = None
                        self._consecutive_failures[ep.name] = 0
                    logger.info(
                        f"[{ep.name}] 恢复健康 (曾是 unhealthy，本次成功)"
                    )
                    self._record_embedding(ep, len(text) // 4, False)
                    return (ep.name, embedding, None)
            except Exception:
                pass
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
            self._record_embedding(ep, len(text) // 4, False)
            return (ep.name, embedding, None)
        except Exception as e:
            text_len = len(text[:8192])
            with self._lock:
                self._failures[ep.name] += 1
                self._consecutive_failures[ep.name] += 1

                if self._consecutive_failures[ep.name] >= self._failure_threshold:
                    ep.is_healthy = False
                    ep.last_error = str(e)
                    logger.error(
                        f"[{ep.name}] 连续 {self._consecutive_failures[ep.name]} 次失败，已标记为不健康 (text_len={text_len}): {type(e).__name__}: {e}"
                    )

            logger.warning(
                f"[{ep.name}] Ollama embedding 失败，切换到 SiliconFlow (text_len={text_len}): {type(e).__name__}: {e}"
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
                best_inflight = best_ep.inflight

                for ep in healthy_eps:
                    if ep.inflight < best_inflight:
                        best_inflight = ep.inflight
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
            if self.endpoints:
                return self.endpoints[0]
            raise RuntimeError("没有配置任何 embedding 端点，无法进行 embedding")

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

        端点分配策略：per-chunk execution-time allocation
        - 每个 chunk 在实际执行时才选择端点（不是提交时预分配）
        - _get_best_endpoint() 看到的是实时 inflight 计数
        - 快的端点自然被分配更多任务
        - unhealthy 的端点会被及时跳过

        这与 process_batch() 的动态分配行为一致。

        Args:
            texts: 文本列表
            base_idx: 起始索引（用于多批次场景）

        Yields:
            (index, (ep_name, embedding, error))
        """
        if not texts:
            return

        futures: List[Tuple[int, asyncio.Task]] = []
        task_to_future: Dict[asyncio.Task, int] = {}

        async def embedding_worker(text: str) -> EmbeddingResult:
            """
            单个 chunk 的 embedding 工作函数

            关键设计：端点选择在**实际执行时**进行，而非任务提交时。
            这确保了：
            1. _get_best_endpoint() 能看到实时的 inflight 计数
            2. 自适应负载均衡能真正生效
            3. 动态响应端点健康状态变化
            """
            ep = self._get_best_endpoint()  # 执行时选择，而非提交时
            return await self._run_embedding_in_thread(text, ep)

        # 提交所有任务，端点选择延迟到实际执行时
        for i in range(len(texts)):
            coro = embedding_worker(texts[i])
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
                    (self.endpoints[0].name, [0.0] * self.endpoints[0].dimensions, str(e)),
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

        results: List[Optional[EmbeddingResult]] = [None] * len(texts)
        completed = 0
        lock = threading.Lock()
        chunk_queue: Queue = Queue()
        for i in range(len(texts)):
            chunk_queue.put(i)

        def worker(ep: EmbeddingEndpoint) -> None:
            nonlocal completed
            while True:
                try:
                    chunk_idx = chunk_queue.get(timeout=0.01)
                except Empty:
                    with lock:
                        if completed >= len(texts):
                            return
                    continue

                result = self._get_embedding_with_retry(texts[chunk_idx], ep)
                results[chunk_idx] = result

                with lock:
                    completed += 1
                chunk_queue.task_done()

        threads = []
        for ep in self.endpoints:
            if not ep.is_healthy or ep.url == "siliconflow://":
                continue
            for _ in range(4):
                t = threading.Thread(target=worker, args=(ep,), daemon=True)
                t.start()
                threads.append(t)

        for t in threads:
            t.join()

        return [
            r
            if r is not None
            else (self.endpoints[0].name, [0.0] * self.endpoints[0].dimensions, "处理超时")
            for r in results
        ]

    async def aget_text_embedding(self, text: str) -> List[float]:
        """异步获取单条文本的 embedding（直接调用，不走批处理流程）"""
        ep = self._get_best_endpoint()
        _, embedding, _ = await self._run_embedding_in_thread(text, ep)
        return embedding

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """异步批量获取 embeddings"""
        return [embedding for _, embedding, _ in await self.process_batch(texts)]

    def _run_sync(self, coro) -> Any:
        """在同步环境中运行协程（用于不支持 async 的调用方）"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: Dict[str, Any] = {}
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

    def get_text_embeddings_with_errors(self, texts: List[str]) -> List[EmbeddingResult]:
        """同步批量获取 embeddings，包含错误信息

        Returns:
            List[EmbeddingResult] - [(ep_name, embedding, error), ...]
        """
        return self._run_sync(self.process_batch(texts))

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

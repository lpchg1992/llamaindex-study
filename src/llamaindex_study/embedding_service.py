"""
Ollama Embedding 服务

提供统一的 Embedding 服务，支持：
- 本地和远程 Ollama 端点
- 批量 embedding（提高吞吐量）
- 负载均衡
- 连接池复用
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

EMBEDDING_DIM = 1024


class SiliconFlowEmbedding:
    """
    SiliconFlow 云端 Embedding（默认备用）

    调用 SiliconFlow 的 /v1/embeddings 接口，
    使用 Pro/BAAI/bge-m3 模型。
    """

    def __init__(
        self,
        model: str = "Pro/BAAI/bge-m3",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        settings = get_settings()
        self.model = model
        self.api_key = api_key or settings.siliconflow_api_key
        self.base_url = base_url or settings.siliconflow_base_url
        self._client = None

    def _get_client(self):
        """懒加载 httpx 客户端"""
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=60.0)
        return self._client

    def get_text_embedding(self, text: str) -> List[float]:
        """单条文本 embedding"""
        results = self.get_text_embeddings([text])
        return results[0]

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """批量文本 embedding"""
        if not texts:
            return []

        payload = {"model": self.model, "input": texts}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            client = self._get_client()
            response = client.post(
                f"{self.base_url}/embeddings", json=payload, headers=headers
            )
            if response.status_code != 200:
                logger.error(
                    f"SiliconFlow embedding 失败: {response.status_code} {response.text}"
                )
                return [[0.0] * EMBEDDING_DIM for _ in texts]

            data = response.json()
            embeddings = data.get("data", [])
            # 按 input 顺序返回
            embedding_map = {item["index"]: item["embedding"] for item in embeddings}
            return [
                embedding_map.get(i, [0.0] * EMBEDDING_DIM) for i in range(len(texts))
            ]
        except Exception as e:
            logger.error(f"SiliconFlow embedding 请求异常: {e}")
            return [[0.0] * EMBEDDING_DIM for _ in texts]

    def close(self):
        """关闭客户端"""
        if self._client:
            self._client.close()
            self._client = None


@dataclass
class OllamaEndpoint:
    """Ollama 端点配置"""

    name: str
    url: str
    model: str
    enabled: bool = True
    healthy: bool = True
    avg_latency: float = 0.0
    total_requests: int = 0
    failed_requests: int = 0
    last_check: float = 0


class OllamaEmbeddingService:
    """
    Ollama Embedding 服务

    支持多端点配置，自动选择最快的端点，
    提供批量 embedding 接口。
    """

    # 默认端点配置
    DEFAULT_LOCAL = OllamaEndpoint(
        name="本地",
        url="http://localhost:11434",
        model="bge-m3",
    )

    DEFAULT_REMOTE = OllamaEndpoint(
        name="远程 3080",
        url="http://192.168.31.169:11434",
        model="bge-m3",
    )

    def __init__(
        self,
        model: Optional[str] = None,
        endpoints: Optional[List[OllamaEndpoint]] = None,
        batch_size: int = 10,
        timeout: float = 60.0,
    ):
        """
        初始化 Embedding 服务

        Args:
            model: 默认模型名称
            endpoints: 端点列表（如果为 None，使用默认端点）
            batch_size: 批量大小
            timeout: 请求超时时间
        """
        settings = get_settings()

        self.default_model = model or settings.ollama_embed_model
        self.default_url = settings.ollama_base_url
        self.batch_size = batch_size
        self.timeout = timeout

        # 端点列表
        if endpoints:
            self.endpoints = endpoints
        else:
            # 使用配置中的端点 + 默认远程端点
            self.endpoints = [self.DEFAULT_LOCAL, self.DEFAULT_REMOTE]

        # 更新端点配置
        for ep in self.endpoints:
            ep.model = self.default_model
            if ep.url == "http://localhost:11434":
                ep.url = self.default_url

        # 选择最佳端点
        self._best_endpoint: Optional[OllamaEndpoint] = None
        self._lock = asyncio.Lock()

        # 统计信息
        self._total_requests = 0
        self._total_latency = 0.0

    async def _check_endpoint_health(self, endpoint: OllamaEndpoint) -> bool:
        """检查端点健康状态"""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{endpoint.url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False

    def _select_best_endpoint(self) -> OllamaEndpoint:
        """选择最佳端点（延迟最低、健康的）"""
        available = [ep for ep in self.endpoints if ep.enabled and ep.healthy]

        if not available:
            # 如果没有可用的健康端点，返回第一个
            return self.endpoints[0] if self.endpoints else self.DEFAULT_LOCAL

        # 按延迟排序
        available.sort(
            key=lambda x: x.avg_latency if x.avg_latency > 0 else float("inf")
        )
        return available[0]

    async def _embed_single(self, endpoint: OllamaEndpoint, text: str) -> List[float]:
        """单条 embedding"""
        import httpx
        import json

        # Ollama /api/embed 端点使用 "input" 字段，且模型名需要带 :latest 后缀
        model_name = endpoint.model
        if not model_name.endswith(":latest"):
            model_name = f"{model_name}:latest"

        payload = {
            "model": model_name,
            "input": text[:8192],  # Ollama 有长度限制
        }

        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{endpoint.url}/api/embed",
                    json=payload,
                )

                latency = time.time() - start_time
                endpoint.avg_latency = (
                    endpoint.avg_latency * endpoint.total_requests + latency
                ) / (endpoint.total_requests + 1)
                endpoint.total_requests += 1

                if response.status_code == 200:
                    result = response.json()
                    return result["embedding"]
                else:
                    endpoint.failed_requests += 1
                    raise Exception(f"API error: {response.status_code}")

        except Exception as e:
            endpoint.healthy = False
            endpoint.failed_requests += 1
            endpoint.last_check = time.time()
            raise

    async def get_embedding(self, text: str) -> List[float]:
        """
        获取单条文本的 embedding

        自动选择最佳端点。
        """
        if self._best_endpoint is None:
            async with self._lock:
                if self._best_endpoint is None:
                    self._best_endpoint = self._select_best_endpoint()

        # 尝试当前最佳端点
        try:
            return await self._embed_single(self._best_endpoint, text)
        except Exception:
            # 端点失败，刷新选择
            async with self._lock:
                self._best_endpoint = self._select_best_endpoint()
                return await self._embed_single(self._best_endpoint, text)

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        批量获取 embeddings

        优化：优先使用一个端点处理所有文本，失败后尝试其他端点。

        Args:
            texts: 文本列表

        Returns:
            embedding 列表
        """
        if not texts:
            return []

        # 排序端点（优先选择延迟最低的）
        sorted_endpoints = sorted(
            [ep for ep in self.endpoints if ep.enabled and ep.healthy],
            key=lambda x: x.avg_latency if x.avg_latency > 0 else float("inf"),
        )

        if not sorted_endpoints:
            sorted_endpoints = self.endpoints

        last_error = None

        for endpoint in sorted_endpoints:
            try:
                results = []
                start_time = time.time()

                # 并发发送所有请求
                tasks = [self._embed_single(endpoint, text) for text in texts]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                total_latency = time.time() - start_time

                # 检查是否有失败
                has_error = any(isinstance(r, Exception) for r in results)

                if has_error:
                    endpoint.healthy = False
                    # 返回成功的结果，失败的重试
                    successful = [r for r in results if not isinstance(r, Exception)]
                    failed_indices = [
                        i for i, r in enumerate(results) if isinstance(r, Exception)
                    ]

                    logger.warning(
                        f"端点 {endpoint.name} 部分失败: {len(failed_indices)}/{len(texts)}"
                    )

                    if successful:
                        endpoint.avg_latency = (
                            endpoint.avg_latency * endpoint.total_requests
                            + total_latency
                        ) / (endpoint.total_requests + 1)
                        endpoint.total_requests += 1
                        return successful

                    continue
                else:
                    endpoint.avg_latency = (
                        endpoint.avg_latency * endpoint.total_requests + total_latency
                    ) / (endpoint.total_requests + 1)
                    endpoint.total_requests += 1
                    return results

            except Exception as e:
                last_error = e
                endpoint.healthy = False
                endpoint.last_check = time.time()
                logger.warning(f"端点 {endpoint.name} 完全失败: {e}")
                continue

        # 所有端点都失败
        raise RuntimeError(f"所有端点都失败: {last_error}")

    def get_embedding_sync(self, text: str) -> List[float]:
        """同步获取 embedding（用于非异步场景）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.get_embedding(text))
        finally:
            loop.close()

    def get_embeddings_sync(self, texts: List[str]) -> List[List[float]]:
        """同步批量获取 embeddings"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.get_embeddings(texts))
        finally:
            loop.close()

    async def health_check_all(self) -> Dict[str, bool]:
        """检查所有端点的健康状态"""
        tasks = [self._check_endpoint_health(ep) for ep in self.endpoints]
        results = await asyncio.gather(*tasks)

        for ep, healthy in zip(self.endpoints, results):
            ep.healthy = healthy
            ep.last_check = time.time()

        return {ep.name: ep.healthy for ep in self.endpoints}

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_requests": self._total_requests,
            "total_latency": self._total_latency,
            "endpoints": [
                {
                    "name": ep.name,
                    "url": ep.url,
                    "healthy": ep.healthy,
                    "avg_latency": ep.avg_latency,
                    "total_requests": ep.total_requests,
                    "failed_requests": ep.failed_requests,
                }
                for ep in self.endpoints
            ],
            "best_endpoint": self._best_endpoint.name if self._best_endpoint else None,
        }


# 全局实例
_embedding_service: Optional[OllamaEmbeddingService] = None


def get_embedding_service(
    model: Optional[str] = None,
    endpoints: Optional[List[OllamaEndpoint]] = None,
    batch_size: int = 10,
) -> OllamaEmbeddingService:
    """获取全局 Embedding 服务实例"""
    global _embedding_service

    if _embedding_service is None:
        _embedding_service = OllamaEmbeddingService(
            model=model,
            endpoints=endpoints,
            batch_size=batch_size,
        )

    return _embedding_service


def reset_embedding_service():
    """重置全局实例（用于测试或配置变更）"""
    global _embedding_service
    _embedding_service = None

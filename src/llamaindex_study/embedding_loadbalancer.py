"""
Embedding 负载均衡器

自动检测并使用本地和远程 Ollama 服务，支持：
- 并行调用（同时向所有健康端点发送请求）
- 故障自动切换
- 性能监控
"""

import asyncio
import time
import random
from typing import List, Optional, Tuple, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class Endpoint:
    """Ollama 端点"""
    name: str
    url: str
    enabled: bool = True
    healthy: bool = True
    avg_latency: float = 0.0
    total_requests: int = 0
    failed_requests: int = 0
    last_check: float = 0
    last_error: Optional[str] = None
    is_local: bool = False  # 标记是否为本地端点


@dataclass
class LoadBalancerConfig:
    """负载均衡配置"""
    endpoints: List[Tuple[str, str]] = field(default_factory=list)
    health_check_interval: int = 30
    failure_threshold: int = 3
    parallel_mode: bool = True  # 是否使用并行模式


class EmbeddingLoadBalancer:
    """
    Embedding 负载均衡器
    
    支持两种模式：
    1. 本地优先模式（默认）：优先使用本地，本地失败时切换到远程
    2. 并行模式：同时向所有健康端点发送请求，使用最快的结果
    
    使用方式：
    ```python
    lb = EmbeddingLoadBalancer()
    lb.add_endpoint("本地", "http://localhost:11434", is_local=True)
    lb.add_endpoint("远程 3080", "http://192.168.31.63:11434")
    
    # 获取 embedding
    result = lb.get_text_embedding("测试文本")
    
    # 或使用并行模式
    lb.config.parallel_mode = True
    ```
    """
    
    def __init__(self, model_name: str = "bge-m3", config: LoadBalancerConfig = None):
        self.model_name = model_name
        self.config = config or LoadBalancerConfig()
        self.endpoints: List[Endpoint] = []
        self._health_check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._embedders_cache: dict = {}  # 缓存 embedder 实例
        
    def add_endpoint(self, name: str, url: str, is_local: bool = False) -> "EmbeddingLoadBalancer":
        """添加端点"""
        endpoint = Endpoint(name=name, url=url, is_local=is_local)
        self.endpoints.append(endpoint)
        logger.info(f"添加端点: {name} ({url}), 本地={is_local}")
        return self
    
    async def _get_embedder(self, endpoint: Endpoint):
        """获取或创建 embedder（每次创建新实例，避免事件循环问题）"""
        from llama_index.embeddings.ollama import OllamaEmbedding
        return OllamaEmbedding(
            model_name=self.model_name,
            base_url=endpoint.url,
        )
    
    async def _health_check_endpoint(self, endpoint: Endpoint) -> bool:
        """检查端点健康状态"""
        try:
            embedder = await self._get_embedder(endpoint)
            
            start = time.time()
            await asyncio.wait_for(
                embedder.aget_text_embedding("health check"),
                timeout=15
            )
            latency = time.time() - start
            
            async with self._lock:
                endpoint.healthy = True
                endpoint.last_check = time.time()
                endpoint.last_error = None
                endpoint.avg_latency = (endpoint.avg_latency + latency) / 2 if endpoint.avg_latency > 0 else latency
                    
            logger.info(f"端点 {endpoint.name} 健康 (延迟: {latency:.2f}s)")
            return True
            
        except asyncio.TimeoutError:
            async with self._lock:
                endpoint.healthy = False
                endpoint.last_error = "Timeout"
            logger.warning(f"端点 {endpoint.name} 健康检查超时")
            return False
        except Exception as e:
            async with self._lock:
                endpoint.healthy = False
                endpoint.last_error = str(e)
            logger.warning(f"端点 {endpoint.name} 健康检查失败: {e}")
            return False
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while True:
            try:
                for endpoint in self.endpoints:
                    if endpoint.enabled:
                        await self._health_check_endpoint(endpoint)
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"健康检查循环错误: {e}")
                await asyncio.sleep(5)
    
    async def start_health_checks(self):
        """启动健康检查"""
        if self._health_check_task is None:
            self._health_check_task = asyncio.create_task(self._health_check_loop())
            # 立即执行一次检查
            for endpoint in self.endpoints:
                await self._health_check_endpoint(endpoint)
    
    async def stop_health_checks(self):
        """停止健康检查"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
    
    def _get_healthy_endpoints(self) -> List[Endpoint]:
        """获取所有健康的端点"""
        return [ep for ep in self.endpoints if ep.enabled and ep.healthy]
    
    async def _parallel_get_embedding(self, text: str) -> List[float]:
        """并行模式：同时向所有健康端点发送请求，使用最快的结果"""
        healthy = self._get_healthy_endpoints()
        
        if not healthy:
            raise RuntimeError("没有可用的 embedding 端点")
        
        async def try_endpoint(endpoint: Endpoint):
            """尝试获取 embedding"""
            start = time.time()
            try:
                embedder = await self._get_embedder(endpoint)
                result = await asyncio.wait_for(
                    embedder.aget_text_embedding(text),
                    timeout=60
                )
                elapsed = time.time() - start
                async with self._lock:
                    endpoint.total_requests += 1
                return (result, elapsed, endpoint.name, None)
            except Exception as e:
                async with self._lock:
                    endpoint.failed_requests += 1
                return (None, time.time() - start, endpoint.name, str(e))
        
        # 同时向所有端点发送请求
        tasks = [try_endpoint(ep) for ep in healthy]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 找出最快成功的
        best = None
        best_latency = float('inf')
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"端点异常: {r}")
                continue
            embedding, latency, name, error = r
            if error:
                logger.warning(f"端点 {name} 失败: {error}")
                continue
            if embedding is not None and latency < best_latency:
                best = embedding
                best_latency = latency
                logger.debug(f"端点 {name} 最快 ({latency:.2f}s)")
        
        if best is not None:
            return best
        
        raise RuntimeError("所有端点都失败了")
    
    async def _local_first_get_embedding(self, text: str) -> List[float]:
        """本地优先模式：优先使用本地，本地失败时切换到远程"""
        # 优先选择本地
        local = [ep for ep in self._get_healthy_endpoints() if ep.is_local]
        remote = [ep for ep in self._get_healthy_endpoints() if not ep.is_local]
        
        priority = local + remote
        
        for endpoint in priority:
            try:
                embedder = await self._get_embedder(endpoint)
                result = await asyncio.wait_for(
                    embedder.aget_text_embedding(text),
                    timeout=60
                )
                async with self._lock:
                    endpoint.total_requests += 1
                return result
            except Exception as e:
                async with self._lock:
                    endpoint.failed_requests += 1
                    endpoint.last_error = str(e)
                logger.warning(f"端点 {endpoint.name} 失败，尝试下一个")
                continue
        
        raise RuntimeError("所有端点都失败了")
    
    async def aget_text_embedding(self, text: str) -> List[float]:
        """异步获取 embedding"""
        if self.config.parallel_mode:
            return await self._parallel_get_embedding(text)
        else:
            return await self._local_first_get_embedding(text)
    
    def get_text_embedding(self, text: str) -> List[float]:
        """同步获取 embedding（轮询分配到不同端点）"""
        from llama_index.embeddings.ollama import OllamaEmbedding
        
        # 获取所有可用端点
        available = [ep for ep in self.endpoints if ep.enabled]
        
        if not available:
            raise RuntimeError("没有可用的 embedding 端点")
        
        # 轮询选择端点（实现负载均衡）
        if not hasattr(self, '_round_robin_counter'):
            self._round_robin_counter = 0
        
        endpoint = available[self._round_robin_counter % len(available)]
        self._round_robin_counter += 1
        
        try:
            embedder = OllamaEmbedding(
                model_name=self.model_name,
                base_url=endpoint.url,
            )
            result = embedder.get_text_embedding(text)
            endpoint.total_requests += 1
            return result
        except Exception as e:
            endpoint.failed_requests += 1
            endpoint.last_error = str(e)
            # 尝试其他端点
            for ep in available:
                if ep == endpoint:
                    continue
                try:
                    embedder = OllamaEmbedding(
                        model_name=self.model_name,
                        base_url=ep.url,
                    )
                    result = embedder.get_text_embedding(text)
                    ep.total_requests += 1
                    return result
                except Exception:
                    ep.failed_requests += 1
                    continue
            
            raise RuntimeError(f"所有端点都失败了: {e}")
    
    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """异步批量获取 embeddings（使用并行模式）"""
        if self.config.parallel_mode:
            # 并行模式：所有文本同时处理
            tasks = [self.aget_text_embedding(text) for text in texts]
            return await asyncio.gather(*tasks)
        else:
            # 顺序处理
            return [await self.aget_text_embedding(text) for text in texts]
    
    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        批量获取 embeddings（并行分配到多个端点）
        
        策略：将文本平均分配到所有可用端点，实现真正的并行处理
        """
        from llama_index.embeddings.ollama import OllamaEmbedding
        import concurrent.futures
        
        if not texts:
            return []
        
        # 获取所有可用端点
        available = [ep for ep in self.endpoints if ep.enabled]
        
        if not available:
            raise RuntimeError("没有可用的 embedding 端点")
        
        # 将文本平均分配到各个端点
        texts_per_endpoint = len(texts) // len(available) + 1
        assignments = []
        
        for i, endpoint in enumerate(available):
            start = i * texts_per_endpoint
            end = min((i + 1) * texts_per_endpoint, len(texts))
            if start < len(texts):
                assignments.append((endpoint, texts[start:end]))
        
        def process_endpoint(args):
            """处理单个端点的文本"""
            endpoint, endpoint_texts = args
            results = []
            embedder = OllamaEmbedding(
                model_name=self.model_name,
                base_url=endpoint.url,
            )
            
            for text in endpoint_texts:
                try:
                    result = embedder.get_text_embedding(text)
                    endpoint.total_requests += 1
                    results.append(result)
                except Exception as e:
                    endpoint.failed_requests += 1
                    # 使用零向量作为占位
                    results.append([0.0] * 1024)
            
            return results
        
        # 并行处理所有端点
        all_results = [None] * len(texts)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(available)) as executor:
            futures = {executor.submit(process_endpoint, assign): assign for assign in assignments}
            
            for future in concurrent.futures.as_completed(futures):
                assign = futures[future]
                endpoint = assign[0]
                endpoint_texts = assign[1]
                results = future.result()
                
                # 将结果放回对应位置
                for i, text in enumerate(endpoint_texts):
                    original_idx = texts.index(text)
                    all_results[original_idx] = results[i]
        
        # 处理可能遗漏的（理论上不会发生）
        for i, result in enumerate(all_results):
            if result is None:
                all_results[i] = [0.0] * 1024
        
        return all_results
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "endpoints": [
                {
                    "name": ep.name,
                    "url": ep.url,
                    "healthy": ep.healthy,
                    "enabled": ep.enabled,
                    "is_local": ep.is_local,
                    "avg_latency": ep.avg_latency,
                    "total_requests": ep.total_requests,
                    "failed_requests": ep.failed_requests,
                }
                for ep in self.endpoints
            ],
            "model": self.model_name,
            "parallel_mode": self.config.parallel_mode,
        }


# 全局实例
_global_lb: Optional[EmbeddingLoadBalancer] = None


def get_embedding_loadbalancer(model_name: str = "bge-m3", parallel: bool = True) -> EmbeddingLoadBalancer:
    """获取全局负载均衡器实例"""
    global _global_lb
    if _global_lb is None:
        _global_lb = EmbeddingLoadBalancer(model_name=model_name)
        _global_lb.add_endpoint("本地", "http://localhost:11434", is_local=True)
        _global_lb.add_endpoint("远程 3080", "http://192.168.31.63:11434", is_local=False)
        _global_lb.config.parallel_mode = parallel
    return _global_lb


async def health_check_remote() -> bool:
    """快速检查远程 Ollama 是否可用"""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            response = await asyncio.wait_for(
                client.get("http://192.168.31.63:11434/api/tags", timeout=5)
            )
            return response.status_code == 200
    except Exception:
        return False

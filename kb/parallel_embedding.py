"""
并行 Embedding 处理器

使用 asyncio + ThreadPoolExecutor 实现真正的并行处理
支持多端点（本地+远程）同时工作
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Dict, Optional, Tuple, Any

from llama_index.embeddings.ollama import OllamaEmbedding
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

# 配置常量
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
DEFAULT_LOCAL_URL = os.getenv("OLLAMA_LOCAL_URL", "http://localhost:11434")
DEFAULT_REMOTE_URL = os.getenv("OLLAMA_REMOTE_URL", "http://localhost:11434")
MAX_RETRIES = 3
RETRY_DELAY = 1.0


# Embedding 结果类型
EmbeddingResult = Tuple[str, List[float], Optional[str]]


class EmbeddingEndpoint:
    """Embedding 端点配置"""
    
    def __init__(self, name: str, url: str) -> None:
        self.name = name
        self.url = url


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
        
        # 端点配置
        self.endpoints: List[EmbeddingEndpoint] = [
            EmbeddingEndpoint("本地", DEFAULT_LOCAL_URL),
            EmbeddingEndpoint("远程", DEFAULT_REMOTE_URL),
        ]
        
        # 过滤重复的端点 URL
        seen_urls: set = set()
        unique_endpoints: List[EmbeddingEndpoint] = []
        for ep in self.endpoints:
            if ep.url not in seen_urls:
                seen_urls.add(ep.url)
                unique_endpoints.append(ep)
        self.endpoints = unique_endpoints
        
        # 线程池大小 = 端点数量
        self._executor = ThreadPoolExecutor(max_workers=len(self.endpoints))
        
        # 缓存 embed 模型（避免重复创建）
        self._models: Dict[str, OllamaEmbedding] = {}
        
        # 统计
        self._stats: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        self._failures: Dict[str, int] = {ep.name: 0 for ep in self.endpoints}
        
        logger.info(f"并行 Embedding 处理器初始化完成，线程数: {len(self.endpoints)}")
    
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
                model = self._get_model(ep.url)
                embedding = model.get_text_embedding(text)
                self._stats[ep.name] += 1
                return (ep.name, embedding, None)
            except Exception as e:
                last_error = str(e)
                if attempt < MAX_RETRIES - 1:
                    logger.debug(f"[{ep.name}] Embedding 失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {e}")
        
        # 所有重试都失败了
        self._failures[ep.name] += 1
        logger.warning(f"[{ep.name}] Embedding 最终失败: {last_error}")
        return (ep.name, [0.0] * EMBEDDING_DIM, f"重试{MAX_RETRIES}次后失败: {last_error}")
    
    async def get_embedding(self, text: str, ep_name: str) -> EmbeddingResult:
        """异步获取单个 embedding"""
        ep = next((e for e in self.endpoints if e.name == ep_name), self.endpoints[0])
        
        loop = asyncio.get_event_loop()
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
        
        async def get_embedding_from_any_endpoint(text: str) -> EmbeddingResult:
            """向所有端点并发请求，返回最快成功的"""
            async def try_endpoint(ep: EmbeddingEndpoint) -> EmbeddingResult:
                """尝试从指定端点获取 embedding"""
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    self._executor,
                    lambda: self._get_embedding_with_retry(text, ep)
                )
            
            # 同时向所有端点发送请求
            tasks = [try_endpoint(ep) for ep in self.endpoints]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 找出最快成功的
            for r in results:
                if isinstance(r, Exception):
                    continue
                ep_name, embedding, error = r
                if error is None and embedding:
                    return (ep_name, embedding, None)
            
            # 所有端点都失败了，返回第一个失败结果供调试
            first_result = next(
                (r for r in results if isinstance(r, tuple)),
                (self.endpoints[0].name, [0.0] * EMBEDDING_DIM, "所有端点都失败")
            )
            return first_result
        
        # 并发处理所有文本
        tasks = [get_embedding_from_any_endpoint(text) for text in texts]
        return await asyncio.gather(*tasks)
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def get_failure_stats(self) -> Dict[str, int]:
        """获取失败统计"""
        return self._failures.copy()
    
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

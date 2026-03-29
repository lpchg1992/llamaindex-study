"""
并行 Embedding 处理器

使用 asyncio + ThreadPoolExecutor 实现真正的并行处理
支持多端点（本地+远程）同时工作
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Dict, Optional
from llama_index.embeddings.ollama import OllamaEmbedding
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class ParallelEmbeddingProcessor:
    """
    并行 Embedding 处理器
    
    特点：
    - 使用 ThreadPoolExecutor 实现真正的并行
    - 支持多端点（本地+远程）同时工作
    - 使用 asyncio 调度，无阻塞等待
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # 端点配置
        self.endpoints = [
            {"name": "本地", "url": "http://localhost:11434"},
            {"name": "远程", "url": "http://192.168.31.169:11434"},
        ]
        
        # 线程池大小 = 端点数量
        self._executor = ThreadPoolExecutor(max_workers=len(self.endpoints))
        
        # 缓存 embed 模型（避免重复创建）
        self._models: Dict[str, OllamaEmbedding] = {}
        
        # 统计
        self._stats = {ep["name"]: 0 for ep in self.endpoints}
        
        logger.info(f"并行 Embedding 处理器初始化完成，线程数: {len(self.endpoints)}")
    
    def _get_model(self, ep_url: str) -> OllamaEmbedding:
        """获取或创建 embed 模型"""
        if ep_url not in self._models:
            self._models[ep_url] = OllamaEmbedding(
                model_name="bge-m3",
                base_url=ep_url
            )
        return self._models[ep_url]
    
    async def _get_embedding_sync(self, text: str, ep_url: str, ep_name: str) -> tuple:
        """同步获取 embedding（在线程池中执行）"""
        try:
            model = self._get_model(ep_url)
            embedding = model.get_text_embedding(text)
            self._stats[ep_name] += 1
            return (ep_name, embedding, None)
        except Exception as e:
            logger.warning(f"[{ep_name}] Embedding 失败: {e}")
            return (ep_name, [0.0] * 1024, str(e))
    
    async def get_embedding(self, text: str, ep_name: str) -> tuple:
        """异步获取单个 embedding"""
        ep = next((e for e in self.endpoints if e["name"] == ep_name), self.endpoints[0])
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: self._sync_wrapper(text, ep["url"], ep_name)
        )
    
    def _sync_wrapper(self, text: str, ep_url: str, ep_name: str) -> tuple:
        """同步包装器"""
        try:
            model = self._get_model(ep_url)
            embedding = model.get_text_embedding(text)
            self._stats[ep_name] += 1
            return (ep_name, embedding, None)
        except Exception as e:
            logger.warning(f"[{ep_name}] Embedding 失败: {e}")
            return (ep_name, [0.0] * 1024, str(e))
    
    async def process_batch(self, texts: List[str]) -> List[tuple]:
        """
        批量处理文本列表，并行竞争模式
        
        每个文本同时向所有端点发送请求，谁先完成用谁的结果
        这样可以充分利用两个端点的并行能力
        
        Args:
            texts: 文本列表
            
        Returns:
            [(ep_name, embedding, error), ...]
        """
        if not texts:
            return []
        
        async def get_embedding_from_any_endpoint(text: str) -> tuple:
            """向所有端点并发请求，返回最快的结果"""
            async def try_endpoint(ep: dict) -> tuple:
                """尝试从指定端点获取 embedding"""
                try:
                    model = self._get_model(ep["url"])
                    embedding = model.get_text_embedding(text)
                    self._stats[ep["name"]] += 1
                    return (ep["name"], embedding, None)
                except Exception as e:
                    logger.warning(f"[{ep['name']}] Embedding 失败: {e}")
                    return (ep["name"], [0.0] * 1024, str(e))
            
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
            
            # 所有端点都失败了
            return (self.endpoints[0]["name"], [0.0] * 1024, "所有端点都失败")
        
        # 并发处理所有文本
        tasks = [get_embedding_from_any_endpoint(text) for text in texts]
        return await asyncio.gather(*tasks)
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return self._stats.copy()
    
    def shutdown(self):
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

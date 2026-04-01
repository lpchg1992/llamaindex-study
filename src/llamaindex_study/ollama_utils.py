"""
Ollama 工具模块

提供统一的 Ollama 配置接口，消除重复的 embedding 模型初始化代码。
"""

import asyncio
from typing import Any, List, Optional

from llama_index.embeddings.ollama import OllamaEmbedding


class OllamaEmbedder:
    """Ollama Embedding 封装类，使用正确的 /api/embed 端点"""

    def __init__(self, model_name: str, base_url: str):
        self.model_name = model_name
        self.base_url = base_url
        self._sync_model = None

    def _get_sync_model(self):
        """获取同步 embedding 模型（懒加载）"""
        if self._sync_model is None:
            self._sync_model = OllamaEmbedding(
                model_name=self.model_name,
                base_url=self.base_url,
            )
        return self._sync_model

    def get_text_embedding(self, text: str) -> List[float]:
        """同步获取单条 embedding"""
        return self._call_ollama_embed(text)

    def aget_text_embedding(self, text: str) -> List[float]:
        """异步获取单条 embedding"""
        import asyncio

        try:
            asyncio.get_running_loop()
            return asyncio.run(self._call_ollama_embed_async(text))
        except RuntimeError:
            return self._call_ollama_embed(text)

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """同步批量获取 embeddings"""
        return [self._call_ollama_embed(text) for text in texts]

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        """异步批量获取 embeddings"""
        return [self._call_ollama_embed(text) for text in texts]

    def _call_ollama_embed(self, text: str) -> List[float]:
        """直接调用 Ollama /api/embed 端点"""
        import httpx

        model_name = self.model_name
        if not model_name.endswith(":latest"):
            model_name = f"{model_name}:latest"

        payload = {
            "model": model_name,
            "input": text[:8192],
        }

        with httpx.Client(timeout=60.0) as client:
            response = client.post(f"{self.base_url}/api/embed", json=payload)
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            result = response.json()
            return result["embedding"]

    async def _call_ollama_embed_async(self, text: str) -> List[float]:
        """异步调用 Ollama /api/embed 端点"""
        import httpx

        model_name = self.model_name
        if not model_name.endswith(":latest"):
            model_name = f"{model_name}:latest"

        payload = {
            "model": model_name,
            "input": text[:8192],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/api/embed", json=payload)
            if response.status_code != 200:
                raise Exception(f"API error: {response.status_code}")
            result = response.json()
            return result["embedding"]


from llama_index.core import Settings as LlamaSettings

from llamaindex_study.config import get_settings


def create_ollama_embedding(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OllamaEmbedding:
    settings = get_settings()
    return OllamaEmbedding(
        model_name=model or settings.ollama_embed_model,
        base_url=base_url or settings.ollama_base_url,
    )


def configure_global_embed_model(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    chunk_size: int = 512,
    embed_batch_size: int = 10,
) -> OllamaEmbedding:
    settings = get_settings()
    embed_model = OllamaEmbedding(
        model_name=model or settings.ollama_embed_model,
        base_url=base_url or settings.ollama_base_url,
    )

    LlamaSettings.embed_model = embed_model
    LlamaSettings.chunk_size = chunk_size
    LlamaSettings.embed_batch_size = embed_batch_size

    return embed_model


def create_parallel_ollama_embedding():
    """创建支持多端点调度的 Embedding 模型适配器"""
    from kb.parallel_embedding import create_parallel_embedding_model

    return create_parallel_embedding_model()


def configure_llamaindex_for_siliconflow() -> None:
    """
    配置 LlamaIndex 使用 SiliconFlow LLM

    注册 DeepSeek-V3.2 模型的上下文窗口和 tokenizer，
    使 LlamaIndex 能正确处理该模型。
    """
    from llama_index.llms.openai import OpenAI
    from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS
    import tiktoken
    import tiktoken.model as tm

    settings = get_settings()

    model_key = settings.siliconflow_model
    if model_key not in ALL_AVAILABLE_MODELS:
        ALL_AVAILABLE_MODELS[model_key] = 128000

    try:
        tiktoken.encoding_for_model(model_key)
    except KeyError:
        tm.MODEL_TO_ENCODING[model_key] = "cl100k_base"

    LlamaSettings.llm = OpenAI(
        model=model_key,
        api_key=settings.siliconflow_api_key,
        api_base=settings.siliconflow_base_url,
    )


class RetryableOllama:
    """Ollama LLM 包装类，支持 503 错误重试

    当 Ollama 模型未加载时，会返回 503 Service Unavailable。
    此包装类会自动重试请求，直到模型加载完成。
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
    ):
        from llama_index.llms.ollama import Ollama

        self._ollama = Ollama(
            model=model,
            base_url=base_url,
            request_timeout=300,
        )
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._backoff_factor = backoff_factor

    def _call_with_retry(self, method_name: str, *args, **kwargs) -> Any:
        """带重试的调用"""
        import time
        import logging

        logger = logging.getLogger(__name__)
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                method = getattr(self._ollama, method_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                if "503" in error_str or "service unavailable" in error_str:
                    logger.warning(
                        f"Ollama 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    def complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("complete", prompt, **kwargs)

    def completion(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("completion", prompt, **kwargs)

    def predict(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("predict", prompt, **kwargs)

    def stream_complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("stream_complete", prompt, **kwargs)

    def chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_retry("chat", messages, **kwargs)

    def stream_chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_retry("stream_chat", messages, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ollama, name)


def create_llm(
    mode: Optional[str] = None,
    model: Optional[str] = None,
) -> Any:
    """
    根据配置创建 LLM 实例

    Args:
        mode: LLM 模式，可选 "siliconflow" 或 "ollama"。如果为 None，使用配置默认值。
        model: 模型名称。对于 ollama 模式，可选 "tomng/lfm2.5-instruct:1.2b" 或 "lfm2.5-thinking:latest"。
               对于 siliconflow 模式，忽略此参数。

    Returns:
        LLM 实例
    """
    from llama_index.llms.openai import OpenAI

    settings = get_settings()
    mode = mode or settings.llm_mode

    if mode == "ollama":
        ollama_model = model or settings.ollama_llm_model
        return RetryableOllama(
            model=ollama_model,
            base_url=settings.ollama_base_url,
            max_retries=5,
            initial_delay=2.0,
            backoff_factor=1.5,
        )
    else:
        configure_llamaindex_for_siliconflow()
        return LlamaSettings.llm


def configure_llamaindex(mode: Optional[str] = None) -> None:
    """
    配置 LlamaIndex 全局 LLM

    Args:
        mode: LLM 模式，可选 "siliconflow" 或 "ollama"。如果为 None，使用配置默认值。
    """
    settings = get_settings()
    mode = mode or settings.llm_mode

    if mode == "ollama":
        from llama_index.llms.ollama import Ollama

        ollama_model = settings.ollama_llm_model
        llm = Ollama(
            model=ollama_model,
            base_url=settings.ollama_base_url,
            request_timeout=300,
        )
        LlamaSettings.llm = llm
    else:
        configure_llamaindex_for_siliconflow()


class BatchEmbeddingHelper:
    """
    批量 Embedding 辅助类

    提供高效的批量 embedding 生成，支持：
    - 并发请求
    - 批量处理
    - 自动重试
    """

    def __init__(
        self,
        embed_model: Optional[OllamaEmbedding] = None,
        batch_size: int = 10,
        max_concurrency: int = 3,
    ):
        """
        初始化批量 Embedding 辅助类

        Args:
            embed_model: Embedding 模型（如果不提供，创建默认模型）
            batch_size: 每批处理的数量
            max_concurrency: 最大并发数
        """
        self.embed_model = embed_model or create_ollama_embedding()
        self.batch_size = batch_size
        self.max_concurrency = max_concurrency

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成 embeddings（同步）

        Args:
            texts: 文本列表

        Returns:
            embedding 列表
        """
        if not texts:
            return []

        if hasattr(self.embed_model, "get_text_embeddings"):
            try:
                return self.embed_model.get_text_embeddings(texts)
            except Exception as e:
                print(f"      ⚠️  批量 Embedding 失败，回退逐条模式: {e}")

        results = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            for text in batch:
                try:
                    embedding = self.embed_model.get_text_embedding(text)
                    results.append(embedding)
                except Exception as e:
                    print(f"      ⚠️  Embedding 失败: {e}")
                    results.append([0.0] * 1024)

        return results

    async def embed_documents_async(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成 embeddings（异步）

        使用信号量控制并发数。

        Args:
            texts: 文本列表

        Returns:
            embedding 列表
        """
        if not texts:
            return []

        if hasattr(self.embed_model, "aget_text_embeddings"):
            try:
                return await self.embed_model.aget_text_embeddings(texts)
            except Exception as e:
                print(f"      ⚠️  异步批量 Embedding 失败，回退并发模式: {e}")

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def embed_with_semaphore(text: str) -> List[float]:
            async with semaphore:
                return await self.embed_model.aget_text_embedding(text)

        # 分批处理
        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            tasks = [embed_with_semaphore(text) for text in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for j, result in enumerate(batch_results):
                if isinstance(result, Exception):
                    # 如果失败，使用同步方法重试
                    try:
                        results.append(self.embed_model.get_text_embedding(batch[j]))
                    except Exception:
                        results.append([0.0] * 1024)  # 返回零向量作为占位
                else:
                    results.append(result)

        return results

    def embed_node(self, node) -> None:
        """
        为单个节点生成 embedding

        Args:
            node: LlamaIndex Node 对象
        """
        node.embedding = self.embed_model.get_text_embedding(node.get_content())

    def embed_nodes(self, nodes: List[Any]) -> None:
        """
        批量为节点生成 embeddings

        Args:
            nodes: LlamaIndex Node 列表
        """
        texts = [node.get_content() for node in nodes]
        embeddings = self.embed_documents(texts)

        for node, embedding in zip(nodes, embeddings):
            node.embedding = embedding


__all__ = [
    "create_ollama_embedding",
    "create_parallel_ollama_embedding",
    "configure_global_embed_model",
    "configure_llamaindex_for_siliconflow",
    "BatchEmbeddingHelper",
]

"""
Ollama 工具模块

提供统一的 Ollama 配置接口，消除重复的 embedding 模型初始化代码。
"""

import asyncio
import logging
import time
from typing import Any, List, Optional

from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.core.constants import DEFAULT_NUM_OUTPUTS, DEFAULT_CONTEXT_WINDOW

logger = logging.getLogger(__name__)


class OllamaEmbedder(OllamaEmbedding):
    """Ollama Embedding 封装类，继承自 OllamaEmbedding，支持 503 重试"""

    def __init__(
        self,
        model_name: str,
        base_url: str,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
    ):
        super().__init__(model_name=model_name, base_url=base_url)
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._backoff_factor = backoff_factor

    def _call_with_retry(self, method, *args, **kwargs):
        """带重试的调用"""
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                return method(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                if "503" in error_str or "service unavailable" in error_str:
                    logger.warning(
                        f"Embedding 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    def get_text_embedding(self, text: str) -> List[float]:
        return self._call_with_retry(super().get_text_embedding, text)

    async def aget_text_embedding(self, text: str) -> List[float]:
        return self._call_with_retry(super().aget_text_embedding, text)

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        results = []
        for text in texts:
            result = self._call_with_retry(super().get_text_embedding, text)
            results.append(result)
        return results

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        results = []
        for text in texts:
            result = await self._call_with_retry(super().aget_text_embedding, text)
            results.append(result)
        return results


from llama_index.core import Settings as LlamaSettings

from llamaindex_study.config import get_settings


def create_ollama_embedding(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OllamaEmbedder:
    settings = get_settings()
    return OllamaEmbedder(
        model_name=model or settings.ollama_embed_model,
        base_url=base_url or settings.ollama_base_url,
        max_retries=settings.ollama_max_retries,
        initial_delay=settings.ollama_retry_delay,
        backoff_factor=1.5,
    )


def configure_global_embed_model(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    chunk_size: int = 512,
    embed_batch_size: int = 10,
) -> OllamaEmbedder:
    """配置全局 Embedding 模型（默认使用 OllamaEmbedder，带 503 重试）"""
    settings = get_settings()
    embed_model = OllamaEmbedder(
        model_name=model or settings.ollama_embed_model,
        base_url=base_url or settings.ollama_base_url,
        max_retries=settings.ollama_max_retries,
        initial_delay=settings.ollama_retry_delay,
        backoff_factor=1.5,
    )

    LlamaSettings.embed_model = embed_model
    LlamaSettings.chunk_size = chunk_size
    LlamaSettings.embed_batch_size = embed_batch_size

    return embed_model


def create_parallel_ollama_embedding():
    """创建支持多端点调度的 Embedding 模型适配器"""
    from kb.parallel_embedding import create_parallel_embedding_model

    return create_parallel_embedding_model()


def _configure_siliconflow_llm(
    model: str,
    api_key: str,
    api_base: str,
) -> None:
    """
    配置 LlamaIndex 使用 SiliconFlow LLM

    注册模型的上下文窗口和 tokenizer，
    使 LlamaIndex 能正确处理该模型。
    """
    from llama_index.llms.openai import OpenAI
    from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS
    import tiktoken
    import tiktoken.model as tm

    if model not in ALL_AVAILABLE_MODELS:
        ALL_AVAILABLE_MODELS[model] = 128000

    try:
        tiktoken.encoding_for_model(model)
    except KeyError:
        tm.MODEL_TO_ENCODING[model] = "cl100k_base"

    LlamaSettings.llm = OpenAI(
        model=model,
        api_key=api_key,
        api_base=api_base,
    )


def configure_llamaindex_for_siliconflow() -> None:
    """
    配置 LlamaIndex 使用 SiliconFlow LLM（使用默认配置）

    注册 DeepSeek-V3.2 模型的上下文窗口和 tokenizer，
    使 LlamaIndex 能正确处理该模型。
    """
    settings = get_settings()
    _configure_siliconflow_llm(
        model=settings.siliconflow_model,
        api_key=settings.siliconflow_api_key,
        api_base=settings.siliconflow_base_url,
    )


class RetryableOllama(Ollama):
    """Ollama LLM 子类，支持 503 错误重试

    当 Ollama 模型未加载时，会返回 503 Service Unavailable。
    此子类会自动重试请求，直到模型加载完成。
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
        **kwargs,
    ):
        super().__init__(
            model=model,
            base_url=base_url,
            request_timeout=300,
            **kwargs,
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
                method = getattr(super(), method_name)
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

    async def acomplete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("acomplete", prompt, **kwargs)

    async def achat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_retry("achat", messages, **kwargs)

    async def astream_complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("astream_complete", prompt, **kwargs)

    async def astream_chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_retry("astream_chat", messages, **kwargs)

    def get_context_window(self) -> int:
        """获取上下文窗口大小，带重试机制"""
        import time

        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                # 调用父类的逻辑，但通过 try/except 检测 503
                if self.context_window != -1:
                    return self.context_window

                info = self.client.show(self.model).modelinfo
                for key, value in info.items():
                    if "context_length" in key:
                        self.context_window = int(value)
                        break

                return (
                    self.context_window
                    if self.context_window != -1
                    else 128000  # DEFAULT_CONTEXT_WINDOW fallback
                )
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

    @property
    def metadata(self) -> Any:
        """LLM metadata，带重试机制"""
        from llama_index.core.base.llms.types import LLMMetadata

        return LLMMetadata(
            context_window=self.get_context_window(),
            num_output=DEFAULT_NUM_OUTPUTS,
            model_name=self.model,
            is_chat_model=True,
            is_function_calling_model=self.is_function_calling_model,
        )


# 默认降级模型配置
FALLBACK_OLLAMA_MODEL = "lfm2.5-thinking:latest"


class RetryableSiliconFlowLLM:
    """SiliconFlow LLM 封装类，支持 503 重试和降级到 Ollama

    当 SiliconFlow 返回 503 或服务不可用时，自动重试指定次数。
    如果重试失败，则降级到本地 Ollama 模型 (lfm2.5-thinking:latest)。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str,
        max_retries: int = 3,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
        fallback_model: str = FALLBACK_OLLAMA_MODEL,
    ):
        from llama_index.llms.openai import OpenAI

        self._primary_llm = OpenAI(
            model=model,
            api_key=api_key,
            api_base=api_base,
        )
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._backoff_factor = backoff_factor
        self._fallback_model = fallback_model
        self._fallback_llm: Optional[Any] = None
        self._use_fallback = False

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断是否为可重试的错误"""
        error_str = str(error).lower()
        return any(
            keyword in error_str
            for keyword in [
                "503",
                "service unavailable",
                "rate limit",
                "timeout",
                "connection",
                "network",
            ]
        )

    def _get_fallback_llm(self) -> Any:
        """获取降级用的 Ollama LLM"""
        if self._fallback_llm is None:
            settings = get_settings()
            self._fallback_llm = RetryableOllama(
                model=self._fallback_model,
                base_url=settings.ollama_base_url,
                max_retries=5,
                initial_delay=2.0,
                backoff_factor=1.5,
            )
        return self._fallback_llm

    def _call_with_retry(self, method_name: str, *args, **kwargs) -> Any:
        """带重试的调用，失败后降级到 Ollama"""
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        # 尝试主 LLM (SiliconFlow)
        for attempt in range(self._max_retries):
            try:
                method = getattr(self._primary_llm, method_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_error = e
                if self._is_retryable_error(e):
                    logger.warning(
                        f"SiliconFlow LLM 调用失败 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    # 非重试错误，直接降级
                    logger.warning(f"SiliconFlow LLM 非重试错误，降级到 Ollama: {e}")
                    break

        # 重试耗尽，降级到 Ollama
        logger.info(f"SiliconFlow LLM 重试耗尽，降级到 Ollama ({self._fallback_model})")
        self._use_fallback = True
        fallback_llm = self._get_fallback_llm()
        method = getattr(fallback_llm, method_name)
        return method(*args, **kwargs)

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

    async def acomplete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("acomplete", prompt, **kwargs)

    async def achat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_retry("achat", messages, **kwargs)

    async def astream_complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_retry("astream_complete", prompt, **kwargs)

    async def astream_chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_retry("astream_chat", messages, **kwargs)

    @property
    def metadata(self) -> Any:
        """返回当前使用的 LLM 的 metadata"""
        if self._use_fallback:
            return self._get_fallback_llm().metadata
        from llama_index.core.base.llms.types import LLMMetadata

        return LLMMetadata(
            context_window=128000,
            num_output=DEFAULT_NUM_OUTPUTS,
            model_name=self._model,
            is_chat_model=True,
            is_function_calling_model=False,
        )

    def __repr__(self) -> str:
        if self._use_fallback:
            return f"RetryableSiliconFlowLLM(fallback={self._fallback_model})"
        return f"RetryableSiliconFlowLLM(primary={self._model})"


def create_llm(
    model_id: Optional[str] = None,
    mode: Optional[str] = None,
    model: Optional[str] = None,
) -> Any:
    """
    根据配置创建 LLM 实例

    Args:
        model_id: 模型ID (如 siliconflow/DeepSeek-V3.2, ollama/lfm2.5-instruct)，优先于 mode 参数
        mode: LLM 模式，可选 "siliconflow" 或 "ollama"。如果为 None，使用配置默认值。
        model: 模型名称 (已废弃，使用 model_id 代替)

    Returns:
        LLM 实例
    """
    if model_id:
        from llamaindex_study.config import get_model_registry
        from kb.database import init_vendor_db

        registry = get_model_registry()
        model_info = registry.get_model(model_id)
        if not model_info:
            raise ValueError(f"模型不存在: {model_id}")

        vendor_id = model_info.get("vendor_id", "")
        vendor_db = init_vendor_db()
        vendor_info = vendor_db.get(vendor_id) if vendor_id else None

        if vendor_id.startswith("ollama"):
            base_url = (
                vendor_info.get("api_base") if vendor_info else None
            ) or get_settings().ollama_base_url
            return RetryableOllama(
                model=model_info["name"],
                base_url=base_url,
                max_retries=5,
                initial_delay=2.0,
                backoff_factor=1.5,
            )
        else:
            api_key = (
                vendor_info.get("api_key") if vendor_info else None
            ) or get_settings().siliconflow_api_key
            api_base = (
                vendor_info.get("api_base") if vendor_info else None
            ) or get_settings().siliconflow_base_url
            return RetryableSiliconFlowLLM(
                model=model_info["name"],
                api_key=api_key or "",
                api_base=api_base or "",
                max_retries=3,
                initial_delay=2.0,
                backoff_factor=1.5,
            )

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


def configure_llm_by_model_id(model_id: str) -> None:
    """根据模型ID配置全局 LLM

    Args:
        model_id: 模型ID (如 siliconflow/DeepSeek-V3.2, ollama/lfm2.5-instruct)
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

    if vendor_id.startswith("ollama"):
        settings = get_settings()
        base_url = (
            vendor_info.get("api_base") if vendor_info else None
        ) or settings.ollama_base_url
        llm = RetryableOllama(
            model=model_info["name"],
            base_url=base_url,
            max_retries=settings.ollama_max_retries,
            initial_delay=settings.ollama_retry_delay,
            backoff_factor=1.5,
        )
        LlamaSettings.llm = llm
    else:
        api_key = (
            vendor_info.get("api_key") if vendor_info else None
        ) or get_settings().siliconflow_api_key
        api_base = (
            vendor_info.get("api_base") if vendor_info else None
        ) or get_settings().siliconflow_base_url
        LlamaSettings.llm = RetryableSiliconFlowLLM(
            model=model_info["name"],
            api_key=api_key or "",
            api_base=api_base or "",
            max_retries=3,
            initial_delay=2.0,
            backoff_factor=1.5,
        )


def configure_embed_model_by_model_id(model_id: str) -> OllamaEmbedding:
    """根据模型ID配置全局 Embedding 模型

    Args:
        model_id: 模型ID (如 ollama/bge-m3:latest, ollama_homepc/bge-m3:latest)

    Returns:
        OllamaEmbedding 实例
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
    ) or get_settings().ollama_base_url

    settings = get_settings()
    is_ollama = vendor_id.startswith("ollama") or model_id.startswith("ollama")

    if is_ollama:
        embed_model = OllamaEmbedder(
            model_name=model_info["name"],
            base_url=base_url,
            max_retries=settings.ollama_max_retries,
            initial_delay=settings.ollama_retry_delay,
            backoff_factor=1.5,
        )
    else:
        embed_model = OllamaEmbedding(
            model_name=model_info["name"],
            base_url=base_url,
        )

    LlamaSettings.embed_model = embed_model
    return embed_model


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


_sf_fallback_count = 0
_SF_FALLBACK_THRESHOLD = 3


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
        if not texts:
            return []

        global _sf_fallback_count

        if _sf_fallback_count >= _SF_FALLBACK_THRESHOLD:
            sf = create_siliconflow_embedding()
            return sf.get_text_embeddings(texts)

        if hasattr(self.embed_model, "get_text_embeddings"):
            try:
                result = self.embed_model.get_text_embeddings(texts)
                _sf_fallback_count = 0
                return result
            except Exception as e:
                print(f"      ⚠️  Ollama 批量 embedding 失败: {e}")
                _sf_fallback_count += 1

        results = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            for text in batch:
                try:
                    embedding = self.embed_model.get_text_embedding(text)
                    results.append(embedding)
                except Exception as e:
                    print(f"      ⚠️  Ollama embedding 失败: {e}")
                    _sf_fallback_count += 1
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


def create_siliconflow_embedding(
    model: str = "Pro/BAAI/bge-m3",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
):
    """创建 SiliconFlow embedding 模型"""
    from llamaindex_study.embedding_service import SiliconFlowEmbedding

    return SiliconFlowEmbedding(
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


__all__ = [
    "create_ollama_embedding",
    "create_parallel_ollama_embedding",
    "create_siliconflow_embedding",
    "configure_global_embed_model",
    "configure_embed_model_by_model_id",
    "configure_llamaindex_for_siliconflow",
    "BatchEmbeddingHelper",
]

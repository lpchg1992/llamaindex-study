"""
Embedding 工厂模块

提供 Ollama Embedding 模型的创建和配置接口。
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple, Dict, Any

from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.core import Settings as LlamaSettings

from rag._infra import get_ollama_request_queue, RetryableError, CircuitBreakerOpenError
from rag.config import get_settings, get_model_registry
from rag.embedding_service import get_default_embedding_from_registry
from kb_core.database import init_vendor_db

logger = logging.getLogger(__name__)


def _record_embedding_call(
    vendor_id: str, model_id: str, token_count: int, error: bool
):
    """记录 Embedding 调用统计"""
    try:
        from rag.callbacks import record_model_call

        record_model_call(
            vendor_id=vendor_id,
            model_type="embedding",
            model_id=model_id,
            prompt_tokens=token_count,
            completion_tokens=0,
            error=error,
        )
    except Exception as e:
        logger.warning(f"Failed to record embedding call for {vendor_id}/{model_id}: {e}")


def _resolve_embedding_base_url(
    model: Optional[str],
    model_id: Optional[str],
    base_url: Optional[str],
) -> Tuple[str, str, str]:
    """解析 embedding 模型的 base_url 和 model_id。

    Returns:
        (resolved_model, resolved_base_url, resolved_model_id)
    """
    if model is None:
        model_name, resolved_url = get_default_embedding_from_registry()
        base_url = base_url or resolved_url
        model = model_name
        if model_id is None:
            registry = get_model_registry()
            for mid, minfo in registry._models.items():
                if minfo.get("name") == model_name and minfo.get("type") == "embedding":
                    model_id = mid
                    break
    elif model_id is None:
        model_id = model

    if not base_url:
        if model_id:
            registry = get_model_registry()
            model_info = registry.get_model(model_id)
            if model_info:
                vendor_db = init_vendor_db()
                vendor = vendor_db.get(model_info.get("vendor_id") or "")
                if vendor:
                    base_url = vendor.get("api_base")
        if not base_url:
            raise ValueError(f"Cannot determine base_url for model {model_id}. Please configure vendor or pass base_url explicitly.")

    return model, base_url, model_id


class OllamaEmbedder(OllamaEmbedding):
    """Ollama Embedding 封装类，继承自 OllamaEmbedding，支持 503 重试和请求队列"""

    def __init__(
        self,
        model_name: str,
        base_url: str,
        model_id: Optional[str] = None,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
        client_kwargs: Optional[Dict[str, Any]] = None,
    ):
        if client_kwargs is None:
            client_kwargs = {"proxy": None}
        super().__init__(model_name=model_name, base_url=base_url, client_kwargs=client_kwargs)
        self._base_url = base_url
        self._model_id = model_id
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._backoff_factor = backoff_factor
        self._queue = get_ollama_request_queue()

    def _get_full_model_id(self) -> str:
        if self._model_id:
            return self._model_id
        return f"ollama/{self.model_name}"

    def _call_with_queue(self, method, *args, **kwargs):
        try:
            return self._queue.call_with_queue(self._base_url, method, *args, **kwargs)
        except (CircuitBreakerOpenError, TimeoutError):
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "503" in error_str or "service unavailable" in error_str:
                raise RetryableError(str(e)) from e
            raise

    def _sync_call_with_retry(self, method, *args, **kwargs):
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                return self._call_with_queue(method, *args, **kwargs)
            except RetryableError as e:
                last_error = e
                import time
                time.sleep(delay)
                delay *= self._backoff_factor
            except (CircuitBreakerOpenError, TimeoutError):
                raise
            except Exception as e:
                error_str = str(e).lower()
                if "503" in error_str or "service unavailable" in error_str:
                    last_error = e
                    import time
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    async def _async_call_with_retry(self, method, *args, **kwargs):
        import asyncio
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                coro = method(*args, **kwargs)
                return await asyncio.wait_for(coro, timeout=300.0)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Embedding[{self._base_url}] request timed out after 300s"
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "503" in error_str or "service unavailable" in error_str:
                    await asyncio.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    def _get_vendor_id(self) -> str:
        return "ollama"

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def get_text_embedding(self, text: str) -> list[float]:
        try:
            result = self._sync_call_with_retry(super().get_text_embedding, text)
            _record_embedding_call(
                self._get_vendor_id(),
                self._get_full_model_id(),
                self._estimate_tokens(text),
                False,
            )
            return result
        except Exception as e:
            _record_embedding_call(self._get_vendor_id(), self._get_full_model_id(), 0, True)
            raise

    async def aget_text_embedding(self, text: str) -> list[float]:
        try:
            result = await self._async_call_with_retry(
                super().aget_text_embedding, text
            )
            _record_embedding_call(
                self._get_vendor_id(),
                self._get_full_model_id(),
                self._estimate_tokens(text),
                False,
            )
            return result
        except Exception as e:
            _record_embedding_call(self._get_vendor_id(), self._get_full_model_id(), 0, True)
            raise

    def get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            try:
                result = self._sync_call_with_retry(super().get_text_embedding, text)
                _record_embedding_call(
                    self._get_vendor_id(),
                    self._get_full_model_id(),
                    self._estimate_tokens(text),
                    False,
                )
                results.append(result)
            except Exception as e:
                _record_embedding_call(self._get_vendor_id(), self._get_full_model_id(), 0, True)
                raise
        return results

    async def aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            try:
                result = await self._async_call_with_retry(
                    super().aget_text_embedding, text
                )
                _record_embedding_call(
                    self._get_vendor_id(),
                    self._get_full_model_id(),
                    self._estimate_tokens(text),
                    False,
                )
                results.append(result)
            except Exception as e:
                _record_embedding_call(self._get_vendor_id(), self.model_name, 0, True)
                raise
        return results


def create_ollama_embedding(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    model_id: Optional[str] = None,
) -> OllamaEmbedder:
    """创建 Ollama Embedding 模型"""
    settings = get_settings()
    model, base_url, model_id = _resolve_embedding_base_url(model, model_id, base_url)
    return OllamaEmbedder(
        model_name=model,
        base_url=base_url,
        model_id=model_id,
        max_retries=settings.max_retries,
        initial_delay=settings.retry_delay,
        backoff_factor=1.5,
    )


def configure_global_embed_model(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    chunk_size: int = 512,
    embed_batch_size: int = 10,
    model_id: Optional[str] = None,
) -> OllamaEmbedder:
    """配置 LlamaIndex 全局 Embedding 模型"""
    settings = get_settings()
    model, base_url, model_id = _resolve_embedding_base_url(model, model_id, base_url)
    embed_model = OllamaEmbedder(
        model_name=model,
        base_url=base_url,
        model_id=model_id,
        max_retries=settings.max_retries,
        initial_delay=settings.retry_delay,
        backoff_factor=1.5,
        client_kwargs={"proxy": None},
    )
    LlamaSettings.embed_model = embed_model
    LlamaSettings.chunk_size = chunk_size
    LlamaSettings.embed_batch_size = embed_batch_size
    return embed_model


def configure_embed_model_by_model_id(model_id: str) -> OllamaEmbedding:
    """根据模型ID配置全局 Embedding 模型"""
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

    settings = get_settings()
    is_ollama = vendor_id.startswith("ollama") or model_id.startswith("ollama")

    if is_ollama:
        embed_model = OllamaEmbedder(
            model_name=model_info["name"],
            base_url=base_url,
            model_id=model_id,
            max_retries=settings.max_retries,
            initial_delay=settings.retry_delay,
            backoff_factor=1.5,
            client_kwargs={"proxy": None},
        )
    else:
        embed_model = OllamaEmbedding(
            model_name=model_info["name"],
            base_url=base_url,
            client_kwargs={"proxy": None},
        )

    LlamaSettings.embed_model = embed_model
    return embed_model


def create_parallel_ollama_embedding():
    """创建支持多端点调度的 Embedding 模型适配器"""
    from kb_processing.parallel_embedding import create_parallel_embedding_model
    return create_parallel_embedding_model()


def create_siliconflow_embedding(
    model: str,
    dimensions: Optional[int] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    internal_model_id: Optional[str] = None,
) -> "SiliconFlowEmbedding":
    from rag.embedding_service import SiliconFlowEmbedding

    return SiliconFlowEmbedding(
        model=model,
        dimensions=dimensions,
        api_key=api_key,
        base_url=base_url,
        internal_model_id=internal_model_id,
    )


__all__ = [
    "OllamaEmbedder",
    "create_ollama_embedding",
    "configure_global_embed_model",
    "configure_embed_model_by_model_id",
    "create_parallel_ollama_embedding",
    "create_siliconflow_embedding",
    "_record_embedding_call",
]

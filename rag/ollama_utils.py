"""
Ollama 工具模块

职责：
- Embedding 相关：委托至 rag.embedding_factory
- LLM 相关：RetryableOllama, RetryableSiliconFlowLLM, OllamaWithSiliconFlowFallback
- 基础设施：委托至 rag._infra
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from llama_index.llms.ollama import Ollama
from llama_index.core.constants import DEFAULT_NUM_OUTPUTS, DEFAULT_CONTEXT_WINDOW

from rag._infra import (
    CircuitBreakerOpenError,
    RetryableError,
    get_circuit_breaker,
    get_ollama_request_queue,
    OllamaRequestQueue,
    _extract_llm_tokens,
    DEFAULT_TIMEOUT,
)
from rag.embedding_factory import (
    OllamaEmbedder,
    create_ollama_embedding,
    configure_global_embed_model,
    create_parallel_ollama_embedding,
    configure_embed_model_by_model_id,
    BatchEmbeddingHelper,
    create_siliconflow_embedding,
    _record_embedding_call,
)

logger = logging.getLogger(__name__)


def _record_llm_call(
    vendor_id: str,
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    error: bool,
):
    """记录 LLM 调用统计"""
    try:
        from rag.callbacks import record_model_call

        record_model_call(
            vendor_id=vendor_id,
            model_type="llm",
            model_id=model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error=error,
        )
    except Exception:
        pass


def _record_reranker_call(vendor_id: str, model_id: str, token_count: int, error: bool):
    """记录 Reranker 调用统计"""
    try:
        from rag.callbacks import record_model_call

        record_model_call(
            vendor_id=vendor_id,
            model_type="reranker",
            model_id=model_id,
            prompt_tokens=token_count,
            completion_tokens=0,
            error=error,
        )
    except Exception:
        pass


class RetryableOllama(Ollama):
    """Ollama LLM 子类，支持 503 错误重试、请求超时和熔断器"""

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
        self._queue = get_ollama_request_queue()

    def _call_with_queue(self, method: Callable[..., Any], *args, **kwargs) -> Any:
        try:
            return self._queue.call_with_queue(self.base_url, method, *args, **kwargs)
        except CircuitBreakerOpenError:
            raise
        except TimeoutError:
            raise
        except Exception as e:
            error_type_name = type(e).__name__
            retryable_types = {
                "ConnectionError",
                "TimeoutError",
                "RemoteDisconnected",
                "ConnectionResetError",
                "BrokenPipeError",
            }
            if error_type_name in retryable_types:
                raise RetryableError(str(e)) from e
            error_str = str(e).lower()
            if any(
                kw in error_str
                for kw in [
                    "503",
                    "service unavailable",
                    "remote end closed",
                    "connection reset",
                    "broken pipe",
                ]
            ):
                raise RetryableError(str(e)) from e
            raise

    def _sync_call_with_retry(self, method_name: str, *args, **kwargs) -> Any:
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                method = getattr(super(), method_name)
                return method(*args, **kwargs)
            except Exception as e:
                error_type_name = type(e).__name__
                retryable_types = {
                    "ConnectionError",
                    "TimeoutError",
                    "RemoteDisconnected",
                    "ConnectionResetError",
                    "BrokenPipeError",
                }
                isRetryable = (
                    error_type_name in retryable_types
                    or "503" in str(e).lower()
                    or "service unavailable" in str(e).lower()
                    or "remote end closed" in str(e).lower()
                )
                if isRetryable:
                    last_error = e
                    logger.warning(
                        f"Ollama[{self.base_url}] 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    def _get_vendor_id(self) -> str:
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            return "ollama"
        return "ollama"

    def complete(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._sync_call_with_retry("complete", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self.model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    def completion(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._sync_call_with_retry("completion", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self.model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    def predict(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._sync_call_with_retry("predict", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self.model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    def stream_complete(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._sync_call_with_retry("stream_complete", prompt, **kwargs)
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    def chat(self, messages: Any, **kwargs) -> Any:
        try:
            response = self._sync_call_with_retry("chat", messages, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self.model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    def stream_chat(self, messages: Any, **kwargs) -> Any:
        try:
            response = self._sync_call_with_retry("stream_chat", messages, **kwargs)
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    async def _async_call_with_retry(self, method_name: str, *args, **kwargs) -> Any:
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                method = getattr(super(), method_name)
                coro = method(*args, **kwargs)
                return await asyncio.wait_for(coro, timeout=DEFAULT_TIMEOUT)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Ollama[{self.base_url}] request timed out after {DEFAULT_TIMEOUT}s"
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "503" in error_str or "service unavailable" in error_str:
                    logger.warning(
                        f"Ollama[{self.base_url}] async 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    async def acomplete(self, prompt: str, **kwargs) -> Any:
        try:
            response = await self._async_call_with_retry("acomplete", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self.model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    async def achat(self, messages: Any, **kwargs) -> Any:
        try:
            response = await self._async_call_with_retry("achat", messages, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self.model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    async def astream_complete(self, prompt: str, **kwargs) -> Any:
        try:
            response = await self._async_call_with_retry(
                "astream_complete", prompt, **kwargs
            )
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    async def astream_chat(self, messages: Any, **kwargs) -> Any:
        try:
            response = await self._async_call_with_retry(
                "astream_chat", messages, **kwargs
            )
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self.model, 0, 0, True)
            raise

    def get_context_window(self) -> int:
        """获取上下文窗口大小，带重试机制"""
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
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
                    else int(DEFAULT_CONTEXT_WINDOW)
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
        from llama_index.core.base.llms.types import LLMMetadata

        return LLMMetadata(
            context_window=self.get_context_window(),
            num_output=DEFAULT_NUM_OUTPUTS,
            model_name=self.model,
            is_chat_model=True,
            is_function_calling_model=self.is_function_calling_model,
        )

def _get_fallback_model_from_registry() -> tuple[str, str, str, str]:
    """
    从模型数据库获取 SiliconFlow fallback LLM 配置。
    
    Returns:
        tuple: (model_id, model_name, api_key, api_base)
        
    Raises:
        RuntimeError: 当没有可用的 SiliconFlow LLM 时抛出
    """
    from rag.config import get_model_registry
    from kb_core.database import init_vendor_db

    registry = get_model_registry()
    
    # 优先获取默认 LLM，如果它是 SiliconFlow 供应商则直接使用
    default_model = registry.get_default("llm")
    if default_model:
        vendor_id = default_model.get("vendor_id", "")
        if vendor_id == "siliconflow":
            vendor_db = init_vendor_db()
            vendor_info = vendor_db.get(vendor_id)
            if vendor_info and vendor_info.get("api_key"):
                return (
                    default_model["id"],
                    default_model["name"],
                    vendor_info["api_key"],
                    vendor_info.get("api_base", "https://api.siliconflow.cn/v1"),
                )

    # 否则查找任何可用的 SiliconFlow LLM
    siliconflow_models = [
        m for m in registry.get_by_type("llm")
        if m.get("vendor_id") == "siliconflow" and m.get("is_active", True)
    ]
    
    if siliconflow_models:
        model = siliconflow_models[0]
        vendor_db = init_vendor_db()
        vendor_info = vendor_db.get("siliconflow")
        if vendor_info and vendor_info.get("api_key"):
            return (
                model["id"],
                model["name"],
                vendor_info["api_key"],
                vendor_info.get("api_base", "https://api.siliconflow.cn/v1"),
            )

    raise RuntimeError(
        "No SiliconFlow LLM available for fallback. "
        "Please add a SiliconFlow LLM model via CLI: "
        "uv run llamaindex-study model add siliconflow/DeepSeek-V3.2 --vendor-id=siliconflow --type=llm"
    )


def _get_fallback_ollama_model_from_registry() -> tuple[str, str]:
    """
    从模型数据库获取 Ollama fallback LLM 配置。

    Returns:
        tuple: (model_name, base_url)

    Raises:
        RuntimeError: 当没有可用的 Ollama LLM 时抛出
    """
    from rag.config import get_model_registry
    from kb_core.database import init_vendor_db

    registry = get_model_registry()

    default_model = registry.get_default("llm")
    if default_model:
        vendor_id = default_model.get("vendor_id", "")
        if vendor_id.startswith("ollama"):
            vendor_db = init_vendor_db()
            vendor_info = vendor_db.get(vendor_id)
            if vendor_info and vendor_info.get("api_base"):
                return (
                    default_model["name"],
                    vendor_info["api_base"],
                )

    ollama_models = [
        m for m in registry.get_by_type("llm")
        if m.get("vendor_id", "").startswith("ollama") and m.get("is_active", True)
    ]

    if ollama_models:
        model = ollama_models[0]
        vendor_db = init_vendor_db()
        vendor_info = vendor_db.get(model.get("vendor_id", ""))
        if vendor_info and vendor_info.get("api_base"):
            return (
                model["name"],
                vendor_info["api_base"],
            )

    raise RuntimeError(
        "No Ollama LLM available for fallback. "
        "Please add an Ollama LLM model via CLI: "
        "uv run llamaindex-study model add ollama/llama3 --vendor-id=ollama --type=llm"
    )


class OllamaWithSiliconFlowFallback:
    """Ollama LLM 封装类，支持降级到 SiliconFlow"""

    def __init__(self, primary_llm: Any):
        self._primary_llm = primary_llm
        self._fallback_llm: Optional[Any] = None

    def _get_fallback_llm(self) -> Any:
        if self._fallback_llm is None:
            from llama_index.llms.openai import OpenAI
            from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS

            model_id, model_name, api_key, api_base = _get_fallback_model_from_registry()

            if model_name not in ALL_AVAILABLE_MODELS:
                ALL_AVAILABLE_MODELS[model_name] = 128000
            try:
                import tiktoken
                tiktoken.encoding_for_model(model_name)
            except (KeyError, ImportError):
                import tiktoken.model as tm
                tm.MODEL_TO_ENCODING[model_name] = "cl100k_base"

            self._fallback_llm = OpenAI(
                model=model_name,
                api_key=api_key,
                api_base=api_base,
            )
        return self._fallback_llm

    def _call_with_fallback(self, method_name: str, *args, **kwargs) -> Any:
        try:
            method = getattr(self._primary_llm, method_name)
            return method(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Ollama LLM 调用失败，降级到 SiliconFlow: {e}")
            fallback_llm = self._get_fallback_llm()
            method = getattr(fallback_llm, method_name)
            return method(*args, **kwargs)

    def complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_fallback("complete", prompt, **kwargs)

    def completion(self, prompt: str, **kwargs) -> Any:
        return self._call_with_fallback("completion", prompt, **kwargs)

    def chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_fallback("chat", messages, **kwargs)

    def stream_complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_fallback("stream_complete", prompt, **kwargs)

    def stream_chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_fallback("stream_chat", messages, **kwargs)

    async def acomplete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_fallback("acomplete", prompt, **kwargs)

    async def achat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_fallback("achat", messages, **kwargs)

    async def astream_complete(self, prompt: str, **kwargs) -> Any:
        return self._call_with_fallback("astream_complete", prompt, **kwargs)

    async def astream_chat(self, messages: Any, **kwargs) -> Any:
        return self._call_with_fallback("astream_chat", messages, **kwargs)

    def predict(self, prompt: Any, **kwargs: Any) -> Any:
        return self._call_with_fallback("predict", prompt, **kwargs)

    def apredict(self, prompt: Any, **kwargs: Any) -> Any:
        return self._call_with_fallback("apredict", prompt, **kwargs)

    @property
    def model(self) -> str:
        return self._primary_llm.model

    @property
    def base_url(self) -> str:
        return self._primary_llm.base_url

    @property
    def metadata(self) -> Any:
        return self._primary_llm.metadata

    @property
    def system_prompt(self) -> Any:
        return getattr(self._primary_llm, "system_prompt", None)

    @system_prompt.setter
    def system_prompt(self, value: Any) -> None:
        setattr(self._primary_llm, "system_prompt", value)

    @property
    def callback_manager(self) -> Any:
        return getattr(self._primary_llm, "callback_manager", None)

    @callback_manager.setter
    def callback_manager(self, value: Any) -> None:
        setattr(self._primary_llm, "callback_manager", value)

    @property
    def is_chat_model(self) -> bool:
        return True

    @property
    def is_function_calling_model(self) -> bool:
        return False


class RetryableSiliconFlowLLM:
    """SiliconFlow LLM 封装类，支持 503 重试和降级到 Ollama"""

    def __init__(
        self,
        model: str,
        api_key: str,
        api_base: str,
        max_retries: int = 3,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
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
        self._fallback_llm: Optional[Any] = None
        self._use_fallback = False

    def _get_vendor_id(self) -> str:
        if self._use_fallback:
            return "ollama"
        return "siliconflow"

    def _is_retryable_error(self, error: Exception) -> bool:
        error_type_name = type(error).__name__
        retryable_type_names = {
            "ConnectionError",
            "TimeoutError",
            "HTTPError",
            "MaxRetryError",
            "RemoteDisconnected",
            "ConnectionResetError",
            "BrokenPipeError",
        }
        if error_type_name in retryable_type_names:
            return True
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
                "remote end closed",
                "connection reset",
                "broken pipe",
            ]
        )

    def _is_service_unavailable_error(self, error: Exception) -> bool:
        error_str = str(error).lower()
        return "503" in error_str or "service unavailable" in error_str

    def _get_fallback_llm(self) -> Any:
        if self._fallback_llm is None:
            model_name, base_url = _get_fallback_ollama_model_from_registry()
            self._fallback_llm = RetryableOllama(
                model=model_name,
                base_url=base_url,
                max_retries=5,
                initial_delay=2.0,
                backoff_factor=1.5,
            )
        return self._fallback_llm

    def _call_with_retry(self, method_name: str, *args, **kwargs) -> Any:
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay
        service_unavailable = False

        for attempt in range(self._max_retries):
            try:
                method = getattr(self._primary_llm, method_name)
                return method(*args, **kwargs)
            except Exception as e:
                last_error = e
                if self._is_service_unavailable_error(e):
                    service_unavailable = True
                    logger.warning(
                        f"SiliconFlow 服务不可用 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                elif self._is_retryable_error(e):
                    logger.warning(
                        f"SiliconFlow LLM 调用失败 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    logger.warning(f"SiliconFlow LLM 错误，降级到 Ollama: {e}")
                    break

        logger.info("SiliconFlow LLM 重试耗尽，降级到 Ollama")
        self._use_fallback = True
        fallback_llm = self._get_fallback_llm()
        method = getattr(fallback_llm, method_name)
        return method(*args, **kwargs)

    def complete(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._call_with_retry("complete", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self._model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    def completion(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._call_with_retry("completion", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self._model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    def predict(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._call_with_retry("predict", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self._model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    def stream_complete(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._call_with_retry("stream_complete", prompt, **kwargs)
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    def chat(self, messages: Any, **kwargs) -> Any:
        try:
            response = self._call_with_retry("chat", messages, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self._model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    def stream_chat(self, messages: Any, **kwargs) -> Any:
        try:
            response = self._call_with_retry("stream_chat", messages, **kwargs)
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    async def acomplete(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._call_with_retry("acomplete", prompt, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self._model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    async def achat(self, messages: Any, **kwargs) -> Any:
        try:
            response = self._call_with_retry("achat", messages, **kwargs)
            prompt_tokens, completion_tokens = _extract_llm_tokens(response)
            _record_llm_call(
                self._get_vendor_id(),
                self._model,
                prompt_tokens,
                completion_tokens,
                False,
            )
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    async def astream_complete(self, prompt: str, **kwargs) -> Any:
        try:
            response = self._call_with_retry("astream_complete", prompt, **kwargs)
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    async def astream_chat(self, messages: Any, **kwargs) -> Any:
        try:
            response = self._call_with_retry("astream_chat", messages, **kwargs)
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, False)
            return response
        except Exception as e:
            _record_llm_call(self._get_vendor_id(), self._model, 0, 0, True)
            raise

    @property
    def metadata(self) -> Any:
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

    @property
    def system_prompt(self) -> Any:
        return getattr(self._primary_llm, "system_prompt", None)

    @system_prompt.setter
    def system_prompt(self, value: Any) -> None:
        setattr(self._primary_llm, "system_prompt", value)

    @property
    def callback_manager(self) -> Any:
        return getattr(self._primary_llm, "callback_manager", None)

    @callback_manager.setter
    def callback_manager(self, value: Any) -> None:
        setattr(self._primary_llm, "callback_manager", value)

    def __repr__(self) -> str:
        if self._use_fallback:
            return "RetryableSiliconFlowLLM(fallback=Ollama)"
        return f"RetryableSiliconFlowLLM(primary={self._model})"


def get_default_llm_from_registry() -> tuple[str, str, str, str]:
    """Get default LLM from registry: (model_id, model_name, api_key, base_url)."""
    from rag.config import get_model_registry
    from kb_core.database import init_vendor_db

    registry = get_model_registry()
    model = registry.get_default("llm")
    if not model:
        raise RuntimeError(
            "No default LLM found in registry. Please add an LLM model via CLI or API."
        )

    vendor_db = init_vendor_db()
    vendor_info = vendor_db.get(model["vendor_id"])
    if not vendor_info:
        raise RuntimeError(f"Vendor '{model['vendor_id']}' not found in database.")

    api_key = vendor_info.get("api_key", "")
    base_url = vendor_info.get("api_base", "")

    return model["id"], model["name"], api_key, base_url


def create_llm(
    model_id: Optional[str] = None,
    mode: Optional[str] = None,
    model: Optional[str] = None,
) -> Any:
    """根据配置创建 LLM 实例"""
    if model_id:
        from rag.config import get_model_registry
        from kb_core.database import init_vendor_db

        registry = get_model_registry()
        model_info = registry.get_model(model_id)
        if not model_info:
            raise ValueError(f"模型不存在: {model_id}")

        vendor_id = model_info.get("vendor_id", "")
        vendor_db = init_vendor_db()
        vendor_info = vendor_db.get(vendor_id) if vendor_id else None

        if vendor_id.startswith("ollama"):
            if not vendor_info or not vendor_info.get("api_base"):
                raise ValueError(f"Ollama vendor {vendor_id} not configured. Run: uv run llamaindex-study vendor add --help")
            base_url = vendor_info["api_base"]
            primary_llm = RetryableOllama(
                model=model_info["name"],
                base_url=base_url,
                max_retries=5,
                initial_delay=2.0,
                backoff_factor=1.5,
            )
            return OllamaWithSiliconFlowFallback(primary_llm)
        else:
            if not vendor_info:
                raise ValueError(f"Vendor {vendor_id} not configured. Run: uv run llamaindex-study vendor add --help")
            api_key = vendor_info.get("api_key")
            api_base = vendor_info.get("api_base")
            if not api_key:
                raise ValueError(f"API key not configured for vendor {vendor_id}. Run: uv run llamaindex-study vendor update {vendor_id} --api-key=YOUR_KEY")
            if not api_base:
                raise ValueError(f"API base not configured for vendor {vendor_id}.")

            return RetryableSiliconFlowLLM(
                model=model_info["name"],
                api_key=api_key,
                api_base=api_base,
                max_retries=3,
                initial_delay=2.0,
                backoff_factor=1.5,
            )

    model_id, model_name, api_key, base_url = get_default_llm_from_registry()
    return create_llm(model_id=model_id)


def configure_llm_by_model_id(model_id: str) -> Any:
    """根据模型ID配置 LLM"""
    return create_llm(model_id=model_id)


__all__ = [
    "create_ollama_embedding",
    "create_parallel_ollama_embedding",
    "create_siliconflow_embedding",
    "configure_global_embed_model",
    "configure_embed_model_by_model_id",
    "BatchEmbeddingHelper",
    "OllamaEmbedder",
    "RetryableOllama",
    "RetryableSiliconFlowLLM",
    "OllamaWithSiliconFlowFallback",
    "create_llm",
    "configure_llm_by_model_id",
    "get_default_llm_from_registry",
]

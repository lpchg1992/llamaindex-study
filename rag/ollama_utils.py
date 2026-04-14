"""
Ollama 工具模块

提供统一的 Ollama 配置接口，消除重复的 embedding 模型初始化代码。
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable, Dict, List, Optional

from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.llms.ollama import Ollama
from llama_index.core.constants import DEFAULT_NUM_OUTPUTS, DEFAULT_CONTEXT_WINDOW

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


def _extract_llm_tokens(response: Any) -> tuple[int, int]:
    """从 LLM 响应中提取 token 数量，返回 (prompt_tokens, completion_tokens)"""
    prompt_tokens = 0
    completion_tokens = 0

    if response is None:
        return prompt_tokens, completion_tokens

    # 尝试从原始响应中提取
    raw = getattr(response, "raw", None)
    if raw is None:
        raw = response

    # 检查 openai 格式的 usage 字段
    if hasattr(raw, "usage") and raw.usage:
        usage = raw.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    elif isinstance(raw, dict):
        usage = raw.get("usage") or {}
        if usage:
            prompt_tokens = usage.get("prompt_tokens", 0) or 0
            completion_tokens = usage.get("completion_tokens", 0) or 0

    return prompt_tokens, completion_tokens


# 默认配置
DEFAULT_TIMEOUT = 300.0
DEFAULT_MAX_CONCURRENT = 2
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60.0


class CircuitBreaker:
    """熔断器，防止向故障服务持续发送请求

    当 URL 连续失败次数超过阈值后，熔断打开。
    熔断打开期间对该 URL 的请求会立即失败。
    等待恢复超时后，熔断半开，允许一个请求试探。
    """

    def __init__(
        self,
        failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: float = CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._circuit_state: Dict[str, str] = {}  # "closed", "open", "half-open"
        self._lock = threading.Lock()

    def _get_state(self, url: str) -> str:
        state = self._circuit_state.get(url, "closed")
        if state == "open":
            time_since_failure = time.time() - self._last_failure_time.get(url, 0)
            if time_since_failure >= self._recovery_timeout:
                self._circuit_state[url] = "half-open"
                return "half-open"
        return state

    def is_available(self, url: str) -> bool:
        with self._lock:
            state = self._get_state(url)
            return state != "open"

    def record_success(self, url: str):
        with self._lock:
            self._failure_count[url] = 0
            self._circuit_state[url] = "closed"

    def record_failure(self, url: str):
        with self._lock:
            self._failure_count[url] = self._failure_count.get(url, 0) + 1
            self._last_failure_time[url] = time.time()
            if self._failure_count[url] >= self._failure_threshold:
                self._circuit_state[url] = "open"
                logger.warning(
                    f"Circuit breaker opened for {url} after {self._failure_count[url]} failures"
                )

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                url: {
                    "failure_count": self._failure_count.get(url, 0),
                    "state": self._circuit_state.get(url, "closed"),
                }
                for url in set(
                    list(self._failure_count.keys()) + list(self._circuit_state.keys())
                )
            }


_circuit_breaker: Optional[CircuitBreaker] = None


def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


class _PerURLQueue:
    """单个 Ollama URL 的请求队列，带超时和熔断器支持"""

    def __init__(
        self,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._timeout = timeout
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._active_requests = 0
        self._total_requests = 0
        self._total_wait_time = 0.0
        self._timeouts = 0
        self._request_lock = threading.Lock()

    def acquire(self) -> float:
        start_time = time.time()
        self._semaphore.acquire()
        wait_time = time.time() - start_time
        with self._request_lock:
            self._active_requests += 1
            self._total_requests += 1
            self._total_wait_time += wait_time
        return wait_time

    def release(self):
        with self._request_lock:
            self._active_requests -= 1
        self._semaphore.release()

    def call_with_queue(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        self.acquire()
        try:
            future = self._executor.submit(func, *args, **kwargs)
            return future.result(timeout=self._timeout)
        except FutureTimeoutError:
            with self._request_lock:
                self._timeouts += 1
            raise TimeoutError(f"Ollama request timed out after {self._timeout}s")
        finally:
            self.release()

    @property
    def stats(self) -> dict:
        with self._request_lock:
            avg_wait = (
                self._total_wait_time / self._total_requests
                if self._total_requests > 0
                else 0
            )
            return {
                "active_requests": self._active_requests,
                "total_requests": self._total_requests,
                "average_wait_time": avg_wait,
                "timeouts": self._timeouts,
            }


class OllamaRequestQueue:
    """Ollama LLM 请求队列，按 URL 组织确保对不同 Ollama 服务的串行访问

    由于 Ollama 默认 OLLAMA_NUM_PARALLEL=1，高并发请求会导致 503 错误。
    此队列通过信号量控制，确保同一时间只有一个请求访问同一 Ollama 服务，
    避免因并发竞争导致的 503 错误。
    不同 URL 的 Ollama 实例相互独立。

    带超时保护和熔断器支持：
    - 单请求超时：120秒
    - 每个 URL 最大并发：2
    - 熔断器阈值：5次连续失败后打开
    """

    _instance: Optional["OllamaRequestQueue"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "OllamaRequestQueue":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._queues: Dict[str, _PerURLQueue] = {}
        self._queues_lock = threading.Lock()
        self._circuit_breaker = get_circuit_breaker()

    def _get_queue(self, url: str) -> _PerURLQueue:
        with self._queues_lock:
            if url not in self._queues:
                self._queues[url] = _PerURLQueue(
                    max_concurrent=DEFAULT_MAX_CONCURRENT,
                    timeout=DEFAULT_TIMEOUT,
                )
            return self._queues[url]

    def call_with_queue(
        self, url: str, func: Callable[..., Any], *args, **kwargs
    ) -> Any:
        if not self._circuit_breaker.is_available(url):
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for {url}. Service unavailable."
            )

        queue = self._get_queue(url)
        wait_time = queue.acquire()
        logger.debug(
            f"OllamaRequestQueue[{url}]: 请求获得访问权限 (等待 {wait_time:.2f}s)"
        )
        try:
            result = queue.call_with_queue(func, *args, **kwargs)
            self._circuit_breaker.record_success(url)
            return result
        except TimeoutError:
            self._circuit_breaker.record_failure(url)
            raise
        except Exception as e:
            error_str = str(e).lower()
            if "503" in error_str or "service unavailable" in error_str:
                self._circuit_breaker.record_failure(url)
            raise
        finally:
            queue.release()
            logger.debug(f"OllamaRequestQueue[{url}]: 请求释放访问权限")

    def get_stats(self, url: str) -> dict:
        queue = self._get_queue(url)
        return {
            "queue": queue.stats,
            "circuit_breaker": self._circuit_breaker.stats.get(url, {}),
        }

    def get_all_stats(self) -> dict:
        with self._queues_lock:
            return {
                url: {
                    "queue": q.stats,
                    "circuit_breaker": self._circuit_breaker.stats.get(url, {}),
                }
                for url, q in self._queues.items()
            }


class CircuitBreakerOpenError(Exception):
    pass


class RetryableError(Exception):
    pass


_ollama_request_queue: Optional[OllamaRequestQueue] = None


def get_ollama_request_queue() -> OllamaRequestQueue:
    global _ollama_request_queue
    if _ollama_request_queue is None:
        _ollama_request_queue = OllamaRequestQueue()
    return _ollama_request_queue


class OllamaEmbedder(OllamaEmbedding):
    """Ollama Embedding 封装类，继承自 OllamaEmbedding，支持 503 重试和请求队列

    特性：
    - 503 重试：模型加载时自动等待和重试
    - 请求超时：单请求最多等待 120 秒
    - 熔断器：连续失败后自动暂停向故障服务发请求
    """

    def __init__(
        self,
        model_name: str,
        base_url: str,
        max_retries: int = 5,
        initial_delay: float = 2.0,
        backoff_factor: float = 1.5,
    ):
        super().__init__(model_name=model_name, base_url=base_url)
        self._base_url = base_url
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._backoff_factor = backoff_factor
        self._queue = get_ollama_request_queue()

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
                logger.warning(
                    f"Embedding[{self._base_url}] 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                    f"等待 {delay:.1f}s: {e}"
                )
                time.sleep(delay)
                delay *= self._backoff_factor
            except (CircuitBreakerOpenError, TimeoutError):
                raise
            except Exception as e:
                error_str = str(e).lower()
                if "503" in error_str or "service unavailable" in error_str:
                    last_error = e
                    logger.warning(
                        f"Embedding[{self._base_url}] 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    time.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    async def _async_call_with_retry(self, method, *args, **kwargs):
        last_error: BaseException = Exception("Unknown error")
        delay = self._initial_delay

        for attempt in range(self._max_retries):
            try:
                coro = method(*args, **kwargs)
                return await asyncio.wait_for(coro, timeout=DEFAULT_TIMEOUT)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Embedding[{self._base_url}] request timed out after {DEFAULT_TIMEOUT}s"
                )
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if "503" in error_str or "service unavailable" in error_str:
                    logger.warning(
                        f"Embedding[{self._base_url}] async 模型加载中 (尝试 {attempt + 1}/{self._max_retries})，"
                        f"等待 {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    delay *= self._backoff_factor
                else:
                    raise

        raise last_error

    def _get_vendor_id(self) -> str:
        if "localhost" in self._base_url or "127.0.0.1" in self._base_url:
            return "ollama"
        return "ollama"

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def get_text_embedding(self, text: str) -> List[float]:
        try:
            result = self._sync_call_with_retry(super().get_text_embedding, text)
            _record_embedding_call(
                self._get_vendor_id(),
                self.model_name,
                self._estimate_tokens(text),
                False,
            )
            return result
        except Exception as e:
            _record_embedding_call(self._get_vendor_id(), self.model_name, 0, True)
            raise

    async def aget_text_embedding(self, text: str) -> List[float]:
        try:
            result = await self._async_call_with_retry(
                super().aget_text_embedding, text
            )
            _record_embedding_call(
                self._get_vendor_id(),
                self.model_name,
                self._estimate_tokens(text),
                False,
            )
            return result
        except Exception as e:
            _record_embedding_call(self._get_vendor_id(), self.model_name, 0, True)
            raise

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        results = []
        for text in texts:
            try:
                result = self._sync_call_with_retry(super().get_text_embedding, text)
                _record_embedding_call(
                    self._get_vendor_id(),
                    self.model_name,
                    self._estimate_tokens(text),
                    False,
                )
                results.append(result)
            except Exception as e:
                _record_embedding_call(self._get_vendor_id(), self.model_name, 0, True)
                raise
        return results

    async def aget_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        results = []
        for text in texts:
            try:
                result = await self._async_call_with_retry(
                    super().aget_text_embedding, text
                )
                _record_embedding_call(
                    self._get_vendor_id(),
                    self.model_name,
                    self._estimate_tokens(text),
                    False,
                )
                results.append(result)
            except Exception as e:
                _record_embedding_call(self._get_vendor_id(), self.model_name, 0, True)
                raise
        return results


from llama_index.core import Settings as LlamaSettings

from rag.config import get_settings


def create_ollama_embedding(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OllamaEmbedder:
    from rag.embedding_service import get_default_embedding_from_registry

    settings = get_settings()
    if model is None:
        model, resolved_url = get_default_embedding_from_registry()
        base_url = base_url or resolved_url
    return OllamaEmbedder(
        model_name=model,
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
    from rag.embedding_service import get_default_embedding_from_registry

    settings = get_settings()
    if model is None:
        model, resolved_url = get_default_embedding_from_registry()
        base_url = base_url or resolved_url
    embed_model = OllamaEmbedder(
        model_name=model,
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
    from kb_processing.parallel_embedding import create_parallel_embedding_model

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
    """Ollama LLM 子类，支持 503 错误重试、请求超时和熔断器

    当 Ollama 模型未加载时，会返回 503 Service Unavailable。
    此子类会自动重试请求，直到模型加载完成。

    特性：
    - 503 重试：模型加载时自动等待和重试
    - 请求超时：单请求最多等待 120 秒
    - 熔断器：连续失败后自动暂停向故障服务发请求
    - 并发控制：每个 URL 最多 2 个并发请求
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
        import time

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
        """从 base_url 推断 vendor_id"""
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
        import time

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
FALLBACK_SILICONFLOW_MODEL = "Pro/deepseek-ai/DeepSeek-V3.2"


class OllamaWithSiliconFlowFallback:
    """Ollama LLM 封装类，支持降级到 SiliconFlow

    当 Ollama 调用失败时，自动降级到 SiliconFlow 云端模型。
    """

    def __init__(self, primary_llm: Any):
        self._primary_llm = primary_llm
        self._fallback_llm: Optional[Any] = None

    def _get_fallback_llm(self) -> Any:
        if self._fallback_llm is None:
            settings = get_settings()
            from llama_index.llms.openai import OpenAI
            from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS

            model_name = FALLBACK_SILICONFLOW_MODEL
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
                api_key=settings.siliconflow_api_key or "",
                api_base=settings.siliconflow_base_url,
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

    def _get_vendor_id(self) -> str:
        if self._use_fallback:
            return "ollama"
        return "siliconflow"

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断是否为可重试的错误"""
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
        """判断是否为服务不可用错误（503），这类错误只需等待重试"""
        error_str = str(error).lower()
        return "503" in error_str or "service unavailable" in error_str

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
        """带重试的调用，失败后降级到 Ollama

        错误处理策略：
        - 503/服务不可用：等待后重试，不切换
        - 其它可重试错误（连接断开等）：等待重试，耗尽后切换到 Ollama
        - 非重试错误：直接切换到 Ollama
        """
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

        logger.info(f"SiliconFlow LLM 重试耗尽，降级到 Ollama ({self._fallback_model})")
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
            return f"RetryableSiliconFlowLLM(fallback={self._fallback_model})"
        return f"RetryableSiliconFlowLLM(primary={self._model})"


def get_default_llm_from_registry() -> tuple[str, str, str, str]:
    """Get default LLM from registry: (model_id, model_name, api_key, base_url).

    Returns:
        (model_id, model_name, api_key, base_url)
    """
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
    """
    根据配置创建 LLM 实例

    Args:
        model_id: 模型ID (如 siliconflow/DeepSeek-V3.2, ollama/lfm2.5-instruct)，优先于其他参数
        mode: LLM 模式，可选 "siliconflow" 或 "ollama"。(已废弃，使用 model_id)
        model: 模型名称 (已废弃，使用 model_id)

    Returns:
        LLM 实例
    """
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
            base_url = (
                vendor_info.get("api_base") if vendor_info else None
            ) or get_settings().ollama_base_url
            primary_llm = RetryableOllama(
                model=model_info["name"],
                base_url=base_url,
                max_retries=5,
                initial_delay=2.0,
                backoff_factor=1.5,
            )
            return OllamaWithSiliconFlowFallback(primary_llm)
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

    model_id, model_name, api_key, base_url = get_default_llm_from_registry()
    return create_llm(model_id=model_id)


def configure_llm_by_model_id(model_id: str) -> Any:
    """根据模型ID创建 LLM 实例

    Args:
        model_id: 模型ID (如 siliconflow/DeepSeek-V3.2, ollama/lfm2.5-instruct)

    Returns:
        LLM 实例
    """
    from rag.config import get_model_registry
    from kb_core.database import init_vendor_db

    registry = get_model_registry()
    model_info = registry.get_model(model_id)
    if not model_info:
        raise ValueError(f"模型不存在: {model_id}")

    llm = create_llm(model_id=model_id)
    return llm


def configure_embed_model_by_model_id(model_id: str) -> OllamaEmbedding:
    """根据模型ID配置全局 Embedding 模型

    Args:
        model_id: 模型ID (如 ollama/bge-m3:latest, ollama_homepc/bge-m3:latest)

    Returns:
        OllamaEmbedding 实例
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
    """配置 LlamaIndex 全局 LLM"""
    llm = create_llm(model_id=None, mode=mode)
    LlamaSettings.llm = llm


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
    from rag.embedding_service import SiliconFlowEmbedding

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

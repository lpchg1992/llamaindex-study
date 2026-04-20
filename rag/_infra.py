"""
基础设施模块

提供 Ollama 请求治理相关的核心组件：
- 熔断器 (CircuitBreaker)
- Per-URL 请求队列 (OllamaRequestQueue)
- 重试和超时控制
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300.0
DEFAULT_MAX_CONCURRENT = 2
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60.0


def extract_llm_tokens(response: Any) -> tuple[int, int]:
    """从 LLM 响应中提取 token 数量，返回 (prompt_tokens, completion_tokens)"""
    prompt_tokens = 0
    completion_tokens = 0

    if response is None:
        return prompt_tokens, completion_tokens

    raw = getattr(response, "raw", None)
    if raw is None:
        raw = response

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


class CircuitBreaker:
    """熔断器，防止向故障服务持续发送请求"""

    def __init__(
        self,
        failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        recovery_timeout: float = CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count: Dict[str, int] = {}
        self._last_failure_time: Dict[str, float] = {}
        self._circuit_state: Dict[str, str] = {}
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
    """Ollama LLM 请求队列，按 URL 组织确保对不同 Ollama 服务的串行访问"""

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

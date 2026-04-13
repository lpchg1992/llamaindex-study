import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Optional

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WriteTask:
    """写入任务，包含数据和完成回调"""

    lance_store: Any
    nodes: list
    kb_id: str
    callback: Optional[Callable[[bool, str], None]] = None
    error: Optional[str] = None


class LanceDBWriteQueue:
    """Async queue for serializing LanceDB write operations.

    Singleton per process. Workers consume from a shared asyncio.Queue,
    ensuring LanceDB writes from concurrent tasks are serialized to avoid
    corruption. Each task carries a completion callback for notification.

    Args:
        max_workers: Number of concurrent workers (default 1 for serialized writes)
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_workers: int = 1):
        """Initialize the queue.

        Args:
            max_workers: Number of worker coroutines processing the queue
        """
        if self._initialized:
            return
        self._initialized = True
        self.max_workers = max_workers
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list = []
        self._running = False
        self._pending_tasks: dict[
            int, WriteTask
        ] = {}  # task_id -> WriteTask for callback lookup

    async def start(self):
        if self._running:
            return
        self._running = True
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
        logger.info(f"启动 {self.max_workers} 个写入线程")

    async def stop(self):
        self._running = False
        await self._queue.join()
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("写入线程已停止")

    async def wait_until_empty(self, timeout: Optional[float] = None) -> bool:
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("写入队列等待超时")
            return False

    async def enqueue(
        self,
        lance_store: Any,
        nodes: list,
        kb_id: str,
        callback: Optional[Callable[[bool, str], None]] = None,
    ):
        """
        将写入任务加入队列。

        Args:
            lance_store: LanceDB store 实例
            nodes: 要写入的节点列表
            kb_id: 知识库 ID
            callback: 写入完成后的回调，签名: callback(success: bool, error: str)
                     - success=True 表示写入成功
                     - success=False 表示写入失败，error 包含错误信息
        """
        task = WriteTask(
            lance_store=lance_store,
            nodes=nodes,
            kb_id=kb_id,
            callback=callback,
        )
        await self._queue.put(task)

    async def _worker(self, worker_id: int):
        while self._running:
            try:
                task: WriteTask = await self._queue.get()
                success = False
                error_msg = None
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: task.lance_store.add(task.nodes)
                    )
                    success = True
                    logger.debug(
                        f"Worker {worker_id}: 写入 {len(task.nodes)} 个节点到 {task.kb_id}"
                    )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"LanceDB 写入失败 ({task.kb_id}): {e}")
                finally:
                    # 调用回调（如果提供）
                    if task.callback is not None:
                        try:
                            task.callback(success, error_msg)
                        except Exception as cb_err:
                            logger.error(f"写入回调执行失败: {cb_err}")
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"写入队列错误: {e}")
                self._queue.task_done()


lance_write_queue = LanceDBWriteQueue()


async def write_nodes_sync(
    lance_store: Any, nodes: list, kb_id: str
) -> tuple[bool, str]:
    """
    同步写入节点到 LanceDB（通过线程池）。

    Returns:
        (success, error_message)
    """
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: lance_store.add(nodes))
        logger.debug(f"同步写入 {len(nodes)} 个节点到 {kb_id}")
        return (True, "")
    except Exception as e:
        logger.error(f"LanceDB 同步写入失败 ({kb_id}): {e}")
        return (False, str(e))

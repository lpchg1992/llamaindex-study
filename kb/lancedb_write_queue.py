import asyncio
from typing import Any, Optional

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class LanceDBWriteQueue:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_workers: int = 1):
        if self._initialized:
            return
        self._initialized = True
        self.max_workers = max_workers
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list = []
        self._running = False

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

    async def enqueue(self, lance_store: Any, nodes: list, kb_id: str):
        await self._queue.put((lance_store, nodes, kb_id))

    async def _worker(self, worker_id: int):
        while self._running:
            try:
                lance_store, nodes, kb_id = await self._queue.get()
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: lance_store.add(nodes)
                    )
                    logger.debug(
                        f"Worker {worker_id}: 写入 {len(nodes)} 个节点到 {kb_id}"
                    )
                except Exception as e:
                    logger.error(f"LanceDB 写入失败 ({kb_id}): {e}")
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"写入队列错误: {e}")
                self._queue.task_done()


lance_write_queue = LanceDBWriteQueue()

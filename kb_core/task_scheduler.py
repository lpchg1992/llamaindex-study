import asyncio
import logging
from pathlib import Path
from typing import Optional

sys_path = str(Path(__file__).parent.parent)
import sys
sys.path.insert(0, sys_path)

from rag.logger import get_logger
from rag.config import get_settings

logger = get_logger(__name__)

settings = get_settings()
DEFAULT_MAX_CONCURRENT = settings.max_concurrent_tasks
STALE_TASK_TIMEOUT = settings.stale_task_timeout


def is_scheduler_running() -> bool:
    """调度器已内嵌于 API 进程，随 API 一同启停"""
    return True


class TaskScheduler:
    """任务调度器 — 作为 asyncio 后台任务内嵌于 API 进程"""

    def __init__(self, max_concurrent: int = DEFAULT_MAX_CONCURRENT) -> None:
        from .task_queue import TaskQueue
        from .task_executor import TaskExecutor

        self.queue: TaskQueue = TaskQueue()
        self.executor: TaskExecutor = TaskExecutor()
        self._running: bool = True
        self.max_concurrent: int = max_concurrent
        self._stale_check_counter: int = 0

    async def run(self) -> None:
        """运行调度器"""
        logger.info(f"任务调度器已启动 (最大并发: {self.max_concurrent})")

        self._sync_task_states()

        from kb_processing.parallel_embedding import get_parallel_processor
        get_parallel_processor().start_health_checks()

        while self._running:
            try:
                running_count = len(self.executor._running_tasks)

                if running_count < self.max_concurrent:
                    pending = self.queue.get_pending(
                        limit=self.max_concurrent - running_count
                    )

                    for task in pending:
                        if task.task_id in self.executor._running_tasks:
                            continue

                        self.executor._running_tasks[task.task_id] = (
                            asyncio.create_task(
                                self.executor.execute_task(task.task_id)
                            )
                        )
                        logger.info(f"启动任务: {task.task_id[:8]} ({task.kb_id})")

                self._cleanup_completed_tasks()

                self._stale_check_counter += 1
                if self._stale_check_counter >= 10:
                    self._stale_check_counter = 0
                    self._check_and_recover_stale_tasks()

            except Exception as e:
                logger.error(f"调度器错误: {e}")

            await asyncio.sleep(1)

        logger.info("任务调度器已停止")

        from kb_processing.parallel_embedding import get_parallel_processor
        processor = get_parallel_processor()
        if processor._health_check_task is not None:
            processor._health_check_task.cancel()
            logger.info("Embedding 健康检查循环已停止")

    def _cleanup_completed_tasks(self) -> None:
        """清理已完成的任务引用"""
        try:
            done = [
                tid
                for tid, t in list(self.executor._running_tasks.items())
                if isinstance(t, asyncio.Task) and t.done()
            ]
            for tid in done:
                self.executor._running_tasks.pop(tid, None)
        except Exception as e:
            logger.debug(f"清理已完成任务失败: {e}")

    def _sync_task_states(self) -> None:
        """同步内存与数据库状态，恢复崩溃的任务"""
        no_heartbeat = self.queue.get_tasks_needing_recovery()
        for task in no_heartbeat:
            self.queue.update_status(task.task_id, "pending", "进程崩溃已恢复")
            logger.info(f"恢复崩溃任务: {task.task_id[:8]}")

        recovered = self.queue.recover_stale_tasks(STALE_TASK_TIMEOUT)
        if recovered > 0:
            logger.info(f"恢复 {recovered} 个超时任务")

    def _check_and_recover_stale_tasks(self) -> None:
        """检查并恢复超时任务"""
        stale = self.queue.get_stale_tasks(STALE_TASK_TIMEOUT)
        for task in stale:
            if task.task_id in self.executor._running_tasks:
                t = self.executor._running_tasks[task.task_id]
                if isinstance(t, asyncio.Task) and t.done():
                    self.executor._running_tasks.pop(task.task_id, None)
                    logger.debug(f"清理孤立任务引用: {task.task_id[:8]}")
            else:
                self.queue.update_status(task.task_id, "pending", "任务超时已恢复")
                logger.info(f"恢复超时任务: {task.task_id[:8]}")

    def stop(self) -> None:
        """停止调度器"""
        self._running = False


class SchedulerStarter:
    """向后兼容 — 调度器由 API 生命周期管理，无需单独启动"""

    @classmethod
    def ensure_scheduler_running(cls, wait_seconds: float = 3.0) -> bool:
        """调度器已由 API 生命周期内嵌管理，此方法保留向后兼容"""
        return True

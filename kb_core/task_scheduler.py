#!/usr/bin/env python3
import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.logger import configure_all_loggers, get_log_dir, get_logger
from rag.config import get_settings

logger = get_logger(__name__)

settings = get_settings()
DEFAULT_MAX_CONCURRENT = settings.max_concurrent_tasks
STALE_TASK_TIMEOUT = settings.stale_task_timeout


def get_scheduler_pid_file() -> Path:
    """获取调度器 PID 文件路径"""
    import tempfile
    return Path(tempfile.gettempdir()) / "llamaindex_scheduler.pid"

_scheduler_lock_fd = None

def acquire_scheduler_lock() -> bool:
    """获取排他文件锁，确保只有一个调度器实例运行"""
    global _scheduler_lock_fd
    import fcntl
    pid_file = get_scheduler_pid_file()
    try:
        _scheduler_lock_fd = open(pid_file, "w")
        fcntl.flock(_scheduler_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _scheduler_lock_fd.write(str(os.getpid()))
        _scheduler_lock_fd.flush()
        return True
    except OSError:
        if _scheduler_lock_fd:
            _scheduler_lock_fd.close()
            _scheduler_lock_fd = None
        return False

def release_scheduler_lock() -> None:
    """释放文件锁"""
    global _scheduler_lock_fd
    import fcntl
    if _scheduler_lock_fd:
        try:
            fcntl.flock(_scheduler_lock_fd, fcntl.LOCK_UN)
            _scheduler_lock_fd.close()
        except Exception:
            pass
        _scheduler_lock_fd = None
    pid_file = get_scheduler_pid_file()
    if pid_file.exists():
        try:
            pid_file.unlink()
        except OSError:
            pass

def is_scheduler_running() -> bool:
    """检查调度器是否正在运行（基于文件锁）"""
    import fcntl
    pid_file = get_scheduler_pid_file()
    fd = None
    try:
        fd = open(pid_file, "r")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        if fd:
            fd.close()


def cleanup_scheduler_pid() -> None:
    """释放锁并清理 PID 文件"""
    release_scheduler_lock()
    SchedulerStarter.reset_verified()


class TaskScheduler:
    """任务调度器"""

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
    """调度器单例启动器 - 确保只有一个调度器运行"""

    _process: Optional[subprocess.Popen] = None
    _startup_verified: bool = False

    @classmethod
    def ensure_scheduler_running(cls, wait_seconds: float = 3.0) -> bool:
        """确保调度器正在运行，如果不是则启动它"""
        if is_scheduler_running():
            cls._startup_verified = True
            logger.info("调度器已在运行")
            return True

        logger.info("启动调度器进程...")
        cmd = [
            sys.executable,
            "-m",
            "kb_core.task_scheduler",
        ]
        try:
            cls._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=os.environ.copy(),
            )
            logger.info(f"调度器进程已启动 (PID: {cls._process.pid})")

            import time
            start_time = time.time()
            while time.time() - start_time < wait_seconds:
                time.sleep(0.5)
                if is_scheduler_running():
                    cls._startup_verified = True
                    logger.info(
                        f"调度器已就绪 (等待 {(time.time() - start_time):.1f}s)"
                    )
                    return True
                if cls._process.poll() is not None:
                    stdout, stderr = cls._process.communicate()
                    logger.error(f"调度器进程异常退出: {cls._process.returncode}")
                    if stderr:
                        logger.error(
                            f"stderr: {stderr.decode('utf-8', errors='replace')}"
                        )
                    break

            logger.warning(f"调度器启动验证超时 ({wait_seconds}s)，可能仍在初始化")
            return True

        except Exception as e:
            logger.error(f"启动调度器失败: {e}")
            return False

    @classmethod
    def is_verified(cls) -> bool:
        """检查上次启动是否已验证成功"""
        return cls._startup_verified

    @classmethod
    def reset_verified(cls):
        """重置验证状态（调度器停止后调用）"""
        cls._startup_verified = False


def main():
    print(f"调度器启动 (PID: {os.getpid()})")

    if not acquire_scheduler_lock():
        print("错误: 已有另一个调度器正在运行")
        sys.exit(1)

    configure_all_loggers(get_log_dir(), level=logging.INFO)

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        scheduler = TaskScheduler()
        loop.run_until_complete(scheduler.run())
    except KeyboardInterrupt:
        print("调度器收到停止信号")
    finally:
        cleanup_scheduler_pid()
        print("调度器已停止")


if __name__ == "__main__":
    main()

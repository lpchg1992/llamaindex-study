"""
LanceDB 写入队列

提供串行写入队列，避免数据库锁定。
"""

import argparse
import asyncio
from pathlib import Path
from typing import Any, Optional
import sys

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class LanceDBWriteQueue:
    """
    LanceDB 写入队列

    确保串行写入，避免数据库锁定
    """

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
        """启动工作线程"""
        if self._running:
            return

        self._running = True
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
        logger.info(f"启动 {self.max_workers} 个写入线程")

    async def stop(self):
        """停止工作线程"""
        self._running = False

        # 等待队列清空
        await self._queue.join()

        # 取消工作线程
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("写入线程已停止")

    async def wait_until_empty(self, timeout: Optional[float] = None) -> bool:
        """等待队列清空

        Args:
            timeout: 超时时间（秒），None 表示无限等待

        Returns:
            是否在超时前清空
        """
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("写入队列等待超时")
            return False

    async def enqueue(self, lance_store: Any, nodes: list, kb_id: str):
        """入队"""
        await self._queue.put((lance_store, nodes, kb_id))

    async def _worker(self, worker_id: int):
        """工作线程"""
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


# 全局写入队列
lance_write_queue = LanceDBWriteQueue()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="知识库导入任务 CLI")
    parser.add_argument("--list", action="store_true", help="列出所有知识库")
    parser.add_argument("--tasks", action="store_true", help="列出最近任务")
    parser.add_argument("--show-changes", action="store_true", help="查看待同步变更")
    parser.add_argument("--kb", help="指定知识库 ID")
    parser.add_argument(
        "--rebuild", action="store_true", help="重建知识库（清空后重新导入）"
    )
    parser.add_argument(
        "--force-delete", action="store_true", help="同步时处理已删除文件"
    )
    parser.add_argument("--limit", type=int, default=20, help="列表展示数量")
    return parser


def _print_kbs() -> int:
    from kb.registry import KnowledgeBaseRegistry

    registry = KnowledgeBaseRegistry()
    for kb in registry.list_all():
        print(f"{kb.id}\t{kb.name}\t{kb.description}")
    return 0


def _print_tasks(limit: int) -> int:
    from kb.task_queue import TaskQueue

    queue = TaskQueue()
    for task in queue.list_tasks(limit=limit):
        print(
            f"{task.task_id}\t{task.status}\t{task.task_type}\t{task.kb_id}\t{task.message}"
        )
    return 0


def _collect_markdown_files(kb, vault_root: Path) -> list[Path]:
    files: list[Path] = []
    for source_path in kb.source_paths_abs(vault_root):
        if source_path.exists():
            files.extend(source_path.rglob("*.md"))
    return files


def _show_changes(kb_id: Optional[str]) -> int:
    from kb.deduplication import DeduplicationManager
    from kb.registry import KnowledgeBaseRegistry, get_vault_root

    registry = KnowledgeBaseRegistry()
    vault_root = get_vault_root()

    targets = [registry.get(kb_id)] if kb_id else registry.list_all()
    targets = [kb for kb in targets if kb is not None]
    if not targets:
        print("未找到知识库")
        return 1

    for kb in targets:
        files = _collect_markdown_files(kb, vault_root)
        dedup_manager = DeduplicationManager(kb.id, kb.persist_dir)
        to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(
            files, vault_root
        )
        print(
            f"{kb.id}\t新增:{len(to_add)}\t更新:{len(to_update)}\t删除:{len(to_delete)}\t未变更:{len(unchanged)}"
        )
    return 0


def _submit_tasks(kb_id: Optional[str], rebuild: bool, force_delete: bool) -> int:
    from kb.registry import KnowledgeBaseRegistry
    from kb.task_queue import TaskQueue

    registry = KnowledgeBaseRegistry()
    targets = [registry.get(kb_id)] if kb_id else registry.list_all()
    targets = [kb for kb in targets if kb is not None]
    if not targets:
        print("未找到可提交的知识库")
        return 1

    queue = TaskQueue()
    for kb in targets:
        task_id = queue.submit_task(
            task_type="obsidian",
            kb_id=kb.id,
            params={
                "rebuild": rebuild,
                "force_delete": force_delete,
            },
            source="cli",
        )
        print(f"{kb.id}\t{task_id}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()

    if args.list:
        return _print_kbs()
    if args.tasks:
        return _print_tasks(args.limit)
    if args.show_changes:
        return _show_changes(args.kb)
    return _submit_tasks(args.kb, args.rebuild, args.force_delete)


if __name__ == "__main__":
    raise SystemExit(main())

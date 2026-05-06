import asyncio
import time
from typing import List, Optional, Dict, Any, Callable

from rag.logger import get_logger
from kb_core.document_chunk_service import get_document_chunk_service

logger = get_logger(__name__)

from .vector_store import VectorStoreService

class TaskService:
    """任务服务"""

    @staticmethod
    def submit(
        task_type: str, kb_id: str, params: Dict[str, Any], source: str = ""
    ) -> Dict[str, Any]:
        from ..task_queue import TaskQueue

        queue = TaskQueue()
        task_id = queue.submit_task(
            task_type=task_type,
            kb_id=kb_id,
            params=params,
            source=source,
        )
        return {
            "task_id": task_id,
            "status": "pending",
            "kb_id": kb_id,
            "message": "任务已提交",
        }

    @staticmethod
    def list_tasks(
        kb_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """列出任务
        
        Args:
            kb_id: 知识库 ID（可选，None 表示所有）
            status: 任务状态过滤（可选）
            limit: 返回数量限制
            
        Returns:
            任务列表
        """
        from ..task_queue import TaskQueue, TaskStatus
        from ..task_executor import task_executor
        from ..task_scheduler import is_scheduler_running

        queue = TaskQueue()

        if not is_scheduler_running():
            running_tasks = queue.list_tasks(status=TaskStatus.RUNNING.value, limit=100)
            for task in running_tasks:
                if task.task_id not in task_executor._running_tasks:
                    is_stale = (
                        task.last_heartbeat is None
                        or (time.time() - task.last_heartbeat) > 300
                    )
                    if is_stale:
                        queue.update_status(
                            task.task_id,
                            TaskStatus.FAILED.value,
                            "孤儿任务（执行进程已终止）",
                        )

        return [
            task.to_dict()
            for task in queue.list_tasks(kb_id=kb_id, status=status, limit=limit)
        ]

    @staticmethod
    def get_task(task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情
        
        自动检测孤儿任务（执行进程已终止但状态仍为 running）。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务信息字典，不存在则返回 None
        """
        from ..task_queue import TaskQueue, TaskStatus
        from ..task_executor import task_executor
        from ..task_scheduler import is_scheduler_running

        queue = TaskQueue()
        task = queue.get_task(task_id)

        if task and task.status == TaskStatus.RUNNING.value:
            # Only mark as orphan if scheduler is not running AND task not in local _running_tasks
            # Scheduler runs in separate process, so its _running_tasks is different
            if (
                task_id not in task_executor._running_tasks
                and not is_scheduler_running()
            ):
                # Only mark as orphan if heartbeat is stale (> 5 minutes)
                # A task with fresh heartbeat is likely still running normally
                is_stale = (
                    task.last_heartbeat is None
                    or (time.time() - task.last_heartbeat) > 300
                )
                if is_stale:
                    queue.update_status(
                        task_id,
                        TaskStatus.FAILED.value,
                        "孤儿任务（执行进程已终止）",
                    )
                    task = queue.get_task(task_id)

        return task.to_dict() if task else None

    @staticmethod
    def cancel(task_id: str, cleanup: bool = False) -> Dict[str, Any]:
        """取消任务

        Args:
            task_id: 任务ID
            cleanup: 是否清理已处理的数据（默认 False）
        """
        from ..task_queue import TaskQueue, TaskStatus
        from ..task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == TaskStatus.CANCELLED.value:
            result = {
                "status": "cancelled",
                "task_id": task_id,
                "message": "任务已取消",
            }
            if cleanup:
                result["cleanup"] = TaskService._cleanup_task_data(
                    task.kb_id,
                    task.task_type,
                    sources=task.result.get("partial_sources") if task.result else None,
                )
            return result

        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务已完成，无法取消",
            }

        queue.update_status(task_id, TaskStatus.CANCELLED.value, "已取消")
        task_executor.cancel_and_wait(task_id, timeout=5.0)

        result = {
            "status": "cancelled",
            "task_id": task_id,
            "message": "已取消任务",
        }

        if cleanup:
            task = queue.get_task(task_id)
            if task and task.result:
                partial_sources = task.result.get("partial_sources", [])
                if partial_sources:
                    result["cleanup"] = TaskService._cleanup_task_data(
                        task.kb_id, task.task_type, sources=partial_sources
                    )

        return result

    @staticmethod
    def cleanup_orphan_task(task_id: str) -> bool:
        """清理单个孤儿任务
        
        将状态为 RUNNING 但心跳已过期的任务标记为失败。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            是否成功清理
        """
        from ..task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        task = queue.get_task(task_id)

        if task and task.status == TaskStatus.RUNNING.value:
            queue.update_status(
                task_id,
                TaskStatus.FAILED.value,
                "孤儿任务（执行进程已终止）",
            )
            return True
        return False

    @staticmethod
    def pause(task_id: str) -> Dict[str, Any]:
        from ..task_queue import TaskQueue, TaskStatus
        from ..task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status != TaskStatus.RUNNING.value:
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务当前状态为 {task.status}，无法暂停",
            }

        queue.update_status(task_id, TaskStatus.PAUSED.value, "已暂停")
        task_executor.pause_task(task_id)
        return {
            "status": "paused",
            "task_id": task_id,
            "message": "任务已暂停",
        }

    @staticmethod
    def resume(task_id: str) -> Dict[str, Any]:
        from ..task_queue import TaskQueue, TaskStatus
        from ..task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status != TaskStatus.PAUSED.value:
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务当前状态为 {task.status}，无法恢复",
            }

        queue.update_status(task_id, TaskStatus.RUNNING.value, "继续执行")
        task_executor.resume_task(task_id)
        return {
            "status": "running",
            "task_id": task_id,
            "message": "任务已恢复",
        }

    @staticmethod
    def pause_all(status: str = "running") -> Dict[str, Any]:
        """暂停所有指定状态的任务
        
        Args:
            status: 要暂停的任务状态，默认为 "running"
            
        Returns:
            操作结果统计
        """
        from ..task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status=status)
        paused = []
        failed = []

        for task in tasks:
            if task.status == TaskStatus.RUNNING.value:
                queue.update_status(task.task_id, TaskStatus.PAUSED.value, "已暂停")
                paused.append(task.task_id)
            else:
                failed.append(task.task_id)

        return {
            "status": "completed",
            "paused": paused,
            "failed": failed,
            "message": f"已暂停 {len(paused)} 个任务，{len(failed)} 个无法暂停",
        }

    @staticmethod
    def resume_all() -> Dict[str, Any]:
        """恢复所有已暂停的任务
        
        Returns:
            操作结果统计
        """
        from ..task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status="paused")
        resumed = []

        for task in tasks:
            queue.update_status(task.task_id, TaskStatus.RUNNING.value, "继续执行")
            resumed.append(task.task_id)

        return {
            "status": "completed",
            "resumed": resumed,
            "message": f"已恢复 {len(resumed)} 个任务",
        }

    @staticmethod
    def delete_all(status: str = "completed", cleanup: bool = False) -> Dict[str, Any]:
        """批量删除任务
        
        Args:
            status: 删除指定状态的任务，"all" 表示所有
            cleanup: 是否同时清理关联的知识库数据
            
        Returns:
            操作结果统计
        """
        from ..task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        if status == "all":
            tasks = queue.list_tasks(limit=1000)
        else:
            tasks = queue.list_tasks(status=status)
        deleted = []
        cleaned_results = []

        for task in tasks:
            try:
                if task.status == TaskStatus.RUNNING.value:
                    continue

                if cleanup:
                    sources = task.result.get("sources") if task.result else None
                    cleaned = TaskService._cleanup_task_data(
                        task.kb_id, task.task_type, sources=sources
                    )
                    cleaned_results.append(
                        {"task_id": task.task_id, "cleanup": cleaned}
                    )

                queue.delete_task(task.task_id)
                deleted.append(task.task_id)
            except Exception:
                pass

        result = {
            "status": "completed",
            "deleted": deleted,
            "message": f"已删除 {len(deleted)} 个任务",
        }

        if cleaned_results:
            result["cleaned"] = cleaned_results

        return result

    @staticmethod
    def cleanup_orphan_tasks(cleanup: bool = True) -> Dict[str, Any]:
        """清理所有孤儿任务
        
        检测并标记执行进程已终止但状态仍为 running 的任务。
        
        Args:
            cleanup: 是否同时清理关联数据
            
        Returns:
            清理结果统计
        """
        from ..task_queue import TaskQueue, TaskStatus
        from ..task_executor import task_executor
        from ..task_scheduler import is_scheduler_running

        queue = TaskQueue()
        tasks = queue.list_tasks(status="running")
        cleaned = []
        cleaned_data = []

        if not is_scheduler_running():
            for task in tasks:
                if task.task_id not in task_executor._running_tasks:
                    is_stale = (
                        task.last_heartbeat is None
                        or (time.time() - task.last_heartbeat) > 300
                    )
                    if is_stale:
                        cleaned.append(task.task_id)
                        queue.update_status(
                            task.task_id,
                            TaskStatus.FAILED.value,
                            "孤儿任务（执行进程已终止）",
                        )

                        if cleanup:
                            sources = (
                                task.result.get("sources") if task.result else None
                            )
                            result = TaskService._cleanup_task_data(
                                task.kb_id, task.task_type, sources=sources
                            )
                            cleaned_data.append(
                                {"task_id": task.task_id, "cleanup": result}
                            )

        result = {
            "status": "completed",
            "cleaned": cleaned,
            "message": f"已清理 {len(cleaned)} 个孤儿任务",
        }

        if cleaned_data:
            result["cleaned_data"] = cleaned_data

        return result

    @staticmethod
    def delete(task_id: str, cleanup: Optional[bool] = None) -> Dict[str, Any]:
        """删除任务（物理删除）

        Args:
            task_id: 任务ID
            cleanup: 是否清理关联的知识库数据（可选）
                    - None: 自动模式（任务状态为 failed/cancelled 时自动清理）
                    - True: 强制清理
                    - False: 不清理
        """
        from ..task_queue import TaskQueue

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == "running":
            raise ValueError(f"任务正在运行，无法删除: {task_id}")

        if task.status == "cancelled":
            from ..task_executor import task_executor

            task_executor.cancel_and_wait(task_id, timeout=5.0)

        success = queue.delete_task(task_id)
        if not success:
            raise ValueError(f"删除失败: {task_id}")

        result = {"status": "deleted", "task_id": task_id, "message": "任务已删除"}

        should_cleanup = cleanup if cleanup is not None else False
        if task.status in ("failed", "cancelled"):
            should_cleanup = True

        if should_cleanup:
            sources = task.result.get("sources") if task.result else None
            if not sources:
                sources = task.result.get("partial_sources") if task.result else None
            cleaned = TaskService._cleanup_task_data(
                task.kb_id, task.task_type, sources=sources
            )
            result["cleanup"] = cleaned

        return result

    @staticmethod
    def _cleanup_task_data(
        kb_id: str,
        task_type: str,
        sources: Optional[List[str]] = None,
        cleanup_mode: str = "sources",
    ) -> Dict[str, Any]:
        """清理任务产生的关联数据

        Args:
            kb_id: 知识库ID
            task_type: 任务类型
            sources: 要删除的源文件路径列表
            cleanup_mode:
                - "full": 清空整个知识库数据（仅用于 initialize 类型）
                - "sources": 只清理指定的 sources（推荐，用于取消/删除任务）
        """
        cleaned = {
            "dedup_state": True,
            "vector_store": False,
            "documents": False,
            "chunks": False,
            "deleted_nodes": 0,
        }

        if task_type == "initialize" or cleanup_mode == "full":
            from .vector_store import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True

            doc_service = get_document_chunk_service(kb_id)
            all_docs = doc_service.get_all_documents()
            for doc in all_docs:
                doc_service.delete_document_cascade(
                    doc["id"],
                    delete_lance=False,
                )
            cleaned["documents"] = True
            cleaned["chunks"] = True

        elif task_type == "zotero" and cleanup_mode == "full":
            cleaned["dedup_state"] = True

            from .vector_store import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True

            doc_service = get_document_chunk_service(kb_id)
            all_docs = doc_service.get_all_documents()
            for doc in all_docs:
                doc_service.delete_document_cascade(
                    doc["id"],
                    delete_lance=False,
                )
            cleaned["documents"] = True
            cleaned["chunks"] = True

        elif sources:
            cleaned["dedup_state"] = True

            from .vector_store import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            lance_store = vs._get_lance_vector_store()
            deleted = lance_store.delete_by_source(sources)
            cleaned["deleted_nodes"] = deleted
            cleaned["vector_store"] = deleted > 0

            doc_service = get_document_chunk_service(kb_id)
            for source in sources:
                result = doc_service.delete_documents_by_source(source)
                if result.get("documents", 0) > 0:
                    cleaned["documents"] = cleaned.get("documents", 0) + result.get(
                        "documents", 0
                    )
                    cleaned["chunks"] = cleaned.get("chunks", 0) + result.get(
                        "chunks", 0
                    )

        return cleaned

    @staticmethod
    def run_task(task_id: str) -> Dict[str, Any]:
        """立即执行任务
        
        同步执行单个任务（阻塞直到完成）。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            执行完成后的任务状态
            
        Raises:
            ValueError: 任务不存在
        """
        from ..task_executor import task_executor

        asyncio.run(task_executor.execute_task(task_id))
        task = TaskService.get_task(task_id)
        if task is None:
            raise ValueError(f"任务不存在: {task_id}")
        return task

    @staticmethod
    def wait_for_task(
        task_id: str, interval: float = 1.0, timeout: float = 0
    ) -> Dict[str, Any]:
        """等待任务完成
        
        轮询任务状态直到完成或超时。
        
        Args:
            task_id: 任务 ID
            interval: 轮询间隔（秒）
            timeout: 超时时间（秒），0 表示无限等待
            
        Returns:
            最终任务状态
        """
        start = time.time()
        while True:
            task = TaskService.get_task(task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}")
            if task["status"] in {"completed", "failed", "cancelled"}:
                return task
            if timeout > 0 and time.time() - start >= timeout:
                return task
            time.sleep(interval)

# =============================================================================

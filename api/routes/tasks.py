"""
Task queue management endpoints.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException

from api.schemas import TaskResponse, TaskCreateRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskResponse)
def create_task(req: TaskCreateRequest):
    from kb_core.task_queue import task_queue

    task_id = task_queue.submit_task(
        task_type=req.task_type,
        kb_id=req.kb_id,
        params=req.params,
        source=req.source,
    )

    return TaskResponse(
        task_id=task_id,
        status="pending",
        kb_id=req.kb_id,
        message="任务已提交",
    )


@router.get("", response_model=List[TaskResponse])
def list_tasks(kb_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    from kb_core.task_queue import task_queue

    tasks = task_queue.list_tasks(kb_id=kb_id, status=status, limit=limit)
    return [
        TaskResponse(
            task_id=t.task_id,
            status=t.status,
            kb_id=t.kb_id,
            message=t.message,
            progress=t.progress,
        )
        for t in tasks
    ]


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str):
    from kb_core.task_queue import task_queue

    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        task_id=task.task_id,
        task_type=task.task_type,
        status=task.status,
        kb_id=task.kb_id,
        message=task.message,
        progress=task.progress,
        current=task.current,
        total=task.total,
        result=task.result,
        error=task.error,
        file_progress=task.file_progress,
    )


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    from kb_core.services import TaskService

    try:
        result = TaskService.cancel(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{task_id}/pause")
def pause_task(task_id: str):
    from kb_core.services import TaskService

    try:
        result = TaskService.pause(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{task_id}/resume")
def resume_task(task_id: str):
    from kb_core.services import TaskService

    try:
        result = TaskService.resume(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{task_id}/files/{file_id}")
def cancel_file_in_task(task_id: str, file_id: str):
    from kb_core.task_queue import task_queue

    success = task_queue.cancel_file(task_id, file_id)
    if not success:
        raise HTTPException(
            status_code=400, detail="无法取消文件（可能已完成或不存在）"
        )
    return {"message": "文件已取消", "task_id": task_id, "file_id": file_id}


@router.delete("/{task_id}")
def delete_task(task_id: str, cleanup: bool = False):
    from kb_core.services import TaskService

    try:
        return TaskService.delete(task_id, cleanup=cleanup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pause-all")
def pause_all_tasks(status: str = "running"):
    from kb_core.services import TaskService

    return TaskService.pause_all(status)


@router.post("/resume-all")
def resume_all_tasks():
    from kb_core.services import TaskService

    return TaskService.resume_all()


@router.delete("/delete-all")
def delete_all_tasks(status: str = "completed", cleanup: bool = False):
    from kb_core.services import TaskService

    return TaskService.delete_all(status, cleanup)


@router.post("/cleanup")
def cleanup_orphan_tasks():
    from kb_core.services import TaskService

    return TaskService.cleanup_orphan_tasks()
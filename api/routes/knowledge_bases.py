"""
Knowledge base management endpoints.
"""

from typing import List

from fastapi import APIRouter, Body, HTTPException

from api.schemas import (
    KBInfo,
    KBUpdateRequest,
    DangerousOperationRequest,
    RefreshTopicsRequest,
)

router = APIRouter(prefix="/kbs", tags=["knowledge-bases"])


@router.get("", response_model=List[KBInfo])
def list_kbs():
    from kb_core.services import KnowledgeBaseService

    kbs = KnowledgeBaseService.list_all()
    return [KBInfo(**kb) for kb in kbs]


@router.post("", response_model=KBInfo)
def create_kb(req: KBInfo):
    from kb_core.services import KnowledgeBaseService

    try:
        result = KnowledgeBaseService.create(
            kb_id=req.id,
            name=req.name,
            description=req.description,
            source_type=req.source_type,
        )
        return KBInfo(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{kb_id}")
def get_kb_info(kb_id: str):
    from kb_core.services import KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    return info


@router.put("/{kb_id}")
def update_kb_info(kb_id: str, req: KBUpdateRequest):
    from kb_core.services import KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    try:
        result = KnowledgeBaseService.update_info(
            kb_id,
            name=req.name,
            description=req.description,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{kb_id}")
def delete_kb(kb_id: str, req: DangerousOperationRequest = Body(...)):
    from kb_core.services import KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    if req.confirmation_name != kb_id:
        raise HTTPException(status_code=400, detail="知识库名称不匹配，操作已取消")
    if KnowledgeBaseService.delete(kb_id):
        return {"status": "deleted", "kb_id": kb_id}
    raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")


@router.get("/{kb_id}/topics")
def get_kb_topics(kb_id: str):
    from kb_core.services import KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    topics = KnowledgeBaseService.get_topics(kb_id)
    return {
        "kb_id": kb_id,
        "topics": topics,
        "topic_count": len(topics),
    }


@router.post("/{kb_id}/topics/refresh")
def refresh_kb_topics(kb_id: str, req: RefreshTopicsRequest):
    from kb_core.services import KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    topics = KnowledgeBaseService.refresh_topics(
        kb_id=kb_id,
        has_new_docs=req.has_new_docs,
    )
    return {
        "kb_id": kb_id,
        "topics": topics,
        "topic_count": len(topics),
    }


@router.get("/{kb_id}/consistency")
def check_consistency(kb_id: str):
    from kb_core.services import ConsistencyService, KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    result = ConsistencyService.check(kb_id)
    return result


@router.post("/{kb_id}/consistency/repair")
def repair_consistency(kb_id: str):
    from kb_core.services import ConsistencyService, KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    result = ConsistencyService.repair(kb_id)
    return result


@router.post("/consistency/repair-all")
def repair_all_consistency():
    from kb_core.services import ConsistencyService

    result = ConsistencyService.repair_all()
    return result


@router.get("/{kb_id}/consistency/doc-stats")
def get_doc_embedding_stats(kb_id: str):
    from kb_core.services import ConsistencyService, KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    result = ConsistencyService.get_doc_embedding_stats(kb_id)
    return {
        "kb_id": kb_id,
        "docs": result,
    }


@router.get("/{kb_id}/embedding-stats")
def get_embedding_stats(kb_id: str):
    from kb_core.services import KnowledgeBaseService
    from kb_core.database import init_chunk_db

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    chunk_db = init_chunk_db()
    stats = chunk_db.get_embedding_stats(kb_id)

    return {
        "kb_id": kb_id,
        "total": stats.get("total", 0),
        "success": stats.get("success", 0),
        "failed": stats.get("failed", 0),
        "pending": stats.get("pending", 0),
    }


@router.post("/{kb_id}/consistency/check-and-mark-failed")
def check_and_mark_failed_chunks(kb_id: str, limit: int = 200000):
    from kb_core.services import KnowledgeBaseService
    from kb_core.task_queue import task_queue

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    task_id = task_queue.submit_task(
        task_type="check_mark_failed",
        kb_id=kb_id,
        params={"limit": limit},
        source="api.check_mark_failed",
    )

    return {
        "status": "submitted",
        "task_id": task_id,
        "message": f"检查并标记失败任务已提交: {task_id}",
    }


@router.post("/{kb_id}/initialize")
def initialize_kb(
    kb_id: str, req: DangerousOperationRequest = Body(...), async_mode: bool = True
):
    from kb_core.services import KnowledgeBaseService
    from kb_core.task_queue import task_queue

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    if req.confirmation_name != kb_id:
        raise HTTPException(status_code=400, detail="知识库名称不匹配，操作已取消")

    if async_mode:
        task_id = task_queue.submit_task(
            task_type="initialize",
            kb_id=kb_id,
            params={},
            source=f"initialize:{kb_id}",
        )

        return {
            "status": "pending",
            "task_id": task_id,
            "message": f"初始化任务已提交，ID: {task_id}",
        }
    else:
        KnowledgeBaseService.initialize(kb_id)
        return {
            "status": "success",
            "message": f"知识库 {kb_id} 已初始化（所有数据已清空）",
        }
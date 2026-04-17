"""
Document and chunk management endpoints.
"""

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query

from api.schemas import (
    DocumentResponse,
    ChunkResponse,
)

router = APIRouter(prefix="/kbs/{kb_id}", tags=["documents"])


@router.get("/documents", response_model=List[DocumentResponse])
def list_documents(kb_id: str):
    from kb_core.database import init_document_db

    docs = init_document_db().get_by_kb(kb_id)
    return docs


@router.get("/documents/{doc_id}", response_model=DocumentResponse)
def get_document(kb_id: str, doc_id: str):
    from kb_core.database import init_document_db

    doc = init_document_db().get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    if doc["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不属于知识库 {kb_id}")
    return doc


@router.delete("/documents/{doc_id}")
def delete_document(kb_id: str, doc_id: str):
    from kb_core.document_chunk_service import get_document_chunk_service
    from kb_core.registry import registry

    kb = registry.get(kb_id)
    persist_dir = kb.persist_dir if kb else None

    service = get_document_chunk_service(kb_id=kb_id, persist_dir=persist_dir)
    result = service.delete_document_cascade(doc_id, delete_lance=True)

    if result.get("documents", 0) == 0:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")

    return {"status": "deleted", "doc_id": doc_id, "result": result}


@router.get("/documents/{doc_id}/chunks")
def list_document_chunks(
    kb_id: str,
    doc_id: str,
    page: int = 1,
    page_size: int = 20,
    embedding_status: int = None,
):
    from kb_core.database import init_document_db, init_chunk_db

    doc_db = init_document_db()
    doc = doc_db.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    if doc["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不属于知识库 {kb_id}")

    chunk_db = init_chunk_db()

    if embedding_status is not None:
        total = chunk_db.count_by_doc_filtered(doc_id, embedding_status)
        offset = (page - 1) * page_size
        chunks = chunk_db.get_by_doc_filtered(
            doc_id, embedding_status, offset=offset, limit=page_size
        )
    else:
        total = chunk_db.count_by_doc(doc_id)
        offset = (page - 1) * page_size
        chunks = chunk_db.get_by_doc(doc_id, offset=offset, limit=page_size)

    return {
        "chunks": chunks,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "embedding_status": embedding_status,
    }


@router.get("/chunks/failed")
def list_failed_chunks(kb_id: str, limit: int = 1000):
    from kb_core.database import init_chunk_db

    chunk_db = init_chunk_db()
    failed_chunks = chunk_db.get_failed_chunks(kb_id, limit=limit)
    stats = chunk_db.get_embedding_stats(kb_id)
    return {
        "chunks": failed_chunks,
        "total": len(failed_chunks),
        "stats": stats,
    }


@router.get("/chunks/{chunk_id}", response_model=ChunkResponse)
def get_chunk(kb_id: str, chunk_id: str):
    from kb_core.database import init_chunk_db

    chunk = init_chunk_db().get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")
    return chunk


@router.put("/chunks/{chunk_id}", response_model=ChunkResponse)
def update_chunk_text(kb_id: str, chunk_id: str, req: Dict[str, str]):
    from kb_core.database import init_chunk_db

    if "text" not in req:
        raise HTTPException(status_code=400, detail="需要提供 text 字段")

    chunk_db = init_chunk_db()
    chunk = chunk_db.get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")

    chunk_db.update_text(chunk_id, req["text"])
    return chunk_db.get(chunk_id)


@router.post("/chunks/{chunk_id}/reembed")
def reembed_chunk(kb_id: str, chunk_id: str):
    from kb_core.database import init_chunk_db
    from kb_storage.lance_crud import LanceCRUDService
    from kb_processing.parallel_embedding import get_parallel_processor
    from rag.logger import get_logger

    logger = get_logger(__name__)
    chunk_db = init_chunk_db()
    chunk = chunk_db.get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")

    processor = get_parallel_processor()
    if not processor.endpoints:
        return {
            "status": "error",
            "chunk_id": chunk_id,
            "message": "没有可用的 embedding 端点",
        }

    try:
        ep = processor._get_best_endpoint()
        import asyncio

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _, embedding, error = loop.run_until_complete(
            processor.get_embedding(chunk["text"], ep.name)
        )
        loop.close()

        if error:
            raise Exception(error)

        if all(v == 0.0 for v in embedding):
            raise Exception("Embedding returned zero vector")

        LanceCRUDService.upsert_vector(
            chunk_id, chunk["doc_id"], embedding, kb_id=kb_id
        )
        try:
            chunk_db.mark_embedded(chunk_id)
        except Exception as mark_err:
            try:
                LanceCRUDService.delete_by_chunk_ids(kb_id, [chunk_id])
            except Exception:
                pass
            raise Exception(f"DB update failed after vector write: {mark_err}")
        return {
            "status": "success",
            "chunk_id": chunk_id,
            "message": "embedding 已重新生成",
        }
    except Exception as e:
        chunk_db.mark_failed_bulk([chunk_id])
        return {"status": "error", "chunk_id": chunk_id, "message": str(e)}


@router.post("/chunks/revector")
def submit_revector_task(
    kb_id: str,
    include_pending: bool = True,
    include_failed: bool = True,
    include_embedded: bool = False,
    batch_size: int = 100,
    limit: int = 50000,
):
    from kb_core.task_queue import task_queue
    from kb_core.database import init_chunk_db

    chunk_db = init_chunk_db()

    pending_count = len(chunk_db.get_unembedded(kb_id, limit=1))
    failed_count = len(chunk_db.get_failed_chunks(kb_id, limit=1))
    embedded_count = (
        len(chunk_db.get_embedded(kb_id, limit=1)) if include_embedded else 0
    )

    has_pending = include_pending and pending_count > 0
    has_failed = include_failed and failed_count > 0
    has_embedded = include_embedded and embedded_count > 0

    if not has_pending and not has_failed and not has_embedded:
        return {
            "status": "no_chunks",
            "message": "没有需要重新向量化的 chunks",
            "pending": pending_count,
            "failed": failed_count,
            "embedded": embedded_count,
        }

    task_id = task_queue.submit_task(
        task_type="revector",
        kb_id=kb_id,
        params={
            "include_pending": include_pending,
            "include_failed": include_failed,
            "include_embedded": include_embedded,
            "batch_size": batch_size,
            "limit": limit,
        },
        source="api.revector",
    )

    return {
        "status": "submitted",
        "task_id": task_id,
        "message": f"重新向量化任务已提交: {task_id}",
        "pending": pending_count,
        "failed": failed_count,
        "embedded": embedded_count,
    }


@router.delete("/chunks/{chunk_id}")
def delete_chunk(kb_id: str, chunk_id: str, cascade: bool = True):
    from kb_core.database import init_chunk_db
    from kb_core.document_chunk_service import get_document_chunk_service

    chunk_db = init_chunk_db()
    chunk = chunk_db.get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")

    service = get_document_chunk_service(kb_id)
    result = service.delete_chunk_cascade(chunk_id, cascade_children=cascade)

    return {
        "status": "success",
        "chunk_id": chunk_id,
        "deleted_chunks": result.get("chunks", 0),
        "deleted_lance": result.get("lance", 0),
        "children_orphaned": result.get("children_orphaned", 0),
        "cascade": cascade,
    }


@router.get("/chunks/{chunk_id}/children")
def get_chunk_children(kb_id: str, chunk_id: str):
    from kb_core.database import init_chunk_db
    from kb_core.document_chunk_service import get_document_chunk_service

    chunk_db = init_chunk_db()
    chunk = chunk_db.get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")

    service = get_document_chunk_service(kb_id)
    children = service.get_chunk_children(chunk_id)
    return {"children": children, "count": len(children)}
"""
LanceDB management endpoints.
"""

from typing import Optional
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/lance", tags=["lance"])


@router.get("/tables")
def lance_list_tables():
    from kb_storage.lance_crud import LanceCRUDService

    return {"tables": LanceCRUDService.list_all_tables()}


@router.get("/{kb_id}/stats")
def lance_get_stats(kb_id: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    try:
        stats = LanceCRUDService.get_table_stats(kb_id, table_name)
        return asdict(stats)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{kb_id}/schema")
def lance_get_schema(kb_id: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    try:
        return LanceCRUDService.get_schema(kb_id, table_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{kb_id}/docs")
def lance_get_doc_summary(kb_id: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    try:
        docs = LanceCRUDService.get_doc_summary(kb_id, table_name)
        return {"docs": [asdict(d) for d in docs]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{kb_id}/nodes")
def lance_query_nodes(
    kb_id: str,
    table_name: Optional[str] = None,
    doc_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    from kb_storage.lance_crud import LanceCRUDService

    try:
        nodes = LanceCRUDService.query_nodes(kb_id, table_name, doc_id, limit, offset)
        return {"nodes": [asdict(n) for n in nodes]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{kb_id}/duplicates")
def lance_find_duplicates(kb_id: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    try:
        duplicates = LanceCRUDService.find_duplicate_sources(kb_id, table_name)
        return {"duplicates": duplicates, "count": len(duplicates)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{kb_id}/doc_ids")
def lance_delete_by_doc_ids(kb_id: str, doc_ids: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    doc_id_list = [d.strip() for d in doc_ids.split(",") if d.strip()]
    if not doc_id_list:
        raise HTTPException(status_code=400, detail="doc_ids 不能为空")
    try:
        deleted = LanceCRUDService.delete_by_doc_ids(kb_id, doc_id_list, table_name)
        return {"deleted": deleted, "doc_ids": doc_id_list}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{kb_id}/source")
def lance_delete_by_source(kb_id: str, source: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    if not source:
        raise HTTPException(status_code=400, detail="source 不能为空")
    try:
        deleted = LanceCRUDService.delete_by_source_file(kb_id, source, table_name)
        return {"deleted": deleted, "source": source}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{kb_id}/nodes")
def lance_delete_by_nodes(kb_id: str, node_ids: str, table_name: Optional[str] = None):
    from kb_storage.lance_crud import LanceCRUDService

    node_id_list = [n.strip() for n in node_ids.split(",") if n.strip()]
    if not node_id_list:
        raise HTTPException(status_code=400, detail="node_ids 不能为空")
    try:
        deleted = LanceCRUDService.delete_by_node_ids(kb_id, node_id_list, table_name)
        return {"deleted": deleted, "node_ids": node_id_list}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{kb_id}/export")
def lance_export(kb_id: str, output_path: str, table_name: Optional[str] = None):
    from pathlib import Path
    from kb_storage.lance_crud import LanceCRUDService

    output = Path(output_path)
    if output.exists() and not output.is_file():
        raise HTTPException(status_code=400, detail="output_path 必须是文件路径，不能是目录")

    try:
        count = LanceCRUDService.export_to_jsonl(kb_id, output_path, table_name)
        return {"exported": count, "output_path": output_path}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")
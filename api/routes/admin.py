"""
Admin and system management endpoints.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tables")
def list_tables():
    from rag.config import get_settings
    base = Path(get_settings().llamaindex_storage_base)
    tables = []

    for kb_dir in base.iterdir():
        if not kb_dir.is_dir():
            continue

        lance_file = kb_dir / f"{kb_dir.name}.lance"
        if lance_file.exists():
            tables.append(
                {
                    "kb_id": kb_dir.name,
                    "path": str(kb_dir),
                    "size": sum(f.stat().st_size for f in lance_file.rglob("*.lance"))
                    / 1024
                    / 1024,
                }
            )

    return {"tables": tables}


@router.get("/tables/{kb_id}")
def get_table_info(kb_id: str):
    from kb_core.services import KnowledgeBaseService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    return info


@router.delete("/tables/{kb_id}")
def delete_table(kb_id: str):
    from kb_core.services import KnowledgeBaseService

    if KnowledgeBaseService.delete(kb_id):
        return {"status": "deleted", "kb_id": kb_id}
    raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")


@router.post("/restart-scheduler")
def restart_scheduler():
    """重启内嵌调度器（调度器随 API 一同管理，不再作为独立子进程）"""
    from rag.logger import get_logger
    logger = get_logger(__name__)
    logger.info("调度器随 API 内嵌运行，重启 API 即可重启调度器。使用 POST /restart-api")
    return {
        "status": "embedded",
        "message": "调度器已内嵌于 API 进程，请使用 POST /restart-api 重启"
    }


@router.post("/restart-api")
def restart_api():
    import os
    import signal
    import threading
    from pathlib import Path
    from rag.logger import get_logger

    logger = get_logger(__name__)
    PROJECT_ROOT = Path(__file__).parent.parent

    logger.info(f"重启 API 服务 (PID: {os.getpid()})")
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

    return {"status": "restarting", "message": "API 服务正在重启..."}


@router.post("/reload-config")
def reload_config():
    from rag.config import get_model_registry, get_settings
    from rag.logger import get_logger

    logger = get_logger(__name__)
    try:
        registry = get_model_registry()
        registry.reload()
        s = get_settings()
        s.load_runtime_settings()
        try:
            from kb_processing.parallel_embedding import get_parallel_processor
            get_parallel_processor().refresh_endpoints()
        except Exception:
            pass
        logger.info("模型注册表、运行时设置和 embedding 端点已重新加载")
        return {"status": "success", "message": "配置已重新加载"}
    except Exception as e:
        logger.error(f"配置重载失败: {e}")
        raise HTTPException(status_code=500, detail=f"配置重载失败: {str(e)}")
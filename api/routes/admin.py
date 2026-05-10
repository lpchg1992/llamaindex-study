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
    from rag.logger import get_logger
    logger = get_logger(__name__)
    logger.info("POST /admin/restart-scheduler is deprecated; scheduler runs embedded in API process")
    return {
        "status": "deprecated",
        "message": "Scheduler runs embedded in the API process. Use POST /admin/restart-api to restart everything."
    }


@router.post("/restart-api")
def restart_api():
    import os
    import signal
    import threading
    import time
    from pathlib import Path
    from rag.logger import get_logger

    logger = get_logger(__name__)

    def delayed_shutdown():
        time.sleep(3)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=delayed_shutdown, daemon=True).start()

    return {
        "status": "graceful_restart",
        "message": "API will restart in 3 seconds to allow in-flight requests to complete"
    }


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
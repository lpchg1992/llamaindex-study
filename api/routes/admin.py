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
    from kb_core.task_scheduler import SchedulerStarter, is_scheduler_running, get_scheduler_pid_file
    from rag.logger import get_logger

    logger = get_logger(__name__)
    pid_file = get_scheduler_pid_file()

    if is_scheduler_running():
        import os
        import signal

        try:
            with open(pid_file, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, signal.SIGTERM)
            logger.info(f"已发送停止信号到调度器 (PID: {old_pid})")
        except (ProcessLookupError, OSError, ValueError) as e:
            logger.warning(f"停止调度器失败或进程不存在: {e}")

    SchedulerStarter.ensure_scheduler_running(wait_seconds=5.0)

    return {"status": "restarting", "message": "调度器正在重启..."}


@router.post("/restart-api")
def restart_api():
    import os
    import signal
    import threading
    from pathlib import Path
    from rag.logger import get_logger

    logger = get_logger(__name__)
    PROJECT_ROOT = Path(__file__).parent.parent
    pid_file = PROJECT_ROOT / ".api.pid"
    restart_flag = PROJECT_ROOT / ".api_restart_required"

    restart_flag.write_text(str(os.getpid()))
    logger.info(f"重启标记已写入 PID: {os.getpid()}")

    # 延迟杀进程，确保 HTTP 响应先发送
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
        logger.info("模型注册表和运行时设置已重新加载")
        return {"status": "success", "message": "配置已重新加载"}
    except Exception as e:
        logger.error(f"配置重载失败: {e}")
        raise HTTPException(status_code=500, detail=f"配置重载失败: {str(e)}")
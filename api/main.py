"""
LlamaIndex RAG API Server v3.1

FastAPI application entry point with modular router architecture.

启动:
    uv run python -m api.main

路由拆分:
    - health:     /health, /api-docs
    - tasks:      /tasks/*
    - knowledge_bases: /kbs/*
    - models:     /vendors/*, /models/*
    - search:     /search, /query, /evaluate/*
    - ingest:     /kbs/{kb_id}/ingest/*
    - zotero:     /zotero/*
    - obsidian:   /obsidian/*
    - categories:  /file/preview
    - admin:      /admin/*
    - documents:  /kbs/{kb_id}/documents/*, /kbs/{kb_id}/chunks/*
    - lance:      /lance/*
    - websocket:  /ws/*, /chat/*
    - observability: /observability/*
    - settings:   /settings
    - extraction: /extract/*
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.deps import lifespan, get_cors_origins
from api.routes import (
    health_router,
    tasks_router,
    kb_router,
    models_router,
    search_router,
    ingest_router,
    zotero_router,
    obsidian_router,
    admin_router,
    documents_router,
    lance_router,
    websocket_router,
    observability_router,
    settings_router,
    extraction_router,
)
from rag.logger import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="LlamaIndex RAG API",
        description="""
RAG 检索增强生成 API，支持任务队列异步处理。

## 核心文档

- [Query 参数设计指南](./QUERY_PARAM_GUIDE.md) - 客户端 UI 设计参考
- [CLI 使用文档](./CLI.md) - 命令行接口详细说明
- [架构设计](./ARCHITECTURE.md) - 系统架构与设计模式

## 快速开始

1. 创建知识库: `POST /kbs`
2. 导入文档: `POST /kbs/{kb_id}/ingest`
3. RAG 问答: `POST /kbs/{kb_id}/query`
        """,
        version="3.1.0",
        docs_url="/docs",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        response = JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc):
        logger.error(
            f"Unhandled exception on {request.method} {request.url.path}: "
            f"{type(exc).__name__}: {exc}",
            exc_info=True,
            extra={"method": request.method, "path": request.url.path},
        )
        response = JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {str(exc)}"},
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(kb_router)
    app.include_router(models_router)
    app.include_router(search_router)
    app.include_router(ingest_router)
    app.include_router(zotero_router)
    app.include_router(obsidian_router)
    app.include_router(admin_router)
    app.include_router(documents_router)
    app.include_router(lance_router)
    app.include_router(websocket_router)
    app.include_router(observability_router)
    app.include_router(settings_router)
    app.include_router(extraction_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    from rag.logger import LOG_LEVEL
    from rag.config import get_settings

    port = get_settings().api_port
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None, log_level="info")
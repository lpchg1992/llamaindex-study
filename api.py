"""
LlamaIndex RAG API Server v3.1

启动:
    uv run python api.py

API 端点:
    GET  /health                    - 健康检查

    知识库管理:
    GET  /kbs                      - 列出所有知识库
    POST /kbs                      - 创建新知识库
    GET  /kbs/{kb_id}              - 获取知识库详情
    DELETE /kbs/{kb_id}            - 删除知识库

    检索查询:
    POST /search                     - 统一检索入口（general/auto）
    POST /query                      - 统一问答入口（general/auto）

    RAG 评估:
    POST /evaluate/{kb_id}           - RAG 性能评估
    GET  /evaluate/metrics           - 获取评估指标说明

    任务队列:
    POST /tasks                      - 提交任务
    GET  /tasks                      - 列出任务
    GET  /tasks/{task_id}           - 查询任务状态
    DELETE /tasks/{task_id}          - 取消任务
    DELETE /tasks/{task_id}/delete   - 删除任务

    文档导入 (异步):
    POST /kbs/{kb_id}/ingest        - 通用文件导入（异步）
    POST /kbs/{kb_id}/ingest/zotero - Zotero 收藏夹导入（异步）
    POST /kbs/{kb_id}/ingest/obsidian - Obsidian vault 导入（异步）
    POST /kbs/{kb_id}/initialize    - 初始化知识库（清空数据）

    Zotero 接口:
    GET  /zotero/collections         - 列出所有收藏夹
    GET  /zotero/collections/search - 搜索收藏夹

    Obsidian 接口:
    GET  /obsidian/vaults            - 列出常见 vault 位置
    GET  /obsidian/vaults/{name}    - 获取 vault 信息

    管理接口:
    GET  /admin/tables              - 列出所有向量表
    GET  /admin/tables/{name}        - 获取表统计
    DELETE /admin/tables/{name}      - 删除表

    LanceDB 管理:
    GET  /lance/tables               - 列出所有知识库的 LanceDB 表
    GET  /lance/{kb_id}/stats        - 获取表统计（行数、大小）
    GET  /lance/{kb_id}/schema       - 获取表结构
    GET  /lance/{kb_id}/docs         - 获取文档摘要（按 doc_id 聚合）
    GET  /lance/{kb_id}/nodes        - 查询节点
    GET  /lance/{kb_id}/duplicates   - 查找重复文档（同一源文件多个版本）
    DELETE /lance/{kb_id}/doc_ids    - 按 doc_ids 删除
    DELETE /lance/{kb_id}/source     - 按源文件删除
    DELETE /lance/{kb_id}/nodes      - 按 node_ids 删除
    POST /lance/{kb_id}/export      - 导出到 JSONL
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, Dict, Literal, Any
import markdown

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# 添加项目根目录到 path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from rag.logger import get_logger

logger = get_logger(__name__)

# 导入服务层
from kb_core.services import (
    ObsidianService,
    ZoteroService,
    KnowledgeBaseService,
    SearchService,
)
from kb_core.import_service import ImportApplicationService, ImportRequest
from rag.rag_evaluator import RAGEvaluator, RAGMetrics


# ============== Lifespan 和调度器 ==============

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中...")

    from rag.callbacks import setup_callbacks
    from rag.token_stats_db import init_token_stats_db

    setup_callbacks()
    init_token_stats_db()
    logger.info("Token 监控已初始化")

    logger.info("应用启动完成")
    yield
    logger.info("应用关闭")


# ============== FastAPI 应用 ==============

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
    allow_origins=[
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:37241",
        "http://localhost:37241",
        # 远程 LAN 访问
        "http://100.66.1.2:5173",
        "http://100.66.1.2:37241",
        # 用户 LAN 访问
        "http://192.168.31.207:5173",
        "http://192.168.31.207:37241",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# ============== Exception Handlers (ensure CORS on errors) ==============


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


# ============== 数据模型 ==============


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询")
    top_k: int = Field(5, ge=1, le=100)
    route_mode: Literal["general", "auto"] = Field(
        "general",
        description="路由模式: general(用户选择知识库), auto(自动路由)",
    )
    model_id: Optional[str] = Field(
        None,
        description="使用的LLM模型ID (如 siliconflow/DeepSeek-V3.2, ollama/lfm2.5-instruct)，不填则使用默认模型（Ollama）",
    )
    embed_model_id: Optional[str] = Field(
        None,
        description="使用的 Embedding 模型ID (如 ollama/bge-m3:latest)，不填则使用默认",
    )
    kb_ids: Optional[str] = Field(
        None, description="指定知识库 ID（逗号分隔，route_mode=general 时必填）"
    )
    exclude: Optional[List[str]] = Field(
        None, description="排除的知识库 ID 列表（仅在 route_mode=auto 时有效）"
    )
    use_auto_merging: Optional[bool] = Field(
        None, description="启用 Auto-Merging（合并子节点到父节点）"
    )
    use_reranker: Optional[bool] = Field(
        None, description="启用 Reranker（None=使用配置默认值）"
    )
    retrieval_mode: Literal["vector", "hybrid"] = Field(
        "vector", description="检索模式: vector(向量检索), hybrid(混合搜索)"
    )


class SearchResult(BaseModel):
    text: str
    score: float
    metadata: dict = {}
    kb_id: Optional[str] = None


class QueryRequest(BaseModel):
    query: str = Field(..., description="查询")
    top_k: int = Field(5, ge=1, le=100)
    route_mode: Literal["general", "auto"] = Field(
        "general",
        description="路由模式: general(用户选择知识库), auto(自动路由)",
    )
    retrieval_mode: Literal["vector", "hybrid"] = Field(
        "vector", description="检索模式: vector(向量检索), hybrid(混合搜索)"
    )
    model_id: Optional[str] = Field(
        None,
        description="使用的LLM模型ID (如 siliconflow/DeepSeek-V3.2, ollama/lfm2.5-instruct)，不填则使用默认模型",
    )
    embed_model_id: Optional[str] = Field(
        None,
        description="使用的Embedding模型ID (如 ollama/bge-m3:latest)，不填则使用默认模型",
    )
    llm_mode: Optional[str] = Field(
        None,
        description="LLM 模式 (已废弃，使用 model_id): siliconflow, ollama",
    )
    kb_ids: Optional[str] = Field(
        None, description="指定知识库 ID（逗号分隔，route_mode=general 时必填）"
    )
    exclude: Optional[List[str]] = Field(
        None, description="排除的知识库 ID 列表（仅在 route_mode=auto 时有效）"
    )
    use_hyde: Optional[bool] = Field(
        None, description="启用 HyDE 查询转换（None=使用配置默认值）"
    )
    use_multi_query: Optional[bool] = Field(
        None, description="启用多查询转换（None=使用配置默认值）"
    )
    num_multi_queries: Optional[int] = Field(
        None, description="多查询变体数量（None=使用配置默认值）"
    )
    use_auto_merging: Optional[bool] = Field(
        None, description="启用 Auto-Merging（None=使用配置默认值）"
    )
    use_reranker: Optional[bool] = Field(
        None, description="启用 Reranker（None=使用配置默认值）"
    )
    response_mode: Optional[str] = Field(
        None,
        description="答案生成模式: compact, refine, tree_summarize, simple, no_text, accumulate（None=使用配置默认值）",
    )


class QueryResponse(BaseModel):
    response: str
    sources: List[dict] = []


class EvaluateRequest(BaseModel):
    questions: List[str] = Field(..., description="问题列表")
    ground_truths: List[str] = Field(..., description="标准答案列表")
    top_k: int = Field(5, ge=1, le=100, description="检索返回结果数")


class IngestRequest(BaseModel):
    path: str = Field(..., description="文件路径")
    async_mode: bool = Field(True, description="是否异步处理")
    refresh_topics: bool = Field(False, description="任务完成后是否刷新 topics")


class IngestResponse(BaseModel):
    status: str
    task_id: Optional[str] = None
    message: Optional[str] = None
    files_processed: Optional[int] = None
    nodes_created: Optional[int] = None
    failed: Optional[int] = None
    source: Optional[str] = None


class DangerousOperationRequest(BaseModel):
    """需要输入知识库名称确认的危险操作请求"""

    confirmation_name: str = Field(
        ..., description="输入知识库名称以确认操作（区分大小写）"
    )


class KBInfo(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    source_type: str = "generic"
    status: str = "unknown"
    row_count: Optional[int] = None
    chunk_strategy: Optional[str] = None


class TaskResponse(BaseModel):
    task_id: str
    task_type: Optional[str] = None
    status: str
    kb_id: str
    message: str = ""
    progress: Optional[int] = 0
    current: Optional[int] = None
    total: Optional[int] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    file_progress: Optional[List[Dict[str, Any]]] = None


def _parse_kb_ids_or_raise(kb_ids: Optional[str], route_mode: str) -> List[str]:
    if route_mode != "general":
        raise HTTPException(status_code=400, detail="仅 general 模式支持 kb_ids")
    if not kb_ids:
        raise HTTPException(
            status_code=400,
            detail="route_mode=general 时，kb_ids 为必填参数",
        )
    kb_id_list = [k.strip() for k in kb_ids.split(",") if k.strip()]
    if not kb_id_list:
        raise HTTPException(status_code=400, detail="kb_ids 参数无效")
    return kb_id_list


# ============== 全局事件循环 ==============

_task_loop: Optional[asyncio.AbstractEventLoop] = None
_task_thread: Optional[threading.Thread] = None


def _get_or_create_loop():
    """获取或创建事件循环"""
    global _task_loop, _task_thread

    if _task_loop is None or _task_loop.is_closed():
        _task_loop = asyncio.new_event_loop()
        _task_thread = threading.Thread(
            target=_run_loop, args=(_task_loop,), daemon=True
        )
        _task_thread.start()

    return _task_loop


def _run_loop(loop):
    """运行事件循环"""
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        loop.close()


# ============== 健康检查 ==============


@app.get("/health")
def health():
    """健康检查"""
    return {
        "status": "ok",
        "service": "llamaindex-rag-api",
        "version": "3.1.0",
    }


@app.get("/api-docs", response_class=HTMLResponse)
def api_docs_page(doc: str = None):
    """显示 Markdown 格式的 API 文档页面

    文档列表:
    - /api-docs - 文档首页（所有文档链接）
    - /api-docs?doc=API - API 文档
    - /api-docs?doc=CLI - CLI 使用文档
    - /api-docs?doc=ARCHITECTURE - 架构设计文档
    - /api-docs?doc=QUERY_PARAM_GUIDE - Query 参数设计指南
    """
    docs_dir = Path(__file__).parent / "docs"

    doc_files = {
        "API": "API.md",
        "CLI": "CLI.md",
        "ARCHITECTURE": "ARCHITECTURE.md",
        "QUERY_PARAM_GUIDE": "QUERY_PARAM_GUIDE.md",
        "SEARCH_PARAM_GUIDE": "SEARCH_PARAM_GUIDE.md",
    }

    def render_md_to_html(md_content, title):
        html_content = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "codehilite"],
        )
        return f"""
        <div class="content">
            {html_content}
        </div>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
        <script>hljs.highlightAll();</script>
        """

    common_styles = """
        :root {
            --bg-color: #ffffff;
            --text-color: #333333;
            --code-bg: #f5f5f5;
            --border-color: #dddddd;
            --link-color: #0066cc;
            --header-bg: #2c3e50;
            --header-color: #ffffff;
            --table-header-bg: #f0f0f0;
            --blockquote-border: #4caf50;
            --sidebar-bg: #f8f9fa;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg-color: #1a1a1a;
                --text-color: #e0e0e0;
                --code-bg: #2d2d2d;
                --border-color: #404040;
                --link-color: #66b3ff;
                --header-bg: #2c3e50;
                --table-header-bg: #2d2d2d;
                --sidebar-bg: #252525;
            }
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            background-color: var(--bg-color);
            color: var(--text-color);
        }
        .layout {
            display: flex;
            min-height: 100vh;
        }
        .sidebar {
            width: 280px;
            background-color: var(--sidebar-bg);
            border-right: 1px solid var(--border-color);
            padding: 20px;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }
        .main {
            flex: 1;
            padding: 20px 40px;
            max-width: 1100px;
            margin-left: 280px;
        }
        h1, h2, h3, h4 { margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 600; }
        h1 { font-size: 2.2em; border-bottom: 3px solid var(--header-bg); padding-bottom: 0.3em; }
        h2 { font-size: 1.8em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.2em; }
        a { color: var(--link-color); text-decoration: none; }
        a:hover { text-decoration: underline; }
        code {
            background-color: var(--code-bg);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "SF Mono", Monaco, Consolas, monospace;
            font-size: 0.9em;
        }
        pre {
            background-color: var(--code-bg);
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid var(--border-color);
        }
        pre code { padding: 0; background: none; }
        table { width: 100%; border-collapse: collapse; margin: 1em 0; }
        th, td { border: 1px solid var(--border-color); padding: 10px 12px; text-align: left; }
        th { background-color: var(--table-header-bg); font-weight: 600; }
        blockquote {
            margin: 1em 0;
            padding: 0.5em 1em;
            border-left: 4px solid var(--blockquote-border);
            background-color: var(--code-bg);
        }
        .nav {
            background-color: var(--header-bg);
            color: var(--header-color);
            padding: 15px 20px;
        }
        .nav a { color: var(--header-color); margin-right: 20px; }
        .nav a:hover { text-decoration: underline; }
        .doc-card {
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            transition: box-shadow 0.2s;
        }
        .doc-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .doc-card h3 { margin: 0 0 10px 0; }
        .doc-card p { margin: 0; color: #666; }
        .doc-card .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            margin-right: 8px;
        }
        .badge-api { background: #e3f2fd; color: #1565c0; }
        .badge-cli { background: #e8f5e9; color: #2e7d32; }
        .badge-arch { background: #fff3e0; color: #e65100; }
        .badge-guide { background: #f3e5f5; color: #7b1fa2; }
        .active-doc { font-weight: bold; color: var(--link-color); }
        @media (max-width: 768px) {
            .sidebar { display: none; }
            .main { margin-left: 0; padding: 20px; }
        }
    """

    common_head = f"""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/default.min.css">
    <style>{common_styles}</style>
    """

    sidebar_html = """
    <div class="sidebar">
        <h3 style="margin-top: 0;">📚 文档中心</h3>
        <ul style="list-style: none; padding: 0;">
            <li style="margin-bottom: 8px;">
                <a href="/api-docs" class="%(api_active)s">📖 API 文档</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=CLI" class="%(cli_active)s">💻 CLI 使用指南</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=ARCHITECTURE" class="%(arch_active)s">🏗️ 架构设计</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=QUERY_PARAM_GUIDE" class="%(guide_active)s">🎯 Query 参数指南</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=SEARCH_PARAM_GUIDE" class="%(search_active)s">🔍 Search 参数指南</a>
            </li>
        </ul>
        <hr style="margin: 20px 0; border: none; border-top: 1px solid var(--border-color);">
        <h4>快速链接</h4>
        <ul style="list-style: none; padding: 0; font-size: 0.9em;">
            <li style="margin-bottom: 6px;">📄 <a href="/api-docs?doc=API#检索查询">检索查询 API</a></li>
            <li style="margin-bottom: 6px;">📥 <a href="/api-docs?doc=API#文档导入">文档导入 API</a></li>
            <li style="margin-bottom: 6px;">⚡ <a href="/api-docs?doc=API#任务队列">任务队列 API</a></li>
        </ul>
    </div>
    """

    if doc is None:
        doc_content = """
        <h1>📚 LlamaIndex RAG 文档中心</h1>
        <p style="font-size: 1.1em; color: #666;">欢迎使用 LlamaIndex RAG 文档中心。这里提供了所有相关文档的链接。</p>
        
        <div class="doc-card">
            <span class="badge badge-api">API</span>
            <h3><a href="/api-docs?doc=API">API 完整参考</a></h3>
            <p>FastAPI 所有端点的详细说明，包括请求参数、响应格式、示例。</p>
        </div>
        
        <div class="doc-card">
            <span class="badge badge-guide">🎯 必读</span>
            <h3><a href="/api-docs?doc=QUERY_PARAM_GUIDE">Query 参数设计指南</a></h3>
            <p>客户端 UI 设计必读！详细说明 route_mode、retrieval_mode 及各检索增强参数的适用场景和组合建议。</p>
        </div>
        
        <div class="doc-card">
            <span class="badge badge-guide">🔍 必读</span>
            <h3><a href="/api-docs?doc=SEARCH_PARAM_GUIDE">Search 参数设计指南</a></h3>
            <p>Search 检索的专用指南，说明检索模式、结果排序等参数。</p>
        </div>
        
        <div class="doc-card">
            <span class="badge badge-cli">CLI</span>
            <h3><a href="/api-docs?doc=CLI">CLI 使用指南</a></h3>
            <p>完整的命令行接口文档，包括知识库管理、文档导入、检索查询、任务管理等命令。</p>
        </div>
        
        <div class="doc-card">
            <span class="badge badge-arch">架构</span>
            <h3><a href="/api-docs?doc=ARCHITECTURE">架构设计文档</a></h3>
            <p>系统架构、分层设计、并行处理、资源保护机制、数据库 Schema 等技术细节。</p>
        </div>
        """
        content_html = f"""
        <div class="layout">
            {sidebar_html % {"api_active": "", "cli_active": "", "arch_active": "", "guide_active": "", "search_active": ""}}
            <div class="main">
                {doc_content}
            </div>
        </div>
        """
    elif doc in doc_files:
        docs_path = docs_dir / doc_files[doc]
        if docs_path.exists():
            md_content = docs_path.read_text(encoding="utf-8")
            content_html = render_md_to_html(md_content, doc)

            active_states = {
                "api_active": "",
                "cli_active": "",
                "arch_active": "",
                "guide_active": "",
                "search_active": "",
            }
            if doc == "API":
                active_states["api_active"] = 'class="active-doc"'
            elif doc == "CLI":
                active_states["cli_active"] = 'class="active-doc"'
            elif doc == "ARCHITECTURE":
                active_states["arch_active"] = 'class="active-doc"'
            elif doc == "QUERY_PARAM_GUIDE":
                active_states["guide_active"] = 'class="active-doc"'
            elif doc == "SEARCH_PARAM_GUIDE":
                active_states["search_active"] = 'class="active-doc"'

            content_html = f"""
            <div class="layout">
                {sidebar_html % active_states}
                <div class="main">
                    {content_html}
                </div>
            </div>
            """
        else:
            content_html = f"<h1>文档未找到</h1><p>{doc_files[doc]} 不存在</p>"
    else:
        content_html = f"<h1>文档未找到</h1><p>未知的文档: {doc}</p>"

    html_page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>文档中心 - LlamaIndex RAG API</title>
    {common_head}
</head>
<body>
    {content_html}
</body>
</html>"""
    return html_page


# ============== 任务队列接口 ==============


@app.post("/tasks", response_model=TaskResponse)
def create_task(req: dict):
    """创建任务"""
    from kb_core.task_queue import task_queue

    task_id = task_queue.submit_task(
        task_type=req.get("task_type", "generic"),
        kb_id=req.get("kb_id", ""),
        params=req.get("params", {}),
        source=req.get("source", ""),
    )

    return TaskResponse(
        task_id=task_id,
        status="pending",
        kb_id=req.get("kb_id", ""),
        message="任务已提交",
    )


@app.get("/tasks", response_model=List[TaskResponse])
def list_tasks(kb_id: str = None, status: str = None, limit: int = 50):
    """列出任务"""
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


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str):
    """获取任务详情"""
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


@app.delete("/tasks/{task_id}")
def cancel_task(task_id: str):
    """取消任务"""
    from kb_core.services import TaskService

    try:
        result = TaskService.cancel(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/tasks/{task_id}/pause")
def pause_task(task_id: str):
    """暂停任务"""
    from kb_core.services import TaskService

    try:
        result = TaskService.pause(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: str):
    """恢复任务"""
    from kb_core.services import TaskService

    try:
        result = TaskService.resume(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/tasks/{task_id}/files/{file_id}")
def cancel_file_in_task(task_id: str, file_id: str):
    """取消任务中的单个文件"""
    from kb_core.task_queue import task_queue

    success = task_queue.cancel_file(task_id, file_id)
    if not success:
        raise HTTPException(
            status_code=400, detail="无法取消文件（可能已完成或不存在）"
        )
    return {"message": "文件已取消", "task_id": task_id, "file_id": file_id}


@app.delete("/tasks/{task_id}/delete")
def delete_task(task_id: str, cleanup: bool = False):
    """删除任务（物理删除）

    Args:
        cleanup: 是否清理关联的知识库数据（仅对 failed/cancelled 任务有效）
    """
    from kb_core.services import TaskService

    try:
        return TaskService.delete(task_id, cleanup=cleanup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tasks/pause-all")
def pause_all_tasks(status: str = "running"):
    """暂停所有运行中的任务"""
    from kb_core.services import TaskService

    return TaskService.pause_all(status)


@app.post("/tasks/resume-all")
def resume_all_tasks():
    """恢复所有已暂停的任务"""
    from kb_core.services import TaskService

    return TaskService.resume_all()


@app.delete("/tasks/delete-all")
def delete_all_tasks(status: str = "completed", cleanup: bool = False):
    """删除所有任务"""
    from kb_core.services import TaskService

    return TaskService.delete_all(status, cleanup)


@app.post("/tasks/cleanup")
def cleanup_orphan_tasks():
    """清理孤儿任务（执行进程已终止的任务）"""
    from kb_core.services import TaskService

    return TaskService.cleanup_orphan_tasks()


# ============== 知识库接口 ==============


@app.get("/kbs", response_model=List[KBInfo])
def list_kbs():
    """列出所有知识库"""
    kbs = KnowledgeBaseService.list_all()
    return [KBInfo(**kb) for kb in kbs]


@app.post("/kbs", response_model=KBInfo)
def create_kb(req: KBInfo):
    """创建知识库"""
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


@app.get("/kbs/{kb_id}")
def get_kb_info(kb_id: str):
    """获取知识库详情"""
    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    return info


class KBUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="知识库显示名称")
    description: Optional[str] = Field(None, description="知识库描述")


@app.put("/kbs/{kb_id}")
def update_kb_info(kb_id: str, req: KBUpdateRequest):
    """更新知识库信息"""
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


@app.delete("/kbs/{kb_id}")
def delete_kb(kb_id: str, req: DangerousOperationRequest = Body(...)):
    """删除知识库"""
    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    if req.confirmation_name != kb_id:
        raise HTTPException(status_code=400, detail="知识库名称不匹配，操作已取消")
    if KnowledgeBaseService.delete(kb_id):
        return {"status": "deleted", "kb_id": kb_id}
    raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")


# ============== 模型管理接口 ==============


class VendorInfo(BaseModel):
    id: str
    name: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    is_active: bool = True


class VendorCreateRequest(BaseModel):
    id: str = Field(..., description="供应商ID，如 siliconflow, ollama")
    name: str = Field(..., description="供应商显示名称，如 SiliconFlow, Ollama")
    api_base: Optional[str] = Field(None, description="API端点")
    api_key: Optional[str] = Field(None, description="API密钥（Ollama不需要）")
    is_active: bool = Field(True, description="是否激活")


class ModelInfo(BaseModel):
    id: str
    vendor_id: str
    name: str
    type: str
    is_active: bool = True
    is_default: bool = False
    config: dict = {}


class ModelCreateRequest(BaseModel):
    id: str = Field(
        ...,
        description="模型ID，格式: vendor/model-name (如 siliconflow/DeepSeek-V3.2)",
    )
    vendor_id: str = Field(..., description="供应商ID: siliconflow, ollama")
    name: Optional[str] = Field(None, description="显示名称，不填则从ID提取")
    type: str = Field(..., description="类型: llm, embedding, reranker")
    is_active: bool = Field(True, description="是否激活")
    is_default: bool = Field(False, description="是否设为默认模型")
    config: dict = Field({}, description="其他配置")


# ============== 供应商管理 ==============


@app.get("/vendors", response_model=List[VendorInfo])
def list_vendors():
    """获取所有供应商"""
    from kb_core.database import init_vendor_db

    db = init_vendor_db()
    vendors = db.get_all(active_only=False)
    return [VendorInfo(**v) for v in vendors]


@app.post("/vendors", response_model=VendorInfo)
def create_vendor(req: VendorCreateRequest):
    """创建或更新供应商"""
    from kb_core.database import init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor

    db = init_vendor_db()
    db.upsert(
        vendor_id=req.id,
        name=req.name,
        api_base=req.api_base,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after vendor create: {e}", exc_info=True
        )
    return VendorInfo(**db.get(req.id))


@app.get("/vendors/{vendor_id}", response_model=VendorInfo)
def get_vendor(vendor_id: str):
    """获取指定供应商"""
    from kb_core.database import init_vendor_db

    db = init_vendor_db()
    vendor = db.get(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    return VendorInfo(**vendor)


@app.delete("/vendors/{vendor_id}")
def delete_vendor(vendor_id: str):
    """删除供应商"""
    from kb_core.database import init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor

    db = init_vendor_db()
    if not db.get(vendor_id):
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    db.delete(vendor_id)
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after vendor delete: {e}", exc_info=True
        )
    return {"status": "deleted", "vendor_id": vendor_id}


@app.put("/vendors/{vendor_id}", response_model=VendorInfo)
def update_vendor(vendor_id: str, req: VendorCreateRequest):
    """更新供应商"""
    from kb_core.database import init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor

    db = init_vendor_db()
    if not db.get(vendor_id):
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    db.upsert(
        vendor_id=vendor_id,
        name=req.name,
        api_base=req.api_base,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after vendor update: {e}", exc_info=True
        )
    return VendorInfo(**db.get(vendor_id))


# ============== 模型管理 ==============


@app.get("/models", response_model=List[ModelInfo])
def list_models(type: Optional[str] = None):
    """获取所有模型，或按类型筛选"""
    from rag.config import get_model_registry

    registry = get_model_registry()
    if type:
        models = registry.get_by_type(type)
    else:
        models = registry.list_models()
    return [ModelInfo(**m) for m in models]


@app.post("/models", response_model=ModelInfo)
def create_model(req: ModelCreateRequest):
    """创建或更新模型"""
    from kb_core.database import init_model_db, init_vendor_db
    from kb_processing.parallel_embedding import get_parallel_processor

    vendor_db = init_vendor_db()
    if not vendor_db.get(req.vendor_id):
        vendor_db.upsert(
            vendor_id=req.vendor_id,
            name=req.vendor_id.capitalize(),
            is_active=True,
        )

    model_db = init_model_db()
    name = req.name or req.id.split("/")[-1]
    model_db.upsert(
        model_id=req.id,
        vendor_id=req.vendor_id,
        name=name,
        type=req.type,
        is_active=req.is_active,
        is_default=req.is_default,
        config=req.config,
    )
    if req.is_default:
        model_db.set_default(req.id)
    from rag.config import get_model_registry

    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model create: {e}", exc_info=True
        )
    return ModelInfo(**model_db.get(req.id))


@app.get("/models/{model_id:path}", response_model=ModelInfo)
def get_model(model_id: str):
    """获取指定模型"""
    from rag.config import get_model_registry

    registry = get_model_registry()
    model = registry.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    return ModelInfo(**model)


@app.delete("/models/{model_id:path}")
def delete_model(model_id: str):
    """删除模型"""
    from kb_core.database import init_model_db
    from rag.config import get_model_registry
    from kb_processing.parallel_embedding import get_parallel_processor

    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.delete(model_id)
    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model delete: {e}", exc_info=True
        )
    return {"status": "deleted", "model_id": model_id}


@app.put("/models/{model_id:path}", response_model=ModelInfo)
def update_model(model_id: str, req: ModelCreateRequest):
    """更新模型"""
    from kb_core.database import init_model_db
    from rag.config import get_model_registry
    from kb_processing.parallel_embedding import get_parallel_processor

    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.upsert(
        model_id=model_id,
        vendor_id=req.vendor_id,
        name=req.name or model_id.split("/")[-1],
        type=req.type,
        is_active=req.is_active,
        is_default=req.is_default,
        config=req.config,
    )
    if req.is_default:
        db.set_default(model_id)
    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model update: {e}", exc_info=True
        )
    return ModelInfo(**db.get(model_id))


@app.put("/models/{model_id:path}/default")
def set_default_model(model_id: str):
    """设置默认模型"""
    from kb_core.database import init_model_db
    from rag.config import get_model_registry
    from kb_processing.parallel_embedding import get_parallel_processor

    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.set_default(model_id)
    get_model_registry().reload()
    try:
        get_parallel_processor().refresh_endpoints()
    except Exception as e:
        logger.error(
            f"refresh_endpoints() failed after model set default: {e}", exc_info=True
        )
    return {"status": "success", "model_id": model_id}


# ============== 检索接口 ==============


@app.post("/search", response_model=List[SearchResult])
def search(req: SearchRequest):
    from kb_core.services import QueryRouter

    if req.route_mode == "general" and req.exclude:
        raise HTTPException(
            status_code=400,
            detail="route_mode=general 时不支持 exclude 参数",
        )

    if req.route_mode == "auto":
        result = QueryRouter.search(
            req.query,
            top_k=req.top_k,
            exclude=req.exclude,
            use_auto_merging=req.use_auto_merging,
            use_reranker=req.use_reranker,
            mode="auto",
            model_id=req.model_id,
            embed_model_id=req.embed_model_id,
            retrieval_mode=req.retrieval_mode,
        )
        return [SearchResult(**r) for r in result.get("results", [])]

    kb_id_list = _parse_kb_ids_or_raise(req.kb_ids, req.route_mode)

    results = SearchService.search_multi(
        kb_id_list,
        req.query,
        top_k=req.top_k,
        use_auto_merging=req.use_auto_merging,
        use_reranker=req.use_reranker,
        embed_model_id=req.embed_model_id,
        mode=req.retrieval_mode,
    )
    return [SearchResult(**r) for r in results]


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    from kb_core.services import QueryRouter

    logger.info(
        f"[QUERY] route_mode={req.route_mode}, kb_ids={req.kb_ids}, retrieval_mode={req.retrieval_mode}, query={req.query[:50]}..."
    )

    try:
        if req.route_mode == "general" and req.exclude:
            raise HTTPException(
                status_code=400,
                detail="route_mode=general 时不支持 exclude 参数",
            )

        model_id = req.model_id
        if not model_id and req.llm_mode:
            from rag.config import get_model_registry

            registry = get_model_registry()
            default_llm = registry.get_default("llm")
            if default_llm:
                model_id = default_llm["id"]

        if req.route_mode == "auto":
            result = QueryRouter.query(
                req.query,
                top_k=req.top_k,
                exclude=req.exclude,
                mode="auto",
                use_hyde=req.use_hyde,
                use_multi_query=req.use_multi_query,
                num_multi_queries=req.num_multi_queries,
                use_auto_merging=req.use_auto_merging,
                use_reranker=req.use_reranker,
                response_mode=req.response_mode,
                retrieval_mode=req.retrieval_mode,
                model_id=model_id,
                embed_model_id=req.embed_model_id,
            )
            return QueryResponse(**result)

        kb_id_list = _parse_kb_ids_or_raise(req.kb_ids, req.route_mode)

        result = QueryRouter.query_multi(
            kb_id_list,
            req.query,
            top_k=req.top_k,
            use_hyde=req.use_hyde,
            use_multi_query=req.use_multi_query,
            num_multi_queries=req.num_multi_queries,
            use_auto_merging=req.use_auto_merging,
            use_reranker=req.use_reranker,
            response_mode=req.response_mode,
            retrieval_mode=req.retrieval_mode,
            model_id=model_id,
            embed_model_id=req.embed_model_id,
        )
        return QueryResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[QUERY] Error: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"查询失败: {type(e).__name__}: {str(e)}"
        )


@app.post("/evaluate/{kb_id}")
def evaluate(kb_id: str, req: EvaluateRequest):
    """RAG 性能评估

    对知识库进行 RAG 评估，使用预设的问题和标准答案。

    请求体:
        questions: 问题列表
        ground_truths: 标准答案列表
        top_k: 检索返回结果数

    返回:
        评估结果，包含 faithfulness, answer_relevancy, context_precision, context_recall
    """
    if len(req.questions) != len(req.ground_truths):
        raise HTTPException(
            status_code=400,
            detail="questions 和 ground_truths 数量必须一致",
        )

    contexts, answers = [], []
    for question in req.questions:
        results = SearchService.search(kb_id, question, top_k=req.top_k)
        contexts.append([r["text"] for r in results])
        answers.append("[仅检索模式]")

    evaluator = RAGEvaluator()
    result = evaluator.evaluate(
        questions=req.questions,
        contexts=contexts,
        answers=answers,
        ground_truths=req.ground_truths,
    )

    return result


@app.get("/evaluate/metrics")
def evaluate_metrics():
    """获取 RAG 评估指标说明"""
    return RAGMetrics.get_metrics_info()


# ============== 导入接口 ==============


@app.post("/kbs/{kb_id}/ingest")
def ingest(kb_id: str, req: IngestRequest):
    """通用文件导入

    预验证：检查路径是否存在、是否有可处理的文件
    """
    from pathlib import Path

    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在: {req.path}")

    from kb_processing.generic_processor import GenericImporter

    all_files: List[Path] = []
    if path.is_file():
        all_files.append(path)
    elif path.is_dir():
        importer = GenericImporter()
        all_files = importer.collect_files([path], recursive=True)

    if not all_files:
        raise HTTPException(
            status_code=400,
            detail=f"没有找到可处理的文件: {req.path}",
        )

    if not req.async_mode:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="generic",
                kb_id=kb_id,
                async_mode=False,
                path=req.path,
                refresh_topics=req.refresh_topics,
            )
        )
        return IngestResponse(
            status="completed",
            files_processed=stats.get("files", 0),
            nodes_created=stats.get("nodes", 0),
            failed=stats.get("failed", 0),
            message="同步导入完成",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="generic",
            kb_id=kb_id,
            path=req.path,
            refresh_topics=req.refresh_topics,
            source=req.path,
        )
    )

    task_id = task["task_id"]
    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"导入任务已提交，ID: {task_id}，文件数: {len(all_files)}",
    )


# ============== Zotero 接口 ==============


class ZoteroIngestRequest(BaseModel):
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None
    async_mode: bool = Field(True, description="是否异步处理")
    rebuild: bool = Field(False, description="是否重建")
    refresh_topics: bool = Field(False, description="任务完成后是否刷新 topics")
    chunk_strategy: Optional[str] = Field(
        None, description="分块策略: hierarchical/sentence/semantic"
    )
    chunk_size: Optional[int] = Field(None, description="分块大小")
    hierarchical_chunk_sizes: Optional[List[int]] = Field(
        None, description="hierarchical 模式分层大小列表"
    )


class ZoteroPreviewRequest(BaseModel):
    kb_id: str = Field("default", description="知识库 ID（用于去重检查）")
    item_ids: Optional[List[int]] = Field(None, description="要预览的文献 ID 列表")
    collection_id: Optional[str] = Field(
        None, description="收藏夹 ID（将预览该收藏夹下所有文献）"
    )
    prefix: str = Field("[kb]", description="附件标题前缀标记（默认 [kb]）")
    include_exts: Optional[List[str]] = Field(
        None, description='只包含指定的文件扩展名，如 ["pdf", "docx"]'
    )
    force_ocr: bool = Field(False, description="强制 OCR 重新识别")
    force_md_cache: bool = Field(False, description="强制使用本地 MD 缓存")


class ZoteroPreviewItem(BaseModel):
    item_id: int
    title: str
    creators: List[str] = []
    has_attachment: bool = False
    attachment_path: Optional[str] = None
    attachment_type: Optional[str] = None
    is_scanned_pdf: bool = False
    has_md_cache: bool = False
    is_eligible: bool = True
    ineligible_reason: Optional[str] = None
    is_duplicate: bool = False


class ZoteroPreviewResponse(BaseModel):
    """Zotero 导入预览响应"""

    total_items: int
    eligible_items: int
    ineligible_items: int
    duplicate_items: int
    items: List[ZoteroPreviewItem]
    filtering_rules: List[str] = []


class ObsidianPreviewRequest(BaseModel):
    vault_path: str = Field(..., description="Vault 路径")
    folder_path: Optional[str] = Field(None, description="子文件夹路径")
    prefix: Optional[str] = Field(None, description="文件名前缀筛选")


class ObsidianPreviewItem(BaseModel):
    path: str
    size: int
    relative_path: str


class ObsidianPreviewResponse(BaseModel):
    total_items: int
    eligible_items: int
    filtering_rules: List[str] = []
    items: List[ObsidianPreviewItem]
    warnings: List[str] = []


class FilePreviewRequest(BaseModel):
    paths: List[str] = Field(..., description="文件或目录路径列表")
    include_exts: Optional[List[str]] = Field(None, description="只包含指定的扩展名")
    exclude_exts: Optional[List[str]] = Field(None, description="排除指定的扩展名")


class FilePreviewItem(BaseModel):
    path: str
    name: str
    size: int


class FilePreviewResponse(BaseModel):
    total_items: int
    eligible_items: int
    filtering_rules: List[str] = []
    items: List[FilePreviewItem]
    warnings: List[str] = []


@app.get("/zotero/collections")
def list_zotero_collections():
    """列出 Zotero 收藏夹"""
    collections = ZoteroService.list_collections()
    return {"collections": collections}


@app.get("/zotero/collections/search")
def search_zotero_collections(q: str):
    """搜索 Zotero 收藏夹"""
    results = ZoteroService.search_collections(q)
    return {"results": results}


@app.get("/zotero/collections/{collection_id}/structure")
def get_zotero_collection_structure(collection_id: str):
    """获取收藏夹的层级结构（包含子收藏夹和文献）"""
    result = ZoteroService.get_collection_structure(collection_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/zotero/collections/with-items")
def get_all_collections_with_items():
    """获取所有收藏夹及其直接文献（用于树形展示）"""
    return {"collections": ZoteroService.get_all_collections_with_items()}


@app.post("/zotero/preview", response_model=ZoteroPreviewResponse)
def preview_zotero_import(req: ZoteroPreviewRequest):
    """预览 Zotero 文献导入（应用所有筛选规则）

    检查每个文献是否符合导入条件：
    - 前缀标记过滤（可配置，默认 [kb]）
    - 是否为扫描件 PDF
    - mddocs 缓存是否存在
    - 是否已导入（去重，通过 document 表查询）
    """
    from kb_zotero.processor import ZoteroImporter
    from kb_core.database import init_document_db
    from kb_core.services import KnowledgeBaseService
    from pathlib import Path

    importer = ZoteroImporter()
    mddocs_base = Path("/Volumes/online/llamaindex/mddocs")

    document_db = None
    kb_info = KnowledgeBaseService.get_info(req.kb_id)
    if kb_info and Path(kb_info.get("persist_dir", "")).exists():
        try:
            document_db = init_document_db()
        except Exception:
            pass

    item_ids = list(req.item_ids) if req.item_ids else []

    if req.collection_id and not item_ids:
        try:
            col_id = int(req.collection_id)
            item_ids = importer.get_items_in_collection(col_id, recursive=True)
        except (ValueError, TypeError):
            pass

    prefix = req.prefix or "[kb]"
    include_exts = req.include_exts
    filtering_rules = [
        f"附件标题必须包含 {prefix} 前缀才会被导入",
        "已导入的文献会被跳过（通过 document 表查询）",
    ]
    if include_exts:
        filtering_rules.append(f"只导入扩展名: {', '.join(include_exts)}")

    eligible_items = []
    ineligible_items = []
    duplicate_items = []

    for item_id in item_ids:
        item = importer.get_item(item_id, prefix=prefix)
        if not item:
            continue

        attachment_path = item.file_path

        preview_item = ZoteroPreviewItem(
            item_id=item_id,
            title=item.title,
            creators=item.creators[:3],
            has_attachment=bool(attachment_path),
            attachment_path=attachment_path,
        )

        if not attachment_path:
            preview_item.is_eligible = False
            preview_item.ineligible_reason = f"附件标题不含 {prefix} 标记"
            ineligible_items.append(preview_item)
            continue

        zotero_doc_id = str(item_id)

        if document_db:
            existing_doc = document_db.get_by_zotero_doc_id(req.kb_id, zotero_doc_id)
            if existing_doc:
                preview_item.is_duplicate = True
                preview_item.ineligible_reason = (
                    f"文献已导入（zotero_doc_id: {zotero_doc_id}）"
                )
                duplicate_items.append(preview_item)
                continue

        ext = Path(attachment_path).suffix.lower() if attachment_path else ""
        preview_item.attachment_type = ext.lstrip(".")

        if include_exts and ext.lstrip(".") not in include_exts:
            preview_item.is_eligible = False
            preview_item.ineligible_reason = f"扩展名 {ext.lstrip('.')} 不在筛选范围内"
            ineligible_items.append(preview_item)
            continue

        if ext == ".pdf" and attachment_path:
            pdf_path = Path(attachment_path)
            if pdf_path.exists():
                is_scanned = importer.processor.is_scanned_pdf(str(pdf_path))
                preview_item.is_scanned_pdf = is_scanned

                md_cache_path = mddocs_base / f"{pdf_path.stem}.md"
                preview_item.has_md_cache = (
                    md_cache_path.exists() and md_cache_path.stat().st_size > 100
                )

        preview_item.is_eligible = True
        eligible_items.append(preview_item)

    importer.close()

    return ZoteroPreviewResponse(
        total_items=len(item_ids),
        eligible_items=len(eligible_items),
        ineligible_items=len(ineligible_items),
        duplicate_items=len(duplicate_items),
        items=eligible_items + ineligible_items + duplicate_items,
        filtering_rules=filtering_rules,
    )


@app.post("/obsidian/preview", response_model=ObsidianPreviewResponse)
def preview_obsidian_import(req: ObsidianPreviewRequest):
    from pathlib import Path

    vault = Path(req.vault_path)
    filtering_rules = [
        "只处理 .md 文件",
        "忽略以 _ 开头的目录（Obsidian 约定）",
    ]
    warnings = []

    if not vault.exists():
        return ObsidianPreviewResponse(
            total_items=0,
            eligible_items=0,
            filtering_rules=filtering_rules,
            items=[],
            warnings=[f"Vault 路径不存在: {req.vault_path}"],
        )

    import_dir = vault
    if req.folder_path:
        import_dir = vault / req.folder_path
        if not import_dir.exists():
            return ObsidianPreviewResponse(
                total_items=0,
                eligible_items=0,
                filtering_rules=filtering_rules,
                items=[],
                warnings=[f"文件夹路径不存在: {req.folder_path}"],
            )

    md_files = list(import_dir.rglob("*.md"))
    md_files = [
        f for f in md_files if not any(p.name.startswith("_") for p in f.parents)
    ]

    prefix = req.prefix
    if prefix:
        md_files = [f for f in md_files if f.name.startswith(prefix)]
        filtering_rules.append(f"只导入文件名前缀为 '{prefix}' 的文件")

    total_items = len(md_files)
    filtering_rules.append(f"共找到 {total_items} 个 .md 文件")

    preview_items = [
        ObsidianPreviewItem(
            path=str(f),
            relative_path=str(f.relative_to(import_dir)),
            size=f.stat().st_size,
        )
        for f in md_files[:50]
    ]

    return ObsidianPreviewResponse(
        total_items=total_items,
        eligible_items=total_items,
        filtering_rules=filtering_rules,
        items=preview_items,
        warnings=warnings,
    )


@app.post("/file/preview", response_model=FilePreviewResponse)
def preview_file_import(req: FilePreviewRequest):
    from pathlib import Path
    from kb_processing.generic_processor import GenericImporter

    importer = GenericImporter()
    filtering_rules = []
    warnings = []
    all_files: List[Path] = []

    for path_str in req.paths:
        p = Path(path_str)
        if not p.exists():
            warnings.append(f"路径不存在: {path_str}")
            continue
        if p.is_file():
            all_files.append(p)
        elif p.is_dir():
            files = importer.collect_files(
                [p],
                include_exts=req.include_exts or [],
                exclude_exts=req.exclude_exts or [],
            )
            all_files.extend(files)

    total_items = len(all_files)

    if req.include_exts:
        filtering_rules.append(f"只处理扩展名: {', '.join(req.include_exts)}")
    if req.exclude_exts:
        filtering_rules.append(f"排除扩展名: {', '.join(req.exclude_exts)}")
    if not req.include_exts and not req.exclude_exts:
        filtering_rules.append("使用默认扩展名: pdf, docx, xlsx, md, txt 等")

    filtering_rules.append(f"共找到 {total_items} 个文件")

    preview_items = [
        FilePreviewItem(
            path=str(f),
            name=f.name,
            size=f.stat().st_size,
        )
        for f in all_files[:50]
    ]

    return FilePreviewResponse(
        total_items=total_items,
        eligible_items=total_items,
        filtering_rules=filtering_rules,
        items=preview_items,
        warnings=warnings,
    )


@app.post("/kbs/{kb_id}/ingest/zotero", response_model=IngestResponse)
def ingest_zotero(kb_id: str, req: ZoteroIngestRequest):
    """Zotero 收藏夹导入"""
    from kb_zotero.processor import ZoteroImporter

    # 先验证收藏夹是否存在
    importer = ZoteroImporter()
    collection_id = req.collection_id
    collection_name = req.collection_name or "Unknown"

    if not collection_id and req.collection_name:
        result = importer.get_collection_by_name(req.collection_name)
        if result and "collectionID" in result:
            collection_id = result["collectionID"]
            collection_name = result.get("collectionName", collection_name)
        elif result and "multiple" in result:
            importer.close()
            raise HTTPException(
                status_code=400,
                detail="名称模糊，存在多个匹配，请用 collection_id 精确指定",
            )
        else:
            importer.close()
            raise HTTPException(
                status_code=400, detail=f"未找到收藏夹: {req.collection_name}"
            )

    importer.close()

    if not req.async_mode:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="zotero",
                kb_id=kb_id,
                async_mode=False,
                collection_id=collection_id,
                collection_name=collection_name,
                rebuild=req.rebuild,
                refresh_topics=req.refresh_topics,
                chunk_strategy=req.chunk_strategy,
                chunk_size=req.chunk_size,
                hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
            )
        )
        return IngestResponse(
            status="completed",
            files_processed=stats.get("items", 0),
            nodes_created=stats.get("nodes", 0),
            failed=stats.get("failed", 0),
            message="同步导入完成",
            source="zotero",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="zotero",
            kb_id=kb_id,
            collection_id=collection_id,
            collection_name=collection_name,
            rebuild=req.rebuild,
            refresh_topics=req.refresh_topics,
            source=f"zotero:{collection_name}",
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
        )
    )
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"Zotero {collection_name} 导入任务已提交，ID: {task_id}",
        source="zotero",
    )


# ============== Obsidian 接口 ==============


class ObsidianIngestRequest(BaseModel):
    vault_path: str = Field(
        Path.home() / "Documents" / "Obsidian Vault", description="Vault 路径"
    )
    folder_path: Optional[str] = Field(None, description="子文件夹路径")
    recursive: bool = Field(True, description="递归处理子文件夹")
    async_mode: bool = Field(True, description="是否异步处理")
    exclude_patterns: Optional[List[str]] = Field(None, description="排除模式")
    refresh_topics: bool = Field(False, description="任务完成后是否刷新 topics")


class SelectiveImportRequest(BaseModel):
    source_type: str = Field(..., description="来源类型: zotero, obsidian, files")
    items: List[Dict[str, Any]] = Field(..., description="要导入的项目列表")
    async_mode: bool = Field(True, description="是否异步处理")
    refresh_topics: bool = Field(False, description="任务完成后是否刷新 topics")
    prefix: str = Field("[kb]", description="Zotero 附件标题前缀标记")


class FilesImportRequest(BaseModel):
    paths: List[str] = Field(..., description="文件路径列表")
    async_mode: bool = Field(True, description="是否异步处理")
    refresh_topics: bool = Field(False, description="任务完成后是否刷新 topics")


@app.get("/obsidian/vaults")
def list_obsidian_vaults():
    """列出常见的 Obsidian vault 位置"""
    vaults = ObsidianService.get_vaults()
    return {"vaults": vaults}


@app.get("/obsidian/vaults/{vault_name}")
def get_obsidian_vault(vault_name: str):
    """获取 Obsidian vault 信息"""
    info = ObsidianService.get_vault_info(vault_name)
    if not info:
        raise HTTPException(status_code=404, detail="Vault not found")
    return info


@app.get("/obsidian/vaults/{vault_name}/structure")
def get_obsidian_vault_structure(vault_name: str, folder_path: Optional[str] = None):
    """获取 Obsidian vault 指定文件夹的层级结构"""
    result = ObsidianService.get_vault_structure(vault_name, folder_path)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/obsidian/vaults/{vault_name}/tree")
def get_obsidian_vault_tree(vault_name: str):
    """获取 Obsidian vault 的完整树形结构"""
    result = ObsidianService.get_vault_tree(vault_name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/kbs/{kb_id}/ingest/obsidian", response_model=IngestResponse)
def ingest_obsidian(kb_id: str, req: ObsidianIngestRequest):
    """Obsidian vault 导入"""
    vault_path = Path(req.vault_path)
    if not vault_path.exists():
        raise HTTPException(
            status_code=400, detail=f"Vault 路径不存在: {req.vault_path}"
        )

    import_dir = vault_path
    if req.folder_path:
        import_dir = vault_path / req.folder_path
        if not import_dir.exists():
            raise HTTPException(
                status_code=400, detail=f"文件夹路径不存在: {req.folder_path}"
            )

    if not req.async_mode:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="obsidian",
                kb_id=kb_id,
                async_mode=False,
                vault_path=str(vault_path),
                folder_path=req.folder_path,
                recursive=req.recursive,
                exclude_patterns=req.exclude_patterns,
                refresh_topics=req.refresh_topics,
            )
        )
        return IngestResponse(
            status="completed",
            files_processed=stats.get("files", 0),
            nodes_created=stats.get("nodes", 0),
            failed=stats.get("failed", 0),
            message="同步导入完成",
            source="obsidian",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="obsidian",
            kb_id=kb_id,
            vault_path=str(vault_path),
            folder_path=req.folder_path,
            recursive=req.recursive,
            exclude_patterns=req.exclude_patterns,
            refresh_topics=req.refresh_topics,
            source=f"obsidian:{import_dir.name}",
        )
    )
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"Obsidian {import_dir.name} 导入任务已提交，ID: {task_id}",
        source="obsidian",
    )


@app.post("/kbs/{kb_id}/ingest/selective", response_model=IngestResponse)
def ingest_selective(kb_id: str, req: SelectiveImportRequest):
    """选择性导入 - 导入指定的文献/笔记/文件"""
    from kb_core.import_service import SelectiveImportItem

    items = [
        SelectiveImportItem(
            type=item.get("type", ""),
            id=item.get("id"),
            path=item.get("path"),
            options=item.get("options", {}),
        )
        for item in req.items
    ]

    from kb_core.import_service import SelectiveImportRequest as ServiceSelectiveRequest

    service_req = ServiceSelectiveRequest(
        source_type=req.source_type,
        items=items,
        async_mode=req.async_mode,
        refresh_topics=req.refresh_topics,
        prefix=req.prefix,
    )

    task = ImportApplicationService.submit_selective_import(kb_id, service_req)
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"选择性导入任务已提交，ID: {task_id}，项目数: {len(items)}",
        source=req.source_type,
    )


@app.post("/kbs/{kb_id}/ingest/files", response_model=IngestResponse)
def ingest_files(kb_id: str, req: FilesImportRequest):
    """文件选择器导入 - 导入通过原生文件选择器选择的文件"""
    validated_paths = []
    for path_str in req.paths:
        p = Path(path_str)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"文件不存在: {path_str}")
        validated_paths.append(str(p))

    if not validated_paths:
        raise HTTPException(status_code=400, detail="没有提供有效的文件路径")

    if not req.async_mode:
        from kb_core.services import GenericService

        merged = {"files": 0, "nodes": 0, "failed": 0}
        for path in validated_paths:
            try:
                stats = GenericService.import_file(
                    kb_id=kb_id,
                    path=path,
                    refresh_topics=False,
                )
                merged["files"] += stats.get("files", 0)
                merged["nodes"] += stats.get("nodes", 0)
                merged["failed"] += stats.get("failed", 0)
            except Exception as e:
                merged["failed"] += 1
                logger.error(f"导入文件失败 {path}: {e}")

        from kb_core.services import KnowledgeBaseService

        if req.refresh_topics and merged["files"] > 0:
            KnowledgeBaseService.refresh_topics(kb_id, has_new_docs=True)

        return IngestResponse(
            status="completed",
            files_processed=merged.get("files", 0),
            nodes_created=merged.get("nodes", 0),
            failed=merged.get("failed", 0),
            message="同步导入完成",
            source="files",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="generic",
            kb_id=kb_id,
            paths=validated_paths,
            refresh_topics=req.refresh_topics,
            source=f"files:{len(validated_paths)}files",
        )
    )
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"文件导入任务已提交，ID: {task_id}，文件数: {len(validated_paths)}",
        source="files",
    )


@app.get("/kbs/{kb_id}/topics")
def get_kb_topics(kb_id: str):
    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")
    topics = KnowledgeBaseService.get_topics(kb_id)
    return {
        "kb_id": kb_id,
        "topics": topics,
        "topic_count": len(topics),
    }


class RefreshTopicsRequest(BaseModel):
    has_new_docs: bool = Field(True, description="是否按有新文档方式刷新 topics")


@app.post("/kbs/{kb_id}/topics/refresh")
def refresh_kb_topics(kb_id: str, req: RefreshTopicsRequest):
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


# ============== 知识库一致性校验与修复 ==============


class RepairMode(str):
    SYNC = "sync"
    REBUILD = "rebuild"
    DRY = "dry"


@app.get("/kbs/{kb_id}/consistency")
def check_consistency(kb_id: str):
    """统一的知识库一致性检查"""
    from kb_core.services import ConsistencyService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    result = ConsistencyService.check(kb_id)
    return result


@app.post("/kbs/{kb_id}/consistency/repair")
def repair_consistency(kb_id: str):
    """修复知识库一致性（修正文档统计）"""
    from kb_core.services import ConsistencyService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    result = ConsistencyService.repair(kb_id)
    return result


@app.post("/consistency/repair-all")
def repair_all_consistency():
    """修复所有知识库的一致性"""
    from kb_core.services import ConsistencyService

    result = ConsistencyService.repair_all()
    return result


@app.get("/kbs/{kb_id}/consistency/doc-stats")
def get_doc_embedding_stats(kb_id: str):
    """获取每个文档的向量统计（实际检查 LanceDB）"""
    from kb_core.services import ConsistencyService

    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库不存在: {kb_id}")

    result = ConsistencyService.get_doc_embedding_stats(kb_id)
    return {
        "kb_id": kb_id,
        "docs": result,
    }


@app.post("/kbs/{kb_id}/consistency/check-and-mark-failed")
def check_and_mark_failed_chunks(kb_id: str, limit: int = 200000):
    """提交检查并标记缺失向量任务到任务调度器"""
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


# ============== Obsidian 全库分类导入 ==============


@app.get("/obsidian/mappings")
def list_obsidian_mappings():
    """列出 Obsidian 知识库映射配置"""
    from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

    return {
        "mappings": [
            {
                "kb_id": m.kb_id,
                "name": m.name,
                "folders": m.folders,
                "description": m.description,
            }
            for m in OBSIDIAN_KB_MAPPINGS
        ]
    }


@app.post("/obsidian/import-all")
def import_obsidian_all():
    """Obsidian 全库分类导入"""
    from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS
    from kb_core.registry import get_vault_root

    task_ids = []
    vault_root = get_vault_root()

    for mapping in OBSIDIAN_KB_MAPPINGS:
        if not mapping.folders:
            continue

        for folder in mapping.folders:
            task = ImportApplicationService.submit_task(
                ImportRequest(
                    kind="obsidian",
                    kb_id=mapping.kb_id,
                    vault_path=str(vault_root),
                    folder_path=folder,
                    recursive=True,
                    refresh_topics=True,
                    source=f"obsidian:{folder}",
                )
            )
            task_id = task["task_id"]

            task_ids.append(
                {
                    "kb_id": mapping.kb_id,
                    "folder": folder,
                    "task_id": task_id,
                }
            )

    return {
        "status": "pending",
        "message": f"已提交 {len(task_ids)} 个文件夹导入任务",
        "tasks": task_ids,
    }


# ============== 分类规则管理 ==============


@app.get("/category/rules")
def list_category_rules():
    """列出所有分类规则"""
    from kb_core.database import init_category_rule_db

    rule_db = init_category_rule_db()
    rules = rule_db.get_all_rules()

    return {
        "rules": rules,
        "total": len(rules),
    }


@app.post("/category/rules/sync")
def sync_category_rules():
    """同步分类规则到数据库"""
    from kb_obsidian.config import seed_mappings_to_db

    count = seed_mappings_to_db()

    return {
        "status": "success",
        "message": f"已同步 {count} 条分类规则到数据库",
    }


@app.post("/category/classify")
def classify_folder_llm(
    folder_path: str = "",
    folder_description: str = "",
    use_llm: bool = True,
    request: Optional[Dict] = None,
):
    """
    使用规则或 LLM 分类新文件夹

    Args:
        folder_path: 文件夹路径
        folder_description: 文件夹描述（可选，用于 LLM 分类）
        use_llm: 是否使用 LLM（True=LLM分类, False=仅规则匹配）
    """
    # 支持 JSON body
    if request is not None:
        folder_path = request.get("folder_path", folder_path)
        folder_description = request.get("folder_description", folder_description)
        use_llm = request.get("use_llm", use_llm)

    if not folder_path:
        return {"error": "folder_path is required"}
    from kb_obsidian.config import find_kb_by_path
    from kb_analysis.category_classifier import CategoryClassifier

    # 1. 先用规则匹配
    matched_kbs = find_kb_by_path(folder_path)

    if matched_kbs and not use_llm:
        return {
            "kb_id": matched_kbs[0],
            "matched_by": "rule",
            "confidence": 1.0,
            "reason": f"文件夹路径匹配: {folder_path}",
        }

    # 2. 如果规则没匹配或要求使用 LLM
    if use_llm:
        try:
            classifier = CategoryClassifier()
            result = classifier.classify_folder_llm(
                folder_path=folder_path,
                folder_description=folder_description,
            )

            return {
                "kb_id": result["kb_id"],
                "matched_by": "llm",
                "confidence": result["confidence"],
                "reason": result["reason"],
                "alternatives": matched_kbs if matched_kbs else None,
            }
        except Exception as e:
            return {
                "error": f"LLM 分类失败: {str(e)}",
                "alternatives": matched_kbs,
            }

    return {
        "kb_id": None,
        "matched_by": "none",
        "confidence": 0.0,
        "reason": "未找到匹配的知识库",
        "suggestion": "请手动指定知识库或使用 LLM 分类",
    }


@app.post("/category/rules/add")
def add_category_rule(
    kb_id: str,
    rule_type: str,  # "folder_path" 或 "tag"
    pattern: str,
    description: str = "",
    priority: int = 0,
):
    """添加分类规则"""
    from kb_core.database import init_category_rule_db

    rule_db = init_category_rule_db()
    success = rule_db.add_rule(
        kb_id=kb_id,
        rule_type=rule_type,
        pattern=pattern,
        description=description,
        priority=priority,
    )

    return {
        "status": "success" if success else "error",
        "message": f"规则添加{'成功' if success else '失败'}",
    }


@app.post("/kbs/{kb_id}/initialize")
def initialize_kb(
    kb_id: str, req: DangerousOperationRequest = Body(...), async_mode: bool = True
):
    """初始化知识库（清空所有数据）"""
    from kb_core.task_queue import task_queue
    from kb_core.task_executor import task_executor

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


# ============== 管理接口 ==============


@app.get("/admin/tables")
def list_tables():
    """列出所有向量表"""
    from pathlib import Path

    base = Path("/Volumes/online/llamaindex")
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


@app.get("/admin/tables/{kb_id}")
def get_table_info(kb_id: str):
    """获取表统计"""
    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")
    return info


@app.delete("/admin/tables/{kb_id}")
def delete_table(kb_id: str):
    """删除表"""
    if KnowledgeBaseService.delete(kb_id):
        return {"status": "deleted", "kb_id": kb_id}
    raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")


@app.post("/admin/restart-scheduler")
def restart_scheduler():
    """
    重启任务调度器（统一调度器管理）

    使用 SchedulerStarter 确保调度器作为独立进程运行，
    与 CLI admin restart-scheduler 使用相同的机制。
    """
    from kb_core.task_scheduler import SchedulerStarter, is_scheduler_running, get_scheduler_pid_file

    pid_file = get_scheduler_pid_file()

    # 如果调度器正在运行，先停止它
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

    # 确保调度器启动（使用与 CLI 相同的机制）
    SchedulerStarter.ensure_scheduler_running(wait_seconds=5.0)

    return {"status": "restarting", "message": "调度器正在重启..."}


@app.post("/admin/restart-api")
def restart_api():
    """重启 API 服务（使用 SIGTERM 信号触发外部管理器重启）"""
    import os
    import signal
    import sys
    import time
    from pathlib import Path

    PROJECT_ROOT = Path(__file__).resolve().parent
    pid_file = PROJECT_ROOT / ".api.pid"
    restart_flag = PROJECT_ROOT / ".api_restart_required"

    restart_flag.write_text(str(os.getpid()))
    logger.info(f"重启标记已写入 PID: {os.getpid()}")

    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except OSError:
        pass

    return {"status": "restarting", "message": "API 服务正在重启..."}


@app.post("/admin/reload-config")
def reload_config():
    """重新加载配置（使部分设置生效）"""
    from rag.config import get_model_registry, get_settings

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


# ============== 文档管理接口 ==============


class DocumentResponse(BaseModel):
    id: str
    kb_id: str
    source_file: str
    source_path: str
    file_hash: str
    zotero_doc_id: Optional[str] = None
    file_size: int
    mime_type: str
    chunk_count: int
    total_chars: int
    metadata: Dict[str, Any]
    created_at: float
    updated_at: float


class ChunkResponse(BaseModel):
    id: str
    doc_id: str
    kb_id: str
    text: str
    text_length: int
    chunk_index: int
    parent_chunk_id: Optional[str]
    hierarchy_level: int
    metadata: Dict[str, Any]
    embedding_generated: bool
    created_at: float
    updated_at: float


@app.get("/kbs/{kb_id}/documents", response_model=List[DocumentResponse])
def list_documents(kb_id: str):
    """获取知识库的所有文档"""
    from kb_core.database import init_document_db

    docs = init_document_db().get_by_kb(kb_id)
    return docs


@app.get("/kbs/{kb_id}/documents/{doc_id}", response_model=DocumentResponse)
def get_document(kb_id: str, doc_id: str):
    """获取文档详情"""
    from kb_core.database import init_document_db

    doc = init_document_db().get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    if doc["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"文档不属于知识库 {kb_id}")
    return doc


@app.delete("/kbs/{kb_id}/documents/{doc_id}")
def delete_document(kb_id: str, doc_id: str):
    """删除文档及其所有分块（级联删除 LanceDB 和 Dedup）"""
    from kb_core.document_chunk_service import get_document_chunk_service
    from kb_core.registry import registry

    kb = registry.get(kb_id)
    persist_dir = kb.persist_dir if kb else None

    service = get_document_chunk_service(kb_id=kb_id, persist_dir=persist_dir)
    result = service.delete_document_cascade(doc_id, delete_lance=True)

    if result.get("documents", 0) == 0:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")

    return {"status": "deleted", "doc_id": doc_id, "result": result}


@app.get("/kbs/{kb_id}/documents/{doc_id}/chunks")
def list_document_chunks(
    kb_id: str,
    doc_id: str,
    page: int = 1,
    page_size: int = 20,
    embedding_status: int = None,
):
    """获取文档的分块（分页）

    Args:
        embedding_status: 可选，按 embedding 状态过滤 (0=pending, 1=success, 2=failed)
    """
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


@app.get("/kbs/{kb_id}/chunks/failed")
def list_failed_chunks(kb_id: str, limit: int = 1000):
    """获取所有 embedding 失败的 chunks"""
    from kb_core.database import init_chunk_db

    chunk_db = init_chunk_db()
    failed_chunks = chunk_db.get_failed_chunks(kb_id, limit=limit)
    stats = chunk_db.get_embedding_stats(kb_id)
    return {
        "chunks": failed_chunks,
        "total": len(failed_chunks),
        "stats": stats,
    }


@app.get("/kbs/{kb_id}/chunks/{chunk_id}", response_model=ChunkResponse)
def get_chunk(kb_id: str, chunk_id: str):
    """获取分块详情"""
    from kb_core.database import init_chunk_db

    chunk = init_chunk_db().get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")
    return chunk


@app.put("/kbs/{kb_id}/chunks/{chunk_id}", response_model=ChunkResponse)
def update_chunk_text(kb_id: str, chunk_id: str, req: Dict[str, str]):
    """更新分块文本内容"""
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


@app.post("/kbs/{kb_id}/chunks/{chunk_id}/reembed")
def reembed_chunk(kb_id: str, chunk_id: str):
    """重新生成分块的 embedding"""
    from kb_core.database import init_chunk_db
    from kb_storage.lance_crud import LanceCRUDService
    from kb_processing.parallel_embedding import get_parallel_processor

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
            # Compensation: delete vector from LanceDB since DB update failed
            try:
                LanceCRUDService.delete_by_chunk_ids(kb_id, [chunk_id])
            except Exception:
                pass  # Best effort compensation
            raise Exception(f"DB update failed after vector write: {mark_err}")
        return {
            "status": "success",
            "chunk_id": chunk_id,
            "message": "embedding 已重新生成",
        }
    except Exception as e:
        chunk_db.mark_failed_bulk([chunk_id])
        return {"status": "error", "chunk_id": chunk_id, "message": str(e)}


@app.post("/kbs/{kb_id}/chunks/revector")
def submit_revector_task(
    kb_id: str,
    include_pending: bool = True,
    include_failed: bool = True,
    include_embedded: bool = False,
    batch_size: int = 100,
    limit: int = 50000,
):
    """提交重新向量化任务到任务调度器（处理 pending、failed 和 orphaned success chunks）"""
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


@app.delete("/kbs/{kb_id}/chunks/{chunk_id}")
def delete_chunk(kb_id: str, chunk_id: str, cascade: bool = True):
    """删除单个分块及其关联数据

    Args:
        kb_id: 知识库 ID
        chunk_id: 分块 ID
        cascade: 是否级联删除子分块，默认为 True
    """
    from kb_core.database import init_chunk_db

    chunk_db = init_chunk_db()
    chunk = chunk_db.get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")

    from kb_core.document_chunk_service import get_document_chunk_service

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


@app.get("/kbs/{kb_id}/chunks/{chunk_id}/children")
def get_chunk_children(kb_id: str, chunk_id: str):
    """获取分块的子分块列表"""
    from kb_core.database import init_chunk_db

    chunk_db = init_chunk_db()
    chunk = chunk_db.get(chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"分块 {chunk_id} 不存在")
    if chunk["kb_id"] != kb_id:
        raise HTTPException(status_code=404, detail=f"分块不属于知识库 {kb_id}")

    from kb_core.document_chunk_service import get_document_chunk_service

    service = get_document_chunk_service(kb_id)
    children = service.get_chunk_children(chunk_id)
    return {"children": children, "count": len(children)}


@app.get("/lance/tables")
def lance_list_tables():
    """列出所有知识库的 LanceDB 表"""
    from kb_storage.lance_crud import LanceCRUDService

    return {"tables": LanceCRUDService.list_all_tables()}


@app.get("/lance/{kb_id}/stats")
def lance_get_stats(kb_id: str, table_name: Optional[str] = None):
    """获取 LanceDB 表统计信息"""
    from kb_storage.lance_crud import LanceCRUDService

    try:
        stats = LanceCRUDService.get_table_stats(kb_id, table_name)
        return asdict(stats)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/lance/{kb_id}/schema")
def lance_get_schema(kb_id: str, table_name: Optional[str] = None):
    """获取 LanceDB 表结构"""
    from kb_storage.lance_crud import LanceCRUDService

    try:
        return LanceCRUDService.get_schema(kb_id, table_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/lance/{kb_id}/docs")
def lance_get_doc_summary(kb_id: str, table_name: Optional[str] = None):
    """获取文档摘要（按 doc_id 聚合）"""
    from kb_storage.lance_crud import LanceCRUDService

    try:
        docs = LanceCRUDService.get_doc_summary(kb_id, table_name)
        return {"docs": [asdict(d) for d in docs]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/lance/{kb_id}/nodes")
def lance_query_nodes(
    kb_id: str,
    table_name: Optional[str] = None,
    doc_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """查询节点"""
    from kb_storage.lance_crud import LanceCRUDService

    try:
        nodes = LanceCRUDService.query_nodes(kb_id, table_name, doc_id, limit, offset)
        return {"nodes": [asdict(n) for n in nodes]}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/lance/{kb_id}/duplicates")
def lance_find_duplicates(kb_id: str, table_name: Optional[str] = None):
    """查找重复的源文件（同一路径有多个 doc_id）"""
    from kb_storage.lance_crud import LanceCRUDService

    try:
        duplicates = LanceCRUDService.find_duplicate_sources(kb_id, table_name)
        return {"duplicates": duplicates, "count": len(duplicates)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/lance/{kb_id}/doc_ids")
def lance_delete_by_doc_ids(kb_id: str, doc_ids: str, table_name: Optional[str] = None):
    """按 doc_id 删除节点

    Args:
        kb_id: 知识库 ID
        doc_ids: 逗号分隔的 doc_id 列表
        table_name: 表名
    """
    from kb_storage.lance_crud import LanceCRUDService

    doc_id_list = [d.strip() for d in doc_ids.split(",") if d.strip()]
    if not doc_id_list:
        raise HTTPException(status_code=400, detail="doc_ids 不能为空")
    try:
        deleted = LanceCRUDService.delete_by_doc_ids(kb_id, doc_id_list, table_name)
        return {"deleted": deleted, "doc_ids": doc_id_list}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/lance/{kb_id}/source")
def lance_delete_by_source(kb_id: str, source: str, table_name: Optional[str] = None):
    """按源文件路径删除节点

    Args:
        kb_id: 知识库 ID
        source: 源文件路径或文件名
        table_name: 表名
    """
    from kb_storage.lance_crud import LanceCRUDService

    if not source:
        raise HTTPException(status_code=400, detail="source 不能为空")
    try:
        deleted = LanceCRUDService.delete_by_source_file(kb_id, source, table_name)
        return {"deleted": deleted, "source": source}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/lance/{kb_id}/nodes")
def lance_delete_by_nodes(kb_id: str, node_ids: str, table_name: Optional[str] = None):
    """按节点 ID 删除

    Args:
        kb_id: 知识库 ID
        node_ids: 逗号分隔的节点 ID 列表
        table_name: 表名
    """
    from kb_storage.lance_crud import LanceCRUDService

    node_id_list = [n.strip() for n in node_ids.split(",") if n.strip()]
    if not node_id_list:
        raise HTTPException(status_code=400, detail="node_ids 不能为空")
    try:
        deleted = LanceCRUDService.delete_by_node_ids(kb_id, node_id_list, table_name)
        return {"deleted": deleted, "node_ids": node_id_list}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/lance/{kb_id}/export")
def lance_export(kb_id: str, output_path: str, table_name: Optional[str] = None):
    """导出数据到 JSONL 文件

    Args:
        kb_id: 知识库 ID
        output_path: 输出文件路径
        table_name: 表名
    """
    from kb_storage.lance_crud import LanceCRUDService

    try:
        count = LanceCRUDService.export_to_jsonl(kb_id, output_path, table_name)
        return {"exported": count, "output_path": output_path}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")


# ============== WebSocket 接口 ==============


@app.websocket("/ws/tasks")
async def ws_tasks(websocket):
    """WebSocket 任务状态推送"""
    from kb_core.websocket_manager import ws_manager

    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.debug(f"WebSocket 连接关闭: {e}")
    finally:
        await ws_manager.disconnect(websocket)


@app.websocket("/ws")
async def websocket_endpoint(websocket):
    """通用 WebSocket"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"收到: {data}")
    except Exception as e:
        logger.debug(f"WebSocket 连接关闭: {e}")


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    kb_id: str
    history: List[dict]


class ChatHistoryRequest(BaseModel):
    session_id: str
    limit: int = 10


@app.post("/chat/{kb_id}", response_model=ChatResponse)
def chat(kb_id: str, req: ChatRequest):
    from rag.chat_engine import get_chat_service
    from kb_core.services import SearchService

    chat_service = get_chat_service()

    def query_func(query: str) -> str:
        result = SearchService.query(
            kb_id=kb_id,
            query=query,
            top_k=5,
        )
        return result.get("response", "")

    session_id = req.session_id or f"chat_{kb_id}"

    result = chat_service.chat(
        session_id=session_id,
        message=req.message,
        kb_id=kb_id,
        query_func=query_func,
    )

    return ChatResponse(**result)


@app.get("/chat/{kb_id}/sessions")
def list_chat_sessions(kb_id: str):
    from rag.chat_engine import get_chat_service

    chat_service = get_chat_service()
    sessions = chat_service._chat_store.list_sessions(kb_id=kb_id)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "message_count": len(s.messages),
            }
            for s in sessions
        ]
    }


@app.get("/chat/{kb_id}/history/{session_id}")
def get_chat_history(kb_id: str, session_id: str, limit: int = 10):
    from rag.chat_engine import get_chat_service

    chat_service = get_chat_service()
    history = chat_service.get_session_history(session_id, limit)
    return {"session_id": session_id, "history": history}


@app.delete("/chat/{kb_id}/sessions/{session_id}")
def delete_chat_session(kb_id: str, session_id: str):
    from rag.chat_engine import get_chat_service

    chat_service = get_chat_service()
    success = chat_service.delete_session(session_id)
    return {"deleted": success, "session_id": session_id}


@app.get("/observability/stats")
def get_observability_stats(
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
):
    from rag.callbacks import setup_callbacks
    from rag.token_stats_db import get_token_stats_db

    setup_callbacks()

    db = get_token_stats_db()
    vendor_stats = db.get_stats_by_vendor(start_date, end_date)
    total_stats = db.get_total_stats(start_date, end_date)

    return {
        "vendor_stats": vendor_stats,
        "total_calls": total_stats.get("total_calls", 0),
        "total_tokens": total_stats.get("total_tokens", 0),
        "total_prompt_tokens": total_stats.get("total_prompt_tokens", 0),
        "total_completion_tokens": total_stats.get("total_completion_tokens", 0),
        "total_errors": total_stats.get("total_errors", 0),
        "start_date": start_date,
        "end_date": end_date,
    }


@app.post("/observability/reset")
def reset_observability():
    from rag.callbacks import (
        reset_callbacks,
        setup_callbacks,
        reset_model_call_stats,
    )

    setup_callbacks()
    reset_callbacks()
    reset_model_call_stats()
    return {"status": "reset"}


@app.get("/observability/traces")
def get_traces(
    limit: int = Query(100, description="返回条数"),
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
):
    from rag.callbacks import setup_callbacks, get_rag_stats
    from rag.token_stats_db import get_token_stats_db

    setup_callbacks()

    if start_date or end_date:
        db = get_token_stats_db()
        traces = db.get_trace_events(start_date, end_date, limit)
        return {
            "traces": traces,
            "total": len(traces),
            "start_date": start_date,
            "end_date": end_date,
        }

    rag_stats = get_rag_stats()

    if not rag_stats:
        return {"traces": [], "total": 0}

    traces = rag_stats.trace_events[-limit:]
    return {"traces": traces, "total": len(rag_stats.trace_events)}


@app.get("/observability/dates")
def get_observability_dates():
    from rag.token_stats_db import get_token_stats_db

    db = get_token_stats_db()
    dates = db.get_daily_dates()
    return {"dates": dates}


class ExtractRequest(BaseModel):
    text: str
    schema_definition: Dict[str, Any]
    prompt_template: Optional[str] = None


class ExtractResponse(BaseModel):
    data: Dict[str, Any]
    error: Optional[str] = None


@app.post("/extract", response_model=ExtractResponse)
def extract_structured(req: ExtractRequest):
    from rag.structured_extractor import get_extractor

    extractor = get_extractor()

    try:
        result = extractor.extract(
            text=req.text,
            schema=req.schema_definition,
            prompt_template=req.prompt_template,
        )

        if "error" in result:
            return ExtractResponse(data={}, error=result["error"])

        return ExtractResponse(data=result)
    except Exception as e:
        return ExtractResponse(data={}, error=str(e))


class TextToJsonRequest(BaseModel):
    text: str
    fields: List[str]
    prompt_template: Optional[str] = None


# ============== Settings API ==============


class SystemSettings(BaseModel):
    """系统设置（仅包含可动态修改的部分）"""

    # LLM
    llm_mode: str = Field("ollama", description="LLM模式: ollama/siliconflow")
    default_llm_model: Optional[str] = Field(None, description="默认LLM模型")

    # Embedding
    ollama_embed_model: str = Field("bge-m3", description="Ollama embedding模型")
    ollama_base_url: str = Field("http://localhost:11434", description="Ollama服务地址")
    embed_batch_size: int = Field(32, ge=1, le=256, description="Embedding批处理大小")

    # Retrieval
    top_k: int = Field(5, ge=1, le=100, description="检索返回数量")
    use_semantic_chunking: bool = Field(False, description="启用语义分块")
    use_hybrid_search: bool = Field(False, description="启用混合搜索")
    use_auto_merging: bool = Field(False, description="启用Auto-Merging")
    use_hyde: bool = Field(False, description="启用HyDE查询")
    use_multi_query: bool = Field(False, description="启用多查询转换")
    num_multi_queries: int = Field(3, ge=1, le=10, description="多查询变体数量")
    hybrid_search_alpha: float = Field(0.5, ge=0, le=1, description="混合搜索向量权重")
    hybrid_search_mode: str = Field("relative_score", description="混合搜索融合模式")

    # Chunk
    chunk_strategy: str = Field(
        "hierarchical", description="分块策略: hierarchical/sentence/semantic"
    )
    chunk_size: int = Field(1024, ge=100, le=4096, description="分块大小")
    chunk_overlap: int = Field(100, ge=0, le=500, description="分块重叠")
    hierarchical_chunk_sizes: List[int] = Field(
        [2048, 1024, 512], description="分层分块大小 [parent, child, leaf]"
    )
    sentence_chunk_size: int = Field(1024, ge=100, le=4096, description="句子分块大小")
    sentence_chunk_overlap: int = Field(100, ge=0, le=500, description="句子分块重叠")

    # Reranker
    use_reranker: bool = Field(True, description="启用Reranker")
    rerank_model: str = Field("Pro/BAAI/bge-reranker-v2-m3", description="Reranker模型")

    # Response
    response_mode: str = Field("compact", description="答案生成模式")

    # Task
    progress_update_interval: int = Field(10, ge=1, description="进度更新间隔")
    max_concurrent_tasks: int = Field(10, ge=1, description="最大并发任务数")


class SettingsUpdateRequest(BaseModel):
    """设置更新请求"""

    # LLM
    llm_mode: Optional[str] = Field(None, description="LLM模式: ollama/siliconflow")
    default_llm_model: Optional[str] = Field(None, description="默认LLM模型")

    # Embedding
    ollama_embed_model: Optional[str] = Field(None, description="Ollama embedding模型")
    ollama_base_url: Optional[str] = Field(None, description="Ollama服务地址")
    embed_batch_size: Optional[int] = Field(None, ge=1, le=256, description="Embedding批处理大小")

    # Retrieval
    top_k: Optional[int] = Field(None, ge=1, le=100, description="检索返回数量")
    use_semantic_chunking: Optional[bool] = Field(None, description="启用语义分块")
    use_hybrid_search: Optional[bool] = Field(None, description="启用混合搜索")
    use_auto_merging: Optional[bool] = Field(None, description="启用Auto-Merging")
    use_hyde: Optional[bool] = Field(None, description="启用HyDE查询")
    use_multi_query: Optional[bool] = Field(None, description="启用多查询转换")
    num_multi_queries: Optional[int] = Field(
        None, ge=1, le=10, description="多查询变体数量"
    )
    hybrid_search_alpha: Optional[float] = Field(
        None, ge=0, le=1, description="混合搜索向量权重"
    )
    hybrid_search_mode: Optional[str] = Field(None, description="混合搜索融合模式")

    # Chunk
    chunk_strategy: Optional[str] = Field(
        None, description="分块策略: hierarchical/sentence/semantic"
    )
    chunk_size: Optional[int] = Field(None, ge=100, le=4096, description="分块大小")
    chunk_overlap: Optional[int] = Field(None, ge=0, le=500, description="分块重叠")
    hierarchical_chunk_sizes: Optional[List[int]] = Field(
        None, description="分层分块大小 [parent, child, leaf]"
    )
    sentence_chunk_size: Optional[int] = Field(None, ge=100, le=4096, description="句子分块大小")
    sentence_chunk_overlap: Optional[int] = Field(None, ge=0, le=500, description="句子分块重叠")

    # Reranker
    use_reranker: Optional[bool] = Field(None, description="启用Reranker")
    rerank_model: Optional[str] = Field(None, description="Reranker模型")

    # Response
    response_mode: Optional[str] = Field(None, description="答案生成模式")

    # Task
    progress_update_interval: Optional[int] = Field(None, ge=1, description="进度更新间隔")
    max_concurrent_tasks: Optional[int] = Field(None, ge=1, description="最大并发任务数")


@app.get("/settings", response_model=SystemSettings)
def get_settings():
    """获取系统设置"""
    from rag.config import get_settings

    s = get_settings()
    registry = None
    try:
        from rag.config import get_model_registry

        registry = get_model_registry()
        registry._ensure_loaded()
    except Exception:
        pass

    default_llm = None
    default_embed = None
    default_rerank = None
    if registry:
        default_llm_model = registry.get_default("llm")
        if default_llm_model:
            default_llm = default_llm_model["id"]

        default_embed_model = registry.get_default("embedding")
        if default_embed_model:
            default_embed = f"{default_embed_model.get('vendor_id')}/{default_embed_model.get('name')}"

        default_rerank_model = registry.get_default("reranker")
        if default_rerank_model:
            default_rerank = f"{default_rerank_model.get('vendor_id')}/{default_rerank_model.get('name')}"

    return SystemSettings(
        llm_mode=s.llm_mode,
        default_llm_model=_get_default_llm_model_id(),
        ollama_embed_model=s.ollama_embed_model,
        ollama_base_url=s.ollama_base_url,
        embed_batch_size=s.embed_batch_size,
        top_k=s.top_k,
        use_semantic_chunking=s.use_semantic_chunking,
        use_hybrid_search=s.use_hybrid_search,
        use_auto_merging=s.use_auto_merging,
        use_hyde=s.use_hyde,
        use_multi_query=s.use_multi_query,
        num_multi_queries=s.num_multi_queries,
        hybrid_search_alpha=s.hybrid_search_alpha,
        hybrid_search_mode=s.hybrid_search_mode,
        chunk_strategy=s.chunk_strategy,
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        hierarchical_chunk_sizes=s.hierarchical_chunk_sizes,
        sentence_chunk_size=s.sentence_chunk_size,
        sentence_chunk_overlap=s.sentence_chunk_overlap,
        use_reranker=s.use_reranker,
        rerank_model=default_rerank or "siliconflow/bge-reranker-v2-m3",
        response_mode=s.response_mode,
        progress_update_interval=s.progress_update_interval,
        max_concurrent_tasks=s.max_concurrent_tasks,
    )


@app.put("/settings", response_model=SystemSettings)
def update_settings(req: SettingsUpdateRequest):
    """更新系统设置（仅更新提供的字段）"""
    from pathlib import Path
    from rag.config import get_settings

    s = get_settings()
    updates = req.model_dump(exclude_unset=True)

    if not updates:
        return SystemSettings(
            llm_mode=s.llm_mode,
            default_llm_model=_get_default_llm_model_id(),
            ollama_embed_model=s.ollama_embed_model,
            ollama_base_url=s.ollama_base_url,
            embed_batch_size=s.embed_batch_size,
            top_k=s.top_k,
        use_semantic_chunking=s.use_semantic_chunking,
        use_hybrid_search=s.use_hybrid_search,
            use_auto_merging=s.use_auto_merging,
            use_hyde=s.use_hyde,
            use_multi_query=s.use_multi_query,
            num_multi_queries=s.num_multi_queries,
            hybrid_search_alpha=s.hybrid_search_alpha,
            hybrid_search_mode=s.hybrid_search_mode,
            chunk_strategy=s.chunk_strategy,
            chunk_size=s.chunk_size,
            chunk_overlap=s.chunk_overlap,
            hierarchical_chunk_sizes=s.hierarchical_chunk_sizes,
            sentence_chunk_size=s.sentence_chunk_size,
            sentence_chunk_overlap=s.sentence_chunk_overlap,
            use_reranker=s.use_reranker,
            rerank_model=s.rerank_model,
            response_mode=s.response_mode,
            progress_update_interval=s.progress_update_interval,
            max_concurrent_tasks=s.max_concurrent_tasks,
        )

    runtime_settings = {}
    env_updates = {}
    applied = []
    skipped = []

    for key, value in updates.items():
        if key in (
            "top_k",
            "use_semantic_chunking",
            "use_hybrid_search",
            "use_auto_merging",
            "use_hyde",
            "use_multi_query",
            "num_multi_queries",
            "hybrid_search_alpha",
            "hybrid_search_mode",
            "chunk_strategy",
            "chunk_size",
            "chunk_overlap",
            "hierarchical_chunk_sizes",
            "sentence_chunk_size",
            "sentence_chunk_overlap",
            "embed_batch_size",
            "use_reranker",
            "response_mode",
            "progress_update_interval",
            "max_concurrent_tasks",
        ):
            if key == "hierarchical_chunk_sizes" and isinstance(value, list):
                if len(value) != 3:
                    skipped.append(f"{key} (must have exactly 3 values)")
                    continue
                if not all(isinstance(x, int) and 128 <= x <= 8192 for x in value):
                    skipped.append(
                        f"{key} (values must be integers between 128 and 8192)"
                    )
                    continue
            if hasattr(s, key):
                setattr(s, key, value)
                runtime_settings[key] = value
                applied.append(key)
        elif key == "default_llm_model":
            _set_default_llm_model(value)
            applied.append(key)
        elif key in (
            "llm_mode",
            "ollama_embed_model",
            "ollama_base_url",
            "rerank_model",
        ):
            skipped.append(f"{key} (请使用模型管理 API: /models, /vendors)")
        else:
            skipped.append(key)

    if runtime_settings:
        s.save_runtime_settings(runtime_settings)
        logger.info(f"运行时设置已更新并持久化: {list(runtime_settings.keys())}")

    if env_updates:
        _update_env_file(env_updates)
        for env_var, value in env_updates.items():
            logger.info(f"环境变量已更新: {env_var}={value} (重启服务生效)")

    if skipped:
        logger.warning(f"跳过未知设置: {skipped}")

    return SystemSettings(
        llm_mode=s.llm_mode,
        default_llm_model=_get_default_llm_model_id(),
        ollama_embed_model=s.ollama_embed_model,
        ollama_base_url=s.ollama_base_url,
        embed_batch_size=s.embed_batch_size,
        top_k=s.top_k,
        use_semantic_chunking=s.use_semantic_chunking,
        use_hybrid_search=s.use_hybrid_search,
        use_auto_merging=s.use_auto_merging,
        use_hyde=s.use_hyde,
        use_multi_query=s.use_multi_query,
        num_multi_queries=s.num_multi_queries,
        hybrid_search_alpha=s.hybrid_search_alpha,
        hybrid_search_mode=s.hybrid_search_mode,
        chunk_strategy=s.chunk_strategy,
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        hierarchical_chunk_sizes=s.hierarchical_chunk_sizes,
        sentence_chunk_size=s.sentence_chunk_size,
        sentence_chunk_overlap=s.sentence_chunk_overlap,
        use_reranker=s.use_reranker,
        rerank_model=s.rerank_model,
        response_mode=s.response_mode,
        progress_update_interval=s.progress_update_interval,
        max_concurrent_tasks=s.max_concurrent_tasks,
    )


def _get_default_llm_model_id() -> Optional[str]:
    from rag.config import get_model_registry

    registry = get_model_registry()
    default_llm = registry.get_default("llm")
    return default_llm["id"] if default_llm else None


def _set_default_llm_model(model_id: Optional[str]) -> None:
    if not model_id:
        return
    from kb_core.database import init_model_db

    model_db = init_model_db()
    model_db.set_default(model_id)
    from rag.config import get_model_registry

    get_model_registry().reload()


def _update_env_file(updates: Dict[str, str]) -> None:
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        logger.warning(".env 文件不存在，跳过环境变量更新")
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated_keys = set(updates.keys())
        new_lines = []
        for line in lines:
            key = line.split("=")[0].strip() if "=" in line else ""
            if key in updated_keys:
                new_lines.append(f"{key}={updates[key]}")
            else:
                new_lines.append(line)
        for key, value in updates.items():
            if not any(l.startswith(f"{key}=") for l in new_lines):
                new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.error(f"更新 .env 文件失败: {e}")


@app.post("/extract/fields", response_model=Dict[str, Any])
def extract_fields(req: TextToJsonRequest):
    from rag.structured_extractor import TextToJsonExtractor

    extractor = TextToJsonExtractor()

    try:
        return extractor.extract(
            text=req.text,
            fields=req.fields,
            prompt_template=req.prompt_template,
        )
    except Exception as e:
        return {f: None for f in req.fields}


if __name__ == "__main__":
    import uvicorn
    import os

    from rag.logger import LOG_LEVEL
    from rag.config import get_settings

    port = get_settings().api_port
    uvicorn.run(app, host="0.0.0.0", port=port, log_config=None, log_level="info")

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
    POST /kbs/{kb_id}/search        - 向量检索
    POST /kbs/{kb_id}/query        - RAG 问答
    POST /search                     - 自动路由检索
    POST /query                      - 自动路由问答

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
"""

import asyncio
import threading
from pathlib import Path
from typing import List, Optional, Dict
import markdown

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# 添加项目根目录到 path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

# 导入服务层
from kb.services import (
    VectorStoreService,
    ObsidianService,
    ZoteroService,
    GenericService,
    KnowledgeBaseService,
    SearchService,
)
from llamaindex_study.rag_evaluator import RAGEvaluator, RAGMetrics


# ============== Lifespan 和调度器 ==============

from contextlib import asynccontextmanager

_scheduler_ref = None


async def start_scheduler():
    """启动任务调度器"""
    global _scheduler_ref
    from kb.task_executor import TaskScheduler

    scheduler = TaskScheduler()
    _scheduler_ref = asyncio.create_task(scheduler.run())
    logger.info("任务调度器已启动")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中...")
    await start_scheduler()
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============== 数据模型 ==============


class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询")
    top_k: int = Field(5, ge=1, le=100)
    route_mode: str = Field(
        "general",
        description="路由模式: general(用户选择知识库), auto(自动路由)",
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


class SearchResult(BaseModel):
    text: str
    score: float
    metadata: dict = {}
    kb_id: Optional[str] = None


class QueryRequest(BaseModel):
    query: str = Field(..., description="查询")
    top_k: int = Field(5, ge=1, le=100)
    route_mode: str = Field(
        "general",
        description="路由模式: general(用户选择知识库), auto(自动路由)",
    )
    retrieval_mode: str = Field(
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
    use_auto_merging: Optional[bool] = Field(
        None, description="启用 Auto-Merging（None=使用配置默认值）"
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


class IngestResponse(BaseModel):
    status: str
    task_id: Optional[str] = None
    message: Optional[str] = None
    files_processed: Optional[int] = None
    nodes_created: Optional[int] = None
    failed: Optional[int] = None
    source: Optional[str] = None


class KBInfo(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    status: str = "unknown"
    row_count: Optional[int] = None


class TaskResponse(BaseModel):
    task_id: str
    status: str
    kb_id: str
    message: str = ""
    progress: Optional[int] = 0
    result: Optional[Dict] = None
    error: Optional[str] = None


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
    from kb.task_queue import task_queue

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
    from kb.task_queue import task_queue

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
    from kb.task_queue import task_queue

    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        task_id=task.task_id,
        status=task.status,
        kb_id=task.kb_id,
        message=task.message,
        progress=task.progress,
        result=task.result,
        error=task.error,
    )


@app.delete("/tasks/{task_id}")
def cancel_task(task_id: str):
    """取消任务"""
    from kb.services import TaskService

    try:
        result = TaskService.cancel(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/tasks/{task_id}/pause")
def pause_task(task_id: str):
    """暂停任务"""
    from kb.services import TaskService

    try:
        result = TaskService.pause(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/tasks/{task_id}/resume")
def resume_task(task_id: str):
    """恢复任务"""
    from kb.services import TaskService

    try:
        result = TaskService.resume(task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/tasks/{task_id}/delete")
def delete_task(task_id: str, cleanup: bool = False):
    """删除任务（物理删除）

    Args:
        cleanup: 是否清理关联的知识库数据（仅对 failed/cancelled 任务有效）
    """
    from kb.services import TaskService

    try:
        return TaskService.delete(task_id, cleanup=cleanup)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/tasks/pause-all")
def pause_all_tasks(status: str = "running"):
    """暂停所有运行中的任务"""
    from kb.services import TaskService

    return TaskService.pause_all(status)


@app.post("/tasks/resume-all")
def resume_all_tasks():
    """恢复所有已暂停的任务"""
    from kb.services import TaskService

    return TaskService.resume_all()


@app.delete("/tasks/delete-all")
def delete_all_tasks(status: str = "completed", cleanup: bool = False):
    """删除所有任务"""
    from kb.services import TaskService

    return TaskService.delete_all(status, cleanup)


@app.post("/tasks/cleanup")
def cleanup_orphan_tasks():
    """清理孤儿任务（执行进程已终止的任务）"""
    from kb.services import TaskService

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
        result = KnowledgeBaseService.create(req.id, req.name, req.description)
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


@app.delete("/kbs/{kb_id}")
def delete_kb(kb_id: str):
    """删除知识库"""
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
    from kb.database import init_vendor_db

    db = init_vendor_db()
    vendors = db.get_all(active_only=False)
    return [VendorInfo(**v) for v in vendors]


@app.post("/vendors", response_model=VendorInfo)
def create_vendor(req: VendorCreateRequest):
    """创建或更新供应商"""
    from kb.database import init_vendor_db

    db = init_vendor_db()
    db.upsert(
        vendor_id=req.id,
        name=req.name,
        api_base=req.api_base,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    return VendorInfo(**db.get(req.id))


@app.get("/vendors/{vendor_id}", response_model=VendorInfo)
def get_vendor(vendor_id: str):
    """获取指定供应商"""
    from kb.database import init_vendor_db

    db = init_vendor_db()
    vendor = db.get(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    return VendorInfo(**vendor)


@app.delete("/vendors/{vendor_id}")
def delete_vendor(vendor_id: str):
    """删除供应商"""
    from kb.database import init_vendor_db

    db = init_vendor_db()
    if not db.get(vendor_id):
        raise HTTPException(status_code=404, detail=f"供应商 {vendor_id} 不存在")
    db.delete(vendor_id)
    return {"status": "deleted", "vendor_id": vendor_id}


# ============== 模型管理 ==============


@app.get("/models", response_model=List[ModelInfo])
def list_models(type: Optional[str] = None):
    """获取所有模型，或按类型筛选"""
    from llamaindex_study.config import get_model_registry

    registry = get_model_registry()
    if type:
        models = registry.get_by_type(type)
    else:
        models = registry.list_models()
    return [ModelInfo(**m) for m in models]


@app.post("/models", response_model=ModelInfo)
def create_model(req: ModelCreateRequest):
    """创建或更新模型"""
    from kb.database import init_model_db, init_vendor_db

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
    from llamaindex_study.config import get_model_registry

    get_model_registry().reload()
    return ModelInfo(**model_db.get(req.id))


@app.get("/models/{model_id}", response_model=ModelInfo)
def get_model(model_id: str):
    """获取指定模型"""
    from llamaindex_study.config import get_model_registry

    registry = get_model_registry()
    model = registry.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    return ModelInfo(**model)


@app.delete("/models/{model_id}")
def delete_model(model_id: str):
    """删除模型"""
    from kb.database import init_model_db
    from llamaindex_study.config import get_model_registry

    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.delete(model_id)
    get_model_registry().reload()
    return {"status": "deleted", "model_id": model_id}


@app.put("/models/{model_id}/default")
def set_default_model(model_id: str):
    """设置默认模型"""
    from kb.database import init_model_db
    from llamaindex_study.config import get_model_registry

    db = init_model_db()
    if not db.get(model_id):
        raise HTTPException(status_code=404, detail=f"模型 {model_id} 不存在")
    db.set_default(model_id)
    get_model_registry().reload()
    return {"status": "success", "model_id": model_id}


# ============== 检索接口 ==============


@app.post("/search", response_model=List[SearchResult])
def search(req: SearchRequest):
    from kb.services import QueryRouter

    if req.route_mode == "auto":
        result = QueryRouter.search(
            req.query,
            top_k=req.top_k,
            exclude=req.exclude,
            use_auto_merging=req.use_auto_merging,
            mode="auto",
            embed_model_id=req.embed_model_id,
        )
        return [SearchResult(**r) for r in result.get("results", [])]

    if not req.kb_ids:
        return []

    kb_id_list = [k.strip() for k in req.kb_ids.split(",") if k.strip()]
    if not kb_id_list:
        return []

    results = SearchService.search_multi(
        kb_id_list,
        req.query,
        top_k=req.top_k,
        use_auto_merging=req.use_auto_merging,
        embed_model_id=req.embed_model_id,
    )
    return [SearchResult(**r) for r in results]


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    from kb.services import QueryRouter

    logger.info(
        f"[QUERY] route_mode={req.route_mode}, kb_ids={req.kb_ids}, retrieval_mode={req.retrieval_mode}, query={req.query[:50]}..."
    )

    try:
        model_id = req.model_id
        if not model_id and req.llm_mode:
            from llamaindex_study.config import get_model_registry

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
                use_auto_merging=req.use_auto_merging,
                response_mode=req.response_mode,
                retrieval_mode=req.retrieval_mode,
                model_id=model_id,
                embed_model_id=req.embed_model_id,
            )
            return QueryResponse(**result)

        if not req.kb_ids:
            return QueryResponse(
                response="请提供 kb_ids 参数指定要查询的知识库", sources=[]
            )

        kb_id_list = [k.strip() for k in req.kb_ids.split(",") if k.strip()]
        if not kb_id_list:
            return QueryResponse(response="kb_ids 参数无效", sources=[])

        result = QueryRouter.query_multi(
            kb_id_list,
            req.query,
            top_k=req.top_k,
            use_hyde=req.use_hyde,
            use_multi_query=req.use_multi_query,
            use_auto_merging=req.use_auto_merging,
            response_mode=req.response_mode,
            retrieval_mode=req.retrieval_mode,
            model_id=model_id,
            embed_model_id=req.embed_model_id,
        )
        return QueryResponse(**result)

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

    from kb.generic_processor import GenericImporter

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

    from kb.task_queue import task_queue

    task_id = task_queue.submit_task(
        task_type="generic",
        kb_id=kb_id,
        params={"path": req.path},
        source=req.path,
    )

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


@app.post("/kbs/{kb_id}/ingest/zotero", response_model=IngestResponse)
def ingest_zotero(kb_id: str, req: ZoteroIngestRequest):
    """Zotero 收藏夹导入"""
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor
    from kb.zotero_processor import ZoteroImporter

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

    task_id = task_queue.submit_task(
        task_type="zotero",
        kb_id=kb_id,
        params={
            "collection_id": collection_id,
            "collection_name": collection_name,
            "rebuild": req.rebuild,
        },
        source=f"zotero:{collection_name}",
    )

    # 任务由调度器启动

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


@app.post("/kbs/{kb_id}/ingest/obsidian", response_model=IngestResponse)
def ingest_obsidian(kb_id: str, req: ObsidianIngestRequest):
    """Obsidian vault 导入"""
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor

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

    task_id = task_queue.submit_task(
        task_type="obsidian",
        kb_id=kb_id,
        params={
            "vault_path": str(vault_path),
            "folder_path": req.folder_path,
            "recursive": req.recursive,
            "exclude_patterns": req.exclude_patterns,
        },
        source=f"obsidian:{import_dir.name}",
    )

    # 任务由调度器启动

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"Obsidian {import_dir.name} 导入任务已提交，ID: {task_id}",
        source="obsidian",
    )


# ============== Obsidian 全库分类导入 ==============


@app.get("/obsidian/mappings")
def list_obsidian_mappings():
    """列出 Obsidian 知识库映射配置"""
    from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS

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
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor
    from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS

    task_ids = []
    use_remote_counter = 0

    for mapping in OBSIDIAN_KB_MAPPINGS:
        if not mapping.folders:
            continue

        for folder in mapping.folders:
            use_remote = use_remote_counter % 2 == 1
            use_remote_counter += 1

            task_id = task_queue.submit_task(
                task_type="obsidian_folder",
                kb_id=mapping.kb_id,
                params={
                    "folder": folder,
                    "use_remote": use_remote,
                },
                source=f"obsidian:{folder}",
            )

            # 任务由调度器启动

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
    from kb.database import init_category_rule_db

    rule_db = init_category_rule_db()
    rules = rule_db.get_all_rules()

    return {
        "rules": rules,
        "total": len(rules),
    }


@app.post("/category/rules/sync")
def sync_category_rules():
    """同步分类规则到数据库"""
    from kb.obsidian_config import seed_mappings_to_db

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
    from kb.obsidian_config import find_kb_by_path
    from kb.category_classifier import CategoryClassifier

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
    from kb.database import init_category_rule_db

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
def initialize_kb(kb_id: str, async_mode: bool = True):
    """初始化知识库（清空所有数据）"""
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor

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


# ============== WebSocket 接口 ==============


@app.websocket("/ws/tasks")
async def ws_tasks(websocket):
    """WebSocket 任务状态推送"""
    from kb.websocket_manager import ws_manager

    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.debug(f"WebSocket 连接关闭: {e}")
    finally:
        ws_manager.disconnect(websocket)


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


if __name__ == "__main__":
    import uvicorn
    import os

    port = int(os.getenv("API_PORT", "37241"))
    uvicorn.run(app, host="0.0.0.0", port=port)

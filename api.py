"""
LlamaIndex RAG API Server v3.1

启动:
    poetry run python api.py

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
    POST /kbs/{kb_id}/rebuild       - 重建知识库（异步）

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
    description="RAG 检索增强生成 API，支持任务队列异步处理",
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
    exclude: Optional[List[str]] = Field(None, description="排除的知识库 ID 列表")


class SearchResult(BaseModel):
    text: str
    score: float
    metadata: dict = {}


class QueryRequest(BaseModel):
    query: str = Field(..., description="查询")
    mode: str = Field("hybrid", description="检索模式: hybrid, vector, keyword")
    top_k: int = Field(5, ge=1, le=100)
    exclude: Optional[List[str]] = Field(None, description="排除的知识库 ID 列表")


class QueryResponse(BaseModel):
    response: str
    sources: List[dict] = []


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
def api_docs_page():
    """显示 API 文档页面 (docs/API.md)"""
    docs_path = Path(__file__).parent / "docs" / "API.md"
    if not docs_path.exists():
        return HTMLResponse(
            content="<html><body><h1>API 文档未找到</h1><p>docs/API.md 不存在</p></body></html>",
            status_code=404,
        )

    md_content = docs_path.read_text(encoding="utf-8")
    html_content = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "codehilite"],
    )

    html_page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API 文档 - LlamaIndex RAG API</title>
    <style>
        :root {{
            --bg-color: #ffffff;
            --text-color: #333333;
            --code-bg: #f5f5f5;
            --border-color: #dddddd;
            --link-color: #0066cc;
            --header-bg: #2c3e50;
            --header-color: #ffffff;
            --table-header-bg: #f0f0f0;
            --blockquote-border: #4caf50;
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg-color: #1a1a1a;
                --text-color: #e0e0e0;
                --code-bg: #2d2d2d;
                --border-color: #404040;
                --link-color: #66b3ff;
                --header-bg: #2c3e50;
                --table-header-bg: #2d2d2d;
            }}
        }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: var(--bg-color);
            color: var(--text-color);
        }}
        h1, h2, h3, h4, h5, h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 600; }}
        h1 {{
            font-size: 2.2em;
            border-bottom: 3px solid var(--header-bg);
            padding-bottom: 0.3em;
        }}
        h2 {{ font-size: 1.8em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.2em; }}
        a {{ color: var(--link-color); text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        code {{
            background-color: var(--code-bg);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "SF Mono", Monaco, Consolas, "Liberation Mono", monospace;
            font-size: 0.9em;
        }}
        pre {{
            background-color: var(--code-bg);
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid var(--border-color);
        }}
        pre code {{
            padding: 0;
            background: none;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1em 0;
        }}
        th, td {{
            border: 1px solid var(--border-color);
            padding: 10px 12px;
            text-align: left;
        }}
        th {{
            background-color: var(--table-header-bg);
            font-weight: 600;
        }}
        blockquote {{
            margin: 1em 0;
            padding: 0.5em 1em;
            border-left: 4px solid var(--blockquote-border);
            background-color: var(--code-bg);
        }}
        hr {{
            border: none;
            border-top: 1px solid var(--border-color);
            margin: 2em 0;
        }}
        .nav {{
            background-color: var(--header-bg);
            color: var(--header-color);
            padding: 15px 20px;
            margin: -20px -20px 20px -20px;
            border-radius: 0;
        }}
        .nav a {{
            color: var(--header-color);
            margin-right: 20px;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
        .warning {{
            background-color: #fff3cd;
            border: 1px solid #ffc107;
            color: #856404;
            padding: 10px 15px;
            border-radius: 4px;
            margin: 1em 0;
        }}
        @media (prefers-color-scheme: dark) {{
            .warning {{
                background-color: #3d3d1a;
                border-color: #6b5a00;
                color: #d4a017;
            }}
        }}
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/default.min.css">
</head>
<body>
    <div class="nav">
        <a href="/">首页</a>
        <a href="/docs">Swagger API 文档</a>
        <a href="/redoc">ReDoc 文档</a>
        <a href="/api-docs">Markdown API 文档</a>
    </div>
    <div class="content">
        {html_content}
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
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
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor

    if task_executor.cancel_task(task_id):
        return {"status": "cancelled", "task_id": task_id}
    raise HTTPException(status_code=404, detail="Task not found or already completed")


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


# ============== 检索接口 ==============


@app.post("/kbs/{kb_id}/search", response_model=List[SearchResult])
def search(kb_id: str, req: SearchRequest):
    """向量检索"""
    results = SearchService.search(kb_id, req.query, req.top_k)
    return [SearchResult(**r) for r in results]


@app.post("/kbs/{kb_id}/query", response_model=QueryResponse)
def query(kb_id: str, req: QueryRequest):
    """RAG 问答"""
    result = SearchService.query(kb_id, req.query, req.mode, req.top_k)
    return QueryResponse(**result)


@app.post("/search", response_model=List[SearchResult])
def search_auto(req: SearchRequest):
    """自动路由向量检索"""
    from kb.services import QueryRouter

    result = QueryRouter.search(req.query, req.top_k, exclude=req.exclude)
    return [SearchResult(**r) for r in result.get("results", [])]


@app.post("/query", response_model=QueryResponse)
def query_auto(req: QueryRequest):
    """自动路由 RAG 问答"""
    from kb.services import QueryRouter

    result = QueryRouter.query(req.query, req.top_k, exclude=req.exclude)
    return QueryResponse(**result)


# ============== 导入接口 ==============


@app.post("/kbs/{kb_id}/ingest")
def ingest(kb_id: str, req: IngestRequest):
    """通用文件导入"""
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor

    task_id = task_queue.submit_task(
        task_type="generic",
        kb_id=kb_id,
        params={"path": req.path},
        source=req.path,
    )

    # 任务由调度器启动

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"导入任务已提交，ID: {task_id}",
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


@app.post("/kbs/{kb_id}/rebuild")
def rebuild_kb(kb_id: str, async_mode: bool = True):
    """重建知识库"""
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor

    if async_mode:
        task_id = task_queue.submit_task(
            task_type="rebuild",
            kb_id=kb_id,
            params={},
            source=f"rebuild:{kb_id}",
        )

        # 任务由调度器启动

        return {
            "status": "pending",
            "task_id": task_id,
            "message": f"重建任务已提交，ID: {task_id}",
        }
    else:
        KnowledgeBaseService.rebuild(kb_id)
        return {
            "status": "success",
            "message": f"知识库 {kb_id} 已清空",
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

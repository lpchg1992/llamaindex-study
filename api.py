"""
LlamaIndex RAG API Server v3.0

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

    任务队列:
    POST /tasks                      - 提交任务
    GET  /tasks                      - 列出任务
    GET  /tasks/{task_id}           - 查询任务状态
    DELETE /tasks/{task_id}          - 取消任务

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

import os
import sys
import asyncio
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

app = FastAPI(
    title="LlamaIndex RAG API",
    description="RAG 检索增强生成 API，支持任务队列异步处理",
    version="3.1.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 后台任务执行器
_executor_loop = None
_executor_thread = None


def get_executor_loop():
    """获取或创建事件循环"""
    global _executor_loop, _executor_thread
    if _executor_loop is None:
        _executor_loop = asyncio.new_event_loop()
        _executor_thread = threading.Thread(target=_run_loop, args=(_executor_loop,), daemon=True)
        _executor_thread.start()
    return _executor_loop


def _run_loop(loop):
    """运行事件循环"""
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        loop.close()


# ============== 数据模型 ==============

class SearchRequest(BaseModel):
    query: str = Field(..., description="搜索查询")
    top_k: int = Field(5, ge=1, le=100)


class SearchResult(BaseModel):
    text: str
    score: float
    metadata: dict = {}


class QueryRequest(BaseModel):
    query: str = Field(..., description="查询问题")
    top_k: int = Field(20, ge=1, le=100)


class QueryResponse(BaseModel):
    answer: str
    source_nodes: List[SearchResult]
    total_nodes: int


class CreateKBRequest(BaseModel):
    kb_id: str = Field(..., description="知识库 ID (唯一标识)")
    name: str = Field(..., description="知识库名称")
    description: str = Field("", description="知识库描述")
    chunk_size: int = Field(512, ge=128, le=2048, description="切块大小 (tokens)")
    chunk_overlap: int = Field(50, ge=0, le=256, description="切块重叠 (tokens)")


class IngestRequest(BaseModel):
    """通用文件导入"""
    paths: List[str] = Field(..., description="文件或文件夹路径列表")
    recursive: bool = Field(True, description="是否递归扫描子文件夹")
    exclude_patterns: List[str] = Field(
        default=["*.xls", "*.xlsx", ".DS_Store"],
        description="排除的文件模式"
    )
    async_mode: bool = Field(True, description="是否异步执行")


class ZoteroIngestRequest(BaseModel):
    """Zotero 收藏夹导入"""
    collection_id: Optional[int] = Field(None, description="Zotero 收藏夹 ID")
    collection_name: Optional[str] = Field(None, description="Zotero 收藏夹名称")
    rebuild: bool = Field(False, description="是否强制重建")
    async_mode: bool = Field(True, description="是否异步执行")


class ObsidianIngestRequest(BaseModel):
    """Obsidian vault 导入"""
    vault_path: str = Field(..., description="Obsidian vault 路径")
    folder_path: Optional[str] = Field(None, description="特定文件夹路径")
    recursive: bool = Field(True, description="是否递归")
    exclude_patterns: List[str] = Field(
        default=["*/image/*", "*/_resources/*", "*/.obsidian/*"],
        description="排除的文件模式"
    )
    async_mode: bool = Field(True, description="是否异步执行")


class SubmitTaskRequest(BaseModel):
    """提交任务请求"""
    task_type: str = Field(..., description="任务类型: zotero, obsidian, generic, rebuild")
    kb_id: str = Field(..., description="知识库 ID")
    params: dict = Field(default_factory=dict, description="任务参数")
    source: str = Field("", description="来源描述")


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    task_type: str
    status: str
    kb_id: str
    progress: int
    current: int
    total: int
    message: str
    created_at: float
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class IngestResponse(BaseModel):
    status: str
    task_id: Optional[str] = None
    message: str
    source: str = ""


class TableInfo(BaseModel):
    name: str
    row_count: int
    vector_dim: int
    persist_dir: str


class KBInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    status: str
    row_count: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None


# ============== 辅助函数 ==============

def configure_llamaindex():
    """配置 LlamaIndex 全局设置"""
    from llama_index.core import Settings as LlamaSettings
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llama_index.llms.openai import OpenAI
    from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS
    from llamaindex_study.config import get_settings

    settings = get_settings()

    if "Pro/deepseek-ai/DeepSeek-V3.2" not in ALL_AVAILABLE_MODELS:
        ALL_AVAILABLE_MODELS["Pro/deepseek-ai/DeepSeek-V3.2"] = 128000

    import tiktoken
    try:
        tiktoken.encoding_for_model("Pro/deepseek-ai/DeepSeek-V3.2")
    except KeyError:
        import tiktoken.model as tm
        tm.MODEL_TO_ENCODING["Pro/deepseek-ai/DeepSeek-V3.2"] = "cl100k_base"

    LlamaSettings.embed_model = OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )
    LlamaSettings.llm = OpenAI(
        model=settings.siliconflow_model,
        api_key=settings.siliconflow_api_key,
        api_base=settings.siliconflow_base_url,
    )


def get_embed_model():
    """获取 Embedding 模型"""
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llamaindex_study.config import get_settings
    settings = get_settings()
    return OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )


def get_kb_persist_dir(kb_id: str) -> Path:
    """获取知识库的持久化目录"""
    base = Path("/volumes/online/llamaindex")
    if kb_id == "zotero_nutrition":
        return base / "zotero" / kb_id
    elif kb_id == "hitech_history":
        return base / kb_id
    else:
        return base / kb_id


def get_vector_store(kb_id: str):
    """获取向量存储"""
    from llamaindex_study.vector_store import create_vector_store, VectorStoreType
    persist_dir = get_kb_persist_dir(kb_id)
    return create_vector_store(VectorStoreType.LANCEDB, persist_dir=persist_dir, table_name=kb_id)


# ============== 路由 ==============

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "llamaindex-rag-api", "version": "3.1.0"}


# ============== 任务队列接口 ==============

@app.post("/tasks", response_model=TaskResponse)
def submit_task(req: SubmitTaskRequest):
    """
    提交任务
    
    返回任务 ID，可通过 GET /tasks/{task_id} 查询进度
    """
    from kb.task_queue import task_queue, TaskType
    
    # 验证任务类型
    valid_types = [t.value for t in TaskType]
    if req.task_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"无效的任务类型: {req.task_type}，可选: {valid_types}"
        )
    
    # 提交任务
    task_id = task_queue.submit_task(
        task_type=req.task_type,
        kb_id=req.kb_id,
        params=req.params,
        source=req.source,
    )
    
    # 启动任务执行
    from kb.task_executor import task_executor
    loop = get_executor_loop()
    asyncio.run_coroutine_threadsafe(
        task_executor.execute_task(task_id),
        loop
    )
    
    # 获取任务信息
    task = task_queue.get_task(task_id)
    
    return TaskResponse(
        task_id=task.task_id,
        task_type=task.task_type,
        status=task.status,
        kb_id=task.kb_id,
        progress=task.progress,
        current=task.current,
        total=task.total,
        message=task.message,
        created_at=task.created_at,
    )


@app.get("/tasks", response_model=List[TaskResponse])
def list_tasks(
    kb_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    """列出任务"""
    from kb.task_queue import task_queue
    
    tasks = task_queue.list_tasks(kb_id=kb_id, status=status, limit=limit)
    
    return [
        TaskResponse(
            task_id=t.task_id,
            task_type=t.task_type,
            status=t.status,
            kb_id=t.kb_id,
            progress=t.progress,
            current=t.current,
            total=t.total,
            message=t.message,
            created_at=t.created_at,
            started_at=t.started_at,
            completed_at=t.completed_at,
            result=t.result,
            error=t.error,
        )
        for t in tasks
    ]


@app.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str):
    """获取任务状态"""
    from kb.task_queue import task_queue
    
    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")
    
    return TaskResponse(
        task_id=task.task_id,
        task_type=task.task_type,
        status=task.status,
        kb_id=task.kb_id,
        progress=task.progress,
        current=task.current,
        total=task.total,
        message=task.message,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        result=task.result,
        error=task.error,
    )


@app.delete("/tasks/{task_id}")
def cancel_task(task_id: str):
    """取消任务"""
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor
    
    # 先尝试取消执行中的任务
    task_executor.cancel_task(task_id)
    
    # 再从队列中删除
    success = task_queue.cancel_task(task_id)
    if not success:
        task = task_queue.get_task(task_id)
        if task and task.status == "running":
            return {"status": "cancelled", "task_id": task_id, "message": "正在取消..."}
        raise HTTPException(status_code=400, detail="无法取消任务，只能取消等待中的任务")
    
    return {"status": "cancelled", "task_id": task_id}


# ============== 知识库接口 ==============

@app.get("/kbs", response_model=List[KBInfo])
def list_kbs():
    """列出所有知识库"""
    result = []
    base = Path("/volumes/online/llamaindex")

    if base.exists():
        for subdir in base.iterdir():
            if not subdir.is_dir():
                continue

            if subdir.name == "zotero":
                for zotero_subdir in subdir.iterdir():
                    if zotero_subdir.is_dir():
                        kb_id = zotero_subdir.name
                        lance_file = zotero_subdir / f"{kb_id}.lance"
                        if lance_file.exists():
                            try:
                                import lancedb
                                db = lancedb.connect(str(zotero_subdir))
                                table = db.open_table(kb_id)
                                df = table.to_pandas()
                                result.append(KBInfo(
                                    id=kb_id,
                                    name=kb_id,
                                    description="",
                                    status="indexed",
                                    row_count=len(df),
                                ))
                            except:
                                pass
            else:
                lance_file = subdir / f"{subdir.name}.lance"
                if lance_file.exists():
                    try:
                        import lancedb
                        db = lancedb.connect(str(subdir))
                        table = db.open_table(subdir.name)
                        df = table.to_pandas()
                        result.append(KBInfo(
                            id=subdir.name,
                            name=subdir.name,
                            description="",
                            status="indexed",
                            row_count=len(df),
                        ))
                    except:
                        pass

    return result


@app.post("/kbs", response_model=KBInfo)
def create_kb(req: CreateKBRequest):
    """创建新知识库"""
    kb_id = req.kb_id
    persist_dir = get_kb_persist_dir(kb_id)

    if persist_dir.exists():
        raise HTTPException(status_code=400, detail=f"知识库 {kb_id} 已存在")

    persist_dir.mkdir(parents=True, exist_ok=True)

    vs = get_vector_store(kb_id)

    config_file = persist_dir / "kb_config.json"
    import json
    with open(config_file, "w") as f:
        json.dump({
            "id": kb_id,
            "name": req.name,
            "description": req.description,
            "chunk_size": req.chunk_size,
            "chunk_overlap": req.chunk_overlap,
        }, f, indent=2)

    return KBInfo(
        id=kb_id,
        name=req.name,
        description=req.description,
        status="created",
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
    )


@app.get("/kbs/{kb_id}")
def get_kb_info(kb_id: str):
    """获取知识库详情"""
    persist_dir = get_kb_persist_dir(kb_id)
    config_file = persist_dir / "kb_config.json"

    config = {}
    if config_file.exists():
        import json
        with open(config_file) as f:
            config = json.load(f)

    info = {"id": kb_id, "status": "unknown"}

    if persist_dir.exists():
        try:
            import lancedb
            db = lancedb.connect(str(persist_dir))
            table = db.open_table(kb_id)
            df = table.to_pandas()
            info["status"] = "indexed"
            info["row_count"] = len(df)
        except:
            info["status"] = "empty"

    info.update(config)
    return info


@app.delete("/kbs/{kb_id}")
def delete_kb(kb_id: str):
    """删除知识库"""
    persist_dir = get_kb_persist_dir(kb_id)

    if not persist_dir.exists():
        raise HTTPException(status_code=404, detail=f"知识库 {kb_id} 不存在")

    vs = get_vector_store(kb_id)
    vs.delete_table()

    import shutil
    shutil.rmtree(persist_dir)

    return {"status": "deleted", "kb_id": kb_id}


# ============== 检索接口 ==============

@app.post("/kbs/{kb_id}/search", response_model=List[SearchResult])
def search(kb_id: str, req: SearchRequest):
    """向量检索"""
    from llamaindex_study.reranker import SiliconFlowReranker
    from llamaindex_study.config import get_settings

    configure_llamaindex()
    settings = get_settings()

    vs = get_vector_store(kb_id)
    index = vs.load_index()

    reranker = SiliconFlowReranker(api_key=settings.siliconflow_api_key)
    retriever = index.as_retriever(similarity_top_k=req.top_k * 3)

    from llama_index.core.schema import QueryBundle
    nodes = retriever.retrieve(req.query)
    reranked = reranker._postprocess_nodes(nodes, QueryBundle(query_str=req.query))

    return [
        SearchResult(text=n.get_content(), score=n.score or 0.0, metadata=n.metadata or {})
        for n in reranked[:req.top_k]
    ]


@app.post("/kbs/{kb_id}/query", response_model=QueryResponse)
def query(kb_id: str, req: QueryRequest):
    """RAG 问答"""
    from llamaindex_study.reranker import SiliconFlowReranker
    from llamaindex_study.config import get_settings

    configure_llamaindex()
    settings = get_settings()

    vs = get_vector_store(kb_id)
    index = vs.load_index()

    reranker = SiliconFlowReranker(api_key=settings.siliconflow_api_key)
    query_engine = index.as_query_engine(
        node_postprocessors=[reranker],
        similarity_top_k=req.top_k * 3,
    )

    results = query_engine.query(req.query)

    return QueryResponse(
        answer=str(results),
        source_nodes=[
            SearchResult(text=n.get_content(), score=n.score or 0.0, metadata=n.metadata or {})
            for n in results.source_nodes[:req.top_k]
        ],
        total_nodes=len(results.source_nodes),
    )


# ============== 异步导入接口 ==============

@app.post("/kbs/{kb_id}/ingest", response_model=IngestResponse)
def ingest_files(kb_id: str, req: IngestRequest):
    """
    通用文件导入
    
    设置 async_mode=true 返回任务 ID，通过 /tasks/{task_id} 查询进度
    """
    if req.async_mode:
        # 异步模式
        from kb.task_queue import task_queue
        from kb.task_executor import task_executor
        
        task_id = task_queue.submit_task(
            task_type="generic",
            kb_id=kb_id,
            params={
                "paths": req.paths,
                "recursive": req.recursive,
                "exclude_patterns": req.exclude_patterns,
            },
            source="generic",
        )
        
        # 启动任务
        loop = get_executor_loop()
        asyncio.run_coroutine_threadsafe(
            task_executor.execute_task(task_id),
            loop
        )
        
        return IngestResponse(
            status="pending",
            task_id=task_id,
            message=f"任务已提交，ID: {task_id}，请通过 GET /tasks/{task_id} 查询进度",
            source="generic",
        )
    else:
        # 同步模式（保留原有逻辑）
        return _ingest_files_sync(kb_id, req)


def _ingest_files_sync(kb_id: str, req: IngestRequest):
    """同步导入"""
    from kb.generic_processor import GenericImporter, FileImportConfig
    from kb.document_processor import DocumentProcessorConfig

    configure_llamaindex()
    embed_model = get_embed_model()

    persist_dir = get_kb_persist_dir(kb_id)
    config_file = persist_dir / "kb_config.json"
    chunk_size, chunk_overlap = 512, 50
    if config_file.exists():
        import json
        with open(config_file) as f:
            cfg = json.load(f)
            chunk_size = cfg.get("chunk_size", 512)
            chunk_overlap = cfg.get("chunk_overlap", 50)

    importer = GenericImporter(
        config=FileImportConfig(source_name=kb_id),
        processor_config=DocumentProcessorConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ),
    )

    vs = get_vector_store(kb_id)

    paths = [Path(p) for p in req.paths]
    stats = importer.import_paths(
        paths=[str(p) for p in paths],
        vector_store=vs,
        embed_model=embed_model,
        exclude_patterns=req.exclude_patterns,
        recursive=req.recursive,
    )

    return IngestResponse(
        status="success" if stats["failed"] == 0 else "partial",
        source="generic",
        files_processed=stats["files"],
        nodes_created=stats["nodes"],
        failed=stats["failed"],
        message=f"成功导入 {stats['files']} 个文件，创建 {stats['nodes']} 个节点"
    )


@app.post("/kbs/{kb_id}/ingest/zotero", response_model=IngestResponse)
def ingest_zotero(kb_id: str, req: ZoteroIngestRequest):
    """
    Zotero 收藏夹导入
    
    设置 async_mode=true 返回任务 ID，通过 /tasks/{task_id} 查询进度
    """
    from kb.zotero_processor import ZoteroImporter

    if req.async_mode:
        # 异步模式
        from kb.task_queue import task_queue
        from kb.task_executor import task_executor
        
        # 获取收藏夹信息
        importer = ZoteroImporter()
        collection_id = req.collection_id
        collection_name = req.collection_name or "Unknown"
        
        if not collection_id and req.collection_name:
            result = importer.get_collection_by_name(req.collection_name)
            if result and "collectionID" in result:
                collection_id = result["collectionID"]
                collection_name = result.get("collectionName", collection_name)
            elif result and "multiple" in result:
                raise HTTPException(status_code=400, detail=f"名称模糊，存在多个匹配，请用 collection_id 精确指定")
            else:
                raise HTTPException(status_code=400, detail=f"未找到收藏夹: {req.collection_name}")
        
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
        
        # 启动任务
        loop = get_executor_loop()
        asyncio.run_coroutine_threadsafe(
            task_executor.execute_task(task_id),
            loop
        )
        
        return IngestResponse(
            status="pending",
            task_id=task_id,
            message=f"Zotero {collection_name} 导入任务已提交，ID: {task_id}",
            source="zotero",
        )
    else:
        # 同步模式
        return _ingest_zotero_sync(kb_id, req)


def _ingest_zotero_sync(kb_id: str, req: ZoteroIngestRequest):
    """同步导入"""
    from kb.zotero_processor import ZoteroImporter
    from kb.document_processor import DocumentProcessorConfig, ProcessingProgress

    configure_llamaindex()
    embed_model = get_embed_model()

    vs = get_vector_store(kb_id)
    importer = ZoteroImporter()

    collection_id = req.collection_id
    collection_name = "Unknown"

    if collection_id:
        collections = importer.get_collections()
        for col in collections:
            if col["collectionID"] == collection_id:
                collection_name = col["collectionName"]
                break
    elif req.collection_name:
        result = importer.get_collection_by_name(req.collection_name)
        if result is None:
            return IngestResponse(status="error", message=f"未找到收藏夹: {req.collection_name}")
        if "multiple" in result:
            return IngestResponse(status="error", message=f"名称模糊，存在多个匹配")
        collection_id = result["collectionID"]
        collection_name = result["collectionName"]
    else:
        return IngestResponse(status="error", message="必须提供 collection_id 或 collection_name")

    progress_file = Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
    progress = ProcessingProgress.load(progress_file)

    if req.rebuild:
        vs.delete_table()
        progress = ProcessingProgress()

    stats = importer.import_collection(
        collection_id=collection_id,
        collection_name=collection_name,
        vector_store=vs,
        embed_model=embed_model,
        progress=progress,
        rebuild=req.rebuild,
    )

    importer.close()
    progress_file.unlink(missing_ok=True)

    return IngestResponse(
        status="success" if stats["failed"] == 0 else "partial",
        source="zotero",
        files_processed=stats["items"],
        nodes_created=stats["nodes"],
        failed=stats["failed"],
        message=f"Zotero {collection_name}: 导入 {stats['items']} 篇文献，创建 {stats['nodes']} 个节点"
    )


@app.post("/kbs/{kb_id}/ingest/obsidian", response_model=IngestResponse)
def ingest_obsidian(kb_id: str, req: ObsidianIngestRequest):
    """
    Obsidian vault 导入
    
    设置 async_mode=true 返回任务 ID，通过 /tasks/{task_id} 查询进度
    """
    vault_path = Path(req.vault_path)
    if not vault_path.exists():
        raise HTTPException(status_code=400, detail=f"Vault 路径不存在: {req.vault_path}")

    import_dir = vault_path
    if req.folder_path:
        import_dir = vault_path / req.folder_path
        if not import_dir.exists():
            raise HTTPException(status_code=400, detail=f"文件夹路径不存在: {req.folder_path}")

    if req.async_mode:
        # 异步模式
        from kb.task_queue import task_queue
        from kb.task_executor import task_executor
        
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
        
        # 启动任务
        loop = get_executor_loop()
        asyncio.run_coroutine_threadsafe(
            task_executor.execute_task(task_id),
            loop
        )
        
        return IngestResponse(
            status="pending",
            task_id=task_id,
            message=f"Obsidian {import_dir.name} 导入任务已提交，ID: {task_id}",
            source="obsidian",
        )
    else:
        # 同步模式
        return _ingest_obsidian_sync(kb_id, req)


def _ingest_obsidian_sync(kb_id: str, req: ObsidianIngestRequest):
    """同步导入"""
    from kb.obsidian_processor import ObsidianImporter
    from kb.document_processor import DocumentProcessorConfig, ProcessingProgress

    configure_llamaindex()
    embed_model = get_embed_model()

    vault_path = Path(req.vault_path)
    import_dir = vault_path
    if req.folder_path:
        import_dir = vault_path / req.folder_path

    vs = get_vector_store(kb_id)

    progress_file = Path.home() / ".llamaindex" / f"obsidian_{import_dir.name}_progress.json"
    progress = ProcessingProgress.load(progress_file)

    importer = ObsidianImporter(vault_root=vault_path)

    stats = importer.import_directory(
        directory=import_dir,
        vector_store=vs,
        embed_model=embed_model,
        progress=progress,
        exclude_patterns=req.exclude_patterns,
        recursive=req.recursive,
    )

    progress_file.unlink(missing_ok=True)

    return IngestResponse(
        status="success" if stats["failed"] == 0 else "partial",
        source="obsidian",
        files_processed=stats["files"],
        nodes_created=stats["nodes"],
        failed=stats["failed"],
        message=f"Obsidian {import_dir.name}: 导入 {stats['files']} 个文件，创建 {stats['nodes']} 个节点"
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
    """
    Obsidian 全库分类导入
    
    扫描 vault 中所有文件夹，按配置分类到不同知识库
    """
    from kb.task_queue import task_queue
    from kb.task_executor import task_executor
    from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS
    
    # 为每个知识库提交导入任务
    task_ids = []
    for mapping in OBSIDIAN_KB_MAPPINGS:
        if not mapping.folders:  # 跳过默认库（会单独导入）
            continue
            
        task_id = task_queue.submit_task(
            task_type="obsidian_classified",
            kb_id=mapping.kb_id,
            params={
                "folders": mapping.folders,
                "async_mode": True,
            },
            source=f"obsidian:{mapping.name}",
        )
        
        # 启动任务
        loop = get_executor_loop()
        asyncio.run_coroutine_threadsafe(
            task_executor.execute_task(task_id),
            loop
        )
        
        task_ids.append({
            "kb_id": mapping.kb_id,
            "name": mapping.name,
            "task_id": task_id,
        })
    
    return {
        "status": "pending",
        "message": f"已提交 {len(task_ids)} 个分类导入任务",
        "tasks": task_ids,
    }


@app.post("/kbs/{kb_id}/rebuild")
def rebuild_kb(kb_id: str, async_mode: bool = True):
    """重建知识库"""
    if async_mode:
        from kb.task_queue import task_queue
        from kb.task_executor import task_executor
        
        task_id = task_queue.submit_task(
            task_type="rebuild",
            kb_id=kb_id,
            params={},
            source=f"rebuild:{kb_id}",
        )
        
        # 启动任务
        loop = get_executor_loop()
        asyncio.run_coroutine_threadsafe(
            task_executor.execute_task(task_id),
            loop
        )
        
        return {
            "status": "pending",
            "task_id": task_id,
            "message": f"重建任务已提交，ID: {task_id}"
        }
    else:
        vs = get_vector_store(kb_id)
        vs.delete_table()
        return {"status": "rebuilt", "kb_id": kb_id}


# ============== Zotero 接口 ==============

@app.get("/zotero/collections")
def list_zotero_collections():
    """列出所有 Zotero 收藏夹"""
    from kb.zotero_processor import ZoteroImporter

    importer = ZoteroImporter()
    collections = importer.get_collections()
    importer.close()

    return {"collections": [{"id": c["collectionID"], "name": c["collectionName"]} for c in collections]}


@app.get("/zotero/collections/search")
def search_zotero_collections(q: str = None):
    """搜索 Zotero 收藏夹"""
    from kb.zotero_processor import ZoteroImporter

    if not q:
        return {"collections": [], "message": "请提供搜索关键词"}

    importer = ZoteroImporter()
    result = importer.get_collection_by_name(q)
    importer.close()

    if result is None:
        return {"collections": [], "message": f"未找到: {q}"}
    if "multiple" in result:
        return {"collections": result["matches"], "message": "多个匹配结果，请用 collection_id 精确指定"}
    return {"collections": [{"id": result["collectionID"], "name": result["collectionName"]}]}


# ============== Obsidian 接口 ==============

@app.get("/obsidian/vaults")
def list_obsidian_vaults():
    """列出常见的 Obsidian vault 位置"""
    vaults = []

    common_paths = [
        Path.home() / "Documents" / "Obsidian Vault",
        Path.home() / "Documents" / "Obsidian",
        Path.home() / "Obsidian",
        Path.home() / "iCloud Drive" / "Documents" / "Obsidian",
        Path.home() / "Dropbox" / "Obsidian",
    ]

    for vault_path in common_paths:
        if vault_path.exists():
            if (vault_path / ".obsidian").exists():
                md_count = len(list(vault_path.rglob("*.md")))
                vaults.append({
                    "path": str(vault_path),
                    "name": vault_path.name,
                    "note_count": md_count,
                })

    return {"vaults": vaults}


@app.get("/obsidian/vaults/{vault_name}")
def get_obsidian_vault_info(vault_name: str):
    """获取 Obsidian vault 信息"""
    vaults_response = list_obsidian_vaults()
    vaults = vaults_response.get("vaults", [])

    matched = None
    for vault in vaults:
        if vault["name"] == vault_name or vault_name in vault["path"]:
            matched = vault
            break

    if not matched:
        return {"vault": None, "message": f"未找到 vault: {vault_name}"}

    vault_path = Path(matched["path"])
    folders = []
    seen_names = set()
    for item in vault_path.rglob("*"):
        if item.is_dir() and not item.name.startswith("."):
            name = item.name
            if name not in seen_names:
                seen_names.add(name)
                folders.append({
                    "path": str(item.relative_to(vault_path)),
                    "name": name,
                })
    folders = folders[:20]

    return {
        "vault": matched,
        "folders": folders,
    }


# ============== 管理接口 ==============

@app.get("/admin/tables")
def list_tables():
    """列出所有向量表"""
    import lancedb

    tables = []
    base = Path("/volumes/online/llamaindex")

    if base.exists():
        for subdir in base.rglob("*"):
            if subdir.is_dir() and subdir.name.endswith(".lance"):
                try:
                    db = lancedb.connect(str(subdir.parent))
                    table = db.open_table(subdir.stem)
                    df = table.to_pandas()
                    tables.append(TableInfo(
                        name=subdir.stem,
                        row_count=len(df),
                        vector_dim=len(df["vector"].iloc[0]) if len(df) > 0 and "vector" in df.columns else 0,
                        persist_dir=str(subdir.parent),
                    ))
                except:
                    pass

    return {"tables": tables}


@app.get("/admin/tables/{table_name}")
def get_table_info(table_name: str):
    """获取表统计"""
    import lancedb

    base = Path("/volumes/online/llamaindex")

    for subdir in base.rglob("*"):
        if subdir.is_dir() and subdir.name == f"{table_name}.lance":
            db = lancedb.connect(str(subdir))
            table = db.open_table(table_name)
            df = table.to_pandas()
            return TableInfo(
                name=table_name,
                row_count=len(df),
                vector_dim=len(df["vector"].iloc[0]) if len(df) > 0 and "vector" in df.columns else 0,
                persist_dir=str(subdir),
            )

    raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")


@app.delete("/admin/tables/{table_name}")
def delete_table(table_name: str):
    """删除表"""
    base = Path("/volumes/online/llamaindex")

    for subdir in base.rglob("*"):
        if subdir.is_dir() and subdir.name == f"{table_name}.lance":
            vs = get_vector_store(table_name)
            vs.delete_table()
            return {"status": "deleted", "table": table_name}

    raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")


# ============== WebSocket 接口 ==============

@app.websocket("/ws/tasks")
async def websocket_tasks(websocket: WebSocket, task_id: str = None):
    """
    WebSocket 实时任务进度推送
    
    连接方式:
    - /ws/tasks                    # 接收所有任务更新
    - /ws/tasks?task_id=abc123     # 只接收指定任务更新
    """
    from kb.websocket_manager import ws_manager
    
    task_id_param = websocket.query_params.get("task_id")
    
    await ws_manager.connect(websocket, task_id_param or task_id)
    
    try:
        # 保持连接，接收消息
        while True:
            # 接收客户端消息（心跳等）
            data = await websocket.receive_text()
            
            # 处理心跳
            if data == "ping":
                await websocket.send_text("pong")
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket, task_id_param or task_id)


@app.websocket("/ws")
async def websocket_all(websocket: WebSocket):
    """
    WebSocket 全局连接
    
    接收所有系统消息广播
    """
    from kb.websocket_manager import ws_manager
    
    await ws_manager.connect(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)

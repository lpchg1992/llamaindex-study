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

    文档导入:
    POST /kbs/{kb_id}/ingest        - 通用文件导入
    POST /kbs/{kb_id}/ingest/zotero - Zotero 收藏夹导入
    POST /kbs/{kb_id}/ingest/obsidian - Obsidian vault 导入
    POST /kbs/{kb_id}/rebuild       - 重建知识库

    管理接口:
    GET  /admin/tables              - 列出所有向量表
    GET  /admin/tables/{name}       - 获取表统计
    DELETE /admin/tables/{name}     - 删除表
"""

import os
import sys
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
    description="RAG 检索增强生成 API，支持 Zotero、Obsidian 和通用文件导入",
    version="3.0.0",
    docs_url="/docs",
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


class ZoteroIngestRequest(BaseModel):
    """Zotero 收藏夹导入"""
    collection_id: Optional[int] = Field(None, description="Zotero 收藏夹 ID")
    collection_name: Optional[str] = Field(None, description="Zotero 收藏夹名称（与 collection_id 二选一）")
    rebuild: bool = Field(False, description="是否强制重建")


class ObsidianIngestRequest(BaseModel):
    """Obsidian vault 导入"""
    vault_path: str = Field(..., description="Obsidian vault 路径")
    folder_path: Optional[str] = Field(None, description="特定文件夹路径（可选）")
    recursive: bool = Field(True, description="是否递归")
    exclude_patterns: List[str] = Field(
        default=["*/image/*", "*/_resources/*", "*/.obsidian/*"],
        description="排除的文件模式"
    )


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


class IngestResponse(BaseModel):
    status: str
    source: str
    files_processed: int = 0
    nodes_created: int = 0
    failed: int = 0
    message: str = ""


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
    return {"status": "ok", "service": "llamaindex-rag-api", "version": "3.0.0"}


@app.get("/kbs", response_model=List[KBInfo])
def list_kbs():
    """列出所有知识库"""
    result = []
    base = Path("/volumes/online/llamaindex")

    if base.exists():
        for subdir in base.iterdir():
            if not subdir.is_dir():
                continue

            # 处理 zotero 子目录
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

    # 创建空的向量存储
    vs = get_vector_store(kb_id)

    # 保存配置
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


# ============== 文档导入接口 ==============

@app.post("/kbs/{kb_id}/ingest", response_model=IngestResponse)
def ingest_files(kb_id: str, req: IngestRequest):
    """
    通用文件导入

    从文件或文件夹路径导入文档，支持 PDF（含 OCR）、Word、Excel、PPTX、Markdown 等格式。
    """
    from kb.generic_processor import GenericImporter, FileImportConfig
    from kb.document_processor import DocumentProcessorConfig, ProcessingProgress

    configure_llamaindex()
    embed_model = get_embed_model()

    # 获取知识库配置
    persist_dir = get_kb_persist_dir(kb_id)
    config_file = persist_dir / "kb_config.json"
    chunk_size, chunk_overlap = 512, 50
    if config_file.exists():
        import json
        with open(config_file) as f:
            cfg = json.load(f)
            chunk_size = cfg.get("chunk_size", 512)
            chunk_overlap = cfg.get("chunk_overlap", 50)

    # 创建导入器
    importer = GenericImporter(
        config=FileImportConfig(source_name=kb_id),
        processor_config=DocumentProcessorConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ),
    )

    vs = get_vector_store(kb_id)

    # 导入
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

    从 Zotero 收藏夹导入文献，支持：
    - 文献元数据（标题、作者、标签）
    - 标注和笔记
    - PDF 附件（含扫描件 OCR）
    - Office 文档附件

    可以通过 collection_id 或 collection_name 指定收藏夹
    """
    from kb.zotero_processor import ZoteroImporter
    from kb.document_processor import DocumentProcessorConfig, ProcessingProgress

    configure_llamaindex()
    embed_model = get_embed_model()

    vs = get_vector_store(kb_id)

    importer = ZoteroImporter()

    # 确定收藏夹
    collection_id = req.collection_id
    collection_name = "Unknown"

    if collection_id:
        # 通过 ID 查找
        collections = importer.get_collections()
        for col in collections:
            if col["collectionID"] == collection_id:
                collection_name = col["collectionName"]
                break
    elif req.collection_name:
        # 通过名称查找
        result = importer.get_collection_by_name(req.collection_name)
        if result is None:
            return IngestResponse(
                status="error",
                source="zotero",
                message=f"未找到收藏夹: {req.collection_name}"
            )
        if "multiple" in result:
            matches = "\n".join([f"- [{m['collectionID']}] {m['collectionName']}" 
                               for m in result["matches"]])
            return IngestResponse(
                status="error",
                source="zotero",
                message=f"名称模糊，存在多个匹配:\n{matches}\n\n请使用 collection_id 精确指定"
            )
        collection_id = result["collectionID"]
        collection_name = result["collectionName"]
    else:
        return IngestResponse(
            status="error",
            source="zotero",
            message="必须提供 collection_id 或 collection_name"
        )

    # 加载进度
    progress_file = Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
    progress = ProcessingProgress.load(progress_file)

    if req.rebuild:
        vs.delete_table()
        progress = ProcessingProgress()

    # 导入
    stats = importer.import_collection(
        collection_id=collection_id,
        collection_name=collection_name,
        vector_store=vs,
        embed_model=embed_model,
        progress=progress,
        rebuild=req.rebuild,
    )

    importer.close()

    # 清理进度文件
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

    从 Obsidian vault 导入笔记，支持：
    - Markdown 文件解析
    - YAML frontmatter 提取
    - Wiki 链接和标签处理
    - PDF 附件（含扫描件 OCR）
    """
    from kb.obsidian_processor import ObsidianImporter
    from kb.document_processor import DocumentProcessorConfig, ProcessingProgress

    configure_llamaindex()
    embed_model = get_embed_model()

    # 确定 vault 根目录
    vault_path = Path(req.vault_path)
    if not vault_path.exists():
        raise HTTPException(status_code=400, detail=f"Vault 路径不存在: {req.vault_path}")

    # 确定导入目录
    import_dir = vault_path
    if req.folder_path:
        import_dir = vault_path / req.folder_path
        if not import_dir.exists():
            raise HTTPException(status_code=400, detail=f"文件夹路径不存在: {req.folder_path}")

    vs = get_vector_store(kb_id)

    # 加载进度
    progress_file = Path.home() / ".llamaindex" / f"obsidian_{import_dir.name}_progress.json"
    progress = ProcessingProgress.load(progress_file)

    # 创建导入器
    importer = ObsidianImporter(vault_root=vault_path)

    # 导入
    stats = importer.import_directory(
        directory=import_dir,
        vector_store=vs,
        embed_model=embed_model,
        progress=progress,
        exclude_patterns=req.exclude_patterns,
        recursive=req.recursive,
    )

    # 清理进度文件
    progress_file.unlink(missing_ok=True)

    return IngestResponse(
        status="success" if stats["failed"] == 0 else "partial",
        source="obsidian",
        files_processed=stats["files"],
        nodes_created=stats["nodes"],
        failed=stats["failed"],
        message=f"Obsidian {import_dir.name}: 导入 {stats['files']} 个文件，创建 {stats['nodes']} 个节点"
    )


@app.post("/kbs/{kb_id}/rebuild")
def rebuild_kb(kb_id: str):
    """重建知识库（清空并重新导入）"""
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

    # 常见路径
    common_paths = [
        Path.home() / "Documents" / "Obsidian Vault",
        Path.home() / "Documents" / "Obsidian",
        Path.home() / "Obsidian",
        Path.home() / "iCloud Drive" / "Documents" / "Obsidian",
        Path.home() / "Dropbox" / "Obsidian",
    ]

    for vault_path in common_paths:
        if vault_path.exists():
            # 检查是否有 .obsidian 目录
            if (vault_path / ".obsidian").exists():
                # 统计笔记数量
                md_count = len(list(vault_path.rglob("*.md")))
                vaults.append({
                    "path": str(vault_path),
                    "name": vault_path.name,
                    "note_count": md_count,
                })

    return {"vaults": vaults}


@app.get("/obsidian/vaults/{vault_name}")
def get_obsidian_vault_info(vault_name: str):
    """获取 Obsidian vault 信息（通过名称匹配）"""
    vaults_response = list_obsidian_vaults()
    vaults = vaults_response.get("vaults", [])

    # 匹配 vault
    matched = None
    for vault in vaults:
        if vault["name"] == vault_name or vault_name in vault["path"]:
            matched = vault
            break

    if not matched:
        return {"vault": None, "message": f"未找到 vault: {vault_name}"}

    # 扫描文件夹结构
    vault_path = Path(matched["path"])
    folders = []
    for item in vault_path.rglob("*"):
        if item.is_dir() and not item.name.startswith("."):
            rel_path = str(item.relative_to(vault_path))
            if "/" not in rel_path.replace("\\", "/").split("/")[1] if "/" in rel_path.replace("\\", "/") else True:
                # 只显示顶层目录
                pass
            folders.append({
                "path": rel_path,
                "name": item.name,
            })

    # 去重顶层目录
    top_folders = []
    seen_names = set()
    for f in folders:
        name = f["name"]
        if name not in seen_names:
            seen_names.add(name)
            top_folders.append(f)
    top_folders = top_folders[:20]

    return {
        "vault": matched,
        "folders": top_folders,
    }


# ============== 管理接口 ==============

@app.get("/admin/tables")
def list_tables():
    """列出所有向量表"""
    import lancedb

    tables = []
    base = Path("/volumes/online/llamaindex")

    if base.exists():
        # 扫描根目录
        for subdir in base.iterdir():
            if not subdir.is_dir():
                continue

            if subdir.name == "zotero":
                # 处理 zotero 子目录
                for zotero_subdir in subdir.iterdir():
                    if zotero_subdir.is_dir():
                        lance_file = zotero_subdir / f"{zotero_subdir.name}.lance"
                        if lance_file.exists():
                            try:
                                db = lancedb.connect(str(zotero_subdir))
                                table = db.open_table(zotero_subdir.name)
                                df = table.to_pandas()
                                tables.append(TableInfo(
                                    name=zotero_subdir.name,
                                    row_count=len(df),
                                    vector_dim=len(df["vector"].iloc[0]) if len(df) > 0 and "vector" in df.columns else 0,
                                    persist_dir=str(zotero_subdir),
                                ))
                            except:
                                pass
            else:
                lance_file = subdir / f"{subdir.name}.lance"
                if lance_file.exists():
                    try:
                        db = lancedb.connect(str(subdir))
                        table = db.open_table(subdir.name)
                        df = table.to_pandas()
                        tables.append(TableInfo(
                            name=subdir.name,
                            row_count=len(df),
                            vector_dim=len(df["vector"].iloc[0]) if len(df) > 0 and "vector" in df.columns else 0,
                            persist_dir=str(subdir),
                        ))
                    except:
                        pass

    return {"tables": tables}


@app.get("/admin/tables/{table_name}")
def get_table_info(table_name: str):
    """获取表统计"""
    import lancedb

    base = Path("/volumes/online/llamaindex")

    # 扫描
    for subdir in base.rglob("*"):
        if not subdir.is_dir():
            continue
        lance_file = subdir / f"{table_name}.lance"
        if lance_file.exists():
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
        if not subdir.is_dir():
            continue
        lance_file = subdir / f"{table_name}.lance"
        if lance_file.exists():
            vs = get_vector_store(table_name)
            vs.delete_table()
            return {"status": "deleted", "table": table_name}

    raise HTTPException(status_code=404, detail=f"表 {table_name} 不存在")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)

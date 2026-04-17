"""
Shared data models/schemas for the API.
Extracted from api.py to avoid circular imports.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Literal, Any
from dataclasses import dataclass
from pydantic import BaseModel, Field
import markdown


# ============== Shared Data Models ==============


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


class KBUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="知识库显示名称")
    description: Optional[str] = Field(None, description="知识库描述")


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


# ============== Zotero Request Models ==============


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


# ============== Obsidian Request Models ==============


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


class ObsidianIngestRequest(BaseModel):
    vault_path: str = Field(
        None, description="Vault 路径"
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


# ============== Document/Chunk Models ==============


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


class RefreshTopicsRequest(BaseModel):
    has_new_docs: bool = Field(True, description="是否按有新文档方式刷新 topics")


# ============== Chat/WebSocket Models ==============


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


# ============== Extraction Models ==============


class ExtractRequest(BaseModel):
    text: str
    schema_definition: Dict[str, Any]
    prompt_template: Optional[str] = None


class ExtractResponse(BaseModel):
    data: Dict[str, Any]
    error: Optional[str] = None


class TextToJsonRequest(BaseModel):
    text: str
    fields: List[str]
    prompt_template: Optional[str] = None


# ============== Settings Models ==============


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


# ============== Helper Functions ==============


def _parse_kb_ids_or_raise(kb_ids: Optional[str], route_mode: str) -> List[str]:
    """Parse kb_ids string and validate based on route_mode."""
    from fastapi import HTTPException

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


def _get_default_llm_model_id() -> Optional[str]:
    """Get the default LLM model ID."""
    from rag.config import get_model_registry

    registry = get_model_registry()
    default_llm = registry.get_default("llm")
    return default_llm["id"] if default_llm else None


def _set_default_llm_model(model_id: Optional[str]) -> None:
    """Set the default LLM model."""
    if not model_id:
        return
    from kb_core.database import init_model_db

    model_db = init_model_db()
    model_db.set_default(model_id)
    from rag.config import get_model_registry

    get_model_registry().reload()


def _update_env_file(updates: Dict[str, str]) -> None:
    """Update .env file with new values."""
    from pathlib import Path
    from rag.logger import get_logger

    logger = get_logger(__name__)
    env_path = Path(__file__).parent.parent / ".env"
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
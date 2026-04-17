"""
Settings management endpoints.
"""

from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException

from api.schemas import (
    SystemSettings,
    SettingsUpdateRequest,
    _get_default_llm_model_id,
    _set_default_llm_model,
    _update_env_file,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SystemSettings)
def get_settings():
    from rag.config import get_settings, get_model_registry

    s = get_settings()
    registry = None
    try:
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


@router.put("", response_model=SystemSettings)
def update_settings(req: SettingsUpdateRequest):
    from rag.config import get_settings
    from rag.logger import get_logger

    logger = get_logger(__name__)
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
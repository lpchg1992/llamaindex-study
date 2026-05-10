"""
Settings management endpoints.
"""

from fastapi import APIRouter

from api.schemas import (
    SystemSettings,
    SettingsUpdateRequest,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SystemSettings)
def get_settings():
    from rag.config import get_settings

    s = get_settings()

    return SystemSettings(
        embed_batch_size=s.embed_batch_size,
        top_k=s.top_k,
        use_semantic_chunking=s.use_semantic_chunking,
        use_hybrid_search=s.use_hybrid_search,
        use_auto_merging=s.use_auto_merging,
        auto_merging_simple_ratio_thresh=s.auto_merging_simple_ratio_thresh,
        retrieval_oversampling_factor=s.retrieval_oversampling_factor,
        use_hyde=s.use_hyde,
        use_multi_query=s.use_multi_query,
        num_multi_queries=s.num_multi_queries,
        hybrid_search_alpha=s.hybrid_search_alpha,
        hybrid_search_mode=s.hybrid_search_mode,
        chunk_strategy=s.chunk_strategy,
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        hierarchical_chunk_sizes=s.hierarchical_chunk_sizes,
        semantic_chunking_similarity_threshold=s.semantic_chunking_similarity_threshold,
        semantic_chunking_percentile_threshold=s.semantic_chunking_percentile_threshold,
        reference_strong_ratio=s.reference_strong_ratio,
        reference_moderate_ratio=s.reference_moderate_ratio,
        reference_weak_ratio=s.reference_weak_ratio,
        reference_moderate_min_matches=s.reference_moderate_min_matches,
        reference_weak_min_matches=s.reference_weak_min_matches,
        reference_weak_min_strong=s.reference_weak_min_strong,
        pdf_scan_threshold=s.pdf_scan_threshold,
        pdf_image_ratio_threshold=s.pdf_image_ratio_threshold,
        use_reranker=s.use_reranker,
        reference_strategy=s.reference_strategy,
        response_mode=s.response_mode,
        progress_update_interval=s.progress_update_interval,
        max_concurrent_tasks=s.max_concurrent_tasks,
        embed_concurrent_pool_size=s.embed_concurrent_pool_size,
        embed_endpoint_max_concurrent=s.embed_endpoint_max_concurrent,
        max_retries=s.max_retries,
        retry_delay=s.retry_delay,
        ollama_short_text_threshold=s.ollama_short_text_threshold,
        ollama_fanout_text_threshold=s.ollama_fanout_text_threshold,
        heartbeat_interval=s.heartbeat_interval,
        stale_task_timeout=s.stale_task_timeout,
        mineru_api_key=s.mineru_api_key or "",
        mineru_pipeline_id=s.mineru_pipeline_id or "",
        doc2x_api_key=s.doc2x_api_key or "",
        api_port=s.api_port,
        cors_extra_origins=s.cors_extra_origins,
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
            embed_batch_size=s.embed_batch_size,
            top_k=s.top_k,
            use_semantic_chunking=s.use_semantic_chunking,
            use_hybrid_search=s.use_hybrid_search,
        use_auto_merging=s.use_auto_merging,
        auto_merging_simple_ratio_thresh=s.auto_merging_simple_ratio_thresh,
        retrieval_oversampling_factor=s.retrieval_oversampling_factor,
        use_hyde=s.use_hyde,
        use_multi_query=s.use_multi_query,
        num_multi_queries=s.num_multi_queries,
        hybrid_search_alpha=s.hybrid_search_alpha,
        hybrid_search_mode=s.hybrid_search_mode,
        chunk_strategy=s.chunk_strategy,
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        hierarchical_chunk_sizes=s.hierarchical_chunk_sizes,
        semantic_chunking_similarity_threshold=s.semantic_chunking_similarity_threshold,
        semantic_chunking_percentile_threshold=s.semantic_chunking_percentile_threshold,
        reference_strong_ratio=s.reference_strong_ratio,
        reference_moderate_ratio=s.reference_moderate_ratio,
        reference_weak_ratio=s.reference_weak_ratio,
        reference_moderate_min_matches=s.reference_moderate_min_matches,
        reference_weak_min_matches=s.reference_weak_min_matches,
        reference_weak_min_strong=s.reference_weak_min_strong,
        pdf_scan_threshold=s.pdf_scan_threshold,
        pdf_image_ratio_threshold=s.pdf_image_ratio_threshold,
        use_reranker=s.use_reranker,
        reference_strategy=s.reference_strategy,
        response_mode=s.response_mode,
        progress_update_interval=s.progress_update_interval,
        max_concurrent_tasks=s.max_concurrent_tasks,
        embed_concurrent_pool_size=s.embed_concurrent_pool_size,
        embed_endpoint_max_concurrent=s.embed_endpoint_max_concurrent,
        max_retries=s.max_retries,
        retry_delay=s.retry_delay,
        ollama_short_text_threshold=s.ollama_short_text_threshold,
        ollama_fanout_text_threshold=s.ollama_fanout_text_threshold,
        heartbeat_interval=s.heartbeat_interval,
        stale_task_timeout=s.stale_task_timeout,
        mineru_api_key=s.mineru_api_key or "",
        mineru_pipeline_id=s.mineru_pipeline_id or "",
        doc2x_api_key=s.doc2x_api_key or "",
        api_port=s.api_port,
        cors_extra_origins=s.cors_extra_origins,
    )

    runtime_settings = {}
    applied = []
    skipped = []

    for key, value in updates.items():
        if key in (
            "top_k",
            "use_semantic_chunking",
            "use_hybrid_search",
            "use_auto_merging",
            "auto_merging_simple_ratio_thresh",
            "retrieval_oversampling_factor",
            "use_hyde",
            "use_multi_query",
            "num_multi_queries",
            "hybrid_search_alpha",
            "hybrid_search_mode",
            "chunk_strategy",
            "chunk_size",
            "chunk_overlap",
            "hierarchical_chunk_sizes",
            "semantic_chunking_similarity_threshold",
            "semantic_chunking_percentile_threshold",
            "reference_strong_ratio",
            "reference_moderate_ratio",
            "reference_weak_ratio",
            "reference_moderate_min_matches",
            "reference_weak_min_matches",
            "reference_weak_min_strong",
            "pdf_scan_threshold",
            "pdf_image_ratio_threshold",
            "embed_batch_size",
            "use_reranker",
            "reference_strategy",
            "response_mode",
            "progress_update_interval",
            "max_concurrent_tasks",
            "embed_concurrent_pool_size",
            "embed_endpoint_max_concurrent",
            "max_retries",
            "retry_delay",
            "ollama_short_text_threshold",
            "ollama_fanout_text_threshold",
            "heartbeat_interval",
            "stale_task_timeout",
            "mineru_api_key",
            "mineru_pipeline_id",
            "doc2x_api_key",
            "api_port",
            "cors_extra_origins",
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
        elif key in (
            "default_llm_model",
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

    if skipped:
        logger.warning(f"跳过未知设置: {skipped}")

    return SystemSettings(
        embed_batch_size=s.embed_batch_size,
        top_k=s.top_k,
        use_semantic_chunking=s.use_semantic_chunking,
        use_hybrid_search=s.use_hybrid_search,
        use_auto_merging=s.use_auto_merging,
        auto_merging_simple_ratio_thresh=s.auto_merging_simple_ratio_thresh,
        retrieval_oversampling_factor=s.retrieval_oversampling_factor,
        use_hyde=s.use_hyde,
        use_multi_query=s.use_multi_query,
        num_multi_queries=s.num_multi_queries,
        hybrid_search_alpha=s.hybrid_search_alpha,
        hybrid_search_mode=s.hybrid_search_mode,
        chunk_strategy=s.chunk_strategy,
        chunk_size=s.chunk_size,
        chunk_overlap=s.chunk_overlap,
        hierarchical_chunk_sizes=s.hierarchical_chunk_sizes,
        semantic_chunking_similarity_threshold=s.semantic_chunking_similarity_threshold,
        semantic_chunking_percentile_threshold=s.semantic_chunking_percentile_threshold,
        reference_strong_ratio=s.reference_strong_ratio,
        reference_moderate_ratio=s.reference_moderate_ratio,
        reference_weak_ratio=s.reference_weak_ratio,
        reference_moderate_min_matches=s.reference_moderate_min_matches,
        reference_weak_min_matches=s.reference_weak_min_matches,
        reference_weak_min_strong=s.reference_weak_min_strong,
        pdf_scan_threshold=s.pdf_scan_threshold,
        pdf_image_ratio_threshold=s.pdf_image_ratio_threshold,
        use_reranker=s.use_reranker,
        reference_strategy=s.reference_strategy,
        response_mode=s.response_mode,
        progress_update_interval=s.progress_update_interval,
        max_concurrent_tasks=s.max_concurrent_tasks,
        embed_concurrent_pool_size=s.embed_concurrent_pool_size,
        embed_endpoint_max_concurrent=s.embed_endpoint_max_concurrent,
        max_retries=s.max_retries,
        retry_delay=s.retry_delay,
        ollama_short_text_threshold=s.ollama_short_text_threshold,
        ollama_fanout_text_threshold=s.ollama_fanout_text_threshold,
        heartbeat_interval=s.heartbeat_interval,
        stale_task_timeout=s.stale_task_timeout,
        mineru_api_key=s.mineru_api_key or "",
        mineru_pipeline_id=s.mineru_pipeline_id or "",
        doc2x_api_key=s.doc2x_api_key or "",
        api_port=s.api_port,
        cors_extra_origins=s.cors_extra_origins,
    )
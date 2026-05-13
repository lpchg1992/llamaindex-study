"""
Search and query endpoints.
"""

from typing import List

from fastapi import APIRouter, HTTPException

from api.schemas import (
    SearchRequest,
    SearchResult,
    QueryRequest,
    QueryResponse,
    _parse_kb_ids_or_raise,
)
from rag.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["search"])


@router.post("/search", response_model=List[SearchResult])
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

    if req.route_mode == "all":
        result = QueryRouter.search(
            req.query,
            top_k=req.top_k,
            use_auto_merging=req.use_auto_merging,
            use_reranker=req.use_reranker,
            mode="all",
            model_id=req.model_id,
            embed_model_id=req.embed_model_id,
            retrieval_mode=req.retrieval_mode,
        )
        return [SearchResult(**r) for r in result.get("results", [])]

    kb_id_list = _parse_kb_ids_or_raise(req.kb_ids, req.route_mode)

    from kb_core.services import SearchService

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


@router.post("/query", response_model=QueryResponse)
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

        if req.route_mode == "all":
            result = QueryRouter.query(
                req.query,
                top_k=req.top_k,
                mode="all",
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

        if req.route_mode == "agent":
            result = QueryRouter.query(
                req.query,
                top_k=req.top_k,
                mode="agent",
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
                use_sub_question=req.use_sub_question,
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

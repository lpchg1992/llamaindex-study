from typing import List, Optional, Dict, Any, Callable

from rag.config import get_settings
from rag.logger import get_logger
from rag.ollama_utils import (
    create_parallel_ollama_embedding,
    configure_global_embed_model,
)

logger = get_logger(__name__)

from .vector_store import VectorStoreService

class SearchService:
    """搜索服务"""

    @staticmethod
    def search(
        kb_id: str,
        query: str,
        top_k: int = 5,
        with_metadata: bool = True,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        mode: str = "vector",
        embed_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from rag.config import get_settings

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            configure_global_embed_model()
        settings = get_settings()

        vs = VectorStoreService.get_vector_store(kb_id)
        index = vs.load_index()

        if index is None:
            return []

        base_retriever = index.as_retriever(similarity_top_k=top_k * 5)

        _use_auto_merging = (
            use_auto_merging
            if use_auto_merging is not None
            else settings.use_auto_merging
        )

        if _use_auto_merging:
            try:
                from rag.vector_store import LanceDBDocumentStore

                lance_docstore = LanceDBDocumentStore(kb_id=kb_id)
                lance_doc_count = len(lance_docstore)
                if lance_doc_count > 0:
                    logger.info(f"LanceDB docstore 有 {lance_doc_count} 个节点")
                    index.storage_context.docstore = lance_docstore

                    from llama_index.core.retrievers import AutoMergingRetriever

                    merger = AutoMergingRetriever(
                        base_retriever,
                        index.storage_context,
                        simple_ratio_thresh=0.25,
                        verbose=False,
                    )
                    retriever = merger
                    logger.info("Auto-Merging 已启用（使用 LanceDBDocumentStore）")
                else:
                    logger.warning("LanceDB docstore 为空，无法启用 Auto-Merging")
            except Exception as e:
                logger.warning(f"Auto-Merging 初始化失败: {e}")
        else:
            retriever = base_retriever

        # 支持 hybrid 检索模式
        if mode == "hybrid" or settings.use_hybrid_search:
            retriever = SearchService._create_hybrid_retriever(
                retriever, index, top_k, settings
            )

        results = retriever.retrieve(query)

        # Post-process: prefer parent nodes over children for longer context
        if _use_auto_merging:
            results = SearchService._prefer_parent_nodes(results)

        # Post-process: reranker 排序
        _use_reranker = (
            use_reranker if use_reranker is not None else settings.use_reranker
        )
        if _use_reranker and results:
            try:
                from rag.query_engine import apply_reranker

                results = apply_reranker(results, query, top_k=top_k)
                logger.info("SearchService: Reranker 已应用")
            except Exception as e:
                logger.warning(f"SearchService Reranker 应用失败: {e}")

        return [
            {
                "text": r.text,
                "score": r.score,
                "metadata": r.metadata or {},
            }
            for r in results[:top_k]
        ]

    @staticmethod
    def _prefer_parent_nodes(results: List) -> List:
        """优先返回父节点而非子节点
        
        在 Auto-Merging 检索模式下，优先返回较大的父节点，
        减少冗余并提供更完整的上下文。
        
        Args:
            results: 检索结果列表
            
        Returns:
            去重排序后的结果
        """
        if not results:
            return results

        parent_ids = set()
        child_to_parent = {}

        for r in results:
            node = getattr(r, "node", None)
            if node and hasattr(node, "parent_node") and node.parent_node:
                parent_id = node.parent_node.node_id
                child_to_parent[node.node_id] = parent_id
                parent_ids.add(parent_id)

        if not parent_ids:
            return results

        nodes_to_remove = set()
        for child_id, parent_id in child_to_parent.items():
            if parent_id in parent_ids:
                nodes_to_remove.add(child_id)

        filtered = [
            r
            for r in results
            if getattr(r.node, "node_id", None) not in nodes_to_remove
        ]
        filtered.sort(key=lambda x: x.score, reverse=True)
        return filtered

    @staticmethod
    def _create_hybrid_retriever(
        vector_retriever: Any,
        index: Any,
        top_k: int,
        settings: Any,
    ) -> Any:
        """使用 LanceDB 原生混合搜索（向量 + FTS/BM25）"""
        import lancedb
        from llama_index.core.vector_stores.types import VectorStoreQueryMode
        from llama_index.core.indices.vector_store.retrievers import (
            VectorIndexRetriever,
        )

        vector_store = index.vector_store
        if hasattr(vector_store, "_get_lance_vector_store"):
            lance_store = vector_store._get_lance_vector_store()
        else:
            lance_store = vector_store

        if hasattr(lance_store, "ensure_fts_index"):
            lance_store.ensure_fts_index()

        if settings.hybrid_search_mode == "RRF":
            reranker = lancedb.rerankers.RRFReranker()
        else:
            reranker = lancedb.rerankers.LinearCombinationReranker(
                weight=settings.hybrid_search_alpha
            )

        if hasattr(lance_store, "_reranker"):
            lance_store._reranker = reranker

        hybrid_retriever = VectorIndexRetriever(
            index,
            similarity_top_k=top_k,
            vector_store_query_mode=VectorStoreQueryMode.HYBRID,
            alpha=settings.hybrid_search_alpha,
        )

        logger.info(
            f"混合搜索: LanceDB 原生 hybrid, mode={settings.hybrid_search_mode}, alpha={settings.hybrid_search_alpha}"
        )
        return hybrid_retriever

    @staticmethod
    def search_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        mode: str = "vector",
        embed_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from rag.config import get_model_registry

        registry = get_model_registry()

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            default_embed = registry.get_default("embedding")
            if default_embed:
                from rag.ollama_utils import (
                    configure_embed_model_by_model_id,
                )

                configure_embed_model_by_model_id(default_embed["id"])
                from kb_processing.parallel_embedding import get_parallel_processor

                get_parallel_processor().set_model_by_model_id(default_embed["id"])
            else:
                configure_global_embed_model()

        all_results = []
        for kb_id in kb_ids:
            try:
                results = SearchService.search(
                    kb_id,
                    query,
                    top_k=top_k,
                    use_auto_merging=use_auto_merging,
                    use_reranker=use_reranker,
                    mode=mode,
                    embed_model_id=embed_model_id,
                )
                for r in results:
                    r["kb_id"] = kb_id
                all_results.extend(results)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    @staticmethod
    def query(
        kb_id: str,
        query: str,
        mode: str = "vector",
        top_k: int = 5,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        response_mode: Optional[str] = None,
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from rag.query_engine import create_query_engine

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            configure_global_embed_model()
        settings = get_settings()

        query_engine = create_query_engine(
            kb_id,
            mode=mode,
            top_k=top_k,
            use_auto_merging=use_auto_merging
            if use_auto_merging is not None
            else settings.use_auto_merging,
            use_hyde=use_hyde if use_hyde is not None else settings.use_hyde,
            use_multi_query=use_multi_query
            if use_multi_query is not None
            else settings.use_multi_query,
            num_multi_queries=num_multi_queries,
            use_reranker=use_reranker,
            response_mode=response_mode or settings.response_mode,
            model_id=model_id,
        )
        logger.info(
            f"[SearchService.query] use_hyde={use_hyde}, use_multi_query={use_multi_query}, num_multi_queries={num_multi_queries}, query_engine={type(query_engine).__name__}"
        )
        response = query_engine.query(query)
        logger.info(
            f"[SearchService.query] response={str(response)[:100]}, source_nodes={len(response.source_nodes)}"
        )

        if not response.source_nodes and use_multi_query:
            logger.warning("Multi-Query 返回空结果，尝试回退到普通查询")
            query_engine = create_query_engine(
                kb_id,
                mode=mode,
                top_k=top_k,
                use_auto_merging=use_auto_merging
                if use_auto_merging is not None
                else settings.use_auto_merging,
                use_hyde=use_hyde if use_hyde is not None else settings.use_hyde,
                use_multi_query=False,
                use_reranker=use_reranker,
                response_mode=response_mode or settings.response_mode,
                model_id=model_id,
            )
            response = query_engine.query(query)
            logger.info(
                f"[SearchService.query] fallback response={str(response)[:100]}, source_nodes={len(response.source_nodes)}"
            )

        return {
            "response": str(response),
            "sources": [
                {"text": r.text, "score": r.score} for r in response.source_nodes
            ],
        }

# =============================================================================

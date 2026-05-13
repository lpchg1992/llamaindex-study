import hashlib
import re
from typing import List, Optional, Dict, Any, Callable

from rag.logger import get_logger

logger = get_logger(__name__)

from .knowledge_base import KnowledgeBaseService
from .search import SearchService

class QueryRouter:
    """查询路由服务 — 使用 LlamaIndex LLMMultiSelector 语义匹配路由。

    .. todo:: 大知识库路由优化

       当前路由仅依据 KB 的 name + description 做语义匹配。对于内容
       覆盖广泛的 KB（如「动物营养」库包含数百个子主题），简短描述
       可能导致「发酵纤维」等具体查询匹配不到正确的 KB。

       待调研方案：
       1. 丰富 KB description 字段，列举子领域/关键词
          （改 registry.py + KB 创建界面）
       2. 两级检索：第一阶段全 KB 轻量检索（只取 top-1 score），
          第二阶段对高分 KB 做完整 RAG 查询
    """

    @staticmethod
    def route(
        query: str,
        top_k: int = 5,
        exclude: Optional[List[str]] = None,
        model_id: Optional[str] = None,
    ) -> List[str]:
        """根据查询语义路由到最相关的知识库。

        主路由使用 LlamaIndex LLMMultiSelector（基于 KB 名称 + 描述做语义匹配），
        降级方案使用简单关键词匹配（名称 + 描述，不使用 topics）。
        """
        kbs = KnowledgeBaseService.list_all()
        exclude = exclude or []

        if not kbs:
            return []

        kbs = [kb for kb in kbs if kb["id"] not in exclude]

        if len(kbs) == 1:
            return [kbs[0]["id"]]

        # Primary: LlamaIndex LLMMultiSelector semantic routing
        try:
            kb_ids = QueryRouter._selector_route(query, kbs, model_id=model_id)
            if kb_ids:
                return kb_ids[:top_k]
        except Exception as e:
            logger.warning(f"Selector routing failed: {e}")

        # Fallback: simple name/description keyword matching
        kb_ids = QueryRouter._simple_route(query, kbs)
        return kb_ids[:top_k]

    @staticmethod
    def _build_kb_description(kb: Dict[str, Any]) -> str:
        """Build a description string from KB metadata (NOT topics)."""
        parts = []
        if name := kb.get("name"):
            parts.append(name)
        if desc := kb.get("description"):
            parts.append(desc)
        doc_count = kb.get("row_count") or kb.get("document_count") or 0
        if doc_count > 0:
            parts.append(f"{doc_count} documents")
        return " — ".join(parts) if parts else kb["id"]

    @staticmethod
    def _selector_route(
        query: str,
        kbs: List[Dict[str, Any]],
        model_id: Optional[str] = None,
    ) -> List[str]:
        """Use LlamaIndex LLMMultiSelector to pick relevant KBs by name/description."""
        from llama_index.core.selectors import LLMMultiSelector
        from llama_index.core.tools import ToolMetadata

        choices = [
            ToolMetadata(
                name=kb["id"],
                description=QueryRouter._build_kb_description(kb),
            )
            for kb in kbs
        ]

        selector = LLMMultiSelector.from_defaults()
        result = selector.select(choices, query)
        return [s.id for s in result.selections]

    @staticmethod
    def _simple_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        """Fallback: match query tokens against KB name and description (no topics)."""
        tokens = QueryRouter._tokenize_query(query)
        scores: Dict[str, float] = {}
        for kb in kbs:
            score = 0.0
            kb_name = str(kb.get("name", "")).lower()
            kb_desc = str(kb.get("description", "")).lower()
            for token in tokens:
                if token in kb_name:
                    score += 2.0
                if token in kb_desc:
                    score += 1.0
            if score > 0:
                scores[kb["id"]] = score

        if scores:
            sorted_kbs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return [kid for kid, _ in sorted_kbs]

        indexed = sorted(
            [kb for kb in kbs if int(kb.get("document_count", 0) or kb.get("row_count", 0) or 0) > 0],
            key=lambda kb: int(kb.get("document_count", 0) or kb.get("row_count", 0) or 0),
            reverse=True,
        )
        if indexed:
            return [kb["id"] for kb in indexed]
        return [kb["id"] for kb in kbs]

    @staticmethod
    def _tokenize_query(query: str) -> List[str]:
        query_lower = query.lower().strip()
        tokens = {w for w in query_lower.replace(",", " ").split() if w}
        chinese_segments = re.findall(r"[\u4e00-\u9fff]+", query_lower)
        for seg in chinese_segments:
            tokens.add(seg)
            if len(seg) > 1:
                for i in range(len(seg) - 1):
                    tokens.add(seg[i : i + 2])
        return [t for t in tokens if t]

    # ------------------------------------------------------------------
    # Public query / search methods
    # ------------------------------------------------------------------

    @staticmethod
    def search(
        query: str,
        top_k: int = 5,
        mode: str = "auto",
        exclude: Optional[List[str]] = None,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
        retrieval_mode: str = "vector",
    ) -> Dict[str, Any]:
        if mode == "all":
            all_kbs = KnowledgeBaseService.list_all()
            exclude = exclude or []
            kb_ids = [kb["id"] for kb in all_kbs if kb["id"] not in exclude]
        else:
            kb_ids = QueryRouter.route(query, exclude=exclude, model_id=model_id)

        if not kb_ids:
            return {"results": [], "kbs_queried": [], "query": query}

        all_results = []
        for kb_id in kb_ids:
            try:
                results = SearchService.search(
                    kb_id,
                    query,
                    top_k=top_k,
                    use_auto_merging=use_auto_merging,
                    use_reranker=use_reranker,
                    mode=retrieval_mode,
                    embed_model_id=embed_model_id,
                )
                for r in results:
                    r["kb_id"] = kb_id
                all_results.extend(results)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return {
            "results": all_results[:top_k],
            "kbs_queried": kb_ids,
            "query": query,
        }

    @staticmethod
    def _resolve_kb_ids(
        query: str,
        mode: str,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        if mode == "all":
            all_kbs = KnowledgeBaseService.list_all()
            exclude = exclude or []
            return [kb["id"] for kb in all_kbs if kb["id"] not in exclude]
        return QueryRouter.route(query, exclude=exclude)

    @staticmethod
    def _query_across_kbs(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_sub_question: Optional[bool] = None,
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        all_sources = []
        kb_responses = []

        for kb_id in kb_ids:
            try:
                result = SearchService.query(
                    kb_id,
                    query,
                    mode=retrieval_mode,
                    top_k=top_k,
                    use_hyde=use_hyde,
                    use_multi_query=use_multi_query,
                    num_multi_queries=num_multi_queries,
                    use_auto_merging=use_auto_merging,
                    use_reranker=use_reranker,
                    use_sub_question=use_sub_question,
                    response_mode=response_mode,
                    model_id=model_id,
                    embed_model_id=embed_model_id,
                )
                kb_responses.append(f"[{kb_id}]\n{result['response']}")

                # Add kb_id to each source
                for src in result.get("sources", []):
                    src["kb_id"] = kb_id
                    all_sources.append(src)
            except Exception as e:
                logger = get_logger(__name__)
                logger.warning(f"知识库 {kb_id} 查询失败: {e}")
                continue

        if not kb_responses:
            return {
                "response": "在所有知识库中都没有找到相关内容",
                "sources": [],
                "kbs_queried": kb_ids,
            }

        # Sort sources by score descending and deduplicate
        all_sources.sort(key=lambda x: x.get("score", 0), reverse=True)

        unique_sources = _deduplicate_sources(all_sources)

        if len(kb_responses) <= 1:
            combined_response = kb_responses[0] if kb_responses else "No results"
        else:
            combined_response = _synthesize_cross_kb_response(
                query, kb_responses, kb_ids, model_id
            )

        return {
            "response": combined_response,
            "sources": unique_sources[:top_k],
            "kbs_queried": kb_ids,
        }

    @staticmethod
    def query(
        query: str,
        top_k: int = 5,
        mode: str = "auto",
        exclude: Optional[List[str]] = None,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        use_sub_question: Optional[bool] = None,
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """自动路由 RAG 问答

        Args:
            query: 用户查询
            top_k: 每个知识库检索的数量
            mode: 路由模式 (auto=自动路由, all=所有知识库, agent=ReAct Agent模式)
            exclude: 排除的知识库 ID 列表
            use_hyde: 启用 HyDE（None=使用配置默认值）
            use_multi_query: 启用多查询转换（None=使用配置默认值）
            num_multi_queries: 多查询变体数量（None=使用配置默认值）
            use_auto_merging: 启用 Auto-Merging（None=使用配置默认值）
            response_mode: 答案生成模式（None=使用配置默认值）
            retrieval_mode: 检索模式 (vector, hybrid)
            model_id: 使用的LLM模型ID (None=使用默认模型)
            embed_model_id: 使用的Embedding模型ID (None=使用默认模型)

        Returns:
            RAG 问答结果
        """
        if model_id:
            from rag.ollama_utils import configure_llm_by_model_id

            configure_llm_by_model_id(model_id)

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)

        kb_ids = QueryRouter._resolve_kb_ids(
            query=query,
            mode=mode,
            exclude=exclude,
        )

        if not kb_ids:
            return {
                "response": "没有找到相关的知识库",
                "sources": [],
                "kbs_queried": [],
            }

        if mode == "agent":
            return QueryRouter._query_with_agent(
                kb_ids=kb_ids,
                query=query,
                top_k=top_k,
                model_id=model_id,
            )

        if len(kb_ids) == 1:
            return SearchService.query(
                kb_ids[0],
                query,
                mode=retrieval_mode,
                top_k=top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                num_multi_queries=num_multi_queries,
                use_auto_merging=use_auto_merging,
                use_reranker=use_reranker,
                use_sub_question=use_sub_question,
                response_mode=response_mode,
                model_id=model_id,
                embed_model_id=embed_model_id,
            )

        return QueryRouter._query_across_kbs(
            kb_ids=kb_ids,
            query=query,
            top_k=top_k,
            use_auto_merging=use_auto_merging,
            use_reranker=use_reranker,
            use_hyde=use_hyde,
            use_multi_query=use_multi_query,
            num_multi_queries=num_multi_queries,
            response_mode=response_mode,
            retrieval_mode=retrieval_mode,
            model_id=model_id,
            embed_model_id=embed_model_id,
        )

    @staticmethod
    def query_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_auto_merging: Optional[bool] = None,
        use_reranker: Optional[bool] = None,
        use_sub_question: Optional[bool] = None,
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
        use_agent: bool = False,
    ) -> Dict[str, Any]:
        from rag.config import get_model_registry

        registry = get_model_registry()

        if model_id:
            from rag.ollama_utils import configure_llm_by_model_id

            configure_llm_by_model_id(model_id)
        else:
            default_llm = registry.get_default("llm")
            if default_llm:
                from rag.ollama_utils import configure_llm_by_model_id

                configure_llm_by_model_id(default_llm["id"])

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

        if not kb_ids:
            return {
                "response": "没有指定知识库",
                "sources": [],
                "kbs_queried": [],
            }

        if use_agent:
            return QueryRouter._query_with_agent(
                kb_ids=kb_ids,
                query=query,
                top_k=top_k,
                model_id=model_id,
            )

        if len(kb_ids) == 1:
            return SearchService.query(
                kb_ids[0],
                query,
                mode=retrieval_mode,
                top_k=top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                num_multi_queries=num_multi_queries,
                use_auto_merging=use_auto_merging,
                use_reranker=use_reranker,
                use_sub_question=use_sub_question,
                response_mode=response_mode,
                model_id=model_id,
                embed_model_id=embed_model_id,
            )

        return QueryRouter._query_across_kbs(
            kb_ids=kb_ids,
            query=query,
            top_k=top_k,
            use_auto_merging=use_auto_merging,
            use_reranker=use_reranker,
            use_hyde=use_hyde,
            use_multi_query=use_multi_query,
            num_multi_queries=num_multi_queries,
            use_sub_question=use_sub_question,
            response_mode=response_mode,
            retrieval_mode=retrieval_mode,
            model_id=model_id,
            embed_model_id=embed_model_id,
        )

    @staticmethod
    def _query_with_agent(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from rag.agent import query_with_agent
        from rag.query_engine import create_query_engine
        from llama_index.core.tools import QueryEngineTool, ToolMetadata

        if len(kb_ids) == 1:
            return query_with_agent(
                kb_id=kb_ids[0],
                query=query,
                model_id=model_id,
            )

        tools = []
        for kb_id in kb_ids:
            try:
                engine = create_query_engine(kb_id=kb_id, mode="vector", top_k=top_k)
                tool = QueryEngineTool(
                    query_engine=engine,
                    metadata=ToolMetadata(
                        name=f"kb_{kb_id}",
                        description=f"Search knowledge base '{kb_id}' for relevant information",
                    ),
                )
                tools.append(tool)
            except Exception as e:
                logger.warning(f"Failed to create engine for KB {kb_id}: {e}")
                continue

        if not tools:
            return {
                "response": "No knowledge bases available for agent query",
                "sources": [],
                "kbs_queried": kb_ids,
            }

        from rag.agent import create_react_agent

        try:
            agent = create_react_agent(kb_id=kb_ids[0], tools=tools, model_id=model_id)
            response = agent.chat(query)
            return {
                "response": str(response),
                "sources": [],
                "kbs_queried": kb_ids,
            }
        except Exception as e:
            logger.error(f"Agent query failed: {type(e).__name__}: {e}")
            return {
                "response": f"Agent query failed: {type(e).__name__}: {str(e)}",
                "sources": [],
                "kbs_queried": kb_ids,
            }

# =============================================================================


def _deduplicate_sources(sources: list) -> list:
    seen_hashes = set()
    unique = []
    for s in sorted(sources, key=lambda x: x.get("score", 0), reverse=True):
        text_prefix = s.get("text", "")[:200]
        text_hash = hashlib.md5(text_prefix.encode()).hexdigest()
        if text_hash not in seen_hashes:
            seen_hashes.add(text_hash)
            unique.append(s)
    return unique


def _synthesize_cross_kb_response(
    query: str,
    kb_responses: list,
    kb_ids: list,
    model_id: Optional[str] = None,
) -> str:
    try:
        from rag.ollama_utils import create_llm

        parts = []
        for i, resp in enumerate(kb_responses):
            parts.append(f"[Knowledge Base {kb_ids[i]}]:\n{resp}")
        combined = "\n\n".join(parts)

        prompt = (
            "You are synthesizing answers from multiple knowledge bases. "
            "Combine the information into a single coherent answer. "
            "Remove duplicate information. If sources contradict, note the discrepancy.\n\n"
            f"User Query: {query}\n\n"
            f"Knowledge Base Responses:\n{combined}\n\n"
            "Synthesized Answer:"
        )

        llm = create_llm(model_id=model_id)
        response = llm.complete(prompt)
        return str(response).strip()
    except Exception:
        return "\n\n---\n\n".join(kb_responses)

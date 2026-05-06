import re
from typing import List, Optional, Dict, Any, Callable

from rag.logger import get_logger

logger = get_logger(__name__)

from .knowledge_base import KnowledgeBaseService
from .search import SearchService

class QueryRouter:
    """查询路由服务 - 自动选择知识库"""

    @staticmethod
    def route(
        query: str,
        top_k: int = 5,
        exclude: Optional[List[str]] = None,
        model_id: Optional[str] = None,
    ) -> List[str]:
        """根据查询内容路由到最相关的知识库

        Args:
            query: 用户查询
            top_k: 返回最相关的 top_k 个知识库
            exclude: 排除的知识库 ID 列表
            model_id: 使用的LLM模型ID (None=使用默认Ollama模型)

        Returns:
            知识库 ID 列表
        """
        kbs = KnowledgeBaseService.list_all()
        exclude = exclude or []

        if not kbs:
            return []

        kbs = [kb for kb in kbs if kb["id"] not in exclude]

        if len(kbs) == 1:
            return [kbs[0]["id"]]

        kb_ids = QueryRouter._llm_route(query, kbs, model_id=model_id)

        if not kb_ids:
            kb_ids = QueryRouter._keyword_route(query, kbs)

        if not kb_ids:
            kb_ids = QueryRouter._fallback_route(query, kbs)

        return kb_ids[:top_k]

    @staticmethod
    def _llm_route(
        query: str,
        kbs: List[Dict[str, Any]],
        model_id: Optional[str] = None,
    ) -> List[str]:
        """使用 LLM 进行知识库路由

        Args:
            query: 用户查询
            kbs: 知识库列表
            model_id: 使用的LLM模型ID (None=使用默认Ollama模型)

        Returns:
            知识库 ID 列表
        """
        try:
            from rag.ollama_utils import create_llm

            kb_descriptions = []
            for kb in kbs:
                topics = kb.get("topics", [])
                topics_str = ", ".join(topics) if topics else "无"
                kb_descriptions.append(f"- {kb['id']}: {topics_str}")

            kb_list_text = "\n".join(kb_descriptions)

            prompt = f"""分析用户问题，从知识库列表中找出所有可能相关的知识库。

重要原则：
- 仅根据每个知识库的主题关键词（topics）进行判断
- 如果问题中的关键词与某知识库的主题高度重合，则选择该库
- 主题关键词完全不匹配的知识库不要选择
- 宁可精确匹配，也不要随意扩展

知识库列表：
{kb_list_text}

用户问题：{query}

请先分析问题中的关键词，然后与每个知识库的主题进行匹配，返回最相关的知识库 ID，用逗号分隔。

返回格式示例：kb1,kb2,kb3

请只返回 ID 列表，不要其他内容。"""

            llm = create_llm(model_id=model_id)
            response = llm.complete(prompt)
            result = response.text.strip()

            selected = [kb_id.strip() for kb_id in result.split(",")]

            valid_ids = {kb["id"] for kb in kbs}
            selected = [kb_id for kb_id in selected if kb_id in valid_ids]

            return selected

        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(f"LLM 路由失败: {e}")
            return []

    @staticmethod
    def _keyword_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        """使用关键词匹配进行知识库路由（仅基于 topics）"""
        query_words = QueryRouter._tokenize_query(query)

        scores: Dict[str, float] = {}

        for kb in kbs:
            kb_id = kb["id"]
            topics = kb.get("topics", [])
            if not topics:
                continue

            score = 0.0
            for word in query_words:
                if len(word) < 1:
                    continue
                for topic in topics:
                    topic_lower = topic.lower()
                    if word in topic_lower:
                        score += 1.0
                    if len(topic_lower) >= 2 and topic_lower in word:
                        score += 0.5

            if score > 0:
                scores[kb_id] = score

        if not scores:
            return []

        sorted_kbs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [kb_id for kb_id, _ in sorted_kbs]

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

    @staticmethod
    def _fallback_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        tokens = QueryRouter._tokenize_query(query)
        scores: Dict[str, float] = {}
        for kb in kbs:
            kb_id = kb["id"]
            kb_name = str(kb.get("name", "")).lower()
            kb_desc = str(kb.get("description", "")).lower()
            kb_topics = [str(t).lower() for t in (kb.get("topics") or [])]
            score = 0.0
            for token in tokens:
                if token in kb_name:
                    score += 1.0
                if token in kb_desc:
                    score += 0.8
                for topic in kb_topics:
                    if token in topic:
                        score += 1.2
            if score > 0:
                scores[kb_id] = score

        if scores:
            sorted_kbs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return [kb_id for kb_id, _ in sorted_kbs]

        indexed_kbs = sorted(
            [kb for kb in kbs if int(kb.get("row_count", 0) or 0) > 0],
            key=lambda kb: int(kb.get("row_count", 0) or 0),
            reverse=True,
        )
        if indexed_kbs:
            return [kb["id"] for kb in indexed_kbs]
        return [kb["id"] for kb in kbs]

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

        # Sort sources by score descending
        all_sources.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Combine responses from all KBs
        combined_response = "\n\n---\n\n".join(kb_responses)

        return {
            "response": combined_response,
            "sources": all_sources[: top_k * 3],
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
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """自动路由 RAG 问答

        Args:
            query: 用户查询
            top_k: 每个知识库检索的数量
            mode: 路由模式 (auto=自动路由, all=所有知识库)
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
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
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

# =============================================================================

"""
查询引擎模块

封装 LlamaIndex 的查询引擎，提供统一的查询接口。
支持流式输出、自定义参数、对话模式等功能。
"""

import httpx
from typing import Any, Optional, List

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle, MetadataMode

from rag.config import get_settings
from rag.logger import get_logger

logger = get_logger(__name__)


def _format_node_with_metadata(node: NodeWithScore) -> str:
    metadata = node.metadata or {}
    parts = []
    if file_name := metadata.get("file_name"):
        parts.append(f"[文档: {file_name}]")
    if page_label := metadata.get("page_label"):
        parts.append(f"[页码: {page_label}]")
    if source := metadata.get("source"):
        parts.append(f"[来源: {source}]")
    if categories := metadata.get("categories"):
        if isinstance(categories, list):
            parts.append(f"[分类: {' | '.join(categories)}]")
    text = node.get_content(metadata_mode=MetadataMode.NONE)
    if parts:
        return " ".join(parts) + f"\n{text}"
    return text


def _get_reranker_config() -> tuple[str, str, str, str, str]:
    """从数据库获取默认 reranker 配置，返回 (model, api_key, base_url, vendor_id, model_id)"""
    from kb_core.database import init_vendor_db
    from rag.config import get_model_registry

    registry = get_model_registry()
    model = registry.get_default("reranker")
    if not model:
        raise RuntimeError(
            "No default reranker model found in registry. "
            "Please add a reranker model via CLI or API."
        )

    vendor_db = init_vendor_db()
    vendor_info = vendor_db.get(model["vendor_id"])
    if not vendor_info:
        raise RuntimeError(f"Vendor '{model['vendor_id']}' not found in database.")

    api_key = vendor_info.get("api_key", "")
    base_url = vendor_info.get("api_base", "https://api.siliconflow.cn/v1")
    return model["name"], api_key, base_url, model["vendor_id"], model["id"]


class SiliconFlowReranker(BaseNodePostprocessor):
    api_key: str
    model: str = "Pro/BAAI/bge-reranker-v2-m3"
    base_url: str = "https://api.siliconflow.cn/v1"
    top_n: int = 5
    _vendor_id: str = "siliconflow"
    _model_id: str = "siliconflow/bge-reranker-v2-m3"

    def _record_reranker_call(self, token_count: int, error: bool):
        from rag.callbacks import record_model_call
        record_model_call(
            vendor_id=self._vendor_id,
            model_type="reranker",
            model_id=self._model_id,
            prompt_tokens=token_count,
            completion_tokens=0,
            error=error,
        )

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle,
    ) -> list[NodeWithScore]:
        if not nodes:
            return nodes

        documents = [_format_node_with_metadata(node) for node in nodes]
        payload = {
            "model": self.model,
            "query": query_bundle.query_str,
            "documents": documents,
            "top_n": min(self.top_n, len(documents)),
        }

        query_len = len(query_bundle.query_str)
        doc_lens = [len(d) for d in documents]
        total_input_tokens = query_len + sum(doc_lens)

        print(f"   🔄 SiliconFlow Reranker: 正在对 {len(nodes)} 个结果进行重排序...")

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/rerank",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
                response.raise_for_status()
                api_results = response.json()["results"]
            self._record_reranker_call(total_input_tokens, False)
        except Exception as e:
            self._record_reranker_call(total_input_tokens, True)
            print(f"   ❌ Reranker 调用失败: {e}")
            raise

        index_to_score = {
            item["index"]: item["relevance_score"] for item in api_results
        }
        for node in nodes:
            node.score = index_to_score.get(nodes.index(node), 0.0)

        nodes.sort(key=lambda n: n.score or 0.0, reverse=True)
        print(f"   ✅ Reranker 完成: Top-{min(self.top_n, len(nodes))} 结果")
        return nodes[: self.top_n]


def apply_reranker(
    nodes: list,
    query: str,
    top_k: int = 5,
) -> list:
    """对检索结果应用 SiliconFlow Reranker 排序

    Args:
        nodes: NodeWithScore 列表
        query: 查询字符串
        top_k: 返回结果数量

    Returns:
        排序后的 NodeWithScore 列表
    """
    if not nodes:
        return nodes

    rerank_model, api_key, base_url, vendor_id, model_id = _get_reranker_config()
    reranker = SiliconFlowReranker(
        api_key=api_key,
        model=rerank_model,
        base_url=base_url,
        top_n=top_k,
    )
    reranker._vendor_id = vendor_id
    reranker._model_id = model_id
    from llama_index.core.schema import QueryBundle

    return reranker._postprocess_nodes(nodes, QueryBundle(query_str=query))


# Multi-Query 默认 Prompt
DEFAULT_MULTI_QUERY_PROMPT = """你是一个查询增强专家。你的任务是根据用户问题，生成 {num_queries} 个不同的查询变体。

核心原则：保持查询在同一个语义空间内，变化用词但不改变概念边界。

要求：
1. 每个变体从不同角度或用不同措辞表达同一个问题
2. 变体之间要有差异化，但仅限于调换语序、补充限定词、拆分/合并子问题
3. 严格保持原问题的核心概念不变：禁止将专业术语替换为近义词（如"diarrhea"不可换成"enteritis"、"piglet"不可换成"neonatal swine"）
4. 如果原问题已经是精炼的专业表达，则变换查询结构而非替换关键词
5. 重要：必须保留原问题中的所有实体词（动物名称、品种、病症、药物、营养素等），只变换功能词和句式
6. 只输出查询变体，每行一个，不要其他解释

原问题：{query_str}

生成 {num_queries} 个查询变体："""


def generate_query_variants(llm: Any, query_str: str, num_queries: int = 3) -> list[str]:
    """使用 LLM 生成 N 个不同角度的查询变体"""
    prompt = DEFAULT_MULTI_QUERY_PROMPT.format(
        num_queries=num_queries,
        query_str=query_str,
    )
    try:
        response = llm.complete(prompt)
        variants = []
        for line in str(response).strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                line = line.lstrip("0123456789.、、）)")
                if line:
                    variants.append(line)
        if not variants:
            logger.warning(f"LLM 未生成有效变体，使用原始查询: {query_str}")
            return [query_str]
        logger.debug(f"生成了 {len(variants)} 个查询变体: {variants}")
        return variants
    except Exception as e:
        logger.warning(f"生成查询变体失败: {e}，使用原始查询")
        return [query_str]


class _FixedQueryRetriever:
    """包装基础检索器，使用固定查询字符串而非输入查询"""

    def __init__(self, base_retriever: Any, fixed_query: str):
        self.base_retriever = base_retriever
        self.fixed_query = fixed_query

    def retrieve(self, query_str: str) -> list[Any]:
        return self.base_retriever.retrieve(self.fixed_query)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base_retriever, name)


class MultiQueryFusionRetriever:
    """多查询变体融合检索器

    策略：用户查询 → LLM 生成 N 个查询变体 → 每个变体独立检索 → RRF 融合

    优化：
    - variant_score_threshold: 变体检索结果的向量相似度阈值，
      低于此值的 chunk 不参与 RRF 融合，防止语义漂移变体引入低质 chunk
    - original_query_weight: 原始查询结果的权重加成系数，
      确保原始查询的精准匹配不会被变体的高相似度误匹配压过
    """

    def __init__(
        self,
        base_retriever: Any,
        llm: Any,
        num_queries: int = 3,
        top_k: int = 5,
        variant_score_threshold: float = 0.5,
        original_query_weight: float = 1.5,
    ):
        self.base_retriever = base_retriever
        self.llm = llm
        self.num_queries = num_queries
        self.top_k = top_k
        self.variant_score_threshold = variant_score_threshold
        self.original_query_weight = original_query_weight
        self._query_variants: list[str] = []
        self._retrievers: list[Any] = []

    def _generate_and_setup_retrievers(self, query_str: str) -> None:
        self._query_variants = generate_query_variants(
            self.llm, query_str, self.num_queries
        )
        self._retrievers = [
            _FixedQueryRetriever(self.base_retriever, variant)
            for variant in self._query_variants
        ]
        logger.debug(
            f"MultiQueryFusionRetriever: 生成了 {len(self._query_variants)} 个变体"
        )

    def _rrf_fusion(self, results: list[tuple], top_k: int) -> list[Any]:
        """Best-Rank RRF：取每个节点在各变体中的最高排名得分，而非累加。

        累加式 RRF（score += weight/(k+rank)）会让「在所有变体中都排第 3」
        的平庸节点，击败「只在原始查询排第 1」的高相关节点。
        Best-Rank 策略避免了这种对「跨变体多次出现」的过度奖励，
        适合于多查询变体共享同一个 base_retriever（信号高度相关）的场景。

        同时使用 node.node_id 做去重（比 id() 可靠，不同检索批次可能
        返回同一逻辑节点的不同 Python 对象）。
        """
        k = 60
        fused_scores: dict = {}
        for node_with_score, weight, rank in results:
            node_obj = node_with_score.node
            node_id = getattr(node_obj, "node_id", None) or id(node_obj)
            score = weight / (k + rank)
            if node_id not in fused_scores or score > fused_scores[node_id]["score"]:
                fused_scores[node_id] = {"node": node_with_score, "score": score}
        sorted_results = sorted(
            fused_scores.values(),
            key=lambda x: x["score"],
            reverse=True,
        )
        return [item["node"] for item in sorted_results[:top_k]]

    def retrieve(self, query_str: str) -> list[Any]:
        if not self._retrievers:
            self._generate_and_setup_retrievers(query_str)
        all_nodes_with_scores: list[tuple[Any, float, int]] = []
        for i, retriever in enumerate(self._retrievers):
            nodes = retriever.retrieve(query_str)
            is_original = (i == 0)
            for rank, node_with_score in enumerate(nodes):
                original_score = getattr(node_with_score, "score", 1.0)
                if original_score is None:
                    original_score = 1.0
                if not is_original and original_score < self.variant_score_threshold:
                    continue
                weight = original_score * (self.original_query_weight if is_original else 1.0)
                all_nodes_with_scores.append((node_with_score, weight, rank + 1))
        return self._rrf_fusion(all_nodes_with_scores, self.top_k)

    def __call__(self, query_str: str) -> list[Any]:
        return self.retrieve(query_str)


class QueryEngineWrapper:
    """
    查询引擎封装类

    封装 LlamaIndex 的查询引擎，提供简洁的查询接口。
    LLM：硅基流动（OpenAI 兼容）
    Embedding：本地 Ollama
    """

    def __init__(
        self,
        index: Any,
        top_k: Optional[int] = None,
        use_reranker: Optional[bool] = None,
        use_auto_merging: bool = False,
        auto_merging_threshold: float = 0.5,
        mode: str = "vector",
        use_hyde: bool = False,
        use_multi_query: bool = False,
        num_multi_queries: Optional[int] = None,
        response_mode: str = "compact",
        vector_store: Optional[Any] = None,
        model_id: Optional[str] = None,
        rerank_model: Optional[str] = None,
        rerank_api_key: Optional[str] = None,
        rerank_base_url: Optional[str] = None,
        chat_mode: str = "condense_question",
    ):
        """
        初始化查询引擎

        Args:
            index: VectorStoreIndex 实例
            top_k: 检索返回的节点数量
            use_reranker: 是否使用 reranker（None=读取 .env 配置，True=启用，False=禁用）
            use_auto_merging: 是否使用 Auto-Merging Retriever（需要知识库使用 HierarchicalNodeParser 构建）
            auto_merging_threshold: 自动合并阈值（0-1），默认从配置读取
            mode: 检索模式 ("vector", "hybrid")，默认 "vector"
            use_hyde: 是否使用 HyDE（假设文档嵌入）
            use_multi_query: 是否使用多查询转换
            num_multi_queries: 多查询变体数量（None=使用配置默认值）
            response_mode: Response Synthesizer 模式
            vector_store: 向量存储实例（用于检测 chunk_strategy）
            model_id: 使用的模型ID (None=使用默认模型)
            rerank_model: Reranker 模型名称 (None=从注册表获取)
            rerank_api_key: Reranker API Key (None=从注册表获取)
            rerank_base_url: Reranker API Base URL (None=从注册表获取)
            chat_mode: LlamaIndex chat engine mode. One of:
                "condense_question" (default), "context",
                "condense_plus_context", "simple", "best".
        """
        self.index = index
        self.vector_store = vector_store
        self.settings = get_settings()
        self.top_k = top_k or self.settings.top_k
        if use_reranker is None:
            self.use_reranker = self.settings.use_reranker
        else:
            self.use_reranker = use_reranker
        self.use_auto_merging = use_auto_merging
        self.auto_merging_threshold = auto_merging_threshold
        self.mode = mode
        self.use_hyde = use_hyde or self.settings.use_hyde
        self.use_multi_query = use_multi_query or self.settings.use_multi_query
        self.num_multi_queries = num_multi_queries or self.settings.num_multi_queries
        self.response_mode = response_mode or self.settings.response_mode
        self.model_id = model_id
        self.chat_mode = chat_mode

        self._rerank_vendor_id: Optional[str] = None
        self._rerank_model_id: Optional[str] = None
        if self.use_reranker:
            if rerank_model:
                self._rerank_model = rerank_model
                from rag.config import get_model_registry
                from kb_core.database import init_vendor_db
                registry = get_model_registry()
                model_info = registry.get_model(rerank_model)
                if model_info:
                    self._rerank_vendor_id = model_info.get("vendor_id", "siliconflow")
                    self._rerank_model_id = model_info.get("id")
                    vendor_db = init_vendor_db()
                    vendor = vendor_db.get(self._rerank_vendor_id)
                    if vendor:
                        rerank_api_key = rerank_api_key or vendor.get("api_key")
                        rerank_base_url = rerank_base_url or vendor.get("api_base")
                self._rerank_api_key = rerank_api_key
                self._rerank_base_url = rerank_base_url or "https://api.siliconflow.cn/v1"
            else:
                self._rerank_model, self._rerank_api_key, self._rerank_base_url, self._rerank_vendor_id, self._rerank_model_id = (
                    _get_reranker_config()
                )

        self._query_engine = self._create_query_engine()

    def _create_retriever(self) -> Any:
        """创建检索器，支持 Auto-Merging 和混合搜索"""
        oversampling = self.settings.retrieval_oversampling_factor
        base_retriever = self.index.as_retriever(similarity_top_k=self.top_k * oversampling)

        docstore = self.index.storage_context.docstore
        is_docstore_empty = not docstore or len(docstore.docs) == 0

        if self.use_auto_merging:
            chunk_strategy = None
            if self.vector_store and hasattr(self.vector_store, "get_chunk_strategy"):
                chunk_strategy = self.vector_store.get_chunk_strategy()

            if is_docstore_empty:
                # 尝试使用 LanceDBDocumentStore（从 LanceDB 读取完整节点信息）
                try:
                    from rag.vector_store import LanceDBDocumentStore

                    # 从 vector_store 获取 kb_id
                    kb_id = None
                    if hasattr(self.vector_store, "kb_id"):
                        kb_id = self.vector_store.kb_id
                    elif hasattr(self.vector_store, "table_name"):
                        kb_id = self.vector_store.table_name

                    if kb_id:
                        lance_docstore = LanceDBDocumentStore(kb_id=kb_id)
                        lance_doc_count = len(lance_docstore)
                        if lance_doc_count > 0:
                            logger.info(f"LanceDB docstore 有 {lance_doc_count} 个节点")
                            self.index.storage_context.docstore = lance_docstore
                            docstore = lance_docstore
                            is_docstore_empty = False
                        else:
                            logger.warning(
                                "LanceDB docstore 为空，无法启用 Auto-Merging"
                            )
                except Exception as e:
                    logger.warning(f"LanceDB docstore 初始化失败: {e}")

            if is_docstore_empty:
                logger.warning(
                    "Auto-Merging 需要 docstore，但当前 KB 的 docstore 为空"
                    "（可能使用 LanceDB 向量索引创建），将使用普通 retriever"
                )
            elif chunk_strategy and chunk_strategy != "hierarchical":
                logger.warning(
                    f"Auto-Merging 需要 hierarchical 策略，"
                    f"当前 KB 使用 {chunk_strategy}，将使用普通 retriever"
                )
            else:
                try:
                    from llama_index.core.retrievers import AutoMergingRetriever

                    storage_context = self.index.storage_context
                    merger = AutoMergingRetriever(
                        base_retriever,
                        storage_context,
                        simple_ratio_thresh=self.auto_merging_threshold,
                        verbose=True,
                    )
                    logger.info("启用 Auto-Merging Retriever")
                    base_retriever = merger
                except Exception as e:
                    logger.warning(f"Auto-Merging Retriever 初始化失败: {e}")

        if self.mode == "hybrid" or self.settings.use_hybrid_search:
            if self.use_auto_merging:
                logger.warning(
                    "Auto-Merging + Hybrid 组合使用: 父子合并与 RRF 融合可能产生意外结果"
                )
            return self._create_hybrid_retriever(base_retriever)

        return base_retriever

    def _create_hybrid_retriever(self, vector_retriever: Any) -> Any:
        """使用 LanceDB 原生混合搜索（向量 + 全文搜索 FTS）"""
        import lancedb
        from llama_index.core.vector_stores.types import VectorStoreQueryMode
        from llama_index.core.indices.vector_store.retrievers import (
            VectorIndexRetriever,
        )

        vs = self.vector_store or self.index.vector_store
        if hasattr(vs, "_get_lance_vector_store"):
            lance_store = vs._get_lance_vector_store()
        else:
            lance_store = vs

        if hasattr(lance_store, "ensure_fts_index"):
            lance_store.ensure_fts_index()

        hybrid_retriever = VectorIndexRetriever(
            self.index,
            similarity_top_k=self.top_k,
            vector_store_query_mode=VectorStoreQueryMode.HYBRID,
            alpha=self.settings.hybrid_search_alpha,
        )

        logger.info(
            f"启用 LanceDB 原生混合搜索: mode={self.settings.hybrid_search_mode}, alpha={self.settings.hybrid_search_alpha}"
        )
        return hybrid_retriever

    def _create_query_engine(self) -> Any:
        """
        创建底层的查询引擎

        Returns:
            BaseQueryEngine: 查询引擎实例
        """
        from rag.ollama_utils import configure_llm_by_model_id

        if self.model_id:
            configure_llm_by_model_id(self.model_id)

        retriever = self._create_retriever()

        if self.use_multi_query:
            try:
                multi_retriever = MultiQueryFusionRetriever(
                    base_retriever=retriever,
                    llm=self._get_llm(),
                    num_queries=self.num_multi_queries,
                    top_k=self.top_k,
                    variant_score_threshold=self.settings.multi_query_variant_score_threshold,
                    original_query_weight=self.settings.multi_query_original_weight,
                )
                retriever = multi_retriever
                logger.info(
                    f"启用 Multi-Query 多查询变体融合: num_queries={self.num_multi_queries}"
                )
            except ImportError as e:
                logger.warning(f"Multi-Query 功能不可用: {e}")
            except Exception as e:
                logger.warning(f"Multi-Query 功能初始化失败: {e}")

        kwargs: dict[str, Any] = {
            "response_mode": self.response_mode,
        }

        postprocessors: list[BaseNodePostprocessor] = []

        if self.settings.enable_similarity_filter:
            from llama_index.core.postprocessor import SimilarityPostprocessor

            postprocessors.append(
                SimilarityPostprocessor(
                    similarity_cutoff=self.settings.similarity_filter_cutoff,
                )
            )
            logger.info(
                f"启用 SimilarityPostprocessor: cutoff={self.settings.similarity_filter_cutoff}"
            )

        if self.use_reranker:
            reranker = SiliconFlowReranker(
                api_key=self._rerank_api_key,
                model=self._rerank_model,
                base_url=self._rerank_base_url,
                top_n=self.top_k,
            )
            reranker._vendor_id = self._rerank_vendor_id or "siliconflow"
            reranker._model_id = self._rerank_model_id or f"siliconflow/{self._rerank_model}"
            postprocessors.append(reranker)
            logger.info(f"启用 SiliconFlow Reranker: {self._rerank_model}")

        if self.settings.enable_long_context_reorder:
            from llama_index.core.postprocessor import LongContextReorder

            postprocessors.append(LongContextReorder())
            logger.info("启用 LongContextReorder")

        if postprocessors:
            kwargs["node_postprocessors"] = postprocessors

        from llama_index.core.query_engine import RetrieverQueryEngine

        base_engine = RetrieverQueryEngine.from_args(
            retriever,
            llm=self._get_llm(),
            **kwargs,
        )

        if self.use_hyde:
            try:
                from llama_index.core.indices.query.query_transform import (
                    HyDEQueryTransform,
                )
                from llama_index.core.query_engine import TransformQueryEngine

                hyde = HyDEQueryTransform(llm=self._get_llm(), include_original=True)
                base_engine = TransformQueryEngine(base_engine, query_transform=hyde)
                logger.info("启用 HyDE 查询转换")
            except Exception as e:
                logger.warning(f"HyDE 查询转换初始化失败: {e}")

        return base_engine

    def query(self, query_str: str, stream: bool = False) -> str:
        """
        执行查询

        Args:
            query_str: 查询字符串
            stream: 是否使用流式输出

        Returns:
            str: 查询结果
        """
        if stream:
            return self._stream_query(query_str)
        else:
            response = self._query_engine.query(query_str)
            return str(response)

    def _stream_query(self, query_str: str) -> str:
        """
        执行流式查询

        Args:
            query_str: 查询字符串

        Returns:
            str: 完整的查询结果
        """
        response_stream = self._query_engine.query(query_str)

        # 收集所有响应块
        full_response = ""
        # 新版 LlamaIndex 使用 response_gen 或 response 属性
        if hasattr(response_stream, "response_gen"):
            for chunk in response_stream.response_gen:
                print(chunk, end="", flush=True)
                full_response += chunk
        elif hasattr(response_stream, "delta"):
            for chunk in response_stream.delta:
                print(chunk, end="", flush=True)
                full_response += chunk

        print()  # 换行
        return full_response

    def chat(
        self,
        message: str,
        chat_history: Optional[List] = None,
    ) -> str:
        """对话模式查询 — 利用 LlamaIndex CondenseQuestionChatEngine。

        每次调用时传入完整的 chat_history（来自会话存储），
        引擎会将历史上下文 + 新消息压缩为独立查询，再交给定制的
        RetrieverQueryEngine（含 reranker / postprocessor 链）执行。

        Args:
            message: 用户最新消息
            chat_history: 历史消息列表，每项为 dict（{role, content}）或
                          LlamaIndex ChatMessage 对象

        Available chat modes (set via wrapper.chat_mode):
            - ``condense_question``: 将历史上下文压缩为独立查询（推荐）
            - ``context``: 仅用检索到的 context 回复
            - ``condense_plus_context``: 历史压缩 + context 检索引擎
            - ``simple``: 无检索，直接 LLM 对话
            - ``best``: 自动选择最优模式
        """
        from llama_index.core.chat_engine import CondenseQuestionChatEngine
        from llama_index.core.llms import ChatMessage as LCMessage

        lc_history: Optional[List[LCMessage]] = None
        if chat_history:
            lc_history = []
            for m in chat_history:
                if isinstance(m, LCMessage):
                    lc_history.append(m)
                elif isinstance(m, dict):
                    lc_history.append(
                        LCMessage(
                            role=m.get("role", "user"),
                            content=m.get("content", ""),
                        )
                    )
                elif hasattr(m, "role") and hasattr(m, "content"):
                    lc_history.append(
                        LCMessage(role=m.role, content=m.content)
                    )

        chat_engine = CondenseQuestionChatEngine.from_defaults(
            query_engine=self._query_engine,
            llm=self._get_llm(),
            chat_history=lc_history,
        )
        response = chat_engine.chat(message)
        return str(response)

    def _get_llm(self) -> Any:
        """
        获取 LLM 实例

        Returns:
            BaseLLM: LLM 实例
        """
        from rag.ollama_utils import create_llm

        return create_llm(model_id=self.model_id)

    def get_retriever(self) -> Any:
        """
        获取检索器（用于自定义检索场景）

        Returns:
            BaseRetriever: 检索器实例
        """
        return self.index.as_retriever(similarity_top_k=self.top_k)

    def retrieve(self, query_str: str) -> List[Any]:
        """
        检索相关文档（不经过 LLM）

        Args:
            query_str: 查询字符串

        Returns:
            List[NodeWithScore]: 相关的文档节点列表
        """
        retriever = self.get_retriever()
        return retriever.retrieve(query_str)


def create_query_engine(
    kb_id: str,
    mode: str = "vector",
    top_k: int = 5,
    use_auto_merging: bool = False,
    use_hyde: bool = False,
    use_multi_query: bool = False,
    num_multi_queries: Optional[int] = None,
    use_reranker: Optional[bool] = None,
    response_mode: str = "compact",
    model_id: Optional[str] = None,
    auto_merging_threshold: Optional[float] = None,
) -> Any:
    from kb_core.services import VectorStoreService
    from rag.config import get_settings

    settings = get_settings()
    vector_store = VectorStoreService.get_vector_store(kb_id)

    index = vector_store.load_index()
    if index is None:
        raise ValueError(f"知识库 {kb_id} 不存在或未建立索引")

    wrapper = QueryEngineWrapper(
        index=index,
        top_k=top_k,
        use_reranker=use_reranker,
        use_auto_merging=use_auto_merging,
        auto_merging_threshold=auto_merging_threshold
        if auto_merging_threshold is not None
        else settings.auto_merging_simple_ratio_thresh,
        mode=mode,
        use_hyde=use_hyde,
        use_multi_query=use_multi_query,
        num_multi_queries=num_multi_queries,
        response_mode=response_mode,
        vector_store=vector_store,
        model_id=model_id,
    )

    return wrapper._query_engine


def create_sub_question_engine(
    kb_id: str,
    *,
    mode: str = "vector",
    top_k: int = 5,
    use_reranker: Optional[bool] = None,
    use_auto_merging: Optional[bool] = None,
    model_id: Optional[str] = None,
) -> Any:
    """Build a SubQuestionQueryEngine that decomposes complex queries.

    For multi-hop or multi-aspect questions, the engine:
    1. Uses LLM to break the query into sub-questions
    2. Executes each sub-question against the base query engine
    3. Synthesizes a final answer from all sub-answers

    This multiplies LLM calls (1 decomposition + N sub-queries + 1 synthesis),
    so it is only appropriate for genuinely complex questions.

    Args:
        kb_id: Knowledge base identifier.
        mode: Retrieval mode ("vector", "hybrid").
        top_k: Nodes per sub-query.
        use_reranker: Enable reranking.
        use_auto_merging: Enable auto-merging.
        model_id: LLM model for the sub-question engine.

    Returns:
        A SubQuestionQueryEngine ready for ``engine.query("...")``.
    """
    from llama_index.core.query_engine import SubQuestionQueryEngine
    from llama_index.core.question_gen import LLMQuestionGenerator
    from llama_index.core.tools import QueryEngineTool, ToolMetadata
    from rag.config import get_settings

    settings = get_settings()
    base_engine = create_query_engine(
        kb_id=kb_id,
        mode=mode,
        top_k=top_k,
        use_reranker=use_reranker if use_reranker is not None else settings.use_reranker,
        use_auto_merging=use_auto_merging if use_auto_merging is not None else settings.use_auto_merging,
        model_id=model_id,
    )

    from rag.ollama_utils import create_llm
    llm = create_llm(model_id=model_id)

    query_tool = QueryEngineTool(
        query_engine=base_engine,
        metadata=ToolMetadata(
            name=f"kb_{kb_id}",
            description=f"Search knowledge base '{kb_id}' for relevant information",
        ),
    )

    question_gen = LLMQuestionGenerator.from_defaults(llm=llm)
    sub_engine = SubQuestionQueryEngine.from_defaults(
        query_engine_tools=[query_tool],
        llm=llm,
        question_gen=question_gen,
    )

    return sub_engine


def create_chat_engine(
    kb_id: str,
    *,
    chat_mode: str = "condense_question",
    chat_history: Optional[List] = None,
    mode: str = "vector",
    top_k: int = 5,
    use_reranker: Optional[bool] = None,
    use_auto_merging: bool = False,
    use_hyde: bool = False,
    use_multi_query: bool = False,
    num_multi_queries: Optional[int] = None,
    response_mode: str = "compact",
    model_id: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    system_prompt: Optional[str] = None,
) -> Any:
    """创建 LlamaIndex 原生 chat engine，支持多种对话模式。

    与 ``create_query_engine`` 共享相同的查询引擎配置（reranker / postprocessor / chunk 策略），
    但返回的是 LlamaIndex 原生 chat engine，支持基于历史上下文的对话。

    Chat modes (ref: https://docs.llamaindex.ai/en/stable/module_guides/deploying/chat_engines/):
        - ``condense_question``: 将历史 + 新消息压缩为独立查询再执行 RAG（默认，推荐）
        - ``context``: 仅用检索到的 context 回复，适合简单知识问答
        - ``condense_plus_context`` / ``best``: 历史压缩 + context 双重上下文
        - ``simple``: 无检索，直接 LLM 对话

    每次调用时需传入完整的 chat_history（从 ChatStore 获取），
    chat engine 会自动将历史 + 最新消息压缩为独立查询再执行检索。

    Args:
        kb_id: 知识库标识。
        chat_mode: 对话模式。
        chat_history: 历史消息列表，dict（{role, content}）或 LlamaIndex ChatMessage。
        model_id: 使用的 LLM 模型 ID。
        temperature: 生成随机性 (0.0-2.0)，None 则使用默认值。
        max_tokens: 最大生成 token 数，None 则不限制。
        system_prompt: 系统提示词，None 则使用默认。

    Returns:
        LlamaIndex BaseChatEngine 实例，调用 ``.chat(message)`` 即可获取回复。
    """
    from kb_core.services import VectorStoreService
    from rag.config import get_settings
    from llama_index.core.llms import ChatMessage as LCMessage

    settings = get_settings()

    from rag.config import get_model_registry
    from rag.ollama_utils import configure_embed_model_by_model_id

    registry = get_model_registry()
    default_embed = registry.get_default("embedding")
    if default_embed:
        configure_embed_model_by_model_id(default_embed["id"])

    vector_store = VectorStoreService.get_vector_store(kb_id)
    index = vector_store.load_index()
    if index is None:
        raise ValueError(f"知识库 {kb_id} 不存在或未建立索引")

    wrapper = QueryEngineWrapper(
        index=index,
        top_k=top_k,
        use_reranker=use_reranker,
        use_auto_merging=use_auto_merging,
        auto_merging_threshold=settings.auto_merging_simple_ratio_thresh,
        mode=mode,
        use_hyde=use_hyde,
        use_multi_query=use_multi_query,
        num_multi_queries=num_multi_queries,
        response_mode=response_mode,
        vector_store=vector_store,
        model_id=model_id,
        chat_mode=chat_mode,
    )

    llm = wrapper._get_llm()
    if temperature is not None:
        llm.temperature = temperature
    if max_tokens is not None:
        llm.max_tokens = max_tokens

    lc_history: Optional[List[LCMessage]] = None
    if chat_history:
        lc_history = []
        for m in chat_history:
            if isinstance(m, LCMessage):
                lc_history.append(m)
            elif isinstance(m, dict):
                lc_history.append(
                    LCMessage(role=m.get("role", "user"), content=m.get("content", ""))
                )
            elif hasattr(m, "role") and hasattr(m, "content"):
                lc_history.append(LCMessage(role=m.role, content=m.content))

    if chat_mode == "simple":
        from llama_index.core.chat_engine import SimpleChatEngine
        return SimpleChatEngine.from_defaults(
            llm=llm,
            chat_history=lc_history,
            system_prompt=system_prompt,
        )

    if chat_mode in ("context", "condense_plus_context", "best"):
        retriever = wrapper.get_retriever()
        if chat_mode == "context":
            from llama_index.core.chat_engine import ContextChatEngine
            return ContextChatEngine.from_defaults(
                retriever=retriever,
                llm=llm,
                chat_history=lc_history,
                system_prompt=system_prompt,
            )
        else:
            from llama_index.core.chat_engine import CondensePlusContextChatEngine
            return CondensePlusContextChatEngine.from_defaults(
                retriever=retriever,
                llm=llm,
                chat_history=lc_history,
                system_prompt=system_prompt,
            )

    from llama_index.core.chat_engine import CondenseQuestionChatEngine
    return CondenseQuestionChatEngine.from_defaults(
        query_engine=wrapper._query_engine,
        llm=llm,
        chat_history=lc_history,
        system_prompt=system_prompt,
    )

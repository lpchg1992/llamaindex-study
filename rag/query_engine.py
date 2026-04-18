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

要求：
1. 每个变体从不同角度或用不同措辞表达同一个问题
2. 变体之间要有差异化，涵盖问题的不同方面
3. 保持原问题的核心意图不变
4. 避免重复，每个变体要有独特价值
5. 重要：必须保留原问题中的专业术语、动物名称、品种名称等关键实体（如"gilt"、"sow"、"pig"、"swine"、"肉鸡"、"蛋鸡"等），只变换通用描述词
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
    """

    def __init__(self, base_retriever: Any, llm: Any, num_queries: int = 3, top_k: int = 5):
        self.base_retriever = base_retriever
        self.llm = llm
        self.num_queries = num_queries
        self.top_k = top_k
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
        k = 60
        fused_scores: dict = {}
        for node_with_score, weight, rank in results:
            node_id = id(node_with_score.node)
            if node_id not in fused_scores:
                fused_scores[node_id] = {"node": node_with_score, "score": 0.0}
            fused_scores[node_id]["score"] += weight / (k + rank)
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
        for retriever in self._retrievers:
            nodes = retriever.retrieve(query_str)
            for rank, node_with_score in enumerate(nodes):
                original_score = getattr(node_with_score, "score", 1.0)
                all_nodes_with_scores.append((node_with_score, original_score, rank + 1))
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
    ):
        """
        初始化查询引擎

        Args:
            index: VectorStoreIndex 实例
            top_k: 检索返回的节点数量
            use_reranker: 是否使用 reranker（None=读取 .env 配置，True=启用，False=禁用）
            use_auto_merging: 是否使用 Auto-Merging Retriever（需要知识库使用 HierarchicalNodeParser 构建）
            auto_merging_threshold: 自动合并阈值（0-1），默认 0.5
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
        base_retriever = self.index.as_retriever(similarity_top_k=self.top_k * 3)

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
                        simple_ratio_thresh=0.25,
                        verbose=True,
                    )
                    logger.info("启用 Auto-Merging Retriever")
                    base_retriever = merger
                except Exception as e:
                    logger.warning(f"Auto-Merging Retriever 初始化失败: {e}")

        if self.mode == "hybrid" or self.settings.use_hybrid_search:
            return self._create_hybrid_retriever(base_retriever)

        return base_retriever

    def _create_hybrid_retriever(self, vector_retriever: Any) -> Any:
        """使用 LanceDB 原生混合搜索（向量 + FTS/BM25）"""
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

        if self.settings.hybrid_search_mode == "RRF":
            reranker = lancedb.rerankers.RRFReranker()
        else:
            reranker = lancedb.rerankers.LinearCombinationReranker(
                weight=self.settings.hybrid_search_alpha
            )

        if hasattr(lance_store, "_reranker"):
            lance_store._reranker = reranker

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

        if self.use_reranker:
            reranker = SiliconFlowReranker(
                api_key=self._rerank_api_key,
                model=self._rerank_model,
                base_url=self._rerank_base_url,
                top_n=self.top_k,
            )
            reranker._vendor_id = self._rerank_vendor_id or "siliconflow"
            reranker._model_id = self._rerank_model_id or f"siliconflow/{self._rerank_model}"
            kwargs["node_postprocessors"] = [reranker]
            logger.info(f"启用 SiliconFlow Reranker: {self._rerank_model}")

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

    def chat(self, message: str) -> str:
        """
        对话模式查询

        Args:
            message: 用户消息

        Returns:
            str: AI 回复
        """
        chat_engine = self.index.as_chat_engine(
            chat_mode="condense_question",
            llm=self._get_llm(),
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
) -> Any:
    from kb_core.services import VectorStoreService

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
        mode=mode,
        use_hyde=use_hyde,
        use_multi_query=use_multi_query,
        num_multi_queries=num_multi_queries,
        response_mode=response_mode,
        vector_store=vector_store,
        model_id=model_id,
    )

    return wrapper._query_engine

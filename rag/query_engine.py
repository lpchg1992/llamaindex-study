"""
查询引擎模块

封装 LlamaIndex 的查询引擎，提供统一的查询接口。
支持流式输出、自定义参数、对话模式等功能。
"""

from typing import Any, Optional, List

from rag.config import get_settings
from rag.logger import get_logger

logger = get_logger(__name__)


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

        if rerank_model or rerank_api_key or rerank_base_url:
            if rerank_model:
                self._rerank_model = rerank_model
                if not rerank_api_key or not rerank_base_url:
                    from rag.config import get_model_registry
                    registry = get_model_registry()
                    model_info = registry.get_model(rerank_model)
                    if model_info:
                        from kb_core.database import init_vendor_db
                        vendor_db = init_vendor_db()
                        vendor = vendor_db.get(model_info.get("vendor_id", "siliconflow"))
                        if vendor:
                            rerank_api_key = rerank_api_key or vendor.get("api_key")
                            rerank_base_url = rerank_base_url or vendor.get("api_base")
            else:
                from rag.reranker import get_default_reranker_from_registry
                self._rerank_model, default_key, default_url = get_default_reranker_from_registry()
                rerank_api_key = rerank_api_key or default_key
                rerank_base_url = rerank_base_url or default_url

            if not rerank_api_key:
                raise ValueError("Reranker API key not configured. Run: uv run llamaindex-study vendor update siliconflow --api-key=YOUR_KEY")
            self._rerank_api_key = rerank_api_key
            self._rerank_base_url = rerank_base_url or "https://api.siliconflow.cn/v1"
        else:
            from rag.reranker import get_default_reranker_from_registry
            self._rerank_model, self._rerank_api_key, self._rerank_base_url = (
                get_default_reranker_from_registry()
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
                from rag.query_transform import (
                    MultiQueryFusionRetriever,
                )

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
            from rag.reranker import SiliconFlowReranker

            reranker = SiliconFlowReranker(
                api_key=self._rerank_api_key,
                model=self._rerank_model,
                base_url=self._rerank_base_url,
                top_n=self.top_k,
            )
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
    response_mode: str = "compact",
    model_id: Optional[str] = None,
) -> Any:
    """
    根据知识库 ID 创建查询引擎

    Args:
        kb_id: 知识库 ID
        mode: 检索模式 ("vector", "hybrid")
        top_k: 返回结果数量
        use_auto_merging: 是否使用 Auto-Merging Retriever（需要知识库使用 HierarchicalNodeParser 构建）
        use_hyde: 是否使用 HyDE（假设文档嵌入）
        use_multi_query: 是否使用多查询转换
        num_multi_queries: 多查询变体数量（None=使用配置默认值）
        response_mode: Response Synthesizer 模式
        model_id: 使用的模型ID (None=使用默认模型)

    Returns:
        BaseQueryEngine: 查询引擎实例
    """
    from kb_core.services import VectorStoreService

    settings = get_settings()

    vector_store = VectorStoreService.get_vector_store(kb_id)

    index = vector_store.load_index()
    if index is None:
        raise ValueError(f"知识库 {kb_id} 不存在或未建立索引")

    wrapper = QueryEngineWrapper(
        index=index,
        top_k=top_k,
        use_reranker=settings.use_reranker,
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

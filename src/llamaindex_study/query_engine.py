"""
查询引擎模块

封装 LlamaIndex 的查询引擎，提供统一的查询接口。
支持流式输出、自定义参数、对话模式等功能。
"""

from typing import Any, Optional, List

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger
from llamaindex_study.ollama_utils import configure_llamaindex_for_siliconflow

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
    ):
        """
        初始化查询引擎

        Args:
            index: VectorStoreIndex 实例
            top_k: 检索返回的节点数量
            use_reranker: 是否使用 reranker（None=读取 .env 配置，True=启用，False=禁用）
        """
        self.index = index
        self.settings = get_settings()
        self.top_k = top_k or self.settings.top_k
        # None 表示使用 .env 中的配置
        if use_reranker is None:
            self.use_reranker = self.settings.use_reranker
        else:
            self.use_reranker = use_reranker

        # 创建底层的查询引擎
        self._query_engine = self._create_query_engine()

    def _create_query_engine(self) -> Any:
        """
        创建底层的查询引擎

        Returns:
            BaseQueryEngine: 查询引擎实例
        """
        # 配置 LlamaIndex 使用 SiliconFlow
        configure_llamaindex_for_siliconflow()

        # 构建查询引擎参数
        # similarity_top_k 设置更大，让 reranker 有更多候选
        similarity_k = self.top_k * 3  # 初始检索 3 倍数量的结果
        kwargs: dict[str, Any] = {"top_k": self.top_k, "similarity_top_k": similarity_k}

        # 如果启用 reranker，添加后处理器
        if self.use_reranker:
            from llamaindex_study.reranker import SiliconFlowReranker
            reranker = SiliconFlowReranker(
                api_key=self.settings.siliconflow_api_key,
                model=self.settings.rerank_model,
                base_url=self.settings.siliconflow_base_url,
                top_n=self.top_k,
            )
            kwargs["node_postprocessors"] = [reranker]
            logger.info(f"启用 SiliconFlow Reranker: {self.settings.rerank_model}")

        return self.index.as_query_engine(**kwargs)

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
        获取 LLM 实例（硅基流动）

        Returns:
            BaseLLM: LLM 实例
        """
        from llama_index.llms.openai import OpenAI

        # 注册 DeepSeek-V3 上下文窗口（同上）
        from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS
        if "Pro/deepseek-ai/DeepSeek-V3.2" not in ALL_AVAILABLE_MODELS:
            ALL_AVAILABLE_MODELS["Pro/deepseek-ai/DeepSeek-V3.2"] = 128000

        return OpenAI(
            model=self.settings.siliconflow_model,
            api_key=self.settings.siliconflow_api_key,
            api_base=self.settings.siliconflow_base_url,
        )

    def get_retriever(self) -> Any:
        """
        获取检索器（用于自定义检索场景）

        Returns:
            BaseRetriever: 检索器实例
        """
        return self.index.as_retriever(top_k=self.top_k)

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
    mode: str = "hybrid",
    top_k: int = 5,
) -> Any:
    """
    根据知识库 ID 创建查询引擎

    Args:
        kb_id: 知识库 ID
        mode: 检索模式 (hybrid, vector, keyword)
        top_k: 返回结果数量

    Returns:
        BaseQueryEngine: 查询引擎实例
    """
    from llamaindex_study.vector_store import LanceDBVectorStore
    from pathlib import Path

    settings = get_settings()

    # 获取知识库存储路径
    from kb.registry import get_storage_root
    persist_dir = get_storage_root() / kb_id

    # 加载向量存储
    vector_store = LanceDBVectorStore(
        persist_dir=persist_dir,
        table_name=kb_id,
    )

    # 加载索引
    index = vector_store.load_index()
    if index is None:
        raise ValueError(f"知识库 {kb_id} 不存在或未建立索引")

    # 创建查询引擎
    wrapper = QueryEngineWrapper(
        index=index,
        top_k=top_k,
        use_reranker=settings.use_reranker,
    )

    return wrapper._query_engine

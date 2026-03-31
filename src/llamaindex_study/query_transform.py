"""
Query Transformations Module

提供检索前的查询转换能力，提升检索质量：

1. HyDE (Hypothetical Document Embeddings)
   - 用 LLM 生成"假设性答案"
   - 用假设答案去检索，比直接检索效果更好

2. Query Rewriting
   - 用 LLM 将模糊问题改写成精确问题
   - 展开缩写、同义词扩展

用法:
    from llamaindex_study.query_transform import get_hyde_engine, get_rewrite_engine

    # HyDE 查询
    hyde_engine = get_hyde_engine(query_engine)
    response = hyde_engine.query("模糊的问题...")

    # Query Rewriting
    rewritten = rewrite_query("问题")
"""

from typing import Any, Optional

from llamaindex_study.config import get_settings


def get_llm():
    """获取 LLM 实例（用于 HyDE 和 Query Rewriting）"""
    from llamaindex_study.ollama_utils import configure_llamaindex_for_siliconflow

    configure_llamaindex_for_siliconflow()

    from llama_index.llms.openai import OpenAI

    settings = get_settings()

    return OpenAI(
        model=settings.siliconflow_model,
        api_key=settings.siliconflow_api_key,
        api_base=settings.siliconflow_base_url,
        temperature=0.1,
    )


def get_hyde_engine(
    base_query_engine: Any,
    include_original: bool = True,
) -> Any:
    """
    创建 HyDE 查询引擎

    HyDE (Hypothetical Document Embeddings) 工作原理：
    1. 用 LLM 根据问题生成一个"假设性答案"
    2. 用这个假设答案去做 embedding 检索
    3. 因为假设答案包含答案的特征，检索匹配度更高

    Args:
        base_query_engine: 基础查询引擎
        include_original: 是否保留原始问题一起检索

    Returns:
        TransformQueryEngine with HyDE
    """
    from llama_index.core.indices.query.query_transform import HyDEQueryTransform
    from llama_index.core.query_engine import TransformQueryEngine

    llm = get_llm()

    hyde = HyDEQueryTransform(
        llm=llm,
        include_original=include_original,
    )

    hyde_query_engine = TransformQueryEngine(
        base_query_engine,
        query_transform=hyde,
    )

    return hyde_query_engine


def rewrite_query(query_str: str, llm: Optional[Any] = None) -> str:
    """
    用 LLM 改写问题，使其更精确

    适用场景：
    - 用户问题模糊、不完整
    - 问题包含缩写或方言
    - 需要展开复杂问题

    Args:
        query_str: 原始问题
        llm: 可选，自定义 LLM

    Returns:
        改写后的问题
    """
    if llm is None:
        llm = get_llm()

    rewrite_prompt = f"""请将以下问题改写成更清晰、精确的形式。

要求：
1. 展开缩写和简称
2. 补充隐含的上下文
3. 使问题更具体明确
4. 保持原意不变

原问题：{query_str}

改写后的问题："""

    response = llm.complete(rewrite_prompt)
    return str(response).strip()


def get_multi_query_engine(
    base_query_engine: Any,
    num_queries: int = 3,
) -> Any:
    """
    创建多查询引擎

    从多个角度生成查询变体，解决单查询可能遗漏的问题

    Args:
        base_query_engine: 基础查询引擎
        num_queries: 生成的查询数量

    Returns:
        QueryEngine with multi-query transformation
    """
    from llama_index.core.indices.query.query_transform import MultiStepQueryTransform
    from llama_index.core.query_engine import MultiStepQueryEngine

    llm = get_llm()

    step_decompose_transform = MultiStepQueryTransform(
        llm=llm,
        num_steps=num_queries,
    )

    query_engine = MultiStepQueryEngine(
        query_engine=base_query_engine,
        query_transform=step_decompose_transform,
    )

    return query_engine


class QueryTransformPipeline:
    """
    查询转换管道

    支持链式调用多种查询转换：
    - HyDE
    - Query Rewriting
    - Multi-Query

    用法:
        pipeline = QueryTransformPipeline(query_engine)
        pipeline.add_hyde().add_rewrite()
        result = pipeline.query("问题")
    """

    def __init__(self, base_query_engine: Any):
        self.base_engine = base_query_engine
        self.current_engine = base_query_engine
        self._hyde_enabled = False
        self._rewrite_enabled = False

    def add_hyde(self, include_original: bool = True) -> "QueryTransformPipeline":
        """添加 HyDE 转换"""
        if not self._hyde_enabled:
            self.current_engine = get_hyde_engine(
                self.current_engine,
                include_original=include_original,
            )
            self._hyde_enabled = True
        return self

    def query(self, query_str: str) -> Any:
        """执行查询"""
        return self.current_engine.query(query_str)


def create_query_engine_with_transform(
    base_query_engine: Any,
    use_hyde: bool = False,
    use_rewrite: bool = False,
    use_multi_query: bool = False,
) -> Any:
    """
    创建带查询转换的引擎

    Args:
        base_query_engine: 基础查询引擎
        use_hyde: 启用 HyDE
        use_rewrite: 启用 Query Rewriting（仅返回改写后的问题）
        use_multi_query: 启用多查询

    Returns:
        配置好的查询引擎
    """
    engine = base_query_engine

    if use_hyde:
        engine = get_hyde_engine(engine)

    if use_multi_query:
        engine = get_multi_query_engine(engine)

    return engine

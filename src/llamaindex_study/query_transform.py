"""
Query Transformations Module

提供检索前的查询转换能力，提升检索质量：

1. HyDE (Hypothetical Document Embeddings)
   - 用 LLM 生成"假设性答案"
   - 用假设答案去检索，比直接检索效果更好

2. Query Rewriting
   - 用 LLM 将模糊问题改写成精确问题
   - 展开缩写、同义词扩展

3. Multi-Query (多查询变体)
   - 用 LLM 生成 N 个不同角度的查询变体
   - 分别检索后使用 RRF 融合结果
   - 减少单一查询可能遗漏的问题

用法:
    from llamaindex_study.query_transform import get_hyde_engine, get_rewrite_engine

    # HyDE 查询
    hyde_engine = get_hyde_engine(query_engine)
    response = hyde_engine.query("模糊的问题...")

    # Multi-Query 多查询变体
    from llamaindex_study.query_transform import create_multi_query_retriever
    retriever = create_multi_query_retriever(base_retriever, llm, num_queries=3)
"""

from dataclasses import dataclass
from typing import Any, List, Optional, TYPE_CHECKING

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


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


@dataclass
class MultiQueryConfig:
    """多查询配置类

    Attributes:
        num_queries: 生成查询变体的数量，默认 3 个
        prompt_template: 生成变体使用的 prompt 模板
    """

    num_queries: int = 3
    prompt_template: str = DEFAULT_MULTI_QUERY_PROMPT


def get_llm():
    """获取 LLM 实例（用于 HyDE 和 Query Rewriting）

    优先从模型注册表获取默认 LLM，失败时回退到配置默认值。
    使用 RetryableSiliconFlowLLM 以支持 token 用量追踪。
    """
    try:
        from llamaindex_study.config import get_model_registry
        from kb.database import init_vendor_db

        registry = get_model_registry()
        default_llm = registry.get_default("llm")

        if default_llm:
            from llamaindex_study.ollama_utils import create_llm

            return create_llm(model_id=default_llm["id"])
    except Exception:
        pass

    settings = get_settings()
    from llamaindex_study.ollama_utils import create_llm

    return create_llm(model_id=settings.siliconflow_model)


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


def generate_query_variants(
    llm: Any,
    query_str: str,
    num_queries: int = 3,
) -> List[str]:
    """使用 LLM 生成 N 个不同角度的查询变体

    工作原理：
    1. 使用专门的 prompt 让 LLM 从不同角度生成查询变体
    2. 每个变体保持原问题核心意图，但表达方式/角度不同
    3. 通过多路检索减少单一查询可能遗漏的问题

    Args:
        llm: LLM 实例
        query_str: 原始查询字符串
        num_queries: 生成变体数量，默认 3 个

    Returns:
        List[str]: 查询变体列表
    """
    prompt = DEFAULT_MULTI_QUERY_PROMPT.format(
        num_queries=num_queries,
        query_str=query_str,
    )

    try:
        response = llm.complete(prompt)
        response_text = str(response).strip()

        variants = []
        for line in response_text.split("\n"):
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
    """包装基础检索器，使用固定查询字符串而非输入查询

    这是实现多查询变体的关键组件。
    QueryFusionRetriever 会把 query 发给每个 retriever，
    但我们希望每个 retriever 始终使用自己特定的变体查询。
    """

    def __init__(self, base_retriever: Any, fixed_query: str):
        self.base_retriever = base_retriever
        self.fixed_query = fixed_query

    def retrieve(self, query_str: str) -> List[Any]:
        """使用固定查询检索，忽略输入的 query_str"""
        return self.base_retriever.retrieve(self.fixed_query)

    def __getattr__(self, name: str) -> Any:
        """代理所有其他属性到底层检索器"""
        return getattr(self.base_retriever, name)


class MultiQueryFusionRetriever:
    """多查询变体融合检索器

    策略：用户查询 → LLM 生成 N 个查询变体 → 每个变体独立检索 → RRF 融合

    工作流程：
    1. 根据原始查询生成 N 个不同角度的查询变体
    2. 为每个变体创建一个固定查询检索器
    3. 所有检索器并行检索
    4. 使用 RRF (Reciprocal Rank Fusion) 融合所有结果
    5. 返回融合后的 Top-K 结果
    """

    def __init__(
        self,
        base_retriever: Any,
        llm: Any,
        num_queries: int = 3,
        top_k: int = 5,
    ):
        self.base_retriever = base_retriever
        self.llm = llm
        self.num_queries = num_queries
        self.top_k = top_k
        self._query_variants: List[str] = []
        self._retrievers: List[Any] = []

    def _generate_and_setup_retrievers(self, query_str: str) -> None:
        """生成查询变体并设置检索器"""
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

    def _retrieve_with_fusion(self, query_str: str) -> List[Any]:
        """使用 RRF 融合多个检索结果"""
        if not self._retrievers:
            self._generate_and_setup_retrievers(query_str)

        all_nodes_with_scores: List[tuple[Any, float, int]] = []

        for retriever in self._retrievers:
            nodes = retriever.retrieve(query_str)
            for rank, node_with_score in enumerate(nodes):
                # 使用原始相似度分数作为权重，并使用实际排名
                # NodeWithScore.score 是原始向量检索的相似度 (0-1)
                original_score = getattr(node_with_score, "score", 1.0)
                all_nodes_with_scores.append(
                    (node_with_score, original_score, rank + 1)
                )

        return self._rrf_fusion(all_nodes_with_scores, self.top_k)

    def _rrf_fusion(self, results: List[tuple], top_k: int) -> List[Any]:
        """RRF (Reciprocal Rank Fusion) 融合算法 (加权版)

        RRF score = sum(weight / (k + rank)), k=60 by default
        weight 是原始相似度分数，使高相似度结果在融合时更具影响力
        """
        k = 60
        fused_scores: dict = {}

        for node_with_score, weight, rank in results:
            node_id = id(node_with_score.node)
            if node_id not in fused_scores:
                fused_scores[node_id] = {
                    "node": node_with_score,
                    "score": 0.0,
                }
            fused_scores[node_id]["score"] += weight / (k + rank)

        sorted_results = sorted(
            fused_scores.values(),
            key=lambda x: x["score"],
            reverse=True,
        )

        return [item["node"] for item in sorted_results[:top_k]]

    def retrieve(self, query_str: str) -> List[Any]:
        """执行多查询变体融合检索"""
        return self._retrieve_with_fusion(query_str)

    def __call__(self, query_str: str) -> List[Any]:
        """支持直接调用"""
        return self.retrieve(query_str)


def create_multi_query_retriever(
    base_retriever: Any,
    llm: Any,
    num_queries: int = 3,
) -> MultiQueryFusionRetriever:
    """创建多查询融合检索器

    策略：用户查询 → LLM 生成 N 个查询变体 → 分别检索 → RRF 融合结果

    Args:
        base_retriever: 基础检索器
        llm: LLM 实例（用于生成查询变体）
        num_queries: 生成的查询变体数量，默认 3 个

    Returns:
        MultiQueryFusionRetriever: 多查询融合检索器实例
    """
    logger.info(f"创建 Multi-Query 检索器: num_queries={num_queries}")
    return MultiQueryFusionRetriever(
        base_retriever=base_retriever,
        llm=llm,
        num_queries=num_queries,
    )


def create_multi_query_retriever_with_variants(
    base_retriever: Any,
    llm: Any,
    query_str: str,
    num_queries: int = 3,
) -> MultiQueryFusionRetriever:
    """创建多查询融合检索器（已知查询字符串，提前生成变体）

    Args:
        base_retriever: 基础检索器
        llm: LLM 实例
        query_str: 查询字符串
        num_queries: 生成的查询变体数量

    Returns:
        MultiQueryFusionRetriever: 多查询融合检索器实例
    """
    retriever = create_multi_query_retriever(base_retriever, llm, num_queries)
    retriever._generate_and_setup_retrievers(query_str)
    return retriever


def get_multi_query_engine(
    base_query_engine: Any,
    num_queries: int = 3,
) -> Any:
    """创建多查询引擎（保留向后兼容）

    注意：此函数已废弃，请使用 create_multi_query_retriever 替代。
    当前实现使用 StepDecomposeQueryTransform，与"多查询变体"策略不符。
    未来版本将移除此函数。

    Args:
        base_query_engine: 基础查询引擎
        num_queries: 生成的查询变体数量（当前未使用）

    Returns:
        基础查询引擎（不做任何转换）
    """
    logger.warning(
        "get_multi_query_engine 已废弃，请使用 create_multi_query_retriever 替代"
    )
    return base_query_engine


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

"""
节点解析器模块

提供统一的节点解析接口，支持多种分块策略：
- SentenceSplitter: 固定大小分块（默认，向后兼容）
- SemanticChunker: 语义分块（基于 embedding 相似度）
- HierarchicalNodeParser: 父子节点分块（支持 Auto-Merging Retriever）

用法：
    from llamaindex_study.node_parser import get_node_parser, get_hierarchical_node_parser

    # 普通分块（SentenceSplitter 或 SemanticChunker）
    parser = get_node_parser(chunk_size=512, chunk_overlap=50)

    # 父子节点分块（用于 Auto-Merging Retriever）
    parser = get_hierarchical_node_parser()

    # 自动选择分块策略（根据文档长度）
    parser = get_node_parser(documents=[doc1, doc2])
"""

import warnings
from typing import Any, List, Optional

from llamaindex_study.config import get_settings


def get_node_parser(
    chunk_size: Optional[int] = None,
    chunk_overlap: Optional[int] = None,
    use_semantic: bool = False,
    embed_model: Optional[Any] = None,
    strategy: Optional[str] = None,
    hierarchical_chunk_sizes: Optional[List[int]] = None,
) -> Any:
    """
    获取节点解析器

    Args:
        chunk_size: 分块大小（默认从配置读取）
        chunk_overlap: 分块重叠大小（默认从配置读取）
        use_semantic: 是否使用语义分块（默认 False）
        embed_model: embedding 模型（语义分块时需要）
        strategy: 分块策略，可选 'hierarchical'/'sentence'/'semantic'
                 默认从配置读取 CHUNK_STRATEGY
        hierarchical_chunk_sizes: hierarchical 模式的分层大小列表，
                                 如 [2048, 1024, 512]

    Returns:
        BaseNodeParser: 节点解析器实例
    """
    settings = get_settings()

    if strategy is None:
        strategy = getattr(settings, "chunk_strategy", "hierarchical")
    chunk_size = chunk_size or settings.chunk_size or 1024
    chunk_overlap = chunk_overlap or settings.chunk_overlap or 100

    if strategy == "hierarchical":
        return get_hierarchical_node_parser(
            chunk_sizes=hierarchical_chunk_sizes,
            chunk_overlap=chunk_overlap,
        )
    elif strategy == "semantic" or use_semantic:
        return _create_semantic_chunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embed_model=embed_model,
        )
    else:
        return _create_sentence_splitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )


def _create_sentence_splitter(
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> Any:
    """创建 SentenceSplitter（固定大小分块）"""
    from llama_index.core.node_parser import SentenceSplitter

    return SentenceSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        include_metadata=True,
        include_prev_next_rel=True,
    )


def _create_semantic_chunker(
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    embed_model: Optional[Any] = None,
    similarity_threshold: float = 0.5,
    percentile_threshold: float = 0.5,
) -> Any:
    """
    创建 SemanticChunker（语义分块）

    语义分块根据句子间的 embedding 相似度动态决定分块边界，
    确保每个分块内部语义连贯。

    Args:
        chunk_size: 目标分块大小
        chunk_overlap: 分块重叠大小
        embed_model: embedding 模型（如果为 None，尝试使用 MockEmbedding）
        similarity_threshold: 相似度阈值（默认 0.5）
        percentile_threshold: 百分位阈值（默认 0.5）

    Returns:
        SemanticChunker 实例，如果不可用则回退到 SentenceSplitter
    """
    try:
        from llama_index.packs.node_parser_semantic_chunking.base import SemanticChunker
        from llama_index.core.embeddings import MockEmbedding

        # 如果没有提供 embed_model，使用 MockEmbedding
        if embed_model is None:
            embed_model = MockEmbedding(embed_dim=1024)

        return SemanticChunker(
            embed_model=embed_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            similarity_threshold=similarity_threshold,
            percentile_threshold=percentile_threshold,
            include_metadata=True,
            include_prev_next_rel=True,
        )
    except ImportError:
        warnings.warn(
            "SemanticChunker 不可用（需要 llama-index-packs-node-parser-semantic-chunking），"
            "回退到 SentenceSplitter"
        )
        return _create_sentence_splitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap
        )


def get_hierarchical_node_parser(
    chunk_sizes: Optional[List[int]] = None,
    chunk_overlap: Optional[int] = None,
) -> Any:
    """
    创建 HierarchicalNodeParser（父子节点分块）

    用于 Auto-Merging Retriever 场景，创建三层结构的节点：
    - 父节点（chunk_sizes[0]，默认 2048）
    - 子节点（chunk_sizes[1]，默认 512）
    - 叶子节点（chunk_sizes[2]，默认 128）

    每个子/叶子节点都包含对父节点的引用（parent_node_id）。

    Args:
        chunk_sizes: 各层分块大小列表，默认从配置 HIERARCHICAL_CHUNK_SIZES 读取
        chunk_overlap: 分块重叠大小，默认从配置 CHUNK_OVERLAP 读取

    Returns:
        HierarchicalNodeParser 实例
    """
    from llama_index.core.node_parser import HierarchicalNodeParser

    settings = get_settings()

    if chunk_sizes is None:
        chunk_sizes = settings.hierarchical_chunk_sizes

    if chunk_overlap is None:
        chunk_overlap = settings.chunk_overlap or 50

    return HierarchicalNodeParser.from_defaults(
        chunk_sizes=chunk_sizes,
        chunk_overlap=chunk_overlap,
        include_metadata=True,
        include_prev_next_rel=True,
    )


def get_leaf_nodes(nodes: List[Any]) -> List[Any]:
    """
    从层级节点中提取叶子节点

    Args:
        nodes: HierarchicalNodeParser 生成的所有节点

    Returns:
        叶子节点列表
    """
    from llama_index.core.node_parser import get_leaf_nodes as _get_leaf_nodes

    return _get_leaf_nodes(nodes)


def get_root_nodes(nodes: List[Any]) -> List[Any]:
    """
    从层级节点中提取根节点

    Args:
        nodes: HierarchicalNodeParser 生成的所有节点

    Returns:
        根节点列表
    """
    from llama_index.core.node_parser import get_root_nodes as _get_root_nodes

    return _get_root_nodes(nodes)


__all__ = [
    "get_node_parser",
    "get_hierarchical_node_parser",
    "get_leaf_nodes",
    "get_root_nodes",
]

"""
索引构建器模块

提供从文档构建 LlamaIndex 索引的能力，支持配置 embedding 模型。

用法:
    from llamaindex_study.index_builder import IndexBuilder

    builder = IndexBuilder(persist_dir="./storage")
    index = builder.build_from_documents(documents)
"""

from pathlib import Path
from typing import List, Optional, Union

from llama_index.core.schema import Document as LlamaDocument

# 类型别名，避免循环导入时使用 any
Index = any


def _configure_embed_model() -> None:
    """配置 LlamaIndex 全局 embedding 模型
    
    从模型注册表获取默认 embedding 配置，
    并设置到 LlamaSettings 以供索引构建使用。
    """
    from llama_index.core import Settings as LlamaSettings
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llamaindex_study.embedding_service import get_default_embedding_from_registry

    model_name, base_url = get_default_embedding_from_registry()

    LlamaSettings.embed_model = OllamaEmbedding(
        model_name=model_name,
        base_url=base_url,
    )


class IndexBuilder:
    """
    索引构建器
    
    从文档列表构建 VectorStoreIndex，支持配置持久化目录。
    内部自动配置 embedding 模型。
    
    Attributes:
        persist_dir: 索引持久化目录（可选）
    """
    
    def __init__(self, persist_dir: Optional[Union[str, Path]] = None):
        """
        初始化索引构建器
        
        Args:
            persist_dir: 持久化目录路径（可选）
        """
        self.persist_dir = Path(persist_dir) if persist_dir else None

    def build_from_documents(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Index:
        """
        从文档构建索引
        
        Args:
            documents: LlamaDocument 文档列表
            show_progress: 是否显示进度条
        
        Returns:
            VectorStoreIndex: 构建好的索引
        """
        from llama_index.core import VectorStoreIndex

        # 配置 embedding 模型
        _configure_embed_model()

        index = VectorStoreIndex.from_documents(
            documents,
            show_progress=show_progress,
        )

        return index

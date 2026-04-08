"""
索引构建模块

使用 LlamaIndex 的 VectorStoreIndex 构建向量索引。
支持从文档构建索引和从持久化存储加载索引。

Embedding 使用本地 Ollama（nomic-embed-text）进行本地化处理，
兼顾质量与隐私。
"""

from pathlib import Path
from typing import List, Optional, Union

from llama_index.core.schema import Document as LlamaDocument

# 类型别名，简化代码
Index = any  # VectorStoreIndex 类型


def _configure_embed_model() -> None:
    """
    配置全局 Embedding 模型为本地 Ollama
    此函数在索引构建前调用，确保使用本地 embedding
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

    负责从文档构建向量索引，以及从持久化存储加载索引。
    """

    def __init__(self, persist_dir: Optional[Union[str, Path]] = None):
        """
        初始化索引构建器

        Args:
            persist_dir: 索引持久化目录路径
        """
        self.persist_dir = Path(persist_dir) if persist_dir else None

    def build_from_documents(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Index:
        """
        从文档列表构建向量索引

        Args:
            documents: 文档列表
            show_progress: 是否显示构建进度

        Returns:
            VectorStoreIndex: 构建好的索引
        """
        from llama_index.core import VectorStoreIndex

        # 配置本地 Ollama embedding
        _configure_embed_model()

        # 创建索引
        index = VectorStoreIndex.from_documents(
            documents,
            show_progress=show_progress,
        )

        return index

    def save(self, index: Index) -> None:
        """
        将索引持久化到磁盘

        Args:
            index: 要保存的索引

        Raises:
            ValueError: 如果 persist_dir 未设置
        """
        if self.persist_dir is None:
            raise ValueError("persist_dir 未设置，无法保存索引")

        if not self.persist_dir.exists():
            self.persist_dir.mkdir(parents=True, exist_ok=True)

        index.storage_context.persist(persist_dir=str(self.persist_dir))
        print(f"✅ 索引已保存到: {self.persist_dir}")

    def load(self) -> Optional[Index]:
        """
        从持久化存储加载索引

        Returns:
            VectorStoreIndex 或 None: 加载的索引，如果不存在则返回 None
        """
        if self.persist_dir is None or not self.persist_dir.exists():
            return None

        # 检查存储文件是否存在
        vector_store_file = self.persist_dir / "vector_store.json"
        if not vector_store_file.exists():
            return None

        from llama_index.core import StorageContext, load_index_from_storage

        # 加载存储上下文
        storage_context = StorageContext.from_defaults(
            persist_dir=str(self.persist_dir)
        )

        # 从存储加载索引
        index = load_index_from_storage(storage_context)
        print(f"✅ 索引已从 {self.persist_dir} 加载")
        return index

    @staticmethod
    def build_and_query(
        documents: List[LlamaDocument],
        query: str,
        persist_dir: Optional[Union[str, Path]] = None,
        save: bool = True,
    ) -> str:
        """
        便捷方法：从文档构建索引并执行查询

        Args:
            documents: 文档列表
            query: 查询字符串
            persist_dir: 持久化目录
            save: 是否保存索引

        Returns:
            str: 查询结果
        """
        from llamaindex_study.query_engine import QueryEngineWrapper

        builder = IndexBuilder(persist_dir=persist_dir)

        # 尝试加载已有索引
        index = builder.load()

        # 如果没有已有索引，则构建新索引
        if index is None:
            print("🔨 正在构建索引（使用本地 Ollama embedding）...")
            index = builder.build_from_documents(documents)
            if save and builder.persist_dir:
                builder.save(index)

        # 创建查询引擎并执行查询
        query_engine = QueryEngineWrapper(index)
        response = query_engine.query(query)

        return response

"""
向量数据库管理器

支持多种向量数据库后端：
- LanceDB: 高性能本地/云端向量数据库（默认）
- Chroma: 轻量级内嵌向量数据库
- Qdrant: 功能强大的向量数据库
"""

import os
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, List, Optional, Union

from llama_index.core.schema import Document as LlamaDocument

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class VectorStoreType(str, Enum):
    """向量数据库类型"""

    LANCEDB = "lancedb"
    CHROMA = "chroma"
    QDRANT = "qdrant"
    DEFAULT = "default"  # LlamaIndex 默认的 JSON 文件存储


class VectorStoreConfig:
    """向量数据库配置"""

    def __init__(
        self,
        store_type: VectorStoreType = VectorStoreType.LANCEDB,
        persist_dir: Optional[Path] = None,
        uri: Optional[str] = None,
        table_name: str = "llamaindex",
        **kwargs,
    ):
        self.store_type = store_type
        self.persist_dir = persist_dir
        self.uri = uri
        self.table_name = table_name
        self.extra_kwargs = kwargs


class BaseVectorStore(ABC):
    """向量数据库抽象基类"""

    @abstractmethod
    def build_index(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Any:
        """从文档构建索引"""
        pass

    @abstractmethod
    def load_index(self) -> Optional[Any]:
        """加载已有索引"""
        pass

    @abstractmethod
    def save_index(self, index: Any) -> None:
        """保存索引"""
        pass

    @abstractmethod
    def exists(self) -> bool:
        """检查索引是否存在"""
        pass


class LanceDBVectorStore(BaseVectorStore):
    """
    LanceDB 向量数据库

    特点：
    - 高性能：使用 Lance 格式，比 Parquet 快 10 倍
    - 本地/云端：支持本地部署和云端（S3/Azure/GCS）
    - 混合搜索：支持向量 + SQL 过滤
    - 与 LlamaIndex 原生集成
    """

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        table_name: str = "llamaindex",
        vectorizer: Optional[Any] = None,
        **kwargs,
    ):
        """
        初始化 LanceDB 向量存储

        Args:
            persist_dir: 持久化目录（用于本地模式）
            table_name: 表名
            vectorizer: 向量化器（如果为 None，使用 OllamaEmbedding）
        """
        self.persist_dir = persist_dir
        self.table_name = table_name
        self.vectorizer = vectorizer
        self._index: Optional[Any] = None
        self._vector_store: Optional[Any] = None

    def _get_embed_model(self):
        """获取 Embedding 模型

        优先使用 LlamaSettings.embed_model（如果已配置），
        以支持用户通过 embed_model_id 指定特定模型（如 ollama_homepc）。
        """
        from llama_index.core import Settings as LlamaSettings
        from llamaindex_study.ollama_utils import create_ollama_embedding

        # 优先使用全局配置的 embed_model（支持 embed_model_id 场景）
        if hasattr(LlamaSettings, "embed_model") and LlamaSettings.embed_model:
            return LlamaSettings.embed_model

        # 回退到默认配置
        return create_ollama_embedding()

    def _get_uri(self) -> str:
        """获取 LanceDB URI"""
        if self.persist_dir:
            return str(self.persist_dir)
        settings = __import__(
            "llamaindex_study.config", fromlist=["get_settings"]
        ).get_settings()
        return settings.persist_dir

    def _get_lance_vector_store(
        self,
        query_type: str = "vector",
        reranker: Any = None,
    ):
        """获取底层的 LlamaIndex LanceDBVectorStore

        Args:
            query_type: 查询类型 ("vector", "hybrid", "fts")
            reranker: LanceDB reranker 实例 (LinearCombinationReranker, RRFReranker 等)
        """
        from llama_index.vector_stores.lancedb import LanceDBVectorStore as LlamaLanceDB

        vector_store = LlamaLanceDB(
            uri=self._get_uri(),
            table_name=self.table_name,
            query_type=query_type,
        )

        if reranker:
            vector_store._reranker = reranker

        return vector_store

    def ensure_fts_index(self) -> None:
        """确保 FTS 索引存在（用于混合搜索）"""
        import lancedb

        db = lancedb.connect(self._get_uri())
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if self.table_name not in table_names:
            return

        table = db.open_table(self.table_name)
        if hasattr(table, "_fts_index_ready"):
            if not table._fts_index_ready:
                table.create_fts_index("text", replace=True)
                table._fts_index_ready = True
        else:
            try:
                table.create_fts_index("text", replace=True)
            except Exception:
                pass

    def _get_metadata_path(self) -> Optional[Path]:
        """获取元数据文件路径"""
        uri = self._get_uri()
        if not uri:
            return None
        return Path(uri) / "kb_metadata.json"

    def _load_metadata(self) -> dict:
        """加载知识库元数据"""
        meta_path = self._get_metadata_path()
        if not meta_path or not meta_path.exists():
            return {}
        try:
            import json

            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_metadata(self, metadata: dict) -> None:
        """保存知识库元数据"""
        meta_path = self._get_metadata_path()
        if not meta_path:
            return
        try:
            import json

            meta_path.parent.mkdir(parents=True, exist_ok=True)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存 KB 元数据失败: {e}")

    def get_chunk_strategy(self) -> str:
        """获取知识库的分块策略"""
        metadata = self._load_metadata()
        return metadata.get("chunk_strategy", "sentence")

    def set_chunk_strategy(self, strategy: str) -> None:
        """设置知识库的分块策略"""
        metadata = self._load_metadata()
        metadata["chunk_strategy"] = strategy
        # Also save hierarchical_chunk_sizes if using hierarchical strategy
        if strategy == "hierarchical":
            from llamaindex_study.config import get_settings

            settings = get_settings()
            if settings.hierarchical_chunk_sizes:
                metadata["hierarchical_chunk_sizes"] = settings.hierarchical_chunk_sizes
        self._save_metadata(metadata)

    def exists(self) -> bool:
        """检查索引是否存在"""
        uri = self._get_uri()
        if not uri:
            return False

        try:
            import lancedb

            db = lancedb.connect(uri)
            result = db.list_tables()
            # list_tables 返回 ListTablesResponse 对象
            table_names = result.tables if hasattr(result, "tables") else []
            return self.table_name in table_names
        except Exception:
            return False

    def build_index(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Any:
        """从文档构建索引"""
        from llama_index.core import VectorStoreIndex, Settings as LlamaSettings

        from llamaindex_study.node_parser import get_node_parser

        embed_model = self._get_embed_model()
        LlamaSettings.embed_model = embed_model

        vector_store = self._get_lance_vector_store()

        node_parser = get_node_parser()
        nodes = node_parser.get_nodes_from_documents(documents)

        print(f"   🔄 正在生成 {len(nodes)} 个节点的 embedding...")
        for node in nodes:
            node.embedding = embed_model.get_text_embedding(node.get_content())

        vector_store.add(nodes)

        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )

        self._index = index
        self._vector_store = vector_store

        from llamaindex_study.config import get_settings

        settings = get_settings()
        self.set_chunk_strategy(settings.chunk_strategy)

        return index

    def load_index(self) -> Optional[Any]:
        """加载已有索引"""
        if not self.exists():
            return None

        from llama_index.core import VectorStoreIndex, Settings as LlamaSettings

        embed_model = self._get_embed_model()
        LlamaSettings.embed_model = embed_model

        vector_store = self._get_lance_vector_store()

        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )

        self._index = index
        self._vector_store = vector_store

        print(f"✅ LanceDB 索引已加载: {self._get_uri()}/{self.table_name}")
        return index

    def save_index(self, index: Any) -> None:
        """LanceDB 自动持久化，无需手动保存"""
        print(f"✅ LanceDB 索引已自动保存: {self._get_uri()}/{self.table_name}")

    def delete_table(self) -> None:
        """删除表"""
        import shutil

        if self.exists():
            import lancedb

            db = lancedb.connect(self._get_uri())
            try:
                db.drop_table(self.table_name)
                print(f"✅ 表已删除: {self.table_name}")
            except Exception as e:
                logger.warning(f"drop_table 失败，使用 rmtree 清理: {e}")
                persist_path = Path(self._get_uri())
                if persist_path.exists():
                    shutil.rmtree(persist_path, ignore_errors=True)
                    print(f"✅ 目录已清理: {persist_path}")

    def delete_by_source(self, sources: List[str]) -> int:
        """按源文件路径删除节点

        Args:
            sources: 要删除的源文件路径列表

        Returns:
            删除的节点数量
        """
        if not sources:
            return 0

        if not self.exists():
            return 0

        import lancedb

        db = lancedb.connect(self._get_uri())
        table = db.open_table(self.table_name)

        deleted = 0
        for source in sources:
            try:
                escaped_source = source.replace("'", "''")
                result = table.delete(f"source = '{escaped_source}'")
                if hasattr(result, "num_deleted"):
                    deleted += result.num_deleted
                elif hasattr(result, "count"):
                    deleted += result.count
            except Exception as e:
                logger.warning(f"删除 source {source} 失败: {e}")

        return deleted

    def get_stats(self) -> dict:
        """获取统计信息"""
        uri = self._get_uri()
        if not uri:
            return {"exists": False}

        try:
            import lancedb

            db = lancedb.connect(uri)

            # 获取表列表
            result = db.list_tables()
            table_names = result.tables if hasattr(result, "tables") else []

            # 尝试使用配置的表名，或者使用第一个可用的表
            table_name = self.table_name
            if table_name not in table_names and table_names:
                table_name = table_names[0]  # 使用第一个表

            if table_name not in table_names:
                return {"exists": False, "reason": f"表 {table_name} 不存在"}

            table = db.open_table(table_name)
            return {
                "exists": True,
                "uri": uri,
                "table_name": table_name,
                "row_count": table.count_rows(),
            }
        except Exception as e:
            return {"exists": False, "error": str(e)}


class ChromaVectorStore(BaseVectorStore):
    """
    Chroma 向量数据库

    特点：
    - 轻量级、易于使用
    - 内嵌式（SQLite 后端）
    - 支持元数据过滤
    """

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        collection_name: str = "llamaindex",
        **kwargs,
    ):
        self.persist_dir = persist_dir or Path("./chroma_db")
        self.collection_name = collection_name
        self._index: Optional[Any] = None
        self._collection: Optional[Any] = None

    def _get_embed_model(self):
        """获取 Embedding 模型"""
        from llama_index.core import Settings as LlamaSettings
        from llamaindex_study.ollama_utils import create_ollama_embedding

        if hasattr(LlamaSettings, "embed_model") and LlamaSettings.embed_model:
            return LlamaSettings.embed_model

        return create_ollama_embedding()

    def exists(self) -> bool:
        """检查索引是否存在"""
        if not self.persist_dir.exists():
            return False
        import chromadb

        client = chromadb.PersistentClient(path=str(self.persist_dir))
        return self.collection_name in [c.name for c in client.list_collections()]

    def build_index(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Any:
        """从文档构建索引"""
        from llama_index.core import VectorStoreIndex, Settings
        from llama_index.vector_stores.chroma import ChromaVectorStore
        import chromadb

        # 配置 embedding 模型
        embed_model = self._get_embed_model()
        Settings.embed_model = embed_model

        # 确保目录存在
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # 创建 Chroma 客户端和集合
        chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))
        collection = chroma_client.get_or_create_collection(name=self.collection_name)

        # 创建向量存储
        vector_store = ChromaVectorStore(chroma_collection=collection)

        # 构建索引
        index = VectorStoreIndex.from_documents(
            documents,
            vector_store=vector_store,
            embed_model=embed_model,
            show_progress=show_progress,
        )

        self._index = index
        self._collection = collection

        return index

    def load_index(self) -> Optional[Any]:
        """加载已有索引"""
        if not self.exists():
            return None

        from llama_index.core import VectorStoreIndex, Settings
        from llama_index.vector_stores.chroma import ChromaVectorStore
        import chromadb

        # 配置 embedding 模型
        embed_model = self._get_embed_model()
        Settings.embed_model = embed_model

        # 加载集合
        chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))
        collection = chroma_client.get_or_create_collection(name=self.collection_name)
        vector_store = ChromaVectorStore(chroma_collection=collection)

        # 加载索引
        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )

        self._index = index
        self._collection = collection

        print(f"✅ Chroma 索引已加载: {self.persist_dir}/{self.collection_name}")
        return index

    def save_index(self, index: Any) -> None:
        """Chroma 自动持久化"""
        print(f"✅ Chroma 索引已自动保存: {self.persist_dir}/{self.collection_name}")

    def get_stats(self) -> dict:
        """获取统计信息"""
        if not self.exists():
            return {"exists": False}

        return {
            "exists": True,
            "persist_dir": str(self.persist_dir),
            "collection_name": self.collection_name,
            "row_count": self._collection.count() if self._collection else 0,
        }


class QdrantVectorStore(BaseVectorStore):
    """
    Qdrant 向量数据库

    特点：
    - 高性能、生产级
    - 支持混合搜索（向量 + 标量过滤）
    - REST & gRPC API
    - 支持云端部署
    """

    def __init__(
        self,
        url: str = "http://localhost:6333",
        collection_name: str = "llamaindex",
        api_key: Optional[str] = None,
        **kwargs,
    ):
        self.url = url
        self.collection_name = collection_name
        self.api_key = api_key
        self._index: Optional[Any] = None

    def _get_embed_model(self):
        """获取 Embedding 模型"""
        from llama_index.core import Settings as LlamaSettings
        from llamaindex_study.ollama_utils import create_ollama_embedding

        if hasattr(LlamaSettings, "embed_model") and LlamaSettings.embed_model:
            return LlamaSettings.embed_model

        return create_ollama_embedding()

    def exists(self) -> bool:
        """检查集合是否存在"""
        try:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=self.url, api_key=self.api_key)
            collections = client.get_collections()
            return self.collection_name in [c.name for c in collections.collections]
        except Exception:
            return False

    def build_index(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Any:
        """从文档构建索引"""
        from llama_index.core import VectorStoreIndex, Settings
        from llama_index.vector_stores.qdrant import QdrantVectorStore

        # 配置 embedding 模型
        embed_model = self._get_embed_model()
        Settings.embed_model = embed_model

        # 获取 embedding 维度
        sample_emb = embed_model.get_text_embedding("test")
        embedding_dim = len(sample_emb)

        # 创建向量存储
        vector_store = QdrantVectorStore(
            client=None,  # 将使用 url
            url=self.url,
            collection_name=self.collection_name,
            api_key=self.api_key,
            embed_dim=embedding_dim,
        )

        # 构建索引
        index = VectorStoreIndex.from_documents(
            documents,
            vector_store=vector_store,
            embed_model=embed_model,
            show_progress=show_progress,
        )

        self._index = index
        return index

    def load_index(self) -> Optional[Any]:
        """加载已有索引"""
        if not self.exists():
            return None

        from llama_index.core import VectorStoreIndex, Settings
        from llama_index.vector_stores.qdrant import QdrantVectorStore

        # 配置 embedding 模型
        embed_model = self._get_embed_model()
        Settings.embed_model = embed_model

        vector_store = QdrantVectorStore(
            url=self.url,
            collection_name=self.collection_name,
            api_key=self.api_key,
        )

        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=embed_model,
        )

        self._index = index
        print(f"✅ Qdrant 索引已加载: {self.url}/{self.collection_name}")
        return index

    def save_index(self, index: Any) -> None:
        """Qdrant 自动持久化"""
        print(f"✅ Qdrant 索引已自动保存: {self.url}/{self.collection_name}")

    def get_stats(self) -> dict:
        """获取统计信息"""
        if not self.exists():
            return {"exists": False}

        from qdrant_client import QdrantClient

        client = QdrantClient(url=self.url, api_key=self.api_key)
        info = client.get_collection(self.collection_name)

        return {
            "exists": True,
            "url": self.url,
            "collection_name": self.collection_name,
            "vectors_count": info.vectors_count,
        }


def create_vector_store(
    store_type: VectorStoreType = VectorStoreType.LANCEDB,
    persist_dir: Optional[Path] = None,
    **kwargs,
) -> BaseVectorStore:
    """
    工厂函数：创建向量数据库实例

    Args:
        store_type: 向量数据库类型
        persist_dir: 持久化目录
        **kwargs: 其他参数

    Returns:
        BaseVectorStore: 向量数据库实例
    """
    stores = {
        VectorStoreType.LANCEDB: LanceDBVectorStore,
        VectorStoreType.CHROMA: ChromaVectorStore,
        VectorStoreType.QDRANT: QdrantVectorStore,
    }

    if store_type not in stores:
        raise ValueError(f"不支持的向量数据库类型: {store_type}")

    return stores[store_type](persist_dir=persist_dir, **kwargs)


# 默认使用 LanceDB
def get_default_vector_store(persist_dir: Optional[Path] = None) -> LanceDBVectorStore:
    """获取默认的 LanceDB 向量存储"""
    return LanceDBVectorStore(persist_dir=persist_dir)


class LanceDBDocumentStore:
    """从 LanceDB 读取数据的 DocumentStore 实现，用于 Auto-Merging"""

    def __init__(self, kb_id: str, persist_dir: Optional[str] = None):
        self.kb_id = kb_id
        if persist_dir:
            self.persist_dir = persist_dir
        else:
            from llamaindex_study.config import get_settings

            settings = get_settings()
            self.persist_dir = f"{settings.persist_dir}/{kb_id}"

        self._table_name = kb_id
        self._db = None
        self._table = None
        self._cached_docs = None

    def _connect(self):
        if self._db is None:
            import lancedb

            self._db = lancedb.connect(self.persist_dir)
            self._table = self._db.open_table(self._table_name)

    def _get_node_from_row(self, row) -> Any:
        from llama_index.core.schema import TextNode, NodeRelationship, RelatedNodeInfo
        import json

        metadata = row.get("metadata", {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        node_content_str = metadata.get("_node_content", "{}")
        node_content = json.loads(node_content_str)

        relationships = node_content.get("relationships", {})
        reconstructed_rels = {}
        for key, val in relationships.items():
            if key == "4":  # PARENT
                if isinstance(val, dict):
                    reconstructed_rels[NodeRelationship.PARENT] = RelatedNodeInfo(
                        node_id=val.get("node_id"),
                        node_type=val.get("node_type"),
                        metadata=val.get("metadata", {}),
                        hash=val.get("hash"),
                    )
            elif key == "5":  # CHILD
                if isinstance(val, list):
                    children = []
                    for child in val:
                        if isinstance(child, dict):
                            children.append(
                                RelatedNodeInfo(
                                    node_id=child.get("node_id"),
                                    node_type=child.get("node_type"),
                                    metadata=child.get("metadata", {}),
                                    hash=child.get("hash"),
                                )
                            )
                    if children:
                        reconstructed_rels[NodeRelationship.CHILD] = children
            elif key == "1":  # SOURCE
                if isinstance(val, dict):
                    reconstructed_rels[NodeRelationship.SOURCE] = RelatedNodeInfo(
                        node_id=val.get("node_id"),
                        node_type=val.get("node_type"),
                        metadata=val.get("metadata", {}),
                        hash=val.get("hash"),
                    )

        node = TextNode(
            id_=row.get("id"),
            text=node_content.get("text", ""),
            metadata=node_content.get("metadata", {}),
            relationships=reconstructed_rels,
            embedding=row.get("vector") if "vector" in row else None,
        )
        return node

    def get_document(self, node_id: str) -> Any:
        self._connect()
        import pandas as pd

        result = self._table.search().where(f'id = "{node_id}"').limit(1).to_pandas()
        if len(result) == 0:
            return None
        return self._get_node_from_row(result.iloc[0])

    def get_nodes(self, node_ids: List[str]) -> List[Any]:
        if not node_ids:
            return []
        self._connect()
        import pandas as pd

        ids_str = '", "'.join(node_ids)
        query = f'id IN ("{ids_str}")'
        result = self._table.search().where(query).limit(len(node_ids)).to_pandas()
        return [self._get_node_from_row(row) for _, row in result.iterrows()]

    def document_exists(self, doc_id: str) -> bool:
        return self.get_document(doc_id) is not None

    def __len__(self) -> int:
        self._connect()
        return self._table.count_rows()

    @property
    def docs(self):
        if self._cached_docs is None:
            self._connect()
            total = self._table.count_rows()
            all_ids = []
            batch_size = 1000
            for offset in range(0, total, batch_size):
                batch = (
                    self._table.search().offset(offset).limit(batch_size).to_pandas()
                )
                all_ids.extend(batch["id"].tolist())
            self._cached_docs = {id_: self.get_document(id_) for id_ in all_ids}
        return self._cached_docs

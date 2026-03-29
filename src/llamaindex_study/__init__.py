"""
LlamaIndex Study - 一个现代化的 LlamaIndex 学习项目

本包提供了文档加载、索引构建、查询等核心功能的封装。
"""

__version__ = "0.1.0"
__author__ = "lpchg1992"

from llamaindex_study.config import Settings, get_settings
from llamaindex_study.logger import get_logger, get_app_logger, get_kb_logger, get_api_logger
from llamaindex_study.ollama_utils import (
    create_ollama_embedding,
    configure_global_embed_model,
    configure_llamaindex_for_siliconflow,
    BatchEmbeddingHelper,
)
from llamaindex_study.embedding_service import (
    OllamaEmbeddingService,
    OllamaEndpoint,
    get_embedding_service,
    reset_embedding_service,
)
from llamaindex_study.reader import DocumentReader, SmartDocumentProcessor, load_and_split
from llamaindex_study.index_builder import IndexBuilder
from llamaindex_study.query_engine import QueryEngineWrapper, create_query_engine
from llamaindex_study.vector_store import (
    VectorStoreType,
    LanceDBVectorStore,
    ChromaVectorStore,
    QdrantVectorStore,
    create_vector_store,
    get_default_vector_store,
)

__all__ = [
    # 配置
    "Settings",
    "get_settings",
    # 日志
    "get_logger",
    "get_app_logger",
    "get_kb_logger",
    "get_api_logger",
    # Ollama 工具
    "create_ollama_embedding",
    "configure_global_embed_model",
    "configure_llamaindex_for_siliconflow",
    "BatchEmbeddingHelper",
    "OllamaEmbeddingService",
    "OllamaEndpoint",
    "get_embedding_service",
    "reset_embedding_service",
    # 文档处理
    "DocumentReader",
    "SmartDocumentProcessor",
    "load_and_split",
    # 索引和查询
    "IndexBuilder",
    "QueryEngineWrapper",
    "create_query_engine",
    # 向量存储
    "VectorStoreType",
    "LanceDBVectorStore",
    "ChromaVectorStore",
    "QdrantVectorStore",
    "create_vector_store",
    "get_default_vector_store",
]

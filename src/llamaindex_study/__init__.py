"""
LlamaIndex Study - 一个现代化的 LlamaIndex 学习项目

本包提供了文档加载、索引构建、查询等核心功能的封装。
"""

__version__ = "0.1.0"
__author__ = "lpchg1992"

from llamaindex_study.config import Settings, get_settings
from llamaindex_study.reader import DocumentReader, SmartDocumentProcessor, load_and_split
from llamaindex_study.index_builder import IndexBuilder
from llamaindex_study.query_engine import QueryEngineWrapper
from llamaindex_study.vector_store import (
    VectorStoreType,
    LanceDBVectorStore,
    ChromaVectorStore,
    QdrantVectorStore,
    create_vector_store,
    get_default_vector_store,
)

__all__ = [
    "Settings",
    "get_settings",
    "DocumentReader",
    "SmartDocumentProcessor",
    "load_and_split",
    "IndexBuilder",
    "QueryEngineWrapper",
    "VectorStoreType",
    "LanceDBVectorStore",
    "ChromaVectorStore",
    "QdrantVectorStore",
    "create_vector_store",
    "get_default_vector_store",
]

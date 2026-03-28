"""
知识库模块

管理多个知识库的创建、导入和查询。
"""

from .registry import KnowledgeBase, KnowledgeBaseRegistry
from .obsidian_reader import ObsidianReader, ObsidianClassifier
from .zotero_reader import (
    ZoteroReader,
    ZoteroItem,
    ZoteroClassifier,
    create_zotero_reader,
    DEFAULT_ZOTERO_DATA_DIR,
)
from .sync_state import SyncState, IncrementalSyncManager
from llamaindex_study.vector_store import (
    VectorStoreType,
    LanceDBVectorStore,
    ChromaVectorStore,
    QdrantVectorStore,
    create_vector_store,
    get_default_vector_store,
)

__all__ = [
    "KnowledgeBase",
    "KnowledgeBaseRegistry",
    "ObsidianReader",
    "ObsidianClassifier",
    "ZoteroReader",
    "ZoteroItem",
    "ZoteroClassifier",
    "create_zotero_reader",
    "DEFAULT_ZOTERO_DATA_DIR",
    "SyncState",
    "IncrementalSyncManager",
    "VectorStoreType",
    "LanceDBVectorStore",
    "ChromaVectorStore",
    "QdrantVectorStore",
    "create_vector_store",
    "get_default_vector_store",
]

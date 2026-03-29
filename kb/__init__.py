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
from .deduplication import (
    DeduplicationManager,
    IncrementalProcessor,
    ChangeType,
    FileChange,
    ProcessingRecord,
)
from .database import (
    get_db,
    get_cursor,
    DatabaseManager,
    SyncStateDB,
    DedupStateDB,
    ProgressDB,
    KnowledgeBaseMetaDB,
    init_sync_db,
    init_dedup_db,
    init_progress_db,
    init_kb_meta_db,
    get_db_path,
)
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
    "DeduplicationManager",
    "IncrementalProcessor",
    "ChangeType",
    "FileChange",
    "ProcessingRecord",
    "get_db",
    "get_cursor",
    "DatabaseManager",
    "SyncStateDB",
    "DedupStateDB",
    "ProgressDB",
    "KnowledgeBaseMetaDB",
    "init_sync_db",
    "init_dedup_db",
    "init_progress_db",
    "init_kb_meta_db",
    "get_db_path",
    "VectorStoreType",
    "LanceDBVectorStore",
    "ChromaVectorStore",
    "QdrantVectorStore",
    "create_vector_store",
    "get_default_vector_store",
]

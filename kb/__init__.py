"""
知识库模块

管理多个知识库的创建、导入和查询。
"""

from .utils.registry import KnowledgeBase, KnowledgeBaseRegistry
from .sources.obsidian import ObsidianReader, ObsidianClassifier
from .sources.zotero import (
    ZoteroReader,
    ZoteroItem,
    ZoteroClassifier,
    create_zotero_reader,
)
from .core.database import (
    get_db,
    get_cursor,
    DatabaseManager,
    SyncStateDB,
    ProgressDB,
    KnowledgeBaseMetaDB,
    DocumentDB,
    ChunkDB,
    init_sync_db,
    init_progress_db,
    init_kb_meta_db,
    init_document_db,
    init_chunk_db,
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

from .core import (
    VectorStoreService,
    ObsidianService,
    ZoteroService,
    GenericService,
    KnowledgeBaseService,
    SearchService,
    QueryRouter,
    TaskService,
    CategoryService,
    AdminService,
    ConsistencyService,
)

from .core.task_queue import TaskQueue
from .core.task_executor import TaskExecutor
from .core.document_chunk_service import DocumentChunkService
from .processing.document_processor import DocumentProcessor
from .processing.generic_processor import GenericImporter
from .processing.parallel_embedding import ParallelEmbeddingProcessor
from .storage.lance_crud import LanceCRUDService
from .storage.sync_state import SyncState
from .analysis.topic_analyzer import TopicAnalyzer
from .analysis.category_classifier import CategoryClassifier
from .utils.import_service import ImportApplicationService
from .utils.preview_service import PreviewService
from .utils.websocket_manager import WebSocketManager

__all__ = [
    "KnowledgeBase",
    "KnowledgeBaseRegistry",
    "ObsidianReader",
    "ObsidianClassifier",
    "ZoteroReader",
    "ZoteroItem",
    "ZoteroClassifier",
    "create_zotero_reader",
    "get_db",
    "get_cursor",
    "DatabaseManager",
    "SyncStateDB",
    "ProgressDB",
    "KnowledgeBaseMetaDB",
    "DocumentDB",
    "ChunkDB",
    "init_sync_db",
    "init_progress_db",
    "init_kb_meta_db",
    "init_document_db",
    "init_chunk_db",
    "get_db_path",
    "VectorStoreType",
    "LanceDBVectorStore",
    "ChromaVectorStore",
    "QdrantVectorStore",
    "create_vector_store",
    "get_default_vector_store",
    "VectorStoreService",
    "ObsidianService",
    "ZoteroService",
    "GenericService",
    "KnowledgeBaseService",
    "SearchService",
    "QueryRouter",
    "TaskService",
    "CategoryService",
    "AdminService",
    "ConsistencyService",
    "TaskQueue",
    "TaskExecutor",
    "DocumentChunkService",
    "DocumentProcessor",
    "GenericImporter",
    "ParallelEmbeddingProcessor",
    "LanceCRUDService",
    "SyncState",
    "TopicAnalyzer",
    "CategoryClassifier",
    "ImportApplicationService",
    "PreviewService",
    "WebSocketManager",
]
